"""Stage 10 — Gap analysis: field completeness + LLM suggestions + coverage gaps.

Runs automatically after Stage 9 (persist). Results are stored on the task (gap_report)
and source file (coverage_gaps) records. No human intervention required.

Fields checked:
  Columns  : acceptance_criteria, schedule_interval, story_points, priority, assignee
  Metadata : project_name, stakeholder_name, objective, expected_outcome,
             connections_db_details, success_conditions, validation_rules
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Quality validators ────────────────────────────────────────────────────────

# Generic database/technology product names that alone don't constitute
# meaningful connection details.
_GENERIC_DB_WORDS = re.compile(
    r"\b(mysql|bigquery|big\s*query|postgresql|postgres|oracle|sql\s*server|sqlserver|"
    r"mongodb|redis|sqlite|mariadb|google|amazon|aws|azure|gcp|database|source|"
    r"destination|target|db|cloud|warehouse|lake|ingestion|pipeline|data|"
    r"dataset|schema|table|primary|secondary|replica)\b",
    re.IGNORECASE,
)


def _connections_db_meaningful(val: str) -> bool:
    """
    Return True only when val contains specific connection details — not just
    generic technology names.

    Passes  : "host=prod-db.internal port=3306 schema=sales_db"
    Passes  : "MySQL source: 10.0.0.1:3306/orders_db → BigQuery project=acme dataset=dw"
    Fails   : "MySQL database (source), Google BigQuery (destination)"
    Fails   : "MySQL database (source), Google BigQuery (target dataset)"
    Fails   : "Source: MySQL, Destination: BigQuery"
    """
    if not val:
        return False
    stripped = val.strip()
    if len(stripped) < 15:
        return False
    # Specific connection indicators: = (key=value), : (host:port), / (path/schema),
    # @ (user@host), multi-digit numbers (port / IP octets)
    if re.search(r"[=:/@]|\b\d{3,}\b", stripped):
        return True
    # Remove generic product/role words, then strip punctuation/whitespace,
    # and measure how many meaningful alphanumeric characters remain.
    remainder = _GENERIC_DB_WORDS.sub("", stripped)
    remainder_alpha = re.sub(r"[^a-zA-Z0-9_\-]", "", remainder)
    return len(remainder_alpha) > 10


def _has_substance(val: str, min_len: int = 20) -> bool:
    """Return True if val is a non-trivial string (not just a few words)."""
    return bool(val) and len(val.strip()) >= min_len

# ── Prompts ───────────────────────────────────────────────────────────────────

_TASK_GAP_SYSTEM = """You are a senior requirements analyst reviewing sprint tasks extracted from a meeting transcript.

For each task provided, suggest concrete values for any missing fields.

Return a raw JSON array only (no markdown, no extra text):
[
  {
    "task_id": "<id>",
    "quality_score": <integer 0-100>,
    "suggestions": {
      "acceptance_criteria": "<JSON array string of 2-4 measurable criteria — only if missing>",
      "schedule_interval":   "<daily|weekly|hourly|on-demand — only if missing>",
      "story_points":        "<Fibonacci: 1|2|3|5|8|13|21 as string — only if missing>",
      "priority":            "<critical|high|medium|low — only if missing>",
      "assignee":            "<developer name from transcript — only if found and missing>",
      "project_name":        "<project name from transcript — only if missing>",
      "stakeholder_name":    "<stakeholder/requestor name — only if missing>",
      "objective":           "<1-2 sentence objective — only if missing>",
      "expected_outcome":    "<measurable outcome — only if missing>",
      "connections_db_details": "<source/target DB and connection details — only if missing>",
      "success_conditions":  "<JSON array string of success conditions — only if missing>",
      "validation_rules":    "<JSON array string of validation rules — only if missing>"
    },
    "assumptions": ["<assumption text for vague/ambiguous requirements>"]
  }
]

Rules:
- ONLY include a field in suggestions if it is missing/empty in the task data
- acceptance_criteria: e.g. "[\"Pipeline completes within SLA\",\"Failures trigger alerts\",\"Schema validated before load\"]"
- success_conditions / validation_rules: use JSON array strings same as acceptance_criteria
- quality_score: start at 100, subtract 20 per high-severity gap, 10 per medium
- assumptions: add only if requirement is genuinely vague (e.g. 'all tables' without specifying which)
"""

_COVERAGE_GAP_SYSTEM = """You are a senior requirements analyst reviewing sprint planning outputs.

Given the extracted task list and the original transcript, identify important topics mentioned in the
transcript that were NOT captured as tasks.

Return raw JSON only (no markdown):
{
  "gaps": [
    {
      "topic": "<short descriptive name>",
      "description": "<what was discussed but not captured as a task>",
      "severity": "high|medium|low"
    }
  ]
}

Focus on:
- Functionality mentioned but missing from the task list
- Missing categories: security/auth, testing/QA, deployment, monitoring, rollback, error handling
- Integrations or dependencies discussed but not captured
- Return at most 6 gaps, ranked by severity (high first)
- If no significant gaps exist, return {"gaps": []}
"""

# ── Field definitions ─────────────────────────────────────────────────────────
# can_apply=True  → stored as a DB column, auto-patchable via /gaps/apply
# can_apply=False → stored in raw_llm_json metadata, must be filled via Edit modal

_GAP_FIELD_DEFS: list[dict] = [
    # ── High severity ─────────────────────────────────────────────────────────
    {"field": "project_name",           "label": "Project Name",           "severity": "high",   "can_apply": False},
    {"field": "objective",              "label": "Objective",              "severity": "high",   "can_apply": False},
    {"field": "acceptance_criteria",    "label": "Acceptance Criteria",    "severity": "high",   "can_apply": True},
    {"field": "success_conditions",     "label": "Success Conditions",     "severity": "high",   "can_apply": False},
    # ── Medium severity ───────────────────────────────────────────────────────
    {"field": "stakeholder_name",       "label": "Stakeholder",            "severity": "medium", "can_apply": False},
    {"field": "schedule_interval",      "label": "Schedule Interval",      "severity": "medium", "can_apply": True},
    {"field": "expected_outcome",       "label": "Expected Outcome",       "severity": "medium", "can_apply": False},
    {"field": "connections_db_details", "label": "Connections & DB Details","severity": "medium","can_apply": False},
    {"field": "validation_rules",       "label": "Validation Rules",       "severity": "medium", "can_apply": False},
    {"field": "story_points",           "label": "Story Points",           "severity": "medium", "can_apply": True},
    {"field": "priority",               "label": "Priority",               "severity": "medium", "can_apply": True},
    {"field": "assignee",               "label": "Assignee",               "severity": "medium", "can_apply": True},
]


_FIELD_LABEL: dict[str, str] = {defn["field"]: defn["label"] for defn in _GAP_FIELD_DEFS}


def _parse_meta(task: Any) -> dict:
    """Extract metadata fields from raw_llm_json."""
    raw = getattr(task, "raw_llm_json", None) or "{}"
    try:
        return json.loads(raw)
    except Exception:
        return {}


# Patterns written into description by _build_description_text() in output.py.
# Each maps a metadata field name to the text marker that signals its presence.
_DESC_MARKERS: dict[str, str] = {
    "project_name":           "Project Name:",
    "stakeholder_name":       "Stakeholder:",
    "objective":              "## Objective",
    "expected_outcome":       "## Expected Outcome",
    "connections_db_details": "## Connections and DB Details",
    "success_conditions":     "**Success Conditions:**",
    "validation_rules":       "**Validation Rules:**",
}


def _in_description(field: str, description: str) -> bool:
    """
    Return True if the field's content is already embedded in the description text.
    Uses the exact markers that _build_description_text() writes.
    """
    marker = _DESC_MARKERS.get(field)
    if not marker or not description:
        return False
    idx = description.find(marker)
    if idx == -1:
        return False
    # There must be non-empty content after the marker on the same or next line
    snippet = description[idx + len(marker):idx + len(marker) + 100].strip()
    return bool(snippet)


def _field_present(field: str, task: Any, meta: dict) -> bool:
    """Return True if the field has a meaningful value — checks column, metadata, and description."""
    # ── Fields stored as direct DB columns ───────────────────────────────────
    if field in ("acceptance_criteria", "schedule_interval", "story_points", "priority", "assignee"):
        val = getattr(task, field, None)
        if field == "acceptance_criteria":
            if not val:
                return False
            try:
                parsed = json.loads(val)
                return isinstance(parsed, list) and len(parsed) > 0
            except Exception:
                return len(val.strip()) > 0
        if field == "story_points":
            return val is not None
        return bool(val)

    # ── Fields stored in raw_llm_json metadata ───────────────────────────────
    val = meta.get(field)
    if isinstance(val, list):
        if len(val) > 0:
            return True
    elif val:
        str_val = str(val)
        # Quality gates: certain fields require more than just a non-empty string
        if field == "connections_db_details":
            if not _connections_db_meaningful(str_val):
                # Generic value (e.g. "MySQL (source), BigQuery (destination)") — treat as missing
                pass
            else:
                return True
        elif field in ("objective", "expected_outcome"):
            if not _has_substance(str_val, min_len=20):
                # Too brief to be meaningful
                pass
            else:
                return True
        else:
            return True

    # ── Fall back: scan description text for embedded field content ───────────
    description = getattr(task, "description", None) or ""
    if not _in_description(field, description):
        return False

    # For quality-gated fields, extract only the section content (stopping at
    # the next ## heading) to avoid false positives from colons/slashes in
    # subsequent sections like "**Success Conditions:**".
    if field in ("connections_db_details", "objective", "expected_outcome"):
        marker = _DESC_MARKERS[field]
        idx = description.find(marker)
        rest = description[idx + len(marker):]
        # Stop at the next section header
        next_section = re.search(r"\n##\s", rest)
        snippet = (rest[:next_section.start()] if next_section else rest[:300]).strip()

        if field == "connections_db_details":
            return _connections_db_meaningful(snippet)
        return _has_substance(snippet, min_len=20)

    return True


# ── Field gap detection (deterministic) ──────────────────────────────────────

_QUALITY_MESSAGES: dict[str, str] = {
    "connections_db_details": (
        "Connections & DB Details are incomplete — provide specific host, port, "
        "schema/dataset, and table names rather than just technology names"
    ),
    "objective": "Objective is too brief — describe the business problem being solved",
    "expected_outcome": "Expected Outcome is too brief — describe the measurable end state",
}


def _gap_message(field: str, label: str, meta: dict, task: Any) -> str:
    """Return a human-readable gap message, distinguishing missing vs low-quality values."""
    val = meta.get(field) or getattr(task, field, None)
    if val and field in _QUALITY_MESSAGES:
        return _QUALITY_MESSAGES[field]
    return f"{label} is missing"


def _check_field_gaps(task: Any) -> list[dict]:
    """Return a gap dict for each missing field, in defined order."""
    meta = _parse_meta(task)
    gaps = []
    for defn in _GAP_FIELD_DEFS:
        if not _field_present(defn["field"], task, meta):
            gaps.append({
                "field":     defn["field"],
                "label":     defn["label"],
                "severity":  defn["severity"],
                "can_apply": defn["can_apply"],
                "message":   _gap_message(defn["field"], defn["label"], meta, task),
                "suggestion": None,
                "resolved":  False,
            })
    return gaps


# ── Assumed-field detection ───────────────────────────────────────────────────

def _get_field_display_value(field: str, task: Any, meta: dict) -> str:
    """Return a short human-readable representation of a field's current value."""
    if field in ("acceptance_criteria", "schedule_interval", "story_points", "priority", "assignee"):
        val = getattr(task, field, None)
        if field == "acceptance_criteria" and val:
            try:
                items = json.loads(val)
                if isinstance(items, list):
                    return f"{len(items)} criteria defined"
            except Exception:
                pass
        return str(val) if val is not None else ""
    val = meta.get(field)
    if isinstance(val, list):
        return f"{len(val)} item(s)" if val else ""
    return str(val) if val else ""


def _check_assumed_fields(task: Any, gap_field_names: set[str]) -> list[dict]:
    """
    Return entries for fields that are present but were flagged by the LLM as assumed/inferred.
    Fields already identified as missing gaps are excluded to avoid duplication.
    """
    meta = _parse_meta(task)
    raw_assumed: list = meta.get("assumed_fields", [])
    if not raw_assumed:
        return []

    results = []
    for field_name in raw_assumed:
        if not isinstance(field_name, str):
            continue
        # Skip if already flagged as a missing gap
        if field_name in gap_field_names:
            continue
        # Only surface fields defined in our gap field defs
        if field_name not in _FIELD_LABEL:
            continue
        current_value = _get_field_display_value(field_name, task, meta)
        results.append({
            "field": field_name,
            "label": _FIELD_LABEL[field_name],
            "current_value": current_value,
            "message": "Assumed from the conversation — verify this is correct",
        })
    return results


# ── LLM-powered batch enrichment ──────────────────────────────────────────────

async def _llm_enrich_gaps(
    tasks_with_gaps: list[Any],
    transcript_text: str,
    llm: Any,
) -> tuple[dict[str, dict], dict[str, list], dict[str, int]]:
    """One LLM call for all tasks that have gaps. Returns (suggestions, assumptions, quality)."""
    suggestions_by_id: dict[str, dict] = {}
    assumptions_by_id: dict[str, list] = {}
    quality_by_id: dict[str, int] = {}

    if not tasks_with_gaps:
        return suggestions_by_id, assumptions_by_id, quality_by_id

    meta_by_id = {t.task_id: _parse_meta(t) for t in tasks_with_gaps}

    task_list = []
    for t in tasks_with_gaps:
        meta = meta_by_id[t.task_id]
        task_type = t.task_type.value if hasattr(t.task_type, "value") else str(t.task_type)
        task_list.append({
            "task_id":               t.task_id,
            "summary":               t.task_heading,
            "type":                  task_type,
            "priority":              t.priority,
            "story_points":          t.story_points,
            "acceptance_criteria":   t.acceptance_criteria,
            "schedule_interval":     t.schedule_interval,
            "assignee":              t.assignee,
            "description":           (t.description or "")[:400],
            # metadata fields
            "project_name":          meta.get("project_name") or "",
            "stakeholder_name":      meta.get("stakeholder_name") or "",
            "objective":             meta.get("objective") or "",
            "expected_outcome":      meta.get("expected_outcome") or "",
            "connections_db_details":meta.get("connections_db_details") or "",
            "success_conditions":    meta.get("success_conditions") or [],
            "validation_rules":      meta.get("validation_rules") or [],
        })

    transcript_excerpt = (transcript_text or "")[:3500]
    user_prompt = (
        f"Tasks to analyze:\n{json.dumps(task_list, indent=2)}\n\n"
        f"Transcript excerpt:\n{transcript_excerpt}"
    )

    try:
        raw = await llm.call_raw(_TASK_GAP_SYSTEM, user_prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
        results: list[dict] = json.loads(raw)
        for item in results:
            tid = item.get("task_id")
            if tid:
                suggestions_by_id[tid] = item.get("suggestions", {})
                assumptions_by_id[tid] = item.get("assumptions", [])
                quality_by_id[tid]     = item.get("quality_score", 70)
    except Exception as exc:
        logger.warning("LLM task gap enrichment failed: %s", exc)

    return suggestions_by_id, assumptions_by_id, quality_by_id


# ── Public: per-task gap analysis ─────────────────────────────────────────────

async def analyze_task_gaps_batch(
    tasks: list[Any],
    transcript_text: str,
    llm: Any,
) -> dict[str, str]:
    """
    Run gap analysis for all tasks. Returns dict[task_id -> gap_report JSON string].
    Field checks are deterministic; one LLM call handles suggestions for all tasks.
    """
    field_gaps_by_id = {t.task_id: _check_field_gaps(t) for t in tasks}
    tasks_with_gaps  = [t for t in tasks if field_gaps_by_id[t.task_id]]

    suggestions_by_id, assumptions_by_id, quality_by_id = await _llm_enrich_gaps(
        tasks_with_gaps, transcript_text, llm
    )

    reports: dict[str, str] = {}
    now = datetime.utcnow().isoformat()

    for task in tasks:
        tid  = task.task_id
        gaps = field_gaps_by_id[tid]

        # Apply suggestions to matching gaps
        suggestions = suggestions_by_id.get(tid, {})
        for gap in gaps:
            if gap["field"] in suggestions:
                gap["suggestion"] = suggestions[gap["field"]]

        # Quality score
        if tid in quality_by_id:
            quality_score = quality_by_id[tid]
        else:
            deductions   = sum(20 if g["severity"] == "high" else 10 for g in gaps)
            quality_score = max(0, 100 - deductions)

        # Assumed fields: present but inferred by the LLM (not explicitly stated)
        gap_field_names = {g["field"] for g in gaps}
        assumed_fields = _check_assumed_fields(task, gap_field_names)

        reports[tid] = json.dumps({
            "analyzed_at":   now,
            "quality_score": quality_score,
            "field_gaps":    gaps,
            "assumed_fields": assumed_fields,
            "assumptions":   assumptions_by_id.get(tid, []),
        })

    return reports


# ── Public: coverage gap analysis ────────────────────────────────────────────

async def analyze_coverage_gaps(
    tasks: list[Any],
    transcript_text: str,
    llm: Any,
) -> Optional[str]:
    """
    Compare extracted tasks vs transcript to find missing topics.
    Returns JSON string for SourceFile.coverage_gaps, or None on failure.
    """
    if not transcript_text or not tasks:
        return None

    task_summaries = "\n".join(
        f"- [{t.task_id}] {t.task_heading} ({t.task_type.value if hasattr(t.task_type, 'value') else t.task_type})"
        for t in tasks
    )
    user_prompt = (
        f"Extracted tasks:\n{task_summaries}\n\n"
        f"Full transcript:\n{(transcript_text or '')[:4000]}"
    )

    try:
        raw = await llm.call_raw(_COVERAGE_GAP_SYSTEM, user_prompt)
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
        result = json.loads(raw)
        return json.dumps({
            "analyzed_at": datetime.utcnow().isoformat(),
            "gaps":        result.get("gaps", []),
        })
    except Exception as exc:
        logger.warning("Coverage gap analysis failed: %s", exc)
        return None
