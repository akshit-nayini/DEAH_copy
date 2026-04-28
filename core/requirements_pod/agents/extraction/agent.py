"""Extraction pipeline orchestrator — all 9 stages — and the public parse_file() entry point."""
from __future__ import annotations

import io
import logging
from collections import defaultdict
from typing import Optional

# ── In-memory progress store ──────────────────────────────────────────────────
# Keyed by file_id; populated during parse_file(), cleared on completion/error.
_progress: dict[str, dict] = {}


def get_progress(file_id: str) -> dict:
    """Return current extraction progress for a file. Empty dict if not in flight."""
    return dict(_progress.get(file_id, {}))


def _update(
    file_id: str,
    stage: str,
    chunks_done: int = 0,
    chunks_total: int = 0,
) -> None:
    if stage == "normalising":
        pct = 3
    elif stage == "chunking":
        pct = 8
    elif stage == "extracting":
        pct = 12 + int(78 * chunks_done / chunks_total) if chunks_total else 12
    elif stage == "deduplicating":
        pct = 92
    elif stage == "merging":
        pct = 95
    elif stage == "scoring":
        pct = 97
    elif stage == "saving":
        pct = 99
    else:
        pct = 100
    _progress[file_id] = {
        "stage": stage,
        "chunks_done": chunks_done,
        "chunks_total": chunks_total,
        "pct": pct,
    }

from sqlalchemy.orm import Session

from core.requirements_pod.config import Settings
from core.requirements_pod.database import repository
from core.requirements_pod.database.schemas.task import TaskOut
from core.utilities.llm.provider_base import BaseLLMProvider
from core.utilities.storage.base import BaseStorageProvider

from .config import ExtractionConfig
from .chunker import chunk_text
from .exceptions import LLMAuthError, LLMQuotaError
from .llm import extract_all, RawTask
from .dedup import local_dedup, build_global_pool
from .merge import graph_merge
from .temporal import apply_temporal_reasoning, TemporalTask
from .scoring import score_confidence
from .output import to_db_fields

logger = logging.getLogger(__name__)


# ── File decoding (unchanged from original extraction.py) ─────────────────────

def _decode_file(raw_bytes: bytes, filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf(raw_bytes)
    elif lower.endswith(".docx"):
        return _extract_docx(raw_bytes)
    else:
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return raw_bytes.decode("latin-1", errors="replace")


def _extract_pdf(raw_bytes: bytes) -> str:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        pages = []
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text()
            pages.append(f"[Page {page_num}]\n{text}")
        return "\n".join(pages)
    except ImportError:
        logger.warning("PyMuPDF not available, falling back to pdfminer")
        from pdfminer.high_level import extract_text_to_fp
        from pdfminer.layout import LAParams
        output = io.StringIO()
        extract_text_to_fp(io.BytesIO(raw_bytes), output, laparams=LAParams())
        return output.getvalue()


def _extract_docx(raw_bytes: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(raw_bytes))
    paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
    return "\n".join(paragraphs)


def _load_project_context(settings: Settings) -> str:
    """Load project_context.md for use as per-chunk project context."""
    try:
        with open(settings.PROJECT_CONTEXT_FILE, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return ""


# ── Stage 1 ───────────────────────────────────────────────────────────────────

def normalise_text(text: str) -> str:
    """Strip null bytes and normalise line endings."""
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


# ── Pipeline (Stages 2–8) ────────────────────────────────────────────────────

async def run_extraction_pipeline(
    text: str,
    project_context: str,
    llm: BaseLLMProvider,
    config: ExtractionConfig,
    file_index: int = 0,
    file_id: str = "",
) -> list[TemporalTask]:
    """Run stages 2–8 and return scored tasks sorted by confidence (desc)."""
    # Stage 2 — chunk
    if file_id:
        _update(file_id, "chunking")
    chunks = chunk_text(text, file_index=file_index, config=config)
    logger.info("Stage 2: %d chunk(s) from file_index=%d", len(chunks), file_index)

    if not chunks:
        return []

    # Stage 3 — parallel LLM extraction
    if file_id:
        _update(file_id, "extracting", 0, len(chunks))

    def _on_chunk(done: int, total: int) -> None:
        _update(file_id, "extracting", done, total)

    raw: list[RawTask] = await extract_all(
        chunks, project_context, config, llm,
        on_chunk_done=_on_chunk if file_id else None,
    )
    logger.info("Stage 3: %d raw task(s) extracted", len(raw))

    # Stage 4 — local dedup per document
    if file_id:
        _update(file_id, "deduplicating")
    by_file: dict[int, list[RawTask]] = defaultdict(list)
    for task in raw:
        by_file[task.file_index].append(task)
    deduped = {fi: local_dedup(tasks, config.local_dedup_threshold) for fi, tasks in by_file.items()}
    local_count = sum(len(v) for v in deduped.values())
    logger.info("Stage 4: %d task(s) after local dedup", local_count)

    # Stage 5 — global pool
    pool = build_global_pool(deduped)

    # Stage 6 — graph similarity merge
    if file_id:
        _update(file_id, "merging")
    merged = graph_merge(pool, config.global_merge_threshold)
    logger.info("Stage 6: %d task(s) after merge", len(merged))

    # Stage 7 — temporal reasoning
    temporal = apply_temporal_reasoning(merged)
    logger.info("Stage 7: %d task(s) after temporal reasoning", len(temporal))

    # Stage 8 — confidence scoring
    if file_id:
        _update(file_id, "scoring")
    for task in temporal:
        task.confidence = score_confidence(task)
    temporal.sort(key=lambda t: t.confidence, reverse=True)

    return temporal


# ── Public interface (drop-in for the original parse_file) ───────────────────

async def parse_file(
    file_id: str,
    db: Session,
    llm: BaseLLMProvider,
    storage: BaseStorageProvider,
    settings: Settings,
) -> list[TaskOut]:
    """Drop-in replacement for the original extraction entry point.

    Internally runs all 9 pipeline stages.
    Externally exposes the identical signature and return type.
    """
    source_file = repository.get_source_file(db, file_id)
    if source_file is None:
        raise ValueError(f"Source file not found: {file_id}")

    _update(file_id, "normalising")

    try:
        raw_bytes = await storage.read(source_file.file_path)
    except Exception as exc:
        repository.update_source_file_status(db, file_id, "error")
        _progress.pop(file_id, None)
        raise RuntimeError(f"Could not read file from storage: {exc}") from exc

    try:
        text = _decode_file(raw_bytes, source_file.filename)
    except Exception as exc:
        repository.update_source_file_status(db, file_id, "error")
        _progress.pop(file_id, None)
        raise RuntimeError(f"Could not decode file: {exc}") from exc

    if not text or not text.strip():
        repository.update_source_file_status(db, file_id, "error")
        _progress.pop(file_id, None)
        raise RuntimeError("No extractable text found in the document.")

    project_context = _load_project_context(settings)
    config = ExtractionConfig.from_settings(settings)

    # Stage 1 — normalise
    clean_text = normalise_text(text)

    # Stages 2–8
    try:
        pipeline_tasks = await run_extraction_pipeline(
            text=clean_text,
            project_context=project_context,
            llm=llm,
            config=config,
            file_index=0,
            file_id=file_id,
        )
    except (LLMAuthError, LLMQuotaError):
        repository.update_source_file_status(db, file_id, "error")
        _progress.pop(file_id, None)
        raise

    logger.info(
        "Pipeline finished for '%s': %d task(s)",
        source_file.filename, len(pipeline_tasks),
    )

    # Stage 9 — clear old non-pushed tasks then write new ones
    _update(file_id, "saving")
    repository.clear_unpushed_tasks_for_file(db, file_id)
    created_tasks: list[TaskOut] = []
    for task in pipeline_tasks:
        fields = to_db_fields(
            task,
            source_file_id=file_id,
            user_name=source_file.uploaded_by,
            task_source=source_file.filename,
        )
        task_obj = repository.create_task(db=db, **fields)
        created_tasks.append(TaskOut.model_validate(task_obj))

    repository.update_source_file_status(db, file_id, "parsed")
    _progress.pop(file_id, None)
    return created_tasks


async def parse_files_merged(
    file_ids: list[str],
    db: Session,
    llm: BaseLLMProvider,
    storage: BaseStorageProvider,
    settings: Settings,
) -> list[TaskOut]:
    """Download multiple files, concatenate their text, run a single extraction pass.

    Progress is tracked under file_ids[0].
    All file records are marked 'parsed' on success.
    """
    if not file_ids:
        raise ValueError("At least one file ID is required.")

    primary_id = file_ids[0]
    _update(primary_id, "normalising")

    # Load + decode each file
    parts: list[str] = []
    filenames: list[str] = []
    for fid in file_ids:
        source_file = repository.get_source_file(db, fid)
        if source_file is None:
            logger.warning("File not found in DB: %s — skipping", fid)
            continue
        try:
            raw_bytes = await storage.read(source_file.file_path)
            text = _decode_file(raw_bytes, source_file.filename)
            clean = normalise_text(text)
            if clean.strip():
                parts.append(f"=== Document: {source_file.filename} ===\n{clean}")
                filenames.append(source_file.filename)
        except Exception as exc:
            logger.warning("Could not read file %s (%s): %s", fid, source_file.filename, exc)

    if not parts:
        _progress.pop(primary_id, None)
        raise RuntimeError("No readable content found in the selected files.")

    merged_text = "\n\n---\n\n".join(parts)
    task_source = ", ".join(filenames)

    project_context = _load_project_context(settings)
    config = ExtractionConfig.from_settings(settings)

    try:
        pipeline_tasks = await run_extraction_pipeline(
            text=merged_text,
            project_context=project_context,
            llm=llm,
            config=config,
            file_index=0,
            file_id=primary_id,
        )
    except (LLMAuthError, LLMQuotaError):
        for fid in file_ids:
            repository.update_source_file_status(db, fid, "error")
        _progress.pop(primary_id, None)
        raise

    logger.info("Merged pipeline finished for [%s]: %d task(s)", task_source, len(pipeline_tasks))

    _update(primary_id, "saving")
    for fid in file_ids:
        repository.clear_unpushed_tasks_for_file(db, fid)
    primary_file = repository.get_source_file(db, primary_id)
    created_tasks: list[TaskOut] = []
    for task in pipeline_tasks:
        fields = to_db_fields(
            task,
            source_file_id=primary_id,
            user_name=primary_file.uploaded_by if primary_file else None,
            task_source=task_source,
        )
        task_obj = repository.create_task(db=db, **fields)
        created_tasks.append(TaskOut.model_validate(task_obj))

    for fid in file_ids:
        repository.update_source_file_status(db, fid, "parsed")
    _progress.pop(primary_id, None)
    return created_tasks
