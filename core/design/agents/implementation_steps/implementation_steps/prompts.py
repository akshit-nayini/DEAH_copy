# implementation_steps/prompts.py
"""
System and user prompts for the Implementation Steps Agent.
"""

from __future__ import annotations

import json
from typing import Optional


SYSTEM_PROMPT = """\
You are a senior data engineer producing implementation plans for a downstream
development agent. Your output is a structured Markdown document.

Rules:
- Output is Markdown only — no preamble, no explanation outside the document.
- Organise the plan into named phases with ordered, actionable steps.
- Assume all infrastructure is already provisioned. Do not include setup steps.
- If source_connections are provided, include a ## Source Connections section
  immediately after the title listing each connection (db_type, host, port,
  database, source_tables). The first step of the first implementation phase
  must then be a connectivity check referencing those details.
- The testing phase must include concrete test cases derived from the inputs —
  state what is being tested, the input condition, and the expected outcome.
- The final phase is always Handover — include steps to update the runbook:
  pipeline design summary, operational procedures, known risks, escalation
  paths, and sign-off confirmation.
- Risks and open blockers are reference material only — do not embed as steps.
- Do not invent anything not present in the input.
- If open blockers are present, list them prominently.

Document structure:
  # Implementation Plan: {project_name}
  ## Source Connections       (omit if none provided)
  ## ⚠️ Open Blockers        (omit if none)
  ## ⚠️ Risks & Mitigations  (reference only)
  ## Phase N: <Name>          (one or more, natural build sequence)
  ## Phase N: Testing         (concrete derived test cases)
  ## Phase N: Handover        (always present)
"""


def generation_prompt(
    request_type: str,
    project_name: str,
    requirements_summary: Optional[dict],
    architecture_summary: Optional[dict],
    data_model_summary: Optional[dict],
) -> str:

    sections = [
        f"Project: {project_name}",
        f"Request Type: {request_type}",
        "",
    ]

    if requirements_summary:
        sections += [
            "## Requirements Summary",
            json.dumps(requirements_summary, indent=2),
            "",
        ]

    if data_model_summary:
        sections += [
            "## Data Model Summary",
            json.dumps(data_model_summary, indent=2),
            "",
        ]

    if architecture_summary:
        sections += [
            "## Architecture Summary",
            json.dumps(architecture_summary, indent=2),
            "",
        ]

    # Extract source_connections explicitly so the LLM always sees them as a
    # dedicated section rather than buried inside a summary JSON blob.
    source_connections: list = []
    for summary in [data_model_summary, requirements_summary, architecture_summary]:
        if summary:
            conns = summary.get("source_connections", [])
            if conns:
                source_connections = conns
                break

    if source_connections:
        sections += [
            "## Source Connections",
            json.dumps(source_connections, indent=2),
            "",
        ]

    sections.append("Generate the implementation plan.")

    return "\n".join(sections)
