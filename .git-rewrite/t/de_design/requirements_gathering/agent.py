# gathering/agent.py
"""
Requirements Gathering Agent (Agent 1)
Reads requirements from Jira or a document file, classifies the ticket,
and produces a structured RequirementsOutput for downstream modules.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import anthropic

from .prompts import SYSTEM_PROMPT, extraction_prompt
from .tools import TOOL_DEFINITIONS, handle_tool_call, JiraContext


# ── Constants ─────────────────────────────────────────────────────────────────

# Maps request_type to the execution modules that should run.
# validator and requirements always run for every type (handled by orchestrator).
RUN_PLAN: dict[str, list[str]] = {
    "bug":             ["impl_steps"],
    "enhancement":     ["architecture", "impl_steps"],        # data_model added conditionally
    "new development": ["data_model", "architecture", "tool_selector", "impl_steps"],
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
    technology: dict
    non_functional: dict
    security: dict
    constraints: dict
    assumptions: list[str]
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

    MAX_TOOL_ROUNDS = 6

    def __init__(self, config: dict):
        self.client = anthropic.Anthropic(api_key=config["api_key"])
        self.model = config.get("model", "claude-sonnet-4-20250514")
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
        Run the agentic tool loop to read the Jira ticket + comments.
        Returns (combined_text, jira_issue_type).
        """
        messages = [
            {
                "role": "user",
                "content": (
                    f"Fetch the Jira ticket {ticket_id} and all its comments. "
                    "Also return the issue type field value exactly as it appears."
                ),
            }
        ]

        raw_text = ""
        jira_issue_type = None

        for _ in range(self.MAX_TOOL_ROUNDS):
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            text_parts = [b.text for b in resp.content if b.type == "text"]

            if resp.stop_reason == "end_turn":
                raw_text = "\n".join(text_parts) or "(no content)"
                break

            if resp.stop_reason == "tool_use":
                tool_results = []
                for block in resp.content:
                    if block.type == "tool_use":
                        result = handle_tool_call(
                            name=block.name,
                            inputs=block.input,
                            jira_ctx=self.jira_ctx,
                        )
                        # Capture issue type from the ticket fetch
                        if block.name == "jira_get_ticket":
                            jira_issue_type = result.get("issue_type")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })

                messages.append({"role": "assistant", "content": resp.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                break
        else:
            raise RuntimeError("Jira fetch loop exhausted without finishing.")

        return raw_text, jira_issue_type

    def _extract(
        self,
        raw_text: str,
        source: str,
        ticket_id: Optional[str],
        jira_issue_type: Optional[str],
    ) -> RequirementsOutput:
        """Ask Claude to extract structured requirements from raw text."""
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": extraction_prompt(raw_text, jira_issue_type, self.confidence_threshold)}],
        )

        json_str = self._parse_json_block(resp.content[0].text)
        data: dict = json.loads(json_str)

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
            assumptions=data.get("assumptions", []),
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
        plan.append("validator")
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
            "Functional Requirements:",
            *[f"  • {r}" for r in output.functional_requirements],
        ]
        handle_tool_call(
            name="jira_add_comment",
            inputs={"ticket_id": ticket_id, "text": "\n".join(summary_lines)},
            jira_ctx=self.jira_ctx,
        )

    @staticmethod
    def _parse_json_block(text: str) -> str:
        """Strip markdown code fences if present."""
        match = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        return match.group(1).strip() if match else text.strip()
