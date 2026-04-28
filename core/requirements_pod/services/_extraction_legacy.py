import json
import logging
from difflib import SequenceMatcher
from typing import Optional
from sqlalchemy.orm import Session

from core.requirements_pod.config import Settings
from core.requirements_pod.db import repository
from core.requirements_pod.schemas.task import TaskOut
from core.utilities.llm.provider_base import BaseLLMProvider
from core.utilities.storage.base import BaseStorageProvider

logger = logging.getLogger(__name__)

VALID_TASK_TYPES = {"bug", "story", "task", "subtask"}


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _is_duplicate(candidate: dict, existing: list[dict], threshold: float = 0.85) -> bool:
    candidate_heading = candidate.get("task_heading", "")
    candidate_location = candidate.get("location") or ""
    for ex in existing:
        heading_sim = _similarity(candidate_heading, ex.get("task_heading", ""))
        loc_sim = _similarity(candidate_location, ex.get("location") or "")
        if heading_sim >= threshold and loc_sim >= 0.5:
            return True
    return False


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end == len(words):
            break
        start += chunk_size - overlap
    return chunks


def _decode_file(raw_bytes: bytes, filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return _extract_pdf(raw_bytes)
    elif lower.endswith(".docx"):
        return _extract_docx(raw_bytes)
    else:
        # Plain text: try UTF-8, fall back to latin-1
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
        import io
        output = io.StringIO()
        extract_text_to_fp(io.BytesIO(raw_bytes), output, laparams=LAParams())
        return output.getvalue()


def _extract_docx(raw_bytes: bytes) -> str:
    import io
    from docx import Document
    doc = Document(io.BytesIO(raw_bytes))
    paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
    return "\n".join(paragraphs)


def _load_system_prompt(settings: Settings) -> str:
    try:
        with open(settings.PROJECT_CONTEXT_FILE, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return (
            "You are a task extraction assistant. "
            "Extract all actionable items from the provided text."
        )


async def parse_file(
    file_id: str,
    db: Session,
    llm: BaseLLMProvider,
    storage: BaseStorageProvider,
    settings: Settings,
) -> list[TaskOut]:
    source_file = repository.get_source_file(db, file_id)
    if source_file is None:
        raise ValueError(f"Source file not found: {file_id}")

    try:
        raw_bytes = await storage.read(source_file.file_path)
    except Exception as exc:
        repository.update_source_file_status(db, file_id, "error")
        raise RuntimeError(f"Could not read file from storage: {exc}") from exc

    try:
        text = _decode_file(raw_bytes, source_file.filename)
    except Exception as exc:
        repository.update_source_file_status(db, file_id, "error")
        raise RuntimeError(f"Could not decode file: {exc}") from exc

    if not text or not text.strip():
        repository.update_source_file_status(db, file_id, "error")
        raise RuntimeError("No extractable text found in the document.")

    system_prompt = _load_system_prompt(settings)

    chunks = _chunk_text(text, settings.LLM_CHUNK_SIZE, settings.LLM_CHUNK_OVERLAP)
    logger.info("Splitting file '%s' into %d chunks", source_file.filename, len(chunks))

    all_raw_tasks: list[dict] = []
    chunk_errors: list[str] = []
    for idx, chunk in enumerate(chunks):
        try:
            extracted = await llm.extract_tasks(chunk, system_prompt)
            all_raw_tasks.extend(extracted)
            logger.info("Chunk %d/%d: extracted %d tasks", idx + 1, len(chunks), len(extracted))
        except Exception as exc:
            chunk_errors.append(str(exc))
            logger.error("Chunk %d/%d failed: %s", idx + 1, len(chunks), exc)

    if chunk_errors and not all_raw_tasks:
        repository.update_source_file_status(db, file_id, "error")
        raise RuntimeError(
            f"LLM extraction failed on all {len(chunks)} chunk(s). {chunk_errors[0]}"
        )

    if chunk_errors:
        logger.warning(
            "%d/%d chunk(s) failed but %d task(s) were recovered from remaining chunks.",
            len(chunk_errors), len(chunks), len(all_raw_tasks),
        )

    # Deduplicate
    unique_tasks: list[dict] = []
    for raw in all_raw_tasks:
        if not _is_duplicate(raw, unique_tasks):
            unique_tasks.append(raw)

    logger.info(
        "After deduplication: %d tasks (was %d)", len(unique_tasks), len(all_raw_tasks)
    )

    # Persist tasks
    created_tasks: list[TaskOut] = []
    for raw in unique_tasks:
        task_type = raw.get("task_type", "task")
        if task_type not in VALID_TASK_TYPES:
            task_type = "task"

        task = repository.create_task(
            db=db,
            task_heading=raw.get("task_heading", "Untitled Task"),
            description=raw.get("description"),
            task_type=task_type,
            user_name=source_file.uploaded_by,
            task_source=source_file.filename,
            source_file_id=file_id,
            location=raw.get("location"),
            raw_llm_json=json.dumps(raw),
        )
        created_tasks.append(TaskOut.model_validate(task))

    repository.update_source_file_status(db, file_id, "parsed")
    return created_tasks
