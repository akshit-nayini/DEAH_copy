# gathering/agent.py
"""
Requirements Gathering Agent (Agent 1)
Reads requirements from Jira or a document file, classifies the ticket,
and produces a structured RequirementsOutput for downstream modules.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

# Ensure DEAH root is on sys.path so core.utilities is importable
_DEAH_ROOT = Path(__file__).resolve().parents[5]
if str(_DEAH_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEAH_ROOT))

from core.utilities.llm import create_llm_client

from .prompts import SYSTEM_PROMPT_EXTRACT, extraction_prompt
from .tools import TOOL_DEFINITIONS, handle_tool_call, JiraContext


# ── Constants ─────────────────────────────────────────────────────────────────

# Maps request_type to the execution modules that should run.
# validator and requirements always run for every type (handled by orchestrator).
RUN_PLAN: dict[str, list[str]] = {
    "bug":             ["implementation_steps"],
    "enhancement":     ["implementation_steps"],        # data_model prepended conditionally
    "new development": ["data_model", "architecture", "implementation_steps"],
}


# ── Exceptions ────────────────────────────────────────────────────────────────

class RequirementsRejected(Exception):
    """Raised when source requirements lack the minimum fields to proceed."""
    def __init__(self, missing_fields: list[str], message: str):
        self.missing_fields = missing_fields
        self.message = message
        super().__init__(f"Requirements rejected — {message} (missing: {', '.join(missing_fields)})")


# ── Output schema ─────────────────────────────────────────────────────────────

@dataclass
class RequirementsOutput:
    source: str                        # "jira" | "document"
    ticket_id: Optional[str]
    request_type: str                  # "bug" | "enhancement" | "new development"
    run_plan: list[str]                # execution modules to invoke, in order
    project_name: str
    objective: str
    business_context: str
    functional_requirements: list[str]
    data_requirements: dict
    technology: dict                   # keys: stack, environment, cloud_or_onprem, preferred_tools
    non_functional: dict
    security: dict
    constraints: dict
    existing_architecture: Optional[str]   # mandatory for enhancement
    source_connections: list[dict]          # connection details per source system
    assumptions: list[str]
    inferred_assumptions: list[str]        # assumptions made by Claude to fill low-confidence fields
    acceptance_criteria: list[str]
    expected_outputs: list[str]
    classification: dict               # {ingestion_type, output_type}
    confidence: float                  # 0-1
    low_confidence_warning: Optional[str]  # set by Claude when confidence < threshold
    raw_text: str                      # original text fed to Claude

    def to_dict(self) -> dict:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            f"# Requirements: {self.project_name}",
            f"**Source:** {self.source}" + (f"  |  **Ticket:** {self.ticket_id}" if self.ticket_id else ""),
            f"**Request Type:** {self.request_type}",
            f"**Ingestion Type:** {self.classification.get('ingestion_type')}  |  **Output Type:** {self.classification.get('output_type')}  (confidence {self.confidence:.0%})",
            f"**Run Plan:** {' → '.join(self.run_plan)}",
            "",
        ]
        if self.low_confidence_warning:
            lines += [
                "## ⚠️ Low Confidence Warning",
                self.low_confidence_warning,
                "",
            ]
        lines += [
            "## Objective",
            self.objective,
            "",
            "## Business Context",
            self.business_context,
            "",
            "## Functional Requirements",
            *[f"- {r}" for r in self.functional_requirements],
            "",
            "## Data Requirements",
            *[f"- **{k}:** {v}" for k, v in self.data_requirements.items()],
            "",
        ]
        if self.source_connections:
            lines += [
                "## Source Connections",
                *[
                    f"- **{c.get('db_type', 'Unknown')}** / {c.get('database', '')} | "
                    + (f"instance: {c.get('instance_connection_name')} | " if c.get('instance_connection_name') else "")
                    + f"{c.get('host', '')}:{c.get('port', '')} "
                    f"| user: {c.get('username', '')} "
                    f"| tables: {', '.join(c.get('source_tables', []))}"
                    for c in self.source_connections
                ],
                "",
            ]
        lines += [
            "## Technology & Environment",
            *[f"- **{k}:** {v}" for k, v in self.technology.items()],
            "",
            "## Non-Functional Requirements",
            *[f"- **{k}:** {v}" for k, v in self.non_functional.items()],
            "",
            "## Security & Compliance",
            *[f"- **{k}:** {v}" for k, v in self.security.items()],
            "",
            "## Constraints",
            *[f"- **{k}:** {v}" for k, v in self.constraints.items()],
            "",
            "## Assumptions",
            *[f"- {a}" for a in self.assumptions],
            "",
            "## Acceptance Criteria",
            *[f"- {c}" for c in self.acceptance_criteria],
            "",
            "## Expected Outputs",
            *[f"- {o}" for o in self.expected_outputs],
        ]
        if self.inferred_assumptions:
            lines += [
                "",
                "## Inferred Assumptions",
                "*These were inferred by the agent due to low confidence — please confirm or correct.*",
                *[f"- {a}" for a in self.inferred_assumptions],
            ]
        return "\n".join(lines)


# ── Agent ─────────────────────────────────────────────────────────────────────

class RequirementsAgent:
    """
    Agentic loop:
      1. Given a Jira ticket ID or a document path, fetch the raw text.
      2. Ask Claude to detect request type, validate minimum fields,
         and extract structured requirements.
      3. Build the run_plan based on request type and data_model_required flag.
      4. Optionally write a summary comment back to Jira.
      5. Return a RequirementsOutput dataclass.
    """

    def __init__(self, config: dict):
        self.llm = create_llm_client("claude-code-sdk")
        self.write_back = config.get("write_back_to_jira", False)
        self.confidence_threshold = config.get("confidence_threshold", 0.6)
        self.jira_ctx = JiraContext(
            base_url=config.get("jira_base_url", ""),
            email=config.get("jira_email", ""),
            api_key=config.get("jira_api_key", ""),
        )

    # ── public entry points ──────────────────────────────────────────────────

    def run_from_jira(self, ticket_id: str) -> RequirementsOutput:
        """Fetch a Jira ticket and extract requirements."""
        raw, jira_issue_type = self._fetch_jira_text(ticket_id)
        try:
            output = self._extract(raw, source="jira", ticket_id=ticket_id, jira_issue_type=jira_issue_type)
        except RequirementsRejected as e:
            if self.write_back:
                self._write_rejection_to_jira(ticket_id, e)
            raise
        if self.write_back:
            self._write_summary_to_jira(ticket_id, output)
        return output

    def run_from_document(self, path: str | Path) -> RequirementsOutput:
        """Load a local requirements document and extract requirements."""
        raw = Path(path).read_text(encoding="utf-8")
        return self._extract(raw, source="document", ticket_id=None, jira_issue_type=None)

    # ── internal helpers ─────────────────────────────────────────────────────

    def _fetch_jira_text(self, ticket_id: str) -> tuple[str, str | None]:
        """
        Directly call Jira tools and assemble the ticket + comments into
        a plain-text string. Returns (combined_text, jira_issue_type).
        """
        jira_issue_type = None
        parts = []

        # Fetch ticket
        ticket_result = handle_tool_call(
            name="jira_get_ticket",
            inputs={"ticket_id": ticket_id},
            jira_ctx=self.jira_ctx,
        )
        jira_issue_type = ticket_result.get("issue_type")
        parts.append(f"Ticket: {ticket_id}")
        parts.append(f"Summary: {ticket_result.get('summary', '')}")
        parts.append(f"Status: {ticket_result.get('status', '')}")
        parts.append(f"Priority: {ticket_result.get('priority', '')}")
        parts.append(f"Assignee: {ticket_result.get('assignee', '')}")
        parts.append(f"Description:\n{ticket_result.get('description', '')}")

        # Fetch comments
        comments_result = handle_tool_call(
            name="jira_get_comments",
            inputs={"ticket_id": ticket_id},
            jira_ctx=self.jira_ctx,
        )
        comments = comments_result.get("comments", [])
        if comments:
            parts.append("\nComments:")
            for c in comments:
                parts.append(f"[{c.get('created', '')}] {c.get('author', '')}: {c.get('body', '')}")

        # Fetch sub-tasks and linked work items — same fields as parent ticket
        related_tickets = ticket_result.get("related_tickets", [])
        if related_tickets:
            parts.append(f"\n--- Related Tickets ({len(related_tickets)}) ---")
            for rel in related_tickets:
                if "error" in rel:
                    parts.append(f"\nRelated Ticket: {rel['ticket_id']} — could not fetch ({rel['error']})")
                    continue
                parts.append(f"\nRelated Ticket: {rel['ticket_id']}")
                parts.append(f"Summary: {rel.get('summary', '')}")
                parts.append(f"Status: {rel.get('status', '')}")
                parts.append(f"Priority: {rel.get('priority', '')}")
                parts.append(f"Description:\n{rel.get('description', '')}")
                rel_comments = handle_tool_call(
                    name="jira_get_comments",
                    inputs={"ticket_id": rel["ticket_id"]},
                    jira_ctx=self.jira_ctx,
                ).get("comments", [])
                if rel_comments:
                    parts.append("Comments:")
                    for c in rel_comments:
                        parts.append(f"[{c.get('created', '')}] {c.get('author', '')}: {c.get('body', '')}")

        return "\n".join(parts), jira_issue_type

    _MAX_RETRIES = 4
    _BACKOFF_BASE = 2.0  # seconds

    def _extract(
        self,
        raw_text: str,
        source: str,
        ticket_id: Optional[str],
        jira_issue_type: Optional[str],
    ) -> RequirementsOutput:
        """Ask Claude to extract structured requirements from raw text."""
        prompt = extraction_prompt(raw_text, jira_issue_type, self.confidence_threshold)

        for attempt in range(self._MAX_RETRIES):
            try:
                resp = self.llm.complete(prompt, system=SYSTEM_PROMPT_EXTRACT, max_tokens=4096)
                break
            except Exception as exc:
                if attempt == self._MAX_RETRIES - 1:
                    raise
                wait = self._BACKOFF_BASE * (2 ** attempt)
                print(f"[agent] LLM error ({exc.__class__.__name__}) — retrying in {wait:.1f}s (attempt {attempt + 1}/{self._MAX_RETRIES})")
                time.sleep(wait)

        data: dict = self._parse_json_block(resp.content)

        if data.get("status") == "rejected":
            raise RequirementsRejected(
                missing_fields=data.get("missing_fields", []),
                message=data.get("message", "Insufficient requirements to proceed."),
            )

        request_type = data.get("request_type", "new development")
        run_plan = self._build_run_plan(request_type, data.get("data_model_required", False))

        return RequirementsOutput(
            source=source,
            ticket_id=ticket_id,
            request_type=request_type,
            run_plan=run_plan,
            raw_text=raw_text,
            project_name=data.get("project_name", "Unknown"),
            objective=data.get("objective", ""),
            business_context=data.get("business_context", ""),
            functional_requirements=data.get("functional_requirements", []),
            data_requirements=data.get("data_requirements", {}),
            technology=data.get("technology", {}),
            non_functional=data.get("non_functional", {}),
            security=data.get("security", {}),
            constraints=data.get("constraints", {}),
            existing_architecture=data.get("existing_architecture"),
            source_connections=data.get("source_connections", []),
            assumptions=data.get("assumptions", []),
            inferred_assumptions=data.get("inferred_assumptions", []),
            acceptance_criteria=data.get("acceptance_criteria", []),
            expected_outputs=data.get("expected_outputs", []),
            classification=data.get("classification", {"ingestion_type": "unknown", "output_type": "unknown"}),
            confidence=float(data.get("confidence", 0.0)),
            low_confidence_warning=data.get("low_confidence_warning"),
        )

    def _build_run_plan(self, request_type: str, data_model_required: bool) -> list[str]:
        """
        Build the ordered list of execution modules to run.
        validator is always appended last as it runs for every request type.
        For enhancement, data_model is inserted only if data_model_required is True.
        """
        plan = list(RUN_PLAN.get(request_type, RUN_PLAN["new development"]))
        if request_type == "enhancement" and data_model_required:
            plan.insert(0, "data_model")
        return plan

    def _write_rejection_to_jira(self, ticket_id: str, rejection: RequirementsRejected):
        """Post a rejection comment to the Jira ticket so the author knows what's missing."""
        comment_lines = [
            "🤖 *Requirements Agent — Action Required*",
            "",
            rejection.message,
            "",
            f"Missing fields: {', '.join(rejection.missing_fields)}",
        ]
        handle_tool_call(
            name="jira_add_comment",
            inputs={"ticket_id": ticket_id, "text": "\n".join(comment_lines)},
            jira_ctx=self.jira_ctx,
        )

    def _write_summary_to_jira(self, ticket_id: str, output: RequirementsOutput):
        """Post a structured summary comment back to the Jira ticket."""
        summary_lines = [
            "🤖 *Requirements Agent Summary*",
            "",
            f"Request Type: *{output.request_type}*",
            f"Ingestion Type: *{output.classification.get('ingestion_type')}*  |  Output Type: *{output.classification.get('output_type')}*  (confidence {output.confidence:.0%})",
            f"Run Plan: {' → '.join(output.run_plan)}",
            "",
            f"Objective: {output.objective}",
            "",
            *(["Business Context:", output.business_context, ""] if output.business_context else []),
            "Functional Requirements:",
            *(output.functional_requirements or ["(none — please provide directly on the ticket)"]),
            "",
            "Acceptance Criteria:",
            *(output.acceptance_criteria or ["(none — please provide directly on the ticket)"]),
        ]
        if output.source_connections:
            summary_lines += [
                "",
                "Source Connections:",
                *[
                    f"  • {c.get('db_type', 'Unknown')} / {c.get('database', '')} | "
                    + (f"instance: {c.get('instance_connection_name')} | " if c.get('instance_connection_name') else "")
                    + f"{c.get('host', '')}:{c.get('port', '')} "
                    f"| user: {c.get('username', '')} "
                    f"| tables: {', '.join(c.get('source_tables', []))}"
                    for c in output.source_connections
                ],
            ]
        if output.inferred_assumptions:
            summary_lines += [
                "",
                "⚠️ Inferred Assumptions (please confirm or correct):",
                *[f"  • {a}" for a in output.inferred_assumptions],
            ]
        if output.low_confidence_warning:
            summary_lines += [
                "",
                f"⚠️ {output.low_confidence_warning}",
            ]

        handle_tool_call(
            name="jira_add_comment",
            inputs={"ticket_id": ticket_id, "text": "\n".join(summary_lines)},
            jira_ctx=self.jira_ctx,
        )

    @staticmethod
    def _parse_json_block(text: str) -> dict:
        """Strip markdown code fences if present, then parse JSON."""
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        clean = match.group(1).strip() if match else text.strip()
        return json.loads(clean)
