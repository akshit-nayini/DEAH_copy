"""
JiraService for the requirements POD — creates/updates Jira issues via REST API v3
and attaches structured MD + JSON requirement files to each issue.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any
import httpx

logger = logging.getLogger(__name__)

_JIRA_PRIORITY_MAP = {
    "critical": "Highest",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}


def _lower(val: str | None) -> str:
    """Lowercase a string value, returning empty string for None."""
    return (val or "").lower()


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
    content: list[dict] = []
    lines = description.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("## "):
            content.append(_adf_heading(stripped[3:], level=3))

        elif stripped.startswith("**") and stripped.endswith("**"):
            label = stripped.strip("*").rstrip(":")
            content.append(_adf_paragraph(label + ":", bold=True))

        elif stripped.startswith("- "):
            items: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:])
                i += 1
            content.append(_adf_bullet_list(items))
            continue

        elif stripped:
            content.append(_adf_paragraph(stripped))

        i += 1

    if not content:
        content.append(_adf_paragraph(""))

    return {"version": 1, "type": "doc", "content": content}


def _build_fields(task: Any, settings: Any, include_project: bool = False) -> dict:
    issue_type_map = settings.get_jira_issue_type_map()
    issue_type_name = issue_type_map.get(task.task_type.value, "Task")

    fields: dict = {
        "summary": _lower(task.task_heading),
        "description": _description_to_adf(_lower(getattr(task, "description", ""))),
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
        fields["fixVersions"] = [{"name": _lower(fix_version)}]

    sprint = getattr(task, "sprint", None)
    if sprint:
        fields.setdefault("labels", [])
        fields["labels"].append(f"sprint:{_lower(sprint).replace(' ', '-')}")

    due_date = getattr(task, "due_date", None)
    if due_date:
        if isinstance(due_date, datetime):
            fields["duedate"] = due_date.strftime("%Y-%m-%d")
        elif isinstance(due_date, str):
            fields["duedate"] = due_date[:10]

    start_date = getattr(task, "start_date", None)
    start_field = getattr(settings, "JIRA_START_DATE_FIELD", None)
    if start_date and start_field:
        # Only send start date when JIRA_START_DATE_FIELD is explicitly configured.
        # The default customfield_10015 is often restricted to Epics; omitting it
        # prevents 400 errors on Task/Story issue types.
        if isinstance(start_date, datetime):
            fields[start_field] = start_date.strftime("%Y-%m-%d")
        elif isinstance(start_date, str):
            fields[start_field] = start_date[:10]

    return fields


def _build_md_attachment(task: Any) -> str:
    task_id = getattr(task, "task_id", "")
    heading = _lower(getattr(task, "task_heading", ""))
    priority = _lower(getattr(task, "priority", "") or "")
    task_type = _lower(str(getattr(task, "task_type", "")))
    description = _lower(getattr(task, "description", "") or "")

    lines = [
        f"# {heading}",
        f"**task id:** {task_id}  |  **priority:** {priority}  |  **type:** {task_type}",
        "",
        description,
        "",
        "---",
        f"*generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
    ]
    return "\n".join(lines)


def _build_json_attachment(task: Any) -> str:
    req = _get_req_fields(task)
    success_conditions = req["success_conditions"]
    validation_rules = req["validation_rules"]
    ac = _parse_json_list(getattr(task, "acceptance_criteria", None))

    payload = {
        "task_id": getattr(task, "task_id", ""),
        "task_heading": _lower(getattr(task, "task_heading", "")),
        "priority": _lower(getattr(task, "priority", None) or ""),
        "task_type": _lower(str(getattr(task, "task_type", ""))),
        "story_points": getattr(task, "story_points", None),
        "reporter": _lower(getattr(task, "reporter", None) or ""),
        "sprint": _lower(getattr(task, "sprint", None) or ""),
        "fix_version": _lower(getattr(task, "fix_version", None) or ""),
        "project_name": _lower(req["project_name"]),
        "requirement_type": _lower(req["requirement_type"]),
        "stakeholder_name": _lower(req["stakeholder_name"]),
        "objective": _lower(req["objective"]),
        "description": _lower(getattr(task, "description", None) or ""),
        "expected_outcome": _lower(req["expected_outcome"]),
        "connections_db_details": _lower(req["connections_db_details"]),
        "acceptance_criteria": {
            "success_conditions": [_lower(s) for s in success_conditions],
            "validation_rules": [_lower(r) for r in validation_rules],
            "other": [_lower(a) for a in ac] if not (success_conditions or validation_rules) else [],
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return json.dumps(payload, indent=2)


class JiraService:
    async def _resolve_account_id(
        self,
        name: str,
        auth: tuple[str, str],
        base_url: str,
        client: httpx.AsyncClient,
    ) -> str | None:
        """Return the Jira accountId for a display name or email, or None if not found."""
        if not name:
            return None
        try:
            response = await client.get(
                f"{base_url}/rest/api/3/user/search",
                params={"query": name, "maxResults": 1},
                auth=auth,
            )
            if response.status_code == 200:
                users = response.json()
                if users:
                    return users[0].get("accountId")
        except Exception:
            logger.warning("Failed to resolve Jira accountId for %r", name)
        return None

    async def _delete_existing_attachments(
        self,
        jira_id: str,
        filenames: set[str],
        auth: tuple[str, str],
        client: httpx.AsyncClient,
        base_url: str,
    ) -> None:
        """Delete attachments on a Jira issue whose filenames match the given set."""
        response = await client.get(
            f"{base_url}/rest/api/3/issue/{jira_id}",
            params={"fields": "attachment"},
            auth=auth,
        )
        if response.status_code != 200:
            logger.warning("Could not list attachments for %s: HTTP %d", jira_id, response.status_code)
            return
        for att in response.json().get("fields", {}).get("attachment", []):
            if att.get("filename") in filenames:
                del_resp = await client.delete(
                    f"{base_url}/rest/api/3/attachment/{att['id']}",
                    auth=auth,
                )
                if del_resp.status_code == 204:
                    logger.info("Deleted old attachment %s from %s", att["filename"], jira_id)
                else:
                    logger.warning(
                        "Failed to delete attachment %s from %s: HTTP %d",
                        att["filename"], jira_id, del_resp.status_code,
                    )

    async def _attach_files(
        self, jira_id: str, task: Any, settings: Any, client: httpx.AsyncClient, replace: bool = False
    ) -> None:
        """Attach MD and JSON requirement files to a Jira issue.

        When replace=True, existing attachments with the same filenames are deleted first.
        """
        task_id = getattr(task, "task_id", jira_id)
        md_content = _build_md_attachment(task)
        json_content = _build_json_attachment(task)

        auth = (settings.JIRA_EMAIL, settings.JIRA_API_KEY)
        filenames = {f"{task_id}_requirements.md", f"{task_id}_requirements.json"}

        if replace:
            await self._delete_existing_attachments(jira_id, filenames, auth, client, settings.JIRA_BASE_URL)

        url = f"{settings.JIRA_BASE_URL}/rest/api/3/issue/{jira_id}/attachments"
        headers = {"X-Atlassian-Token": "no-check"}

        for filename, content, mime in [
            (f"{task_id}_requirements.md", md_content.encode("utf-8"), "text/markdown"),
            (f"{task_id}_requirements.json", json_content.encode("utf-8"), "application/json"),
        ]:
            response = await client.post(
                url, headers=headers, auth=auth,
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
        auth = (settings.JIRA_EMAIL, settings.JIRA_API_KEY)

        async with httpx.AsyncClient(timeout=30) as client:
            fields = _build_fields(task, settings, include_project=True)

            assignee = getattr(task, "assignee", None)
            if assignee:
                aid = await self._resolve_account_id(assignee, auth, settings.JIRA_BASE_URL, client)
                if aid:
                    fields["assignee"] = {"accountId": aid}
                else:
                    logger.warning("Could not resolve Jira accountId for assignee %r — field omitted", assignee)

            response = await client.post(
                f"{settings.JIRA_BASE_URL}/rest/api/3/issue",
                json={"fields": fields},
                auth=auth,
            )

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
                await self._attach_files(jira_id, task, settings, client)

        return {"jira_id": jira_id, "jira_url": jira_url, "action": "created"}

    async def update_existing_task(self, task: Any, settings: Any) -> dict:
        """Update existing Jira issue, re-attach MD+JSON files, return {jira_id, jira_url, action}."""
        auth = (settings.JIRA_EMAIL, settings.JIRA_API_KEY)

        async with httpx.AsyncClient(timeout=30) as client:
            fields = _build_fields(task, settings, include_project=False)

            assignee = getattr(task, "assignee", None)
            if assignee:
                aid = await self._resolve_account_id(assignee, auth, settings.JIRA_BASE_URL, client)
                if aid:
                    fields["assignee"] = {"accountId": aid}
                else:
                    logger.warning("Could not resolve Jira accountId for assignee %r — field omitted", assignee)

            response = await client.put(
                f"{settings.JIRA_BASE_URL}/rest/api/3/issue/{task.jira_id}",
                json={"fields": fields},
                auth=auth,
            )

            if response.status_code not in (200, 204):
                logger.error(
                    "Jira update failed for task %s (issue %s): HTTP %d — %s",
                    task.task_id, task.jira_id, response.status_code, response.text[:500],
                )
                raise RuntimeError(
                    f"Jira API returned {response.status_code}: {response.text[:200]}"
                )

            await self._attach_files(task.jira_id, task, settings, client, replace=True)

        return {"jira_id": task.jira_id, "jira_url": task.jira_url, "action": "updated"}

    async def create_issue_link(self, story_jira_key: str, task_jira_key: str, settings: Any) -> bool:
        """Create a 'relates to' issue link between a task and a story. Returns True on success."""
        payload = {
            "type": {"name": "Relates"},
            "inwardIssue": {"key": task_jira_key},
            "outwardIssue": {"key": story_jira_key},
        }
        auth = (settings.JIRA_EMAIL, settings.JIRA_API_KEY)
        url = f"{settings.JIRA_BASE_URL}/rest/api/3/issueLink"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, auth=auth)

        if response.status_code not in (200, 201, 204):
            logger.warning(
                "Jira issue link failed (%s → %s): HTTP %d — %s",
                task_jira_key, story_jira_key, response.status_code, response.text[:200],
            )
            return False

        logger.info("Linked %s → %s in Jira", task_jira_key, story_jira_key)
        return True
