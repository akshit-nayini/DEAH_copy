# implementation_steps/agent.py
"""
Implementation Steps Agent
Receives summaries from requirements (bug), architecture (enhancement + new dev),
and data_model (new dev only), and produces a structured Markdown implementation
plan for consumption by a downstream development agent.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure DEAH root is on sys.path so core.utilities is importable
_DEAH_ROOT = Path(__file__).resolve().parents[5]
if str(_DEAH_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEAH_ROOT))

from core.utilities.llm import create_llm_client

from .prompts import SYSTEM_PROMPT, generation_prompt


# ── Output schema ─────────────────────────────────────────────────────────────

@dataclass
class ImplStepsOutput:
    project_name: str
    request_type: str
    output_path: Path
    markdown: str

    def write(self):
        """Write the markdown file to disk."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(self.markdown, encoding="utf-8")


# ── Agent ─────────────────────────────────────────────────────────────────────

class ImplStepsAgent:
    """
    Single-call agent. Receives input summaries, generates a structured
    implementation plan as Markdown, and writes it to disk.

    Input combinations by request type:
      bug:             requirements_summary only
      enhancement:     architecture_summary only
      new development: data_model_summary + architecture_summary
    """

    def __init__(self, config: dict):
        self.llm = create_llm_client("claude-code-sdk")
        self.output_root = Path(config.get("output_root", "output"))

    # ── public entry point ───────────────────────────────────────────────────

    def run(
        self,
        request_type: str,
        project_name: str,
        requirements_summary: Optional[dict] = None,
        architecture_summary: Optional[dict] = None,
        data_model_summary: Optional[dict] = None,
    ) -> ImplStepsOutput:
        """
        Generate implementation steps from the provided summaries.
        Caller is responsible for passing the correct combination of summaries
        for the request type.
        """
        self._validate_inputs(request_type, requirements_summary, architecture_summary, data_model_summary)

        prompt = generation_prompt(
            request_type=request_type,
            project_name=project_name,
            requirements_summary=requirements_summary,
            architecture_summary=architecture_summary,
            data_model_summary=data_model_summary,
        )

        result = self.llm.complete(prompt=prompt, system=SYSTEM_PROMPT, max_tokens=8096)
        markdown = result.content.strip()

        # Resolve ticket_id from summaries (data_model carries it for new dev/enhancement;
        # requirements carries it for bug; falls back to slugified project name)
        ticket_id: Optional[str] = None
        for summary in [data_model_summary, architecture_summary, requirements_summary]:
            ticket_id = (summary or {}).get("ticket_id") or None
            if ticket_id:
                break

        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H")
        identifier = ticket_id if ticket_id else self._slugify(project_name)
        prefix = self.output_root / f"impl_{identifier}_{run_id}"

        output = ImplStepsOutput(
            project_name=project_name,
            request_type=request_type,
            output_path=prefix.with_suffix(".md"),
            markdown=markdown,
        )
        output.write()
        return output

    # ── internal helpers ─────────────────────────────────────────────────────

    def _validate_inputs(
        self,
        request_type: str,
        requirements_summary: Optional[dict],
        architecture_summary: Optional[dict],
        data_model_summary: Optional[dict],
    ):
        if request_type == "bug" and not requirements_summary:
            raise ValueError("Bug request requires requirements_summary.")
        if request_type == "enhancement" and not architecture_summary:
            raise ValueError("Enhancement request requires architecture_summary.")
        if request_type == "new development" and not (architecture_summary and data_model_summary):
            raise ValueError("New development request requires both architecture_summary and data_model_summary.")

    @staticmethod
    def _slugify(name: str) -> str:
        """Convert project name to a filesystem-safe directory name."""
        return name.lower().replace(" ", "_").replace("/", "_")
