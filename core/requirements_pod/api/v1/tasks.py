import csv
import io
import json
import logging
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.requirements_pod.config import Settings, get_settings
from core.requirements_pod.database.session import get_db
from core.requirements_pod.database import repository
from core.requirements_pod.database.schemas.task import TaskOut, TaskUpdate
from core.utilities.scrum_tools.jira import JiraService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    source_file: Optional[str] = Query(None),
    user_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    tasks = repository.list_tasks(db, source_file=source_file, user_name=user_name, status=status)
    return [TaskOut.model_validate(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: str,
    db: Session = Depends(get_db),
):
    task = repository.get_task(db, task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"detail": f"Task '{task_id}' not found.", "code": "TASK_NOT_FOUND"},
        )
    return TaskOut.model_validate(task)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: str,
    data: TaskUpdate,
    db: Session = Depends(get_db),
):
    task = repository.get_task(db, task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"detail": f"Task '{task_id}' not found.", "code": "TASK_NOT_FOUND"},
        )
    if task.status == "deleted":
        raise HTTPException(
            status_code=410,
            detail={"detail": "Cannot update a deleted task.", "code": "TASK_DELETED"},
        )
    updated = repository.update_task(db, task_id, data)

    # Re-run deterministic gap checks so the badge reflects the current field state.
    # Fields that were just filled disappear from field_gaps; existing LLM suggestions
    # are carried forward for fields that are still missing.
    if updated and updated.gap_report:
        from core.requirements_pod.agents.gap_analysis.agent import refresh_task_gap_report
        refreshed = refresh_task_gap_report(updated)
        repository.update_task_gap_report(db, task_id, refreshed)
        updated = repository.get_task(db, task_id)

    return TaskOut.model_validate(updated)


@router.delete("/{task_id}", response_model=TaskOut)
async def delete_task(
    task_id: str,
    db: Session = Depends(get_db),
):
    task = repository.get_task(db, task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail={"detail": f"Task '{task_id}' not found.", "code": "TASK_NOT_FOUND"},
        )
    deleted = repository.soft_delete_task(db, task_id)
    return TaskOut.model_validate(deleted)


class GapApplyBody(BaseModel):
    field: str
    value: Any   # string for most fields; numeric string for story_points


_ALLOWED_GAP_FIELDS = {
    "acceptance_criteria", "schedule_interval", "story_points", "priority", "assignee",
    "description", "due_date", "start_date",
}


@router.get("/{task_id}/gaps")
async def get_task_gaps(
    task_id: str,
    db: Session = Depends(get_db),
):
    """Return the stored gap report for a task."""
    task = repository.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"detail": f"Task '{task_id}' not found.", "code": "TASK_NOT_FOUND"})
    if not task.gap_report:
        return {"task_id": task_id, "gap_report": None}
    return {"task_id": task_id, "gap_report": json.loads(task.gap_report)}


@router.post("/{task_id}/gaps/apply", response_model=TaskOut)
async def apply_gap_suggestion(
    task_id: str,
    body: GapApplyBody,
    db: Session = Depends(get_db),
):
    """Accept a suggested gap fill: updates the task field and marks that gap resolved."""
    if body.field not in _ALLOWED_GAP_FIELDS:
        raise HTTPException(status_code=422, detail={"detail": f"Field '{body.field}' cannot be updated via gap apply.", "code": "INVALID_FIELD"})

    task = repository.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"detail": f"Task '{task_id}' not found.", "code": "TASK_NOT_FOUND"})

    # Coerce value to correct type
    value = body.value
    if body.field == "story_points":
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = None

    update_data = TaskUpdate(**{body.field: value})
    updated = repository.update_task(db, task_id, update_data)

    # Re-run deterministic gap checks — the accepted field is now populated so it
    # disappears from field_gaps naturally, no need to manually flag resolved=True.
    if updated and updated.gap_report:
        from core.requirements_pod.agents.gap_analysis.agent import refresh_task_gap_report
        refreshed = refresh_task_gap_report(updated)
        repository.update_task_gap_report(db, task_id, refreshed)
        updated = repository.get_task(db, task_id)

    return TaskOut.model_validate(updated)


class ExportBody(BaseModel):
    task_ids: list[str]
    format: str = "json"




class JiraPushBody(BaseModel):
    task_ids: list[str]


class JiraPushLinkedBody(BaseModel):
    story_task_id: str       # SRC-XXX id of the story (parent)
    task_ids: list[str]      # SRC-XXX ids of tasks to push and link under the story


@router.post("/export")
async def export_tasks(
    body: ExportBody,
    db: Session = Depends(get_db),
):
    tasks_db = repository.bulk_get_tasks(db, body.task_ids)
    tasks = [TaskOut.model_validate(t) for t in tasks_db]

    fmt = body.format.lower()

    if fmt == "json":
        content = json.dumps([t.model_dump(mode="json") for t in tasks], indent=2)
        media_type = "application/json"
        filename = "tasks.json"
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    elif fmt == "csv":
        output = io.StringIO()
        fieldnames = ["task_id", "task_heading", "description", "task_type", "user_name",
                      "location", "status", "jira_id", "jira_url", "created_at", "updated_at"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for t in tasks:
            row = t.model_dump(mode="json")
            writer.writerow({k: row.get(k, "") for k in fieldnames})
        content = output.getvalue()
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=tasks.csv"},
        )

    elif fmt == "md":
        lines = ["# Exported Tasks\n"]
        for t in tasks:
            lines.append(f"## [{t.task_id}] {t.task_heading}\n")
            lines.append(f"**Type:** {t.task_type.value}  ")
            lines.append(f"**Status:** {t.status.value}  ")
            lines.append(f"**Assigned to:** {t.user_name or 'Unassigned'}  ")
            if t.location:
                lines.append(f"**Location:** {t.location}  ")
            if t.jira_id:
                lines.append(f"**Jira:** [{t.jira_id}]({t.jira_url})  ")
            lines.append("")
            lines.append(t.description or "")
            lines.append("\n---\n")
        content = "\n".join(lines)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="text/markdown",
            headers={"Content-Disposition": "attachment; filename=tasks.md"},
        )

    else:
        raise HTTPException(
            status_code=422,
            detail={"detail": f"Unknown export format: {fmt}", "code": "INVALID_FORMAT"},
        )


@router.post("/jira-push")
async def jira_push(
    body: JiraPushBody,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    tasks_db = repository.bulk_get_tasks(db, body.task_ids)
    jira_service = JiraService()
    results = []

    for task_db in tasks_db:
        task = TaskOut.model_validate(task_db)
        try:
            if task.jira_id:
                push_result = await jira_service.update_existing_task(task, settings)
            else:
                push_result = await jira_service.push_task(task, settings)
            repository.update_task_jira(
                db,
                task.task_id,
                jira_id=push_result["jira_id"],
                jira_url=push_result["jira_url"],
            )
            results.append(
                {
                    "task_id": task.task_id,
                    "success": True,
                    "jira_id": push_result["jira_id"],
                    "jira_url": push_result["jira_url"],
                    "action": push_result["action"],
                }
            )
        except Exception as exc:
            logger.error("Jira push failed for %s: %s", task.task_id, exc)
            results.append(
                {
                    "task_id": task.task_id,
                    "success": False,
                    "error": str(exc),
                }
            )

    return {"results": results}


@router.post("/jira-push-linked")
async def jira_push_linked(
    body: JiraPushLinkedBody,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Push a story + its tasks to Jira, then create issue links from each task to the story.
    The story is pushed first to ensure its Jira key is available for linking.
    """
    jira_service = JiraService()
    results = []

    # ── Step 1: Push / update the story ──────────────────────────────────────
    story_db = repository.get_task(db, body.story_task_id)
    if story_db is None:
        raise HTTPException(
            status_code=404,
            detail={"detail": f"Story task '{body.story_task_id}' not found.", "code": "TASK_NOT_FOUND"},
        )

    story = TaskOut.model_validate(story_db)
    try:
        if story.jira_id:
            story_push = await jira_service.update_existing_task(story, settings)
        else:
            story_push = await jira_service.push_task(story, settings)
        repository.update_task_jira(db, story.task_id, jira_id=story_push["jira_id"], jira_url=story_push["jira_url"])
        story_jira_key = story_push["jira_id"]
        results.append({
            "task_id": story.task_id,
            "role": "story",
            "success": True,
            "jira_id": story_jira_key,
            "jira_url": story_push["jira_url"],
            "action": story_push["action"],
            "linked_to": None,
        })
    except Exception as exc:
        logger.error("Jira push failed for story %s: %s", story.task_id, exc)
        return {"results": [{
            "task_id": story.task_id,
            "role": "story",
            "success": False,
            "error": str(exc),
        }]}

    # ── Step 2: Push each task and link it to the story ───────────────────────
    tasks_db = repository.bulk_get_tasks(db, body.task_ids)
    for task_db in tasks_db:
        task = TaskOut.model_validate(task_db)
        try:
            if task.jira_id:
                push_result = await jira_service.update_existing_task(task, settings)
            else:
                push_result = await jira_service.push_task(task, settings)
            repository.update_task_jira(db, task.task_id, jira_id=push_result["jira_id"], jira_url=push_result["jira_url"])

            # Link the task to the story
            linked = await jira_service.create_issue_link(story_jira_key, push_result["jira_id"], settings)

            results.append({
                "task_id": task.task_id,
                "role": "task",
                "success": True,
                "jira_id": push_result["jira_id"],
                "jira_url": push_result["jira_url"],
                "action": push_result["action"],
                "linked_to": story_jira_key if linked else None,
                "link_warning": None if linked else f"Pushed but could not link to {story_jira_key}",
            })
        except Exception as exc:
            logger.error("Jira push failed for task %s: %s", task.task_id, exc)
            results.append({
                "task_id": task.task_id,
                "role": "task",
                "success": False,
                "error": str(exc),
            })

    return {"story_jira_key": story_jira_key, "results": results}
