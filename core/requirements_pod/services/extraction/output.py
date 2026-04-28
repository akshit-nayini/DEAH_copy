"""Stage 9 — Output normalisation: map pipeline fields to the existing DB/schema types."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from .temporal import TemporalTask


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO date string (YYYY-MM-DD) to datetime, return None on failure."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None

# Maps new pipeline issuetype values to the existing task_type enum values
_ISSUETYPE_TO_TASK_TYPE: dict[str, str] = {
    "Bug": "bug",
    "Story": "story",
    "Task": "task",
    "Sub-task": "task",  # subtasks not supported; demote to task
    "Epic": "story",     # closest existing equivalent
}


_PRIORITY_NORM: dict[str, str] = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
}


def _build_description_text(task: TemporalTask) -> str:
    """
    Build a single structured description string that includes all mandatory
    requirement fields.  This is stored in the description column so the UI,
    Jira description, and attachments all show identical content.
    """
    lines: list[str] = []

    # ── Project / stakeholder / assignee header ───────────────────────────────
    if task.project_name:
        lines.append(f"Project Name: {task.project_name}")
    if task.requirement_type:
        lines.append(f"Requirement Type: {task.requirement_type}")
    if task.stakeholder_name:
        lines.append(f"Stakeholder: {task.stakeholder_name}")
    if getattr(task, "assignee", None):
        lines.append(f"Assignee: {task.assignee}")
    if getattr(task, "schedule_interval", None):
        lines.append(f"Schedule Interval: {task.schedule_interval}")
    if getattr(task, "start_date", None):
        lines.append(f"Start Date: {task.start_date}")
    if getattr(task, "due_date", None):
        lines.append(f"Due Date: {task.due_date}")
    if lines:
        lines.append("")

    # ── Objective ────────────────────────────────────────────────────────────
    if task.objective:
        lines += ["## Objective", task.objective, ""]

    # ── Description (no heading — avoids duplicate with Jira's own label) ────
    if task.description:
        lines += [task.description, ""]

    # ── Expected Outcome ─────────────────────────────────────────────────────
    if task.expected_outcome:
        lines += ["## Expected Outcome", task.expected_outcome, ""]

    # ── Connections and DB Details ────────────────────────────────────────────
    if task.connections_db_details:
        lines += ["## Connections and DB Details", task.connections_db_details, ""]

    # ── Acceptance Criteria ──────────────────────────────────────────────────
    if task.success_conditions or task.validation_rules:
        lines.append("## Acceptance Criteria")
        if task.success_conditions:
            lines.append("**Success Conditions:**")
            for sc in task.success_conditions:
                lines.append(f"- {sc}")
        if task.validation_rules:
            lines.append("**Validation Rules:**")
            for vr in task.validation_rules:
                lines.append(f"- {vr}")
        lines.append("")

    # Fall back to plain description if nothing was built
    result = "\n".join(lines).strip()
    return result if result else (task.description or "")


def to_db_fields(
    task: TemporalTask,
    source_file_id: str,
    user_name: Optional[str],
    task_source: Optional[str],
) -> dict:
    """Return keyword arguments for repository.create_task() from a scored pipeline task."""
    task_type = _ISSUETYPE_TO_TASK_TYPE.get(task.issuetype, "task")
    priority = _PRIORITY_NORM.get((task.priority or "").lower(), "medium")
    ac_json = json.dumps(task.acceptance_criteria) if task.acceptance_criteria else None

    # Rich description stored in DB — shown in UI, Jira, and attachments
    structured_description = _build_description_text(task)

    metadata = {
        "confidence": task.confidence,
        "cluster_size": task.cluster_size,
        "source_indices": task.source_indices,
        "overrode_count": task.overrode_count,
        "labels": task.labels,
        "temporal_markers": task.temporal_markers,
        # Requirement fields kept in metadata for structured ADF rendering in Jira
        "project_name": task.project_name,
        "requirement_type": task.requirement_type,
        "stakeholder_name": task.stakeholder_name,
        "objective": task.objective,
        "expected_outcome": task.expected_outcome,
        "connections_db_details": task.connections_db_details,
        "success_conditions": task.success_conditions,
        "validation_rules": task.validation_rules,
        "assumed_fields": task.assumed_fields,
    }

    return {
        "task_heading": task.summary,
        "description": structured_description,
        "task_type": task_type,
        "user_name": user_name,
        "task_source": task_source,
        "source_file_id": source_file_id,
        "location": None,
        "raw_llm_json": json.dumps(metadata),
        "priority": priority,
        "reporter": task.reporter,
        "sprint": task.sprint,
        "fix_version": task.fix_version,
        "story_points": task.story_points if task.story_points else None,
        "acceptance_criteria": ac_json,
        "confidence_score": task.confidence,
        "schedule_interval": task.schedule_interval,
        "assignee": getattr(task, "assignee", None),
        "start_date": _parse_date(getattr(task, "start_date", None)),
        "due_date": _parse_date(getattr(task, "due_date", None)),
    }
