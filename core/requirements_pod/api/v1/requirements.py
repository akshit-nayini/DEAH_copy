import json
import logging
import re
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.requirements_pod.agents.extraction import parse_file
from core.requirements_pod.agents.extraction.exceptions import LLMAuthError, LLMQuotaError
from core.requirements_pod.config import Settings, get_settings
from core.requirements_pod.database import repository
from core.requirements_pod.database.schemas.task import TaskOut
from core.requirements_pod.database.session import get_db
from core.utilities.scrum_tools.jira import JiraService
from core.utilities.storage.base import BaseStorageProvider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/requirements", tags=["requirements"])


# ── Request models ─────────────────────────────────────────────────────────────

class GitHubSource(BaseModel):
    org: str
    repo: str
    branch: str = "main"
    file_path: str
    pat_token: Optional[str] = None


class GoogleDriveSource(BaseModel):
    drive_url_or_id: str
    oauth_token: str


class ProcessRequirementsRequest(BaseModel):
    session_id: str
    document_source: str  # GITHUB | GOOGLE_DRIVE
    github_source: Optional[GitHubSource] = None
    google_drive_source: Optional[GoogleDriveSource] = None
    additional_context: Optional[str] = None


class PushToJiraRequest(BaseModel):
    task_ids: list[str]


# ── Document fetchers ──────────────────────────────────────────────────────────

async def _fetch_github(src: GitHubSource) -> tuple[str, bytes]:
    url = f"https://api.github.com/repos/{src.org}/{src.repo}/contents/{src.file_path}"
    headers = {"Accept": "application/vnd.github.v3.raw"}
    if src.pat_token:
        headers["Authorization"] = f"Bearer {src.pat_token}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=headers, params={"ref": src.branch})
    if resp.status_code == 404:
        raise HTTPException(404, {"detail": "File not found in GitHub repository.", "code": "GITHUB_NOT_FOUND"})
    if resp.status_code in (401, 403):
        raise HTTPException(403, {"detail": "GitHub access denied. Check PAT token.", "code": "GITHUB_AUTH_ERROR"})
    resp.raise_for_status()
    filename = src.file_path.rsplit("/", 1)[-1]
    return filename, resp.content


async def _fetch_drive(src: GoogleDriveSource) -> tuple[str, bytes]:
    match = re.search(r"(?:d|folders)/([a-zA-Z0-9_-]+)", src.drive_url_or_id)
    file_id = match.group(1) if match else src.drive_url_or_id
    headers = {"Authorization": f"Bearer {src.oauth_token}"}
    async with httpx.AsyncClient(timeout=60) as client:
        meta = await client.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            headers=headers,
            params={"fields": "mimeType,name"},
        )
        if meta.status_code == 404:
            raise HTTPException(404, {"detail": "File not found in Google Drive.", "code": "DRIVE_NOT_FOUND"})
        if meta.status_code in (401, 403):
            raise HTTPException(meta.status_code, {"detail": "Google Drive access denied.", "code": "DRIVE_AUTH_ERROR"})
        meta.raise_for_status()
        info = meta.json()
        mime = info.get("mimeType", "")
        name = info.get("name", "document.txt")
        if mime.startswith("application/vnd.google-apps"):
            resp = await client.get(
                f"https://www.googleapis.com/drive/v3/files/{file_id}/export",
                headers=headers,
                params={"mimeType": "text/plain"},
            )
        else:
            resp = await client.get(
                f"https://www.googleapis.com/drive/v3/files/{file_id}",
                headers=headers,
                params={"alt": "media"},
            )
    resp.raise_for_status()
    if not any(name.endswith(ext) for ext in (".txt", ".md", ".pdf", ".docx", ".vtt", ".srt")):
        name = name + ".txt"
    return name, resp.content


# ── Response builder ───────────────────────────────────────────────────────────

_PRIORITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _build_agent_response(tasks: list[TaskOut], session_id: str) -> dict:
    jira_tickets = []
    all_ac: list[str] = []
    max_priority: Optional[str] = None
    total_sp = 0
    teams: set[str] = set()

    for t in tasks:
        ac: list[str] = []
        if t.acceptance_criteria:
            try:
                ac = json.loads(t.acceptance_criteria)
            except Exception:
                ac = [t.acceptance_criteria]
        all_ac.extend(ac)

        p = (t.priority or "").lower()
        if p in _PRIORITY_RANK:
            if max_priority is None or _PRIORITY_RANK[p] > _PRIORITY_RANK[max_priority]:
                max_priority = p

        if t.story_points:
            total_sp += t.story_points
        if t.user_name:
            teams.add(t.user_name)

        jira_tickets.append({
            "pod_task_id": t.task_id,
            "issue_key": t.jira_id,
            "jira_url": t.jira_url,
            "issue_type": t.task_type or "task",
            "summary": t.task_heading,
            "description": t.description,
            "priority": t.priority,
            "story_points": t.story_points,
            "labels": [],
            "acceptance_criteria": ac,
            "sprint_target": t.sprint,
            "parent_epic_key": None,
        })

    key_reqs = [t.task_heading for t in tasks if t.task_heading]
    task_types = [t.task_type for t in tasks if t.task_type]
    feature_type = max(set(task_types), key=task_types.count) if task_types else None

    executive_summary: Optional[str] = None
    if key_reqs:
        preview = "; ".join(key_reqs[:3])
        suffix = f" (and {len(key_reqs) - 3} more)" if len(key_reqs) > 3 else ""
        executive_summary = f"{len(tasks)} task(s) extracted: {preview}{suffix}"

    estimated_effort = f"{total_sp} story points" if total_sp else None
    assigned_team = ", ".join(sorted(teams)) if teams else None

    return {
        "success": True,
        "session_id": session_id,
        "data": {
            "session_id": session_id,
            "status": "success",
            "jira_tickets": jira_tickets,
            "requirements_document": {
                "project_name": session_id,
                "feature_type": feature_type,
                "executive_summary": executive_summary,
                "key_requirements": key_reqs,
                "acceptance_criteria": all_ac,
                "priority": max_priority,
                "estimated_effort": estimated_effort,
                "assigned_team": assigned_team,
                "stakeholders": [],
                "tags": [],
                "decisions_made": [],
                "action_items": [],
            },
            "processed_at": datetime.utcnow().isoformat(),
            "agent_duration_ms": 0,
        },
    }


# ── Provider helpers (mirrors files.py) ───────────────────────────────────────

def _get_llm(settings: Settings = Depends(get_settings)):
    from core.requirements_pod.api.v1.files import _ClaudeSDKProvider
    from core.utilities.llm.claude_provider import ClaudeProvider
    from core.utilities.llm.mock_provider import MockLLMProvider

    provider = settings.LLM_PROVIDER
    if provider == "claude":
        return ClaudeProvider(api_key=settings.ANTHROPIC_API_KEY, model=settings.LLM_MODEL, max_tokens=settings.LLM_MAX_TOKENS)
    if provider in ("claude-sdk", "claude-code-sdk"):
        return _ClaudeSDKProvider()
    return MockLLMProvider()


def _get_storage(settings: Settings = Depends(get_settings)) -> BaseStorageProvider:
    from core.utilities.storage.gcs_provider import GCSStorageProvider
    from core.utilities.storage.local_provider import LocalStorageProvider

    if settings.STORAGE_PROVIDER == "gcs":
        return GCSStorageProvider()
    return LocalStorageProvider(base_path=settings.LOCAL_STORAGE_PATH)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/process")
async def process_requirements(
    body: ProcessRequirementsRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    llm=Depends(_get_llm),
    storage: BaseStorageProvider = Depends(_get_storage),
):
    src = body.document_source.upper()
    if src == "GITHUB":
        if not body.github_source:
            raise HTTPException(422, {"detail": "github_source is required.", "code": "MISSING_SOURCE"})
        filename, content = await _fetch_github(body.github_source)
    elif src == "GOOGLE_DRIVE":
        if not body.google_drive_source:
            raise HTTPException(422, {"detail": "google_drive_source is required.", "code": "MISSING_SOURCE"})
        filename, content = await _fetch_drive(body.google_drive_source)
    else:
        raise HTTPException(422, {"detail": f"Unsupported document_source: {body.document_source}", "code": "INVALID_SOURCE"})

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
    if ext not in settings.get_allowed_extensions():
        ext = "txt"
        filename = filename + ".txt"

    from core.requirements_pod.api.v1.files import MIME_MAP
    now = datetime.utcnow()
    timestamp = now.strftime("%y%m%d%H%M%S")
    date_str = now.strftime("%Y-%m-%d")
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    stored_filename = f"{stem}_{timestamp}.{ext}"
    prefix = (settings.GCS_PREFIX.rstrip("/") + "/") if settings.GCS_PREFIX else ""
    storage_path = f"{prefix}{body.session_id}/{date_str}/{stored_filename}"

    raw = content if isinstance(content, bytes) else content.encode()
    try:
        stored_path = await storage.write(storage_path, raw)
    except Exception as exc:
        logger.error("Storage write failed: %s", exc)
        raise HTTPException(500, {"detail": "Failed to store document.", "code": "STORAGE_ERROR"})

    source_file = repository.create_source_file(
        db=db,
        filename=filename,
        file_path=stored_path,
        storage_location=settings.STORAGE_PROVIDER,
        uploaded_by=body.session_id,
        file_size=len(raw),
        mime_type=MIME_MAP.get(ext, "application/octet-stream"),
    )

    try:
        await parse_file(file_id=source_file.id, db=db, llm=llm, storage=storage, settings=settings)
    except LLMAuthError as exc:
        raise HTTPException(401, {"detail": str(exc), "code": "LLM_AUTH_ERROR"})
    except LLMQuotaError as exc:
        raise HTTPException(402, {"detail": str(exc), "code": "LLM_QUOTA_ERROR"})
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(500, {"detail": str(exc), "code": "PARSE_ERROR"})

    task_outs = [TaskOut.model_validate(t) for t in repository.list_tasks(db, source_file=source_file.id)]
    return _build_agent_response(task_outs, body.session_id)


@router.post("/push-to-jira")
async def push_to_jira(
    body: PushToJiraRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    jira = JiraService()
    results = []
    for task_id in body.task_ids:
        task = repository.get_task(db, task_id)
        if task is None:
            results.append({"task_id": task_id, "success": False, "error": "Task not found"})
            continue
        try:
            if task.jira_id:
                push_result = await jira.update_existing_task(task, settings)
            else:
                push_result = await jira.push_task(task, settings)
            repository.update_task_jira(db, task_id, jira_id=push_result["jira_id"], jira_url=push_result["jira_url"])
            results.append({
                "task_id": task_id,
                "success": True,
                "jira_id": push_result["jira_id"],
                "jira_url": push_result["jira_url"],
                "action": push_result.get("action", "created"),
            })
        except Exception as exc:
            logger.error("Jira push failed for task %s: %s", task_id, exc)
            results.append({"task_id": task_id, "success": False, "error": str(exc)})
    return {"success": True, "data": results}
