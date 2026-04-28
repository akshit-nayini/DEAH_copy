import json
import logging
from datetime import datetime
from typing import Any
import httpx

logger = logging.getLogger(__name__)

_JIRA_PRIORITY_MAP = {
    "critical": "Highest",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}


def _parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def _get_req_fields(task: Any) -> dict:
    """Read requirement fields from raw_llm_json metadata."""
    raw = getattr(task, "raw_llm_json", None) or "{}"
    try:
        meta = json.loads(raw)
    except Exception:
        meta = {}
    return {
        "project_name": meta.get("project_name") or "",
        "requirement_type": meta.get("requirement_type") or "",
        "stakeholder_name": meta.get("stakeholder_name") or "",
        "objective": meta.get("objective") or "",
        "expected_outcome": meta.get("expected_outcome") or "",
        "connections_db_details": meta.get("connections_db_details") or "",
        "success_conditions": meta.get("success_conditions") or [],
        "validation_rules": meta.get("validation_rules") or [],
    }


# ── ADF helpers ──────────────────────────────────────────────────────────────

def _adf_heading(text: str, level: int = 3) -> dict:
    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": [{"type": "text", "text": text}],
    }


def _adf_paragraph(text: str, bold: bool = False) -> dict:
    node: dict = {"type": "text", "text": text}
    if bold:
        node["marks"] = [{"type": "strong"}]
    return {"type": "paragraph", "content": [node]}


def _adf_bullet_list(items: list[str]) -> dict:
    return {
        "type": "bulletList",
        "content": [
            {
                "type": "listItem",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": item}]}],
            }
            for item in items
        ],
    }


def _description_to_adf(description: str) -> dict:
    """
    Convert the structured description text (built by output.py) into ADF.
    Handles:
      ## Heading     → ADF heading level 3
      **Bold:**      → ADF paragraph with bold mark
      - bullet item  → ADF bulletList
      plain text     → ADF paragraph
    This is the single source of truth — no separate field reading needed.
    """
    content: list[dict] = []
    lines = description.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("## "):
            content.append(_adf_heading(stripped[3:], level=3))

        elif stripped.startswith("**") and stripped.endswith("**"):
            # e.g. **Success Conditions:**
            label = stripped.strip("*").rstrip(":")
            content.append(_adf_paragraph(label + ":", bold=True))

        elif stripped.startswith("- "):
            # Collect all consecutive bullet lines
            items: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:])
                i += 1
            content.append(_adf_bullet_list(items))
            continue  # already advanced i

        elif stripped:
            content.append(_adf_paragraph(stripped))

        i += 1

    if not content:
        content.append(_adf_paragraph(""))

    return {"version": 1, "type": "doc", "content": content}


def _build_fields(task: Any, settings: Any, include_project: bool = False) -> dict:
    issue_type_map = settings.get_jira_issue_type_map()
    issue_type_name = issue_type_map.get(task.task_type.value, "Task")

    # description column already contains all structured sections — convert directly to ADF
    fields: dict = {
        "summary": task.task_heading,
        "description": _description_to_adf(getattr(task, "description", "") or ""),
        "issuetype": {"name": issue_type_name},
    }

    if include_project:
        fields["project"] = {"key": settings.JIRA_PROJECT_KEY}

    priority = getattr(task, "priority", None)
    if priority:
        fields["priority"] = {"name": _JIRA_PRIORITY_MAP.get(priority, "Medium")}

    story_points = getattr(task, "story_points", None)
    if story_points is not None:
        fields["customfield_10016"] = story_points

    fix_version = getattr(task, "fix_version", None)
    if fix_version:
        fields["fixVersions"] = [{"name": fix_version}]

    sprint = getattr(task, "sprint", None)
    if sprint:
        fields.setdefault("labels", [])
        fields["labels"].append(f"sprint:{sprint.replace(' ', '-')}")

    return fields


def _build_md_attachment(task: Any) -> str:
    """
    MD attachment mirrors exactly what appears in the Jira description.
    task.description already contains the full structured content.
    """
    task_id = getattr(task, "task_id", "")
    heading = getattr(task, "task_heading", "")
    priority = getattr(task, "priority", "") or ""
    task_type = str(getattr(task, "task_type", ""))
    description = getattr(task, "description", "") or ""

    lines = [
        f"# {heading}",
        f"**Task ID:** {task_id}  |  **Priority:** {priority}  |  **Type:** {task_type}",
        "",
        description,
        "",
        "---",
        f"*Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*",
    ]
    return "\n".join(lines)


def _build_json_attachment(task: Any) -> str:
    """
    JSON attachment contains the same structured fields as the Jira description.
    Reads structured fields from raw_llm_json for clean key/value pairs.
    """
    req = _get_req_fields(task)
    success_conditions = req["success_conditions"]
    validation_rules = req["validation_rules"]
    ac = _parse_json_list(getattr(task, "acceptance_criteria", None))

    payload = {
        "task_id": getattr(task, "task_id", ""),
        "task_heading": getattr(task, "task_heading", ""),
        "priority": getattr(task, "priority", None) or "",
        "task_type": str(getattr(task, "task_type", "")),
        "story_points": getattr(task, "story_points", None),
        "reporter": getattr(task, "reporter", None) or "",
        "sprint": getattr(task, "sprint", None) or "",
        "fix_version": getattr(task, "fix_version", None) or "",
        "project_name": req["project_name"],
        "requirement_type": req["requirement_type"],
        "stakeholder_name": req["stakeholder_name"],
        "objective": req["objective"],
        "description": getattr(task, "description", None) or "",
        "expected_outcome": req["expected_outcome"],
        "connections_db_details": req["connections_db_details"],
        "acceptance_criteria": {
            "success_conditions": success_conditions,
            "validation_rules": validation_rules,
            "other": ac if not (success_conditions or validation_rules) else [],
        },
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return json.dumps(payload, indent=2)


class JiraService:
    async def _attach_files(self, jira_id: str, task: Any, settings: Any) -> None:
        """Attach MD and JSON requirement files to a Jira issue."""
        task_id = getattr(task, "task_id", jira_id)
        md_content = _build_md_attachment(task)
        json_content = _build_json_attachment(task)

        auth = (settings.JIRA_EMAIL, settings.JIRA_API_TOKEN)
        url = f"{settings.JIRA_BASE_URL}/rest/api/3/issue/{jira_id}/attachments"
        headers = {"X-Atlassian-Token": "no-check"}

        async with httpx.AsyncClient(timeout=30) as client:
            for filename, content, mime in [
                (f"{task_id}_requirements.md", md_content.encode("utf-8"), "text/markdown"),
                (f"{task_id}_requirements.json", json_content.encode("utf-8"), "application/json"),
            ]:
                response = await client.post(
                    url,
                    headers=headers,
                    auth=auth,
                    files={"file": (filename, content, mime)},
                )
                if response.status_code not in (200, 201):
                    logger.warning(
                        "Jira attachment upload failed for %s (%s): HTTP %d — %s",
                        jira_id, filename, response.status_code, response.text[:200],
                    )
                else:
                    logger.info("Attached %s to Jira issue %s", filename, jira_id)

    async def push_task(self, task: Any, settings: Any) -> dict:
        """Create a new Jira issue, attach MD+JSON files, return {jira_id, jira_url, action}."""
        payload = {"fields": _build_fields(task, settings, include_project=True)}
        auth = (settings.JIRA_EMAIL, settings.JIRA_API_TOKEN)
        url = f"{settings.JIRA_BASE_URL}/rest/api/3/issue"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, auth=auth)

        if response.status_code not in (200, 201):
            logger.error(
                "Jira create failed for task %s: HTTP %d — %s",
                task.task_id, response.status_code, response.text[:500],
            )
            raise RuntimeError(
                f"Jira API returned {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        jira_id = data.get("key", "")
        jira_url = f"{settings.JIRA_BASE_URL}/browse/{jira_id}" if jira_id else ""

        if jira_id:
            await self._attach_files(jira_id, task, settings)

        return {"jira_id": jira_id, "jira_url": jira_url, "action": "created"}

    async def update_existing_task(self, task: Any, settings: Any) -> dict:
        """Update existing Jira issue, re-attach MD+JSON files, return {jira_id, jira_url, action}."""
        payload = {"fields": _build_fields(task, settings, include_project=False)}
        auth = (settings.JIRA_EMAIL, settings.JIRA_API_TOKEN)
        url = f"{settings.JIRA_BASE_URL}/rest/api/3/issue/{task.jira_id}"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.put(url, json=payload, auth=auth)

        if response.status_code not in (200, 204):
            logger.error(
                "Jira update failed for task %s (issue %s): HTTP %d — %s",
                task.task_id, task.jira_id, response.status_code, response.text[:500],
            )
            raise RuntimeError(
                f"Jira API returned {response.status_code}: {response.text[:200]}"
            )

        await self._attach_files(task.jira_id, task, settings)

        return {"jira_id": task.jira_id, "jira_url": task.jira_url, "action": "updated"}
