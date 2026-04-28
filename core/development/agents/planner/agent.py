"""Planner agent.

Token strategy
──────────────
Sends implementation_md and mapping_csv as CACHED context blocks.
Anthropic stores them server-side for ~5 minutes.  All subsequent agents
(generator, optimizer, reviewer) will read the same blocks from cache,
paying only for the task-specific prompt tokens on each call.

Human context from checkpoints is injected into the task prompt so the LLM
can refine its plan without re-reading the full documents.

No-assumption policy
─────────────────────
The planner must be ≥ 95% confident in every field it states.
If confidence is lower, it outputs ## Clarifying Questions instead of assuming.
The pipeline enforces that BLOCKER questions are answered before code generation.
"""
from __future__ import annotations
import logging
import re

from core.utilities.llm import BaseLLMClient, ContextBlock
from api.models import (
    ExecutionPlan, SessionContext, AuditTableSpec, StoreProcSpec,
    ServiceSpec, TableSpec, ArtifactSpec,
    ConnectionDetailSpec, LoggingSpec, AlertingSpec,
)
from agents.planner.prompts import PLANNER_SYSTEM, build_planner_task, build_question_extraction_task

logger = logging.getLogger("development.planner")

_REQUIRED_CSV_COLUMNS = {
    "source_table", "source_column", "target_table",
    "target_column", "target_data_type",
}


class PlannerAgent:
    def __init__(self, llm: BaseLLMClient) -> None:
        self._llm = llm

    def plan(self, ctx: SessionContext) -> ExecutionPlan:
        issues = _validate_inputs(ctx)
        if issues:
            questions = [f"[BLOCKER] {issue}" for issue in issues]
            logger.warning("Planner pre-flight failed: %d issue(s)", len(issues))
            return ExecutionPlan(
                request_id=ctx.request_id,
                summary="Pre-flight validation failed — inputs are incomplete.",
                clarifying_questions=questions,
                open_blockers=issues,
                raw_plan="{}",
            )

        logger.info("Planner: generating execution plan (cached context)...")

        context_blocks = _build_context_blocks(ctx)
        task = build_planner_task(ctx.human_notes_block())
        response = self._llm.complete_with_context(
            context_blocks=context_blocks,
            task_prompt=task,
            system=PLANNER_SYSTEM,
            max_tokens=4096,
        )
        logger.info(
            "Planner: %d input tokens (%d from cache), %d output tokens",
            response.input_tokens, response.cache_read_tokens, response.output_tokens,
        )
        return _parse_plan_json(ctx.request_id, response.content)

    def extract_questions(self, ctx: SessionContext) -> list[str]:
        """Lightweight first LLM pass — returns only BLOCKER/IMPORTANT questions."""
        issues = _validate_inputs(ctx)
        if issues:
            return [f"[BLOCKER] {issue}" for issue in issues]

        logger.info("Planner: extracting questions (pre-plan pass)...")
        context_blocks = _build_context_blocks(ctx)
        response = self._llm.complete_with_context(
            context_blocks=context_blocks,
            task_prompt=build_question_extraction_task(),
            system=PLANNER_SYSTEM,
            max_tokens=1024,
        )
        return _parse_questions(response.content)


def _validate_inputs(ctx: SessionContext) -> list[str]:
    issues: list[str] = []

    if not ctx.implementation_md or len(ctx.implementation_md.strip()) < 50:
        issues.append(
            "Implementation.md is missing or too short to derive a pipeline plan. "
            "Please provide the full design document."
        )

    if ctx.mapping_csv and len(ctx.mapping_csv.strip()) >= 10:
        issues.extend(_validate_mapping_csv(ctx.mapping_csv))
    # No mapping CSV is allowed — planner will derive schema from the implementation docs.

    return issues


def _validate_mapping_csv(csv_text: str) -> list[str]:
    issues: list[str] = []
    lines = [l.strip() for l in csv_text.strip().splitlines() if l.strip()]
    if not lines:
        issues.append("mapping.csv has no rows.")
        return issues

    headers = [h.strip().lower() for h in lines[0].split(",")]
    missing = _REQUIRED_CSV_COLUMNS - set(headers)
    if missing:
        issues.append(
            f"mapping.csv is missing required column(s): {', '.join(sorted(missing))}. "
            f"Required: {', '.join(sorted(_REQUIRED_CSV_COLUMNS))}."
        )

    data_rows = [l for l in lines[1:] if l and not l.startswith("#")]
    if not data_rows:
        issues.append(
            "mapping.csv has a header row but no data rows. "
            "Add at least one source→target column mapping."
        )

    if "target_data_type" in headers:
        idx = headers.index("target_data_type")
        blank_rows = []
        for i, row in enumerate(data_rows, start=2):
            cols = row.split(",")
            if idx < len(cols) and not cols[idx].strip():
                blank_rows.append(i)
        if blank_rows:
            issues.append(
                f"mapping.csv rows {blank_rows} have blank target_data_type. "
                "Every column must have an explicit BigQuery target type "
                "(e.g. STRING, INT64, DATE, NUMERIC)."
            )

    return issues


def _build_context_blocks(ctx: SessionContext) -> list[ContextBlock]:
    meta_parts = [f"Env: {ctx.environment}", f"Cloud: {ctx.cloud_provider.upper()}"]
    if ctx.project_id:
        meta_parts.insert(0, f"Project: {ctx.project_id}")
    if ctx.dataset_id:
        meta_parts.insert(1 if ctx.project_id else 0, f"Dataset: {ctx.dataset_id}")
    meta_line = " | ".join(meta_parts)

    blocks = [
        ContextBlock(
            text=f"## Implementation Document\n{meta_line}\n\n{ctx.implementation_md}",
            label="implementation_md",
            cacheable=True,
        ),
    ]

    if ctx.mapping_csv and ctx.mapping_csv.strip():
        blocks.append(ContextBlock(
            text=f"## Column Mapping (CSV)\n```csv\n{ctx.mapping_csv}\n```",
            label="mapping_csv",
            cacheable=True,
        ))

    return blocks


def _parse_questions(raw: str) -> list[str]:
    """Extract question list from LLM JSON array response."""
    import json as _json
    json_match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    json_str = json_match.group(1).strip() if json_match else raw.strip()
    try:
        questions = _json.loads(json_str)
        return [q for q in questions if isinstance(q, str) and q.strip()]
    except Exception:
        # Fallback: extract lines starting with [BLOCKER] or [IMPORTANT]
        return [
            line.strip().lstrip("-* ")
            for line in raw.splitlines()
            if "[BLOCKER]" in line.upper() or "[IMPORTANT]" in line.upper()
        ]


def _parse_plan_json(request_id: str, raw: str) -> ExecutionPlan:
    """Parse the JSON plan response from the LLM."""
    import json as _json

    json_match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    json_str = json_match.group(1).strip() if json_match else raw.strip()

    try:
        data = _json.loads(json_str)
    except _json.JSONDecodeError:
        logger.warning("Plan response is not valid JSON — falling back to markdown parser")
        return _parse_plan_markdown(request_id, raw)

    audit_data = data.get("audit_table") or {}
    sp_data = data.get("store_proc") or {}

    # ── Parse new precision-capture fields (graceful degradation for old plans) ─
    def _safe_list(key: str, model):
        return [model(**item) for item in data.get(key, []) if isinstance(item, dict)]

    return ExecutionPlan(
        request_id=data.get("request_id") or request_id,
        sprint=data.get("sprint", ""),
        project=data.get("project", ""),
        summary=data.get("summary", ""),
        services=[ServiceSpec(**s) for s in data.get("services", [])],
        tables=[TableSpec(**t) for t in data.get("tables", [])],
        audit_table=AuditTableSpec(**audit_data) if audit_data else AuditTableSpec(),
        store_proc=StoreProcSpec(**sp_data) if sp_data else StoreProcSpec(),
        artifacts_to_generate=[ArtifactSpec(**a) for a in data.get("artifacts_to_generate", [])],
        patterns=data.get("patterns", []),
        pii_columns=data.get("pii_columns", []),
        clarifying_questions=data.get("clarifying_questions", []),
        open_blockers=data.get("open_blockers", []),
        connection_details=_safe_list("connection_details", ConnectionDetailSpec),
        logging_mechanisms=_safe_list("logging_mechanisms", LoggingSpec),
        alerting_mechanisms=_safe_list("alerting_mechanisms", AlertingSpec),
        raw_plan=_json.dumps(data, indent=2),
    )


def _parse_plan_markdown(request_id: str, raw: str) -> ExecutionPlan:
    """Fallback markdown parser (legacy format)."""
    def _section(header: str, text: str) -> list[str]:
        pattern = rf"##\s*{re.escape(header)}\s*(.*?)(?=\n##|\Z)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if not match:
            return []
        block = match.group(1).strip()
        return [
            line.lstrip("-*•0123456789. ").strip()
            for line in block.splitlines()
            if line.strip()
            and not line.strip().startswith("#")
            and line.strip().lower() != "none"
        ]

    summary_match = re.search(
        r"##\s*Summary\s*(.*?)(?=\n##|\Z)", raw, re.DOTALL | re.IGNORECASE
    )
    summary = summary_match.group(1).strip() if summary_match else raw[:400]

    artifact_lines = _section("Artifacts to Generate", raw)
    artifacts = []
    for line in artifact_lines:
        parts = line.split("—", 1)
        fname = parts[0].strip()
        reason = parts[1].strip() if len(parts) > 1 else ""
        ext = fname.rsplit(".", 1)[-1].upper() if "." in fname else ""
        atype = {"SQL": "DDL", "PY": "DAG"}.get(ext, ext)
        artifacts.append(ArtifactSpec(file_name=fname, type=atype, reason=reason))

    table_lines = _section("Tables", raw)
    tables = []
    for line in table_lines:
        parts = line.split("(", 1)
        name = parts[0].strip()
        layer = ""
        if len(parts) > 1:
            layer_part = parts[1].lower()
            for l in ("staging", "core", "quarantine"):
                if l in layer_part:
                    layer = l
                    break
        tables.append(TableSpec(name=name, layer=layer))

    return ExecutionPlan(
        request_id=request_id,
        summary=summary,
        artifacts_to_generate=artifacts,
        tables=tables,
        patterns=_section("Patterns", raw),
        pii_columns=_section("PII Columns", raw),
        open_blockers=_section("Open Blockers", raw),
        clarifying_questions=_section("Clarifying Questions", raw),
        raw_plan=raw,
    )
