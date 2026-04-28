"""
agent.py — Architecture Agent core orchestration.

Lifecycle:
    1. Orchestrator calls init.get_agent(config) → ArchitectureAgent
    2. Orchestrator calls agent.run(requirements_input)
    3. Agent returns AgentResult with manifest (or skip/error)

Position in the pipeline:
    requirements_agent
          │
    data_model_agent  (parallel with architecture_agent)
          │
    ► architecture_agent   ← YOU ARE HERE
          │
    pipeline_design_agent
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from prompts import SYSTEM_PROMPT, build_user_message
from tools import llm_call, write_file, validate_json

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent


# ──────────────────────────────────────────────
# AgentResult
# ──────────────────────────────────────────────

class AgentResult:
    """Standard result envelope returned to the orchestrator."""

    def __init__(
        self,
        success: bool,
        agent_name: str = "architecture_agent",
        manifest: Optional[dict] = None,
        handoff_summary: Optional[dict] = None,
        skipped: bool = False,
        skip_reason: Optional[str] = None,
        validation_warnings: Optional[list[str]] = None,
        error: Optional[str] = None,
        run_id: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        token_usage: Optional[dict] = None,
    ):
        self.success = success
        self.agent_name = agent_name
        self.manifest = manifest
        self.handoff_summary = handoff_summary  # slim payload for downstream agents
        self.skipped = skipped
        self.skip_reason = skip_reason
        self.validation_warnings = validation_warnings or []
        self.error = error
        self.run_id = run_id
        self.duration_seconds = duration_seconds
        self.token_usage = token_usage

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "agent_name": self.agent_name,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "validation_warnings": self.validation_warnings,
            "error": self.error,
            "run_id": self.run_id,
            "duration_seconds": self.duration_seconds,
            "token_usage": self.token_usage,
            "manifest": self.manifest,
            "handoff_summary": self.handoff_summary,
        }


# ──────────────────────────────────────────────
# Skill Functions
# ──────────────────────────────────────────────

# Cloud resolution

_CLOUD_KEYWORDS = {
    "gcp": "GCP", "google": "GCP",
    "aws": "AWS", "amazon": "AWS",
    "azure": "Azure", "microsoft": "Azure",
}


def _to_str(value) -> str:
    """Normalize a requirements field to a plain string.
    Handles str, list, and None — the LLM sometimes returns a list
    where a scalar string is expected.
    """
    if not value:
        return ""
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value)


def resolve_cloud(technology: dict) -> str:
    """Resolve cloud platform from technology dict. Defaults to GCP."""
    cloud_str = _to_str(technology.get("cloud_or_onprem")).lower()
    for keyword, platform in _CLOUD_KEYWORDS.items():
        if keyword in cloud_str:
            return platform
    stack = _to_str(technology.get("stack")).lower()
    for keyword, platform in _CLOUD_KEYWORDS.items():
        if keyword in stack:
            return platform
    return "GCP"


# Pattern type resolution

def resolve_pattern_type(classification: dict, non_functional: dict) -> str:
    """
    Infer primary architecture pattern from ingestion type and latency.

    batch + T+1 latency  → batch
    streaming            → streaming
    batch + low latency  → hybrid
    mixed or report      → lakehouse
    """
    ingestion = _to_str(classification.get("ingestion_type")).lower()
    output = _to_str(classification.get("output_type")).lower()
    latency = _to_str(non_functional.get("latency")).lower()

    if ingestion == "streaming":
        return "streaming"

    if output in ("report", "ml_feature"):
        return "lakehouse"

    real_time_keywords = ["real-time", "realtime", "real time", "< 1", "<1", "seconds", "minutes"]
    if any(kw in latency for kw in real_time_keywords):
        return "hybrid"

    return "batch"


# Volume tier resolution

def resolve_volume_tier(volume) -> str:
    """Classify data volume as low / medium / high."""
    vol = _to_str(volume).lower()
    if not vol:
        return "unknown"
    high_keywords = ["billion", "tb", "pb", "100m", "500m", "large", "high"]
    medium_keywords = ["million", "gb", "10m", "50m", "medium"]
    if any(kw in vol for kw in high_keywords):
        return "high"
    if any(kw in vol for kw in medium_keywords):
        return "medium"
    return "low"


# Latency tier resolution

def resolve_latency_tier(latency) -> str:
    """Classify latency requirement as real-time / near-real-time / batch."""
    lat = _to_str(latency).lower()
    if not lat:
        return "batch"
    if any(kw in lat for kw in ["real-time", "realtime", "real time", "< 1 min", "<1min", "seconds"]):
        return "real-time"
    if any(kw in lat for kw in ["minutes", "near real", "near-real", "< 15", "<15", "< 5", "<5"]):
        return "near-real-time"
    return "batch"


# Confidence evaluation

def evaluate_confidence(requirements: dict, threshold: float = 0.7) -> dict:
    """Assess input completeness for architecture design."""
    conf = requirements.get("confidence", 0.0)
    below = conf < threshold
    note = None
    questions: list[str] = []

    if below:
        note = requirements.get("low_confidence_warning") or (
            f"Input confidence is {conf:.2f}, below threshold {threshold}."
        )

    dr = requirements.get("data_requirements", {})
    nf = requirements.get("non_functional", {})
    tech = requirements.get("technology", {})

    if not dr.get("volume"):
        questions.append("Data volume not specified — cannot determine processing tier or cost estimate.")
    if not dr.get("frequency"):
        questions.append("Ingestion frequency not specified — cannot confirm batch vs streaming decision.")
    if not nf.get("latency"):
        questions.append("Latency SLA not specified — pattern type may be suboptimal.")
    if not tech.get("cloud_or_onprem"):
        questions.append("Cloud/on-prem not specified — defaulting to GCP.")
    if not nf.get("scalability"):
        questions.append("Scalability requirements not specified — cannot assess managed service sizing.")

    return {
        "is_below_threshold": below,
        "confidence_value": conf,
        "model_confidence_note": note,
        "entity_confidence": "low" if below else "high",
        "seed_open_questions": questions,
    }


# Input validation

_REQUIRED_FIELDS = {
    "bug":             ["objective", "functional_requirements"],
    "enhancement":     ["objective", "functional_requirements"],
    "new development": ["objective", "functional_requirements"],
}


def validate_input(requirements: dict) -> list[str]:
    """Pre-flight validation. Returns list of errors (empty = valid)."""
    errors = []
    rt = requirements.get("request_type", "")
    required = _REQUIRED_FIELDS.get(rt, _REQUIRED_FIELDS["new development"])

    for field in required:
        val = requirements.get(field)
        if val is None or val == "" or val == []:
            errors.append(f"Missing required field for '{rt}': {field}")

    if not requirements.get("classification"):
        errors.append("classification is missing — cannot determine pattern type")

    conf = requirements.get("confidence", 0.0)
    if not (0.0 <= conf <= 1.0):
        errors.append(f"confidence must be 0.0-1.0, got {conf}")

    return errors


# Run-plan validation

def validate_run_plan(run_plan: list[str], request_type: str) -> list[str]:
    """Cross-check run_plan against request_type."""
    warnings = []
    if request_type == "bug" and "architecture" in run_plan:
        warnings.append("run_plan for 'bug' includes 'architecture' — unusual unless a systemic redesign is needed.")
    return warnings


# Manifest validation

def validate_manifest(manifest: dict) -> list[str]:
    """Post-flight validation on the parsed architecture manifest."""
    warnings = []

    options = manifest.get("options", [])
    if len(options) < 2:
        warnings.append(f"Expected 2–3 architecture options, got {len(options)}")

    for opt in options:
        name = opt.get("name", f"option_{opt.get('option_id')}")
        stack = opt.get("tech_stack", {})
        for component in ["ingestion", "processing", "storage", "orchestration", "monitoring", "iac"]:
            if not stack.get(component, {}).get("tool"):
                warnings.append(f"Option '{name}' missing tech_stack.{component}.tool")

        scores = opt.get("scores", {})
        for dim in ["cost", "scalability", "complexity", "latency", "operability", "weighted_score"]:
            if dim not in scores:
                warnings.append(f"Option '{name}' missing scores.{dim}")

        if not opt.get("pros"):
            warnings.append(f"Option '{name}' has no pros listed")
        if not opt.get("cons"):
            warnings.append(f"Option '{name}' has no cons listed")
        if not opt.get("risks"):
            warnings.append(f"Option '{name}' has no risks listed")

    recommended = [o for o in options if o.get("is_recommended")]
    if len(recommended) != 1:
        warnings.append(f"Expected exactly 1 option with is_recommended=true, found {len(recommended)}")
    else:
        rec_opt = recommended[0]
        if not rec_opt.get("justification"):
            warnings.append("Recommended option is missing justification")
        if not rec_opt.get("trade_offs_accepted"):
            warnings.append("Recommended option is missing trade_offs_accepted")

    non_recommended = [o for o in options if not o.get("is_recommended")]
    for opt in non_recommended:
        if not opt.get("rejection_reason"):
            warnings.append(f"Option '{opt.get('name')}' is missing rejection_reason")

    if not manifest.get("recommendation", {}).get("selected_option_id"):
        warnings.append("recommendation.selected_option_id is missing")

    scoring_table = manifest.get("scoring_table", [])
    if len(scoring_table) != len(options):
        warnings.append(
            f"scoring_table has {len(scoring_table)} entries but there are {len(options)} options"
        )

    if not manifest.get("global_risks"):
        warnings.append("global_risks is empty")

    if not manifest.get("traceability"):
        warnings.append("traceability is empty — architecture decisions are not mapped to requirements")

    return warnings


# ──────────────────────────────────────────────
# Handoff Summary Builder
# ──────────────────────────────────────────────

def _build_scoring_table(manifest: dict) -> list[dict]:
    """
    Build scoring_table deterministically from options[].scores.
    Not generated by the LLM — keeps output tokens lower.
    """
    return [
        {
            "option_id": o.get("option_id"),
            "option": o.get("name", ""),
            "cost": o.get("scores", {}).get("cost", 0),
            "scalability": o.get("scores", {}).get("scalability", 0),
            "complexity": o.get("scores", {}).get("complexity", 0),
            "latency": o.get("scores", {}).get("latency", 0),
            "operability": o.get("scores", {}).get("operability", 0),
            "weighted_score": o.get("scores", {}).get("weighted_score", 0.0),
        }
        for o in manifest.get("options", [])
    ]


def _build_handoff_summary(manifest: dict) -> dict:
    """
    Build a compact handoff payload for the implementation specification agent.
    Always built in Python from the manifest — never generated by the LLM.
    Target size: ~300 tokens vs ~3,000+ for the full manifest.
    """
    # Find the recommended option directly from options[] — single source of truth
    selected_opt = next(
        (o for o in manifest.get("options", []) if o.get("is_recommended")),
        manifest.get("options", [{}])[0],
    )
    selected_name = selected_opt.get("name", "")

    # Slim tech stack — tool names only
    slim_stack = {
        component: details.get("tool", "—")
        for component, details in selected_opt.get("tech_stack", {}).items()
    }

    # Flow as ordered steps
    flow = selected_opt.get("flow", {})
    flow_steps = [
        f"1. Ingestion: {flow.get('ingestion', '—')}",
        f"2. Processing: {flow.get('processing', '—')}",
        f"3. Storage: {flow.get('storage', '—')}",
        f"4. Consumption: {flow.get('consumption', '—')}",
    ]

    # High-priority risks only (first 3 global risks)
    high_risks = [
        {"risk": r.get("category", ""), "mitigation": r.get("mitigation", "")}
        for r in manifest.get("global_risks", [])[:3]
    ]

    # Key constraints from traceability
    key_constraints = [
        t.get("requirement_field", "")
        for t in manifest.get("traceability", [])
        if t.get("requirement_field")
    ][:5]

    # Scoring one-liner — pull directly from the recommended option object
    scores = selected_opt.get("scores", {})
    trade_offs = selected_opt.get("trade_offs_accepted", "")
    if scores:
        scoring_line = (
            f"Scored {scores.get('weighted_score', 0):.2f}/10 — "
            f"Cost {scores.get('cost')}, Scalability {scores.get('scalability')}, "
            f"Complexity {scores.get('complexity')}, Latency {scores.get('latency')}, "
            f"Operability {scores.get('operability')}. "
            f"Trade-offs accepted: {trade_offs}"
        )
    else:
        scoring_line = selected_opt.get("justification", "")

    # Open blockers — first 3 open questions
    open_blockers = manifest.get("open_questions", [])[:3]

    return {
        "agent": "architecture",
        "project_name": manifest.get("project_name", ""),
        "request_type": manifest.get("request_type", ""),
        "selected_architecture": selected_name,
        "pattern_type": selected_opt.get("pattern_type", manifest.get("inferred_pattern_type", "")),
        "cloud_platform": manifest.get("cloud_platform", "GCP"),
        "tech_stack": slim_stack,
        "flow_steps": flow_steps,
        "key_constraints": key_constraints,
        "high_priority_risks": high_risks,
        "scoring_one_liner": scoring_line,
        "open_blockers": open_blockers,
    }


# ──────────────────────────────────────────────
# Markdown Report Renderer
# ──────────────────────────────────────────────

def _render_markdown(manifest: dict) -> str:
    """
    Render a human-readable Markdown Architecture Decision Document
    from the parsed JSON manifest. Produces the same structure as
    sample_output.md — suitable for engineering pod review.
    """
    lines: list[str] = []
    project = manifest.get("project_name", "Unknown Project")
    cloud = manifest.get("cloud_platform", "GCP")
    pattern = manifest.get("inferred_pattern_type", "batch")
    request_type = manifest.get("request_type", "")
    options = manifest.get("options", [])
    scoring_table = manifest.get("scoring_table", [])
    risks = manifest.get("global_risks", [])
    assumptions = manifest.get("global_assumptions", [])
    traceability = manifest.get("traceability", [])
    open_questions = manifest.get("open_questions", [])

    # Single source of truth — pull recommendation fields from options[]
    rec_opt = next((o for o in options if o.get("is_recommended")), options[0] if options else {})
    selected_name = rec_opt.get("name", "")
    rejected_opts = [o for o in options if not o.get("is_recommended")]

    # ── Header ───────────────────────────────────
    lines += [
        f"# Architecture Decision Document — {project}",
        "",
        f"| Field | Value |",
        f"|---|---|",
        f"| **Project** | {project} |",
        f"| **Request Type** | {request_type.title()} |",
        f"| **Cloud** | {cloud} |",
        f"| **Pattern** | {pattern.title()} |",
        f"| **Generated** | Architecture Agent v1.0 |",
        f"| **Status** | Draft — Pending Engineering Review |",
        "",
        "---",
        "",
    ]

    # ── Decision summary ─────────────────────────
    top_score = rec_opt.get("scores", {}).get("weighted_score", 0)

    lines += [
        "## Decision Summary",
        "",
        f"> **Build with:** {selected_name}",
        f">",
        f"> **Why:** {rec_opt.get('justification', '')}",
        f">",
        f"> **Score:** {top_score:.2f} / 10 (highest across all options)",
        "",
        "---",
        "",
    ]

    # ── Options at a glance ───────────────────────
    lines += [
        "## Options at a Glance",
        "",
        "| | " + " | ".join(f"Option {o.get('option_id')} {'✅' if o.get('name') == selected_name else ''}" for o in options) + " |",
        "|---|" + "|".join("---|" for _ in options),
        "| **Name** | " + " | ".join(o.get("name", "") for o in options) + " |",
        "| **Pattern** | " + " | ".join(o.get("pattern_type", "").title() for o in options) + " |",
        "| **Processing** | " + " | ".join(o.get("tech_stack", {}).get("processing", {}).get("tool", "—") for o in options) + " |",
        "| **Storage** | " + " | ".join(o.get("tech_stack", {}).get("storage", {}).get("tool", "—") for o in options) + " |",
        "| **Weighted Score** | " + " | ".join(f"**{o.get('scores', {}).get('weighted_score', 0):.2f}**{'  ✅' if o.get('is_recommended') else ''}" for o in options) + " |",
        "",
        "---",
        "",
    ]

    # ── Each option ───────────────────────────────
    for opt in options:
        is_rec = opt.get("name") == selected_name
        badge = " ✅ Recommended" if is_rec else ""
        lines += [
            f"## Option {opt.get('option_id')} — {opt.get('name')}{badge}",
            "",
            f"**Pattern:** {opt.get('pattern_type', '').title()}",
            "",
        ]

        # Flow
        flow = opt.get("flow", {})
        lines += [
            "### End-to-End Flow",
            "",
            "| Stage | Description |",
            "|---|---|",
            f"| Ingestion | {flow.get('ingestion', '—')} |",
            f"| Processing | {flow.get('processing', '—')} |",
            f"| Storage | {flow.get('storage', '—')} |",
            f"| Consumption | {flow.get('consumption', '—')} |",
            "",
        ]

        # Tool stack
        stack = opt.get("tech_stack", {})
        lines += [
            "### Tool Stack",
            "",
            "| Component | Tool | Version | Managed |",
            "|---|---|---|---|",
        ]
        for component, details in stack.items():
            tool = details.get("tool", "—")
            version = details.get("version") or "—"
            managed = "Yes" if details.get("managed") else "No"
            lines.append(f"| {component.title()} | {tool} | {version} | {managed} |")
        lines.append("")

        # Pros / Cons
        pros = opt.get("pros", [])
        cons = opt.get("cons", [])
        if pros:
            lines += ["### Pros", ""]
            lines += [f"- {p}" for p in pros]
            lines.append("")
        if cons:
            lines += ["### Cons", ""]
            lines += [f"- {c}" for c in cons]
            lines.append("")

        # Risks
        risk = opt.get("risks", {})
        if risk:
            lines += [
                "### Option Risks",
                "",
                "| Risk Area | Description |",
                "|---|---|",
            ]
            for area, desc in risk.items():
                lines.append(f"| {area.replace('_', ' ').title()} | {desc} |")
            lines.append("")

        # Scores
        scores = opt.get("scores", {})
        lines += [
            "### Scores",
            "",
            "| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |",
            "|:---:|:---:|:---:|:---:|:---:|:---:|",
            f"| {scores.get('cost', '—')} | {scores.get('scalability', '—')} | {scores.get('complexity', '—')} | {scores.get('latency', '—')} | {scores.get('operability', '—')} | **{scores.get('weighted_score', 0):.2f}** |",
            "",
            "---",
            "",
        ]

    # ── Scoring table ─────────────────────────────
    lines += [
        "## Scoring Table",
        "",
        "| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|",
    ]
    for row in scoring_table:
        mark = " ✅" if row.get("option_id") == rec_opt.get("option_id") else ""
        lines.append(
            f"| {row.get('option')}{mark} | {row.get('cost')} | {row.get('scalability')} | "
            f"{row.get('complexity')} | {row.get('latency')} | {row.get('operability')} | "
            f"**{row.get('weighted_score', 0):.2f}** |"
        )
    lines += [
        "",
        "> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`",
        "",
        "---",
        "",
    ]

    # ── Recommendation — reads from options[], not a separate block ──────────
    lines += [
        "## Recommended Architecture",
        "",
        f"**{selected_name}**",
        f"**Weighted Score: {top_score:.2f}**",
        "",
        f"**Justification:** {rec_opt.get('justification', '')}",
        "",
        f"**Why highest score:** {rec_opt.get('why_highest_score', '')}",
        "",
        f"**Trade-offs accepted:** {rec_opt.get('trade_offs_accepted', '')}",
        "",
        "---",
        "",
    ]

    # ── Rejected options — reads from options[], not a separate block ─────────
    if rejected_opts:
        lines += ["## Rejected Options", ""]
        for r in rejected_opts:
            lines += [
                f"### {r.get('name')}",
                "",
                r.get("rejection_reason", ""),
                "",
            ]
        lines += ["---", ""]

    # ── Global risks ──────────────────────────────
    if risks:
        lines += [
            "## Risks & Mitigations",
            "",
            "| Risk | Description | Mitigation |",
            "|---|---|---|",
        ]
        for r in risks:
            lines.append(
                f"| {r.get('category', '—')} | {r.get('description', '—')} | {r.get('mitigation', '—')} |"
            )
        lines += ["", "---", ""]

    # ── Assumptions ───────────────────────────────
    if assumptions:
        lines += ["## Assumptions", ""]
        for i, a in enumerate(assumptions, 1):
            lines.append(f"{i}. {a}")
        lines += ["", "---", ""]

    # ── Traceability ──────────────────────────────
    if traceability:
        lines += [
            "## Requirement Traceability",
            "",
            "| Architecture Decision | Requirement Field | Latency Need | Data Volume |",
            "|---|---|---|---|",
        ]
        for t in traceability:
            lines.append(
                f"| {t.get('decision', '—')} | {t.get('requirement_field', '—')} "
                f"| {t.get('latency_need') or '—'} | {t.get('data_volume') or '—'} |"
            )
        lines += ["", "---", ""]

    # ── Open questions ────────────────────────────
    if open_questions:
        lines += ["## Open Questions — Action Required", ""]
        for i, q in enumerate(open_questions, 1):
            lines.append(f"{i}. {q}")
        lines.append("")

    return "\n".join(lines)


# ──────────────────────────────────────────────
# Mermaid Flow Renderer
# ──────────────────────────────────────────────

def _render_mermaid(manifest: dict) -> str:
    """
    Render a Mermaid flowchart (.mmd) from the manifest.
    The recommended option is shown as the main flow; non-recommended
    options are rendered as separate subgraphs below.
    """
    project = manifest.get("project_name", "Unknown Project")
    cloud = manifest.get("cloud_platform", "GCP")
    pattern = manifest.get("inferred_pattern_type", "batch")
    options = manifest.get("options", [])

    rec = next((o for o in options if o.get("is_recommended")), options[0] if options else {})
    rejected = [o for o in options if not o.get("is_recommended")]

    def _safe(text: str) -> str:
        """Escape double-quotes for Mermaid node labels."""
        return str(text).replace('"', "'")

    def _tool(opt: dict, component: str) -> str:
        return _safe(opt.get("tech_stack", {}).get(component, {}).get("tool", component.title()))

    def _flow_label(opt: dict, stage: str) -> str:
        return _safe(opt.get("flow", {}).get(stage, stage.title()))

    lines: list[str] = [
        f"%% Architecture Flow: {_safe(project)} | {cloud} | {pattern}",
        "flowchart TB",
        "",
    ]

    # ── Recommended option ────────────────────────────────────────────────────
    rec_id = rec.get("option_id", 1)
    rec_name = _safe(rec.get("name", "Recommended"))
    orch_tool = _tool(rec, "orchestration")
    mon_tool = _tool(rec, "monitoring")
    iac_tool = _tool(rec, "iac")

    lines += [
        f'    subgraph rec["\u2b50 Option {rec_id}: {rec_name} \u2014 Recommended"]',
        f'        I1["\U0001f4e5 Ingestion<br/>{_tool(rec, "ingestion")}"]',
        f'        P1["\u2699\ufe0f Processing<br/>{_tool(rec, "processing")}"]',
        f'        S1["\U0001f4be Storage<br/>{_tool(rec, "storage")}"]',
        f'        C1["\U0001f4ca Consumption<br/>{_tool(rec, "consumption")}"]',
        f'        Orch1["\U0001f4c5 Orchestration<br/>{orch_tool}"]',
        f'        Mon1["\U0001f4cb Monitoring<br/>{mon_tool}"]',
        f'        IaC1["\U0001f528 IaC<br/>{iac_tool}"]',
        "        I1 --> P1 --> S1 --> C1",
        "        Orch1 -.->|schedules| I1",
        "        Orch1 -.->|orchestrates| P1",
        "        Mon1 -.->|observes| P1",
        "        IaC1 -.->|provisions| Orch1",
        "    end",
        "",
    ]

    # ── Non-recommended options ───────────────────────────────────────────────
    for opt in rejected:
        oid = opt.get("option_id", "?")
        oname = _safe(opt.get("name", f"Option {oid}"))
        node = f"o{oid}"
        lines += [
            f'    subgraph {node}["Option {oid}: {oname}"]',
            f'        I{oid}["\U0001f4e5 Ingestion<br/>{_tool(opt, "ingestion")}"]',
            f'        P{oid}["\u2699\ufe0f Processing<br/>{_tool(opt, "processing")}"]',
            f'        S{oid}["\U0001f4be Storage<br/>{_tool(opt, "storage")}"]',
            f'        C{oid}["\U0001f4ca Consumption<br/>{_tool(opt, "consumption")}"]',
            f"        I{oid} --> P{oid} --> S{oid} --> C{oid}",
            "    end",
            "",
        ]

    # ── Force vertical stacking via invisible links ──────────────────────────
    if rejected:
        lines.append(f"    rec ~~~ o{rejected[0].get('option_id')}")
        for i in range(len(rejected) - 1):
            lines.append(f"    o{rejected[i].get('option_id')} ~~~ o{rejected[i+1].get('option_id')}")
    lines.append("")

    # ── Styling ───────────────────────────────────────────────────────────────
    lines += [
        "    classDef recommended fill:#d4edda,stroke:#28a745,stroke-width:2px",
        "    classDef rejected fill:#f8f9fa,stroke:#6c757d,stroke-width:1px,stroke-dasharray:4",
        f"    class I1,P1,S1,C1,Orch1,Mon1,IaC1 recommended",
    ]
    if rejected:
        rej_nodes = ",".join(
            f"I{o.get('option_id')},P{o.get('option_id')},S{o.get('option_id')},C{o.get('option_id')}"
            for o in rejected
        )
        lines.append(f"    class {rej_nodes} rejected")

    return "\n".join(lines) + "\n"


# ──────────────────────────────────────────────
# Main Agent Class
# ──────────────────────────────────────────────

class ArchitectureAgent:
    """
    Architecture Agent. Instantiated by the orchestrator via init.get_agent().

    Usage:
        agent = ArchitectureAgent(config=config_dict)
        result = agent.run(requirements_input)
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        model_cfg = self.config.get("model", {})
        self.model = model_cfg.get("model_id", "claude-sonnet-4-20250514")
        self.max_tokens = model_cfg.get("max_tokens", 16000)
        self.temperature = model_cfg.get("temperature", 0.0)
        self.confidence_threshold = self.config.get("confidence_threshold", 0.7)
        self.output_dir = Path(self.config.get("paths", {}).get("output_dir", "output"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── Public ──────────────────────────────────

    def run(
        self,
        requirements_input: dict[str, Any],
    ) -> AgentResult:
        """
        Full agent execution pipeline.

        Args:
            requirements_input: Dict from the Requirements Agent (RequirementsOutput.to_dict()).

        Returns:
            AgentResult with manifest or skip/error info.
        """
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        start = time.monotonic()
        logger.info("=== ArchitectureAgent.run  run_id=%s ===", run_id)

        try:
            req = dict(requirements_input)

            # ── Step 1: Run-plan validation ──
            plan_warnings = validate_run_plan(
                req.get("run_plan", []), req.get("request_type", "")
            )

            # ── Step 2: Gate — should we skip? ──
            skip_reason = self._should_skip(req)
            if skip_reason:
                elapsed = time.monotonic() - start
                logger.info("Agent SKIPPED: %s", skip_reason)
                return AgentResult(
                    success=True, skipped=True, skip_reason=skip_reason,
                    run_id=run_id, duration_seconds=round(elapsed, 2),
                )

            # ── Step 3: Input validation ──
            input_errors = validate_input(req)
            if input_errors:
                elapsed = time.monotonic() - start
                return AgentResult(
                    success=False,
                    error="Input validation failed:\n" + "\n".join(f"  - {e}" for e in input_errors),
                    run_id=run_id, duration_seconds=round(elapsed, 2),
                )

            # ── Step 4: Compute skill context ──
            skill_ctx = self._compute_skill_context(req)
            logger.info(
                "Skills: cloud=%s  pattern=%s  volume=%s  latency=%s",
                skill_ctx["cloud_platform"],
                skill_ctx["inferred_pattern_type"],
                skill_ctx["volume_tier"],
                skill_ctx["latency_tier"],
            )

            # ── Step 5: Build prompt + call LLM ──
            user_msg = build_user_message(
                requirements=req,
                skill_context=skill_ctx,
            )

            logger.info("Calling LLM...")
            llm_result = llm_call(
                system_prompt=SYSTEM_PROMPT,
                user_message=user_msg,
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            # ── Step 6: Parse manifest ──
            parsed = validate_json(llm_result["text"])
            if not parsed["valid"]:
                elapsed = time.monotonic() - start
                return AgentResult(
                    success=False,
                    error=f"Failed to parse LLM response as JSON: {parsed['error']}",
                    run_id=run_id, duration_seconds=round(elapsed, 2),
                    token_usage={"input": llm_result["input_tokens"], "output": llm_result["output_tokens"]},
                )

            manifest = parsed["data"]

            # ── Step 7: Enrich manifest with Python-built fields ──
            # scoring_table and handoff_summary are not generated by the LLM
            # (saves ~500 output tokens per run) — built deterministically here
            manifest["scoring_table"] = _build_scoring_table(manifest)
            manifest["handoff_summary"] = _build_handoff_summary(manifest)

            # ── Step 8: Post-validate ──
            warnings = validate_manifest(manifest)
            warnings.extend(plan_warnings)

            # ── Step 9: Write outputs ──
            handoff = manifest["handoff_summary"]
            self._write_outputs(manifest, handoff, requirements_input)

            elapsed = time.monotonic() - start
            logger.info("=== ArchitectureAgent.run COMPLETE  %.1fs ===", elapsed)

            return AgentResult(
                success=True,
                manifest=manifest,
                handoff_summary=handoff,
                validation_warnings=warnings,
                run_id=run_id,
                duration_seconds=round(elapsed, 2),
                token_usage={"input": llm_result["input_tokens"], "output": llm_result["output_tokens"]},
            )

        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.exception("Agent failed with exception")
            return AgentResult(
                success=False,
                error=str(exc),
                run_id=run_id,
                duration_seconds=round(elapsed, 2),
            )

    # ── Private ─────────────────────────────────

    def _should_skip(self, req: dict) -> Optional[str]:
        """Return skip reason if agent should not run, else None."""
        run_plan = req.get("run_plan", [])
        if run_plan and "architecture" not in run_plan:
            return f"'architecture' not in run_plan {run_plan} — skipping per orchestrator."
        return None

    def _compute_skill_context(self, req: dict) -> dict:
        """Run all skills and assemble context dict for the prompt."""
        classification = req.get("classification", {})
        technology = req.get("technology", {})
        non_functional = req.get("non_functional", {})
        volume = req.get("data_requirements", {}).get("volume")

        cloud = resolve_cloud(technology)
        pattern = resolve_pattern_type(classification, non_functional)
        volume_tier = resolve_volume_tier(volume)
        latency_tier = resolve_latency_tier(non_functional.get("latency"))
        conf = evaluate_confidence(req, self.confidence_threshold)

        return {
            "cloud_platform": cloud,
            "inferred_pattern_type": pattern,
            "volume_tier": volume_tier,
            "latency_tier": latency_tier,
            "ingestion_type": classification.get("ingestion_type", "unknown"),
            "output_type": classification.get("output_type", "unknown"),
            "confidence": conf,
            "confidence_threshold": self.confidence_threshold,
        }

    def _write_outputs(self, manifest: dict, handoff: dict, requirements_input: dict) -> None:
        """Write flow diagram, handoff JSON, and Markdown report."""
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H")
        jira_id = requirements_input.get('ticket_id')
        prefix = str(self.output_dir / f"arc_{jira_id}_{run_id}")

        handoff["ticket_id"] = jira_id

        write_file(f"{prefix}_flow.mmd", _render_mermaid(manifest))
        write_file(f"{prefix}_summary.json", json.dumps(handoff, indent=2))
        write_file(f"{prefix}_report.md", _render_markdown(manifest))

        logger.info("Outputs written to %s_architecture_*", prefix)
