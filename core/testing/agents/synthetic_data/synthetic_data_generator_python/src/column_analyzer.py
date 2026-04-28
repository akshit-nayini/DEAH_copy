"""
column_analyzer.py
------------------
Rule-based column profiler. Analyzes source table rows and produces
a column profile used by data_generator.py and sql_writer.py.

Detects:
  - Data types  : string, integer, float, date, datetime, boolean
  - ENUM        : limited distinct values (status, currency, category…)
  - ID patterns : PREFIX-DIGITS (ORD-10001), UUID
  - Ranges      : min/max for numerics and dates
  - Lengths     : min/max for strings
  - Nullability : null rate
  - Ordinal position
"""

import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional


# ── Constants ──────────────────────────────────────────────────────────────────
SAMPLE_SIZE      = 1000   # max rows to analyze
ENUM_THRESHOLD   = 0.20   # distinct/total ratio for ENUM detection
ENUM_ABSOLUTE    = 30     # if distinct count ≤ this → always ENUM (regardless of ratio)
ENUM_MAX_VALUES  = 50     # hard cap on enum cardinality

DATE_FORMATS = [
    "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y",
    "%d/%m/%Y", "%Y/%m/%d", "%Y%m%d",
]
DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S",   "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f","%Y-%m-%dT%H:%M:%SZ",
    "%d-%m-%Y %H:%M:%S",   "%m/%d/%Y %H:%M:%S",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _try_parse_date(value: str) -> Optional[str]:
    """Return matched format string or None."""
    v = value.strip()
    for fmt in DATETIME_FORMATS + DATE_FORMATS:
        try:
            datetime.strptime(v, fmt)
            return fmt
        except ValueError:
            pass
    return None


def _detect_prefix_pattern(values: List[str]) -> Optional[Dict]:
    """
    Detect structured ID patterns like ORD-12345 or UUID.
    Returns a pattern descriptor dict or None.
    """
    if not values:
        return None

    # UUID check
    uuid_re = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I
    )
    if all(uuid_re.match(v) for v in values[:20] if v):
        return {"type": "uuid"}

    # PREFIX-DIGITS check  e.g. ORD-10001
    pfx_re = re.compile(r'^([A-Z][A-Z0-9_\-]+)-(\d+)$')
    sample  = [v for v in values[:50] if v]
    matches = [pfx_re.match(v) for v in sample]
    matched = [m for m in matches if m]

    if len(matched) >= min(5, len(sample)):
        prefixes  = Counter(m.group(1) for m in matched)
        top_pfx   = prefixes.most_common(1)[0][0]
        dig_lens  = [len(m.group(2)) for m in matched]
        nums      = [int(m.group(2)) for m in matched]
        return {
            "type":         "prefixed_id",
            "prefix":       top_pfx,
            "digit_length": int(sum(dig_lens) / len(dig_lens)),
            "min_num":      min(nums),
            "max_num":      max(nums),
        }

    return None


def _infer_base_type(non_null: List[str]) -> str:
    """Infer the scalar type of a column from its non-null sample values."""
    if not non_null:
        return "string"

    # Boolean
    bool_set = {"true","false","yes","no","1","0","t","f","y","n"}
    if all(v.lower() in bool_set for v in non_null):
        return "boolean"

    # Integer
    def is_int(v):
        try: int(v.replace(",", "")); return True
        except ValueError: return False

    # Float
    def is_float(v):
        try: float(v.replace(",", "")); return True
        except ValueError: return False

    if all(is_int(v) for v in non_null):
        return "integer"

    if all(is_float(v) for v in non_null):
        return "float"

    # Date / Datetime — test first 50 values
    fmt_counter: Counter = Counter()
    for v in non_null[:50]:
        fmt = _try_parse_date(v)
        if fmt:
            fmt_counter[fmt] += 1

    if fmt_counter:
        top_fmt, top_count = fmt_counter.most_common(1)[0]
        if top_count >= len(non_null[:50]) * 0.8:
            return "datetime" if any(c in top_fmt for c in ("H","M","S")) else "date"

    return "string"


# ── Main analyzer ──────────────────────────────────────────────────────────────

def analyze_columns(rows: List[Dict[str, Any]]) -> List[Dict]:
    """
    Analyze source rows and return a list of column profile dicts,
    one per column, in ordinal order.

    Each profile dict contains:
        name, ordinal, base_type, is_enum, enum_values,
        is_nullable, null_rate, min_value, max_value,
        min_length, max_length, date_format, pattern, prefix
    """
    if not rows:
        return []

    sample  = rows[:SAMPLE_SIZE]
    columns = list(sample[0].keys())
    total   = len(sample)
    profile = []

    NULL_SET = {None, "", "NULL", "null", "N/A", "n/a", "NaN", "nan"}

    for pos, col in enumerate(columns):
        raw     = [row.get(col, None) for row in sample]
        non_null = [
            str(v).strip() for v in raw
            if v not in NULL_SET and str(v).strip() not in NULL_SET
        ]
        null_count = total - len(non_null)
        null_rate  = round(null_count / total, 4) if total else 0.0

        base_type = _infer_base_type(non_null)

        # ── ENUM detection ──────────────────────────────────────────────────
        distinct_vals = list(set(non_null))
        n_distinct    = len(distinct_vals)
        ratio         = n_distinct / total if total else 1.0

        # Detect ID pattern first — ID columns are never ENUM
        pattern = _detect_prefix_pattern(non_null) if base_type == "string" else None
        has_id_pattern = pattern is not None
        all_unique     = (n_distinct == len(non_null))

        is_enum = (
            bool(non_null)
            and not has_id_pattern
            and not all_unique
            and base_type not in ("date", "datetime")
            and n_distinct <= ENUM_MAX_VALUES
            and (n_distinct <= ENUM_ABSOLUTE or ratio <= ENUM_THRESHOLD)
        )

        # ── String metrics ──────────────────────────────────────────────────
        min_len = max_len = None
        if base_type == "string" and non_null:
            lengths = [len(v) for v in non_null]
            min_len = min(lengths)
            max_len = max(lengths)

        # ── Numeric metrics ─────────────────────────────────────────────────
        min_val = max_val = None
        if base_type in ("integer", "float") and non_null:
            nums    = [float(v.replace(",", "")) for v in non_null]
            min_val = int(min(nums)) if base_type == "integer" else round(min(nums), 2)
            max_val = int(max(nums)) if base_type == "integer" else round(max(nums), 2)

        # ── Date metrics ────────────────────────────────────────────────────
        date_format = None
        if base_type in ("date", "datetime") and non_null:
            fmt_counter: Counter = Counter()
            for v in non_null[:100]:
                for fmt in DATETIME_FORMATS + DATE_FORMATS:
                    try:
                        datetime.strptime(v.strip(), fmt)
                        fmt_counter[fmt] += 1
                        break
                    except ValueError:
                        pass
            if fmt_counter:
                date_format = fmt_counter.most_common(1)[0][0]

            # min / max dates
            parsed = []
            for v in non_null:
                try:
                    if date_format:
                        parsed.append(datetime.strptime(v.strip(), date_format))
                except ValueError:
                    pass
            if parsed:
                min_val = min(parsed).strftime(date_format)
                max_val = max(parsed).strftime(date_format)

        # ── Prefix extraction ───────────────────────────────────────────────
        prefix = None
        if pattern and pattern.get("type") == "prefixed_id":
            prefix = pattern.get("prefix")

        profile.append({
            "name":        col,
            "ordinal":     pos,
            "base_type":   base_type,
            "is_enum":     is_enum,
            "enum_values": sorted(distinct_vals) if is_enum else None,
            "is_nullable": null_rate > 0,
            "null_rate":   null_rate,
            "min_value":   min_val,
            "max_value":   max_val,
            "min_length":  min_len,
            "max_length":  max_len,
            "date_format": date_format,
            "pattern":     pattern.get("type") if pattern else None,
            "prefix":      prefix,
            "digit_length": pattern.get("digit_length") if pattern else None,
            "min_num":     pattern.get("min_num") if pattern else None,
            "max_num":     pattern.get("max_num") if pattern else None,
        })

    return profile


def print_profile(profile: List[Dict]) -> None:
    """Pretty-print the column profile."""
    print(f"\n{'='*65}")
    print(f"  COLUMN PROFILE  ({len(profile)} columns)")
    print(f"{'='*65}")
    for col in profile:
        print(f"\n  [{col['ordinal']}] {col['name']}")
        print(f"      type     : {col['base_type']}")
        if col["is_enum"]:
            print(f"      ENUM     : {col['enum_values']}")
        if col["pattern"] == "prefixed_id":
            print(f"      pattern  : prefixed_id  [{col['prefix']}-{'X'*col.get('digit_length',5)}]")
        if col["pattern"] == "uuid":
            print(f"      pattern  : UUID")
        if col["min_length"] is not None:
            print(f"      length   : {col['min_length']} – {col['max_length']}")
        if col["min_value"] is not None:
            print(f"      range    : {col['min_value']} – {col['max_value']}")
        if col["date_format"]:
            print(f"      date fmt : {col['date_format']}")
        print(f"      nullable : {col['is_nullable']}  (null_rate={col['null_rate']})")
    print(f"\n{'='*65}\n")
