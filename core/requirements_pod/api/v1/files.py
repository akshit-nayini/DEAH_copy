import asyncio
import json
import logging
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.requirements_pod.config import Settings, get_settings
from core.requirements_pod.database.session import get_db
from core.requirements_pod.database import repository
from core.requirements_pod.database.schemas.file import FileOut
from core.requirements_pod.database.schemas.task import TaskOut
from core.requirements_pod.agents.extraction import parse_file
from core.requirements_pod.agents.extraction.agent import parse_files_merged
from core.requirements_pod.agents.extraction.exceptions import LLMAuthError, LLMQuotaError
from core.utilities.llm.provider_base import BaseLLMProvider
from core.utilities.storage.base import BaseStorageProvider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])

# ── Gap analysis in-flight tracker ───────────────────────────────────────────
# Keyed by primary file_id. Cleared after "done" is polled once by the frontend.
# status: "pending" | "running" | "done" | "error"
_gap_progress: dict[str, dict] = {}

MIME_MAP = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "md": "text/markdown",
    "vtt": "text/vtt",
    "srt": "application/x-subrip",
}


class _ClaudeSDKProvider(BaseLLMProvider):
    """Async adapter that uses ClaudeCodeSDKClient's SDK connection for extraction.

    Borrows _query and _anyio from ClaudeCodeSDKClient (zero changes to that file)
    and collects from both AssistantMessage.content blocks AND ResultMessage.result.
    This handles complex extraction where the full JSON arrives via AssistantMessage
    content blocks rather than ResultMessage.result alone.

    asyncio.to_thread() + anyio.run() give the SDK its own clean event loop so
    FastAPI's asyncio loop is never blocked or conflicted.
    """

    def __init__(self) -> None:
        from core.utilities.llm.claude_code_sdk_client import ClaudeCodeSDKClient
        _sdk = ClaudeCodeSDKClient()
        # Borrow the underlying SDK query function and anyio runner
        self._sdk_query = _sdk._query
        self._anyio = _sdk._anyio

    def _run_sync(self, prompt: str) -> str:
        """Run a full SDK query in its own anyio event loop, collecting all text."""
        async def _collect() -> str:
            text_parts: list[str] = []
            msg_count = 0
            async for message in self._sdk_query(prompt=prompt):
                msg_count += 1
                msg_type = type(message).__name__
                # AssistantMessage: content blocks carry the generated text
                if hasattr(message, "content"):
                    content = message.content
                    if isinstance(content, list):
                        for block in content:
                            if hasattr(block, "text") and block.text:
                                text_parts.append(block.text)
                                logger.debug(
                                    "_ClaudeSDKProvider: msg#%d %s content block text len=%d",
                                    msg_count, msg_type, len(block.text),
                                )
                    elif isinstance(content, str) and content:
                        text_parts.append(content)
                        logger.debug(
                            "_ClaudeSDKProvider: msg#%d %s content str len=%d",
                            msg_count, msg_type, len(content),
                        )
                # ResultMessage: final result string (may duplicate AssistantMessage)
                elif hasattr(message, "result") and message.result:
                    logger.debug(
                        "_ClaudeSDKProvider: msg#%d %s result len=%d",
                        msg_count, msg_type, len(message.result),
                    )
                    # Only use result if we got nothing from content blocks
                    if not text_parts:
                        text_parts.append(message.result)
                else:
                    logger.debug(
                        "_ClaudeSDKProvider: msg#%d %s (no content/result)",
                        msg_count, msg_type,
                    )
            total = sum(len(p) for p in text_parts)
            logger.info(
                "_ClaudeSDKProvider: collected %d messages, %d text parts, %d total chars",
                msg_count, len(text_parts), total,
            )
            return "".join(text_parts)

        return self._anyio.run(_collect)

    async def call_raw(self, system: str, user: str) -> str:
        full_prompt = f"{system}\n\n{user}" if system else user
        return await asyncio.to_thread(self._run_sync, full_prompt)

    async def extract_tasks(self, text: str, system_prompt: str) -> list[dict]:
        raw = await self.call_raw(system_prompt, text)
        stripped = raw.strip()
        logger.info(
            "_ClaudeSDKProvider.extract_tasks: raw response len=%d, first 200 chars: %r",
            len(stripped), stripped[:200],
        )
        if stripped.startswith("```"):
            lines = stripped.split("\n")
            stripped = "\n".join(
                l for l in lines if not l.strip().startswith("```")
            ).strip()
        if not stripped:
            logger.warning("_ClaudeSDKProvider: empty response from SDK")
            return []
        try:
            decoder = json.JSONDecoder()
            result, _ = decoder.raw_decode(stripped)
            logger.info(
                "_ClaudeSDKProvider.extract_tasks: parsed %s with %d items",
                type(result).__name__,
                len(result) if isinstance(result, list) else -1,
            )
            return result if isinstance(result, list) else []
        except json.JSONDecodeError as exc:
            logger.warning(
                "_ClaudeSDKProvider: response was not valid JSON: %s — first 500 chars: %r",
                exc, stripped[:500],
            )
            return []


def _get_llm(settings: Settings = Depends(get_settings)) -> BaseLLMProvider:
    from core.utilities.llm.mock_provider import MockLLMProvider
    from core.utilities.llm.claude_provider import ClaudeProvider

    if settings.LLM_PROVIDER == "claude":
        return ClaudeProvider(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.LLM_MODEL,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
    if settings.LLM_PROVIDER == "claude-sdk":
        return _ClaudeSDKProvider()
    return MockLLMProvider()


def _get_storage(settings: Settings = Depends(get_settings)) -> BaseStorageProvider:
    from core.utilities.storage.local_provider import LocalStorageProvider
    from core.utilities.storage.gcs_provider import GCSStorageProvider

    if settings.STORAGE_PROVIDER == "gcs":
        return GCSStorageProvider()
    return LocalStorageProvider(base_path=settings.LOCAL_STORAGE_PATH)


@router.post("/upload", response_model=FileOut, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    user_name: Optional[str] = Form(None),
    project_name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    storage: BaseStorageProvider = Depends(_get_storage),
):
    allowed = settings.get_allowed_extensions()
    filename = file.filename or "upload"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in allowed:
        raise HTTPException(
            status_code=422,
            detail={"detail": f"File extension '{ext}' is not allowed.", "code": "INVALID_EXTENSION"},
        )

    raw_bytes = await file.read()
    size_mb = len(raw_bytes) / (1024 * 1024)
    if size_mb > settings.MAX_UPLOAD_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail={"detail": f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB} MB.", "code": "FILE_TOO_LARGE"},
        )

    from datetime import datetime
    now = datetime.utcnow()
    date_str = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%y%m%d%H%M%S")
    project_prefix = project_name.strip().replace(" ", "_") if project_name and project_name.strip() else "general"
    stem, dot_ext = filename.rsplit(".", 1) if "." in filename else (filename, "")
    stored_filename = f"{stem}_{timestamp}.{dot_ext}" if dot_ext else f"{stem}_{timestamp}"
    prefix = f"{settings.GCS_PREFIX}/" if settings.GCS_PREFIX else ""

    # Path: {prefix}/{project}/{date}/{file}
    path_parts = [p for p in [prefix.rstrip("/"), project_prefix, date_str] if p]
    storage_path = "/".join(path_parts) + "/" + stored_filename

    try:
        stored_path = await storage.write(storage_path, raw_bytes)
    except Exception as exc:
        logger.error("Storage write failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"detail": "Failed to store file.", "code": "STORAGE_ERROR"},
        )

    mime_type = MIME_MAP.get(dot_ext, "application/octet-stream")
    storage_location = settings.STORAGE_PROVIDER  # "gcs" | "local"
    source_file = repository.create_source_file(
        db=db,
        filename=filename,
        file_path=stored_path,
        storage_location=storage_location,
        uploaded_by=user_name,
        file_size=len(raw_bytes),
        mime_type=mime_type,
    )
    return FileOut.model_validate(source_file)


@router.get("/find", response_model=FileOut)
async def find_file_by_path(
    path: str = Query(..., description="Storage path to look up"),
    db: Session = Depends(get_db),
):
    source_file = repository.get_source_file_by_path(db, path)
    if source_file is None:
        raise HTTPException(
            status_code=404,
            detail={"detail": "No database record found for that storage path.", "code": "FILE_NOT_FOUND"},
        )
    return FileOut.model_validate(source_file)


class RegisterFileIn(BaseModel):
    file_path: str
    storage_location: str = "gcs"
    user_name: Optional[str] = None
    file_size: Optional[int] = None


class ProgressOut(BaseModel):
    stage: Optional[str] = None
    chunks_done: int = 0
    chunks_total: int = 0
    pct: int = 0


@router.post("/register", response_model=FileOut, status_code=201)
async def register_file(
    body: RegisterFileIn,
    db: Session = Depends(get_db),
):
    """Create a DB record for a file that already exists in storage (find-or-create)."""
    existing = repository.get_source_file_by_path(db, body.file_path)
    if existing:
        return FileOut.model_validate(existing)

    filename = body.file_path.rsplit("/", 1)[-1]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    mime_type = MIME_MAP.get(ext, "application/octet-stream")

    source_file = repository.create_source_file(
        db=db,
        filename=filename,
        file_path=body.file_path,
        storage_location=body.storage_location,
        uploaded_by=body.user_name,
        file_size=body.file_size,
        mime_type=mime_type,
    )
    return FileOut.model_validate(source_file)


@router.get("/projects", response_model=list[str])
async def list_projects(
    settings: Settings = Depends(get_settings),
    storage: BaseStorageProvider = Depends(_get_storage),
):
    """Return unique project/product folder names that exist under the GCS prefix."""
    prefix = (settings.GCS_PREFIX.rstrip("/") + "/") if settings.GCS_PREFIX else ""
    all_files = await storage.list_files(prefix=prefix)
    projects: set[str] = set()
    for f in all_files:
        relative = f["name"][len(prefix):] if f["name"].startswith(prefix) else f["name"]
        first_segment = relative.split("/")[0]
        if first_segment:
            projects.add(first_segment)
    return sorted(projects)


@router.get("/list", response_model=list[dict])
async def list_files(
    project_name: str = Query("", alias="project_name"),
    settings: Settings = Depends(get_settings),
    storage: BaseStorageProvider = Depends(_get_storage),
):
    # Build prefix: {GCS_PREFIX}/{project_name}/ — only include non-empty parts
    parts = [p for p in [settings.GCS_PREFIX, project_name.replace(" ", "_")] if p]
    prefix = "/".join(parts) + "/" if parts else ""
    files = await storage.list_files(prefix=prefix)
    # Exclude virtual folder objects (names ending with /)
    return [f for f in files if not f["name"].endswith("/")]


async def _run_gap_analysis_bg(
    file_ids: list[str],
    primary_file_id: str,
    task_ids: list[str],
    llm,
    storage: BaseStorageProvider,
) -> None:
    """
    Background task: gap analysis runs AFTER extraction returns.
    Analyses ALL tasks (story, task, bug, subtask). Coverage gaps run across all tasks.
    Creates its own DB session (request session is closed by this point).
    """
    from core.requirements_pod.database.session import SessionLocal
    from core.requirements_pod.agents.extraction.agent import _decode_file, normalise_text
    from core.requirements_pod.agents.gap_analysis.agent import (
        analyze_task_gaps_batch,
        analyze_coverage_gaps,
    )

    _gap_progress[primary_file_id] = {
        "status": "running",
        "task_count": len(task_ids),
        "done_count": 0,
    }

    db = SessionLocal()
    try:
        # Re-read and merge transcript text from storage
        parts: list[str] = []
        for fid in file_ids:
            src = repository.get_source_file(db, fid)
            if src is None:
                continue
            try:
                raw = await storage.read(src.file_path)
                text = _decode_file(raw, src.filename)
                parts.append(normalise_text(text))
            except Exception as exc:
                logger.warning("Gap BG: could not read file %s: %s", fid, exc)
        transcript_text = "\n\n---\n\n".join(parts)

        # Load all tasks from DB
        all_tasks = [
            TaskOut.model_validate(t)
            for tid in task_ids
            if (t := repository.get_task(db, tid)) is not None
        ]

        # Gap analysis — all tasks (story, task, bug, subtask)
        if all_tasks:
            gap_reports = await analyze_task_gaps_batch(all_tasks, transcript_text, llm)
            done = 0
            for task_out in all_tasks:
                report_json = gap_reports.get(task_out.task_id)
                if report_json:
                    repository.update_task_gap_report(db, task_out.task_id, report_json)
                done += 1
                _gap_progress[primary_file_id]["done_count"] = done
            logger.info("Gap BG: analysed %d task(s) for file %s", len(all_tasks), primary_file_id)

        # Coverage gaps — all tasks vs transcript
        coverage_json = await analyze_coverage_gaps(all_tasks, transcript_text, llm)
        if coverage_json:
            repository.update_source_file_coverage_gaps(db, primary_file_id, coverage_json)
            logger.info("Gap BG: coverage gaps saved for file %s", primary_file_id)

        _gap_progress[primary_file_id]["status"] = "done"

    except Exception as exc:
        logger.warning("Gap BG: analysis failed for %s: %s", primary_file_id, exc)
        _gap_progress[primary_file_id] = {"status": "error", "task_count": len(task_ids), "done_count": 0}
    finally:
        db.close()


@router.post("/{file_id}/parse", response_model=list[TaskOut])
async def parse_file_endpoint(
    file_id: str,
    background_tasks: BackgroundTasks,
    llm_provider: Optional[str] = Query(None, description="Override LLM provider: 'claude' or 'mock'"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    llm: BaseLLMProvider = Depends(_get_llm),
    storage: BaseStorageProvider = Depends(_get_storage),
):
    if llm_provider == "mock":
        from core.utilities.llm.mock_provider import MockLLMProvider
        llm = MockLLMProvider()
    elif llm_provider == "claude":
        from core.utilities.llm.claude_provider import ClaudeProvider
        llm = ClaudeProvider(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.LLM_MODEL,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
    elif llm_provider == "claude-sdk":
        llm = _ClaudeSDKProvider()

    source_file = repository.get_source_file(db, file_id)
    if source_file is None:
        raise HTTPException(
            status_code=404,
            detail={"detail": f"Source file '{file_id}' not found.", "code": "FILE_NOT_FOUND"},
        )

    try:
        tasks = await parse_file(
            file_id=file_id,
            db=db,
            llm=llm,
            storage=storage,
            settings=settings,
        )
    except LLMAuthError as exc:
        raise HTTPException(status_code=401, detail={"detail": str(exc), "code": "LLM_AUTH_ERROR"})
    except LLMQuotaError as exc:
        raise HTTPException(status_code=402, detail={"detail": str(exc), "code": "LLM_QUOTA_ERROR"})
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail={"detail": str(exc), "code": "PARSE_ERROR"})

    all_ids = [t.task_id for t in tasks]
    if all_ids:
        _gap_progress[file_id] = {"status": "pending", "task_count": len(all_ids), "done_count": 0}
        background_tasks.add_task(_run_gap_analysis_bg, [file_id], file_id, all_ids, llm, storage)

    db_tasks = repository.list_tasks(db, source_file=file_id)
    return [TaskOut.model_validate(t) for t in db_tasks]


class MergeParseIn(BaseModel):
    file_ids: list[str]


@router.post("/parse-merged", response_model=list[TaskOut])
async def parse_merged_endpoint(
    body: MergeParseIn,
    background_tasks: BackgroundTasks,
    llm_provider: Optional[str] = Query(None, description="Override LLM: 'claude' or 'mock'"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    llm: BaseLLMProvider = Depends(_get_llm),
    storage: BaseStorageProvider = Depends(_get_storage),
):
    """Download all listed files, merge their text into one document, extract tasks in a single pass."""
    if not body.file_ids:
        raise HTTPException(status_code=422, detail={"detail": "file_ids must not be empty.", "code": "INVALID_REQUEST"})

    if llm_provider == "mock":
        from core.utilities.llm.mock_provider import MockLLMProvider
        llm = MockLLMProvider()
    elif llm_provider == "claude":
        from core.utilities.llm.claude_provider import ClaudeProvider
        llm = ClaudeProvider(api_key=settings.ANTHROPIC_API_KEY, model=settings.LLM_MODEL, max_tokens=settings.LLM_MAX_TOKENS)
    elif llm_provider == "claude-sdk":
        llm = _ClaudeSDKProvider()

    try:
        tasks = await parse_files_merged(
            file_ids=body.file_ids,
            db=db,
            llm=llm,
            storage=storage,
            settings=settings,
        )
    except LLMAuthError as exc:
        raise HTTPException(status_code=401, detail={"detail": str(exc), "code": "LLM_AUTH_ERROR"})
    except LLMQuotaError as exc:
        raise HTTPException(status_code=402, detail={"detail": str(exc), "code": "LLM_QUOTA_ERROR"})
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail={"detail": str(exc), "code": "PARSE_ERROR"})

    all_ids    = [t.task_id for t in tasks]
    primary_id = body.file_ids[0]
    if all_ids:
        _gap_progress[primary_id] = {"status": "pending", "task_count": len(all_ids), "done_count": 0}
        background_tasks.add_task(_run_gap_analysis_bg, body.file_ids, primary_id, all_ids, llm, storage)

    db_tasks = repository.list_tasks(db, source_file=primary_id)
    return [TaskOut.model_validate(t) for t in db_tasks]


@router.get("/{file_id}/progress", response_model=ProgressOut)
async def get_file_progress(file_id: str):
    """Return live extraction progress for a file currently being parsed."""
    from core.requirements_pod.agents.extraction.agent import get_progress
    data = get_progress(file_id)
    return ProgressOut(**data) if data else ProgressOut()


@router.get("/{file_id}/gap-progress")
async def get_gap_progress(file_id: str):
    """Return gap analysis progress for a file. status: pending|running|done|error|idle."""
    prog = _gap_progress.get(file_id)
    if prog is None:
        return {"file_id": file_id, "status": "idle", "story_count": 0, "done_count": 0}
    result = {"file_id": file_id, **prog}
    # Clear "done" entry once polled — frontend will reload tasks after seeing done
    if prog["status"] == "done":
        _gap_progress.pop(file_id, None)
    return result


@router.post("/{file_id}/gaps/reanalyze")
async def reanalyze_gaps(
    file_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    llm: BaseLLMProvider = Depends(_get_llm),
    storage: BaseStorageProvider = Depends(_get_storage),
):
    """
    Clear cached gap reports for all tasks in a file and re-run gap analysis.
    Returns immediately; progress is trackable via GET /{file_id}/gap-progress.
    """
    src = repository.get_source_file(db, file_id)
    if src is None:
        raise HTTPException(
            status_code=404,
            detail={"detail": f"File '{file_id}' not found.", "code": "FILE_NOT_FOUND"},
        )

    # Already running — don't queue a second analysis
    prog = _gap_progress.get(file_id, {})
    if prog.get("status") in ("pending", "running"):
        return {"file_id": file_id, "status": "already_running", "message": "Gap analysis is already in progress."}

    all_ids = repository.get_all_task_ids_for_file(db, file_id)
    if not all_ids:
        return {"file_id": file_id, "status": "skipped", "message": "No tasks found for this file."}

    # Clear existing gap reports so UI shows spinner while analysis runs
    cleared = repository.reset_gap_reports_for_file(db, file_id)
    logger.info("Reanalyze gaps: cleared %d gap report(s) for file %s", cleared, file_id)

    _gap_progress[file_id] = {"status": "pending", "task_count": len(all_ids), "done_count": 0}
    background_tasks.add_task(
        _run_gap_analysis_bg, [file_id], file_id, all_ids, llm, storage
    )

    return {
        "file_id": file_id,
        "status": "started",
        "task_count": len(all_ids),
        "message": f"Gap analysis started for {len(all_ids)} task(s).",
    }


@router.delete("/storage", status_code=204)
async def delete_storage_file(
    path: str = Query(..., description="Storage path of the file to delete"),
    db: Session = Depends(get_db),
    storage: BaseStorageProvider = Depends(_get_storage),
):
    """Delete a file from storage and remove its DB record (if any)."""
    try:
        await storage.delete(path)
    except Exception as exc:
        logger.warning("Storage delete failed for path '%s': %s", path, exc)
        raise HTTPException(
            status_code=500,
            detail={"detail": f"Failed to delete file from storage: {exc}", "code": "STORAGE_ERROR"},
        )

    source_file = repository.get_source_file_by_path(db, path)
    if source_file:
        repository.delete_source_file(db, source_file.id)


@router.get("/{file_id}/status", response_model=FileOut)
async def get_file_status(
    file_id: str,
    db: Session = Depends(get_db),
):
    source_file = repository.get_source_file(db, file_id)
    if source_file is None:
        raise HTTPException(
            status_code=404,
            detail={"detail": f"Source file '{file_id}' not found.", "code": "FILE_NOT_FOUND"},
        )
    return FileOut.model_validate(source_file)


@router.get("/{file_id}/coverage-gaps")
async def get_coverage_gaps(
    file_id: str,
    db: Session = Depends(get_db),
):
    """Return coverage gaps stored after extraction for a source file."""
    source_file = repository.get_source_file(db, file_id)
    if source_file is None:
        raise HTTPException(
            status_code=404,
            detail={"detail": f"Source file '{file_id}' not found.", "code": "FILE_NOT_FOUND"},
        )
    if not source_file.coverage_gaps:
        return {"file_id": file_id, "gaps": []}
    data = json.loads(source_file.coverage_gaps)
    return {"file_id": file_id, "analyzed_at": data.get("analyzed_at"), "gaps": data.get("gaps", [])}
