# gathering/tools.py
"""
Tool definitions (for Claude's tool-use API) and their Python implementations.
Delegates to ScrumTool (base_scurm.py) which routes to jira_utility.py,
replacing the direct jira_rw.py dependency.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Load base_scurm.py from its absolute path — avoids sys.path manipulation
_base_scurm_path = Path(__file__).resolve().parents[4] / "utilities" / "scrum_tools" / "base_scurm.py"
_spec = importlib.util.spec_from_file_location("base_scurm", _base_scurm_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ScrumTool = _mod.ScrumTool


# ── Jira connection context ───────────────────────────────────────────────────

@dataclass
class JiraContext:
    base_url: str
    email: str
    api_key: str


# ── Tool definitions (passed to Claude) ──────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "jira_get_ticket",
        "description": (
            "Fetch a Jira issue by its ticket ID. "
            "Returns summary, status, priority, assignee, created/updated dates, "
            "and the full description text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "Jira issue key, e.g. SCRUM-5",
                }
            },
            "required": ["ticket_id"],
        },
    },
    {
        "name": "jira_get_comments",
        "description": (
            "Fetch all comments on a Jira issue. "
            "Returns a list of {author, created, body} objects."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "Jira issue key, e.g. SCRUM-5",
                }
            },
            "required": ["ticket_id"],
        },
    },
    {
        "name": "jira_add_comment",
        "description": "Post a plain-text comment to a Jira issue, optionally attaching files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "Jira issue key, e.g. SCRUM-5",
                },
                "text": {
                    "type": "string",
                    "description": "Comment body text.",
                },
            },
            "required": ["ticket_id", "text"],
        },
    },
    {
        "name": "jira_update_ticket",
        "description": "Update fields on an existing Jira issue. Only provided fields are changed. Optionally attach files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket_id": {
                    "type": "string",
                    "description": "Jira issue key, e.g. SCRUM-5",
                },
                "summary": {"type": "string", "description": "New summary text."},
                "description": {"type": "string", "description": "New description text."},
                "issue_type": {"type": "string", "description": "Issue type name, e.g. Bug, Story, Task."},
                "priority": {"type": "string", "description": "Priority name, e.g. High, Medium, Low."},
                "assignee_account_id": {"type": "string", "description": "Assignee's Jira account ID."},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of labels to set on the ticket.",
                },
            },
            "required": ["ticket_id"],
        },
    },
]


# ── Tool router ───────────────────────────────────────────────────────────────

def handle_tool_call(
    name: str,
    inputs: dict[str, Any],
    jira_ctx: JiraContext,
) -> dict[str, Any]:
    """
    Dispatch a tool call from Claude to the appropriate ScrumTool method.
    Credentials from JiraContext are patched onto the backend before each call.
    """
    tool = ScrumTool("jira")

    # Patch credentials from JiraContext onto the backend module
    from requests.auth import HTTPBasicAuth
    tool._backend.jira_base_url = jira_ctx.base_url
    tool._backend.email = jira_ctx.email
    tool._backend.api_key = jira_ctx.api_key
    tool._backend.auth = HTTPBasicAuth(jira_ctx.email, jira_ctx.api_key)

    if name == "jira_get_ticket":
        return _tool_get_ticket(tool, inputs["ticket_id"])

    if name == "jira_get_comments":
        return _tool_get_comments(tool, inputs["ticket_id"])

    if name == "jira_add_comment":
        return _tool_add_comment(tool, inputs["ticket_id"], inputs["text"])

    if name == "jira_update_ticket":
        return _tool_update_ticket(
            tool,
            inputs["ticket_id"],
            summary=inputs.get("summary"),
            description=inputs.get("description"),
            issue_type=inputs.get("issue_type"),
            priority=inputs.get("priority"),
            assignee_account_id=inputs.get("assignee_account_id"),
            labels=inputs.get("labels"),
        )

    raise ValueError(f"Unknown tool: {name!r}")


# ── Individual tool implementations ──────────────────────────────────────────

def _tool_get_ticket(tool: ScrumTool, ticket_id: str) -> dict:
    issue = tool.get_ticket(ticket_id)
    f = issue.get("fields", {})

    def _extract_fields(iss: dict) -> dict:
        fi = iss.get("fields", {})
        return {
            "ticket_id": iss["key"],
            "issue_type": (fi.get("issuetype") or {}).get("name", "").lower() or None,
            "summary": fi.get("summary", ""),
            "status": (fi.get("status") or {}).get("name", ""),
            "priority": (fi.get("priority") or {}).get("name", ""),
            "assignee": (fi.get("assignee") or {}).get("displayName", "Unassigned"),
            "created": fi.get("created", ""),
            "updated": fi.get("updated", ""),
            "description": tool._backend.extract_text(fi.get("description") or {}),
        }

    result = _extract_fields(issue)

    # Collect sub-task and linked issue keys from parent
    related_keys = (
        [st.get("key") for st in f.get("subtasks", []) if st.get("key")]
        + [
            (il.get("inwardIssue") or il.get("outwardIssue") or {}).get("key")
            for il in f.get("issuelinks", [])
            if (il.get("inwardIssue") or il.get("outwardIssue"))
        ]
    )

    # Fetch full details for each related ticket — same fields as parent
    related = []
    for key in related_keys:
        try:
            related.append(_extract_fields(tool.get_ticket(key)))
        except Exception as e:
            related.append({"ticket_id": key, "error": str(e)})

    result["related_tickets"] = related
    return result


def _tool_get_comments(tool: ScrumTool, ticket_id: str) -> dict:
    comments = tool.get_comments(ticket_id)
    parsed = [
        {
            "author": (c.get("author") or {}).get("displayName", "Unknown"),
            "created": c.get("created", ""),
            "body": tool._backend.extract_text(c.get("body") or {}),
        }
        for c in comments
    ]
    return {"comments": parsed}


def _tool_add_comment(tool: ScrumTool, ticket_id: str, text: str) -> dict:
    result = tool.add_comment(ticket_id, text)
    return {"status": "created", "comment_id": result.get("id", "")}


def _tool_update_ticket(
    tool: ScrumTool,
    ticket_id: str,
    summary: str | None = None,
    description: str | None = None,
    issue_type: str | None = None,
    priority: str | None = None,
    assignee_account_id: str | None = None,
    labels: list[str] | None = None,
) -> dict:
    tool.update_ticket(
        ticket_id,
        summary=summary,
        description=description,
        issue_type=issue_type,
        priority=priority,
        assignee_account_id=assignee_account_id,
        labels=labels,
    )
    return {"status": "updated", "ticket_id": ticket_id}
