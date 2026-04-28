# gathering/tools.py
"""
Tool definitions (for Claude's tool-use API) and their Python implementations.
The implementations delegate to the logic in jira_rw.py so there is a single
source of truth for Jira I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import sys

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import jira_rw


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
        "description": "Post a plain-text comment to a Jira issue.",
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
]


# ── Tool router ───────────────────────────────────────────────────────────────

def handle_tool_call(
    name: str,
    inputs: dict[str, Any],
    jira_ctx: JiraContext,
) -> dict[str, Any]:
    """
    Dispatch a tool call from Claude to the appropriate implementation.
    Returns a JSON-serialisable dict.
    """
    # Patch jira_rw credentials from the context (avoids global state)
    jira_rw.jira_base_url = jira_ctx.base_url
    jira_rw.email = jira_ctx.email
    jira_rw.api_key = jira_ctx.api_key
    from requests.auth import HTTPBasicAuth
    jira_rw.auth = HTTPBasicAuth(jira_ctx.email, jira_ctx.api_key)

    if name == "jira_get_ticket":
        return _tool_get_ticket(inputs["ticket_id"])

    if name == "jira_get_comments":
        return _tool_get_comments(inputs["ticket_id"])

    if name == "jira_add_comment":
        return _tool_add_comment(inputs["ticket_id"], inputs["text"])

    raise ValueError(f"Unknown tool: {name!r}")


# ── Individual tool implementations ──────────────────────────────────────────

def _tool_get_ticket(ticket_id: str) -> dict:
    issue = jira_rw.get_ticket(ticket_id)
    f = issue.get("fields", {})
    return {
        "ticket_id": issue["key"],
        "issue_type": (f.get("issuetype") or {}).get("name", "").lower() or None,
        "summary": f.get("summary", ""),
        "status": (f.get("status") or {}).get("name", ""),
        "priority": (f.get("priority") or {}).get("name", ""),
        "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
        "created": f.get("created", ""),
        "updated": f.get("updated", ""),
        "description": jira_rw.extract_text(f.get("description") or {}),
    }


def _tool_get_comments(ticket_id: str) -> dict:
    comments = jira_rw.get_comments(ticket_id)
    parsed = []
    for c in comments:
        parsed.append({
            "author": (c.get("author") or {}).get("displayName", "Unknown"),
            "created": c.get("created", ""),
            "body": jira_rw.extract_text(c.get("body") or {}),
        })
    return {"comments": parsed}


def _tool_add_comment(ticket_id: str, text: str) -> dict:
    result = jira_rw.add_comment(ticket_id, text)
    return {"status": "created", "comment_id": result.get("id", "")}
