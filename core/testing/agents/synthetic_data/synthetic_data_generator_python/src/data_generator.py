"""
data_generator.py
-----------------
Rule-based synthetic row generator.
Uses the column profile from column_analyzer.py to produce realistic rows.

Generation strategy per column type:
  - ENUM       → random.choice from enum_values
  - integer    → random int between min_value and max_value
  - float      → random float between min_value and max_value (2 dp)
  - date       → random date between from_date and to_date (user config range)
  - datetime   → random datetime between from_date and to_date
  - boolean    → random TRUE / FALSE
  - prefixed_id→ PREFIX-<zero-padded-num>
  - uuid       → uuid4()
  - string     → random plausible string within min/max length
  - nullable   → emits None at observed null_rate
"""

import random
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


# ── RNG (seedable for reproducibility) ────────────────────────────────────────
_RNG = random.Random()


def set_seed(seed: int) -> None:
    _RNG.seed(seed)


# ── Plausible word pool for string columns ─────────────────────────────────────
_WORDS = [
    "oak", "pine", "elm", "ash", "bay", "cedar", "fir", "jade", "lake",
    "moor", "nova", "peak", "reef", "sage", "tide", "vale", "west", "york",
    "azure", "blaze", "coral", "dune", "ember", "frost", "grove", "haven",
    "iris", "jetty", "knoll", "larch", "marsh", "north", "opal", "prism",
    "quill", "ridge", "slate", "terra", "ultra", "vivid", "willow", "xenon",
    "yield", "zeal", "amber", "birch", "cliff", "delta", "eagle", "fjord",
]


def _random_string(min_len: int, max_len: int) -> str:
    target = _RNG.randint(max(1, min_len), max(1, max_len))
    words, current = [], 0
    while current < target:
        w = _RNG.choice(_WORDS)
        words.append(w)
        current += len(w) + 1
    result = " ".join(words)
    return result[:target].strip() or _RNG.choice(_WORDS)[:target]


def _random_date_in_range(from_date: str, to_date: str, fmt: str) -> str:
    """Generate a random date/datetime string within [from_date, to_date]."""
    try:
        dt_min = datetime.strptime(from_date, "%Y-%m-%d")
        dt_max = datetime.strptime(to_date,   "%Y-%m-%d")
        # For datetime columns extend to end of to_date
        if any(c in fmt for c in ("H", "M", "S")):
            dt_max = dt_max.replace(hour=23, minute=59, second=59)
        delta_secs = int((dt_max - dt_min).total_seconds())
        if delta_secs <= 0:
            return dt_min.strftime(fmt)
        return (dt_min + timedelta(seconds=_RNG.randint(0, delta_secs))).strftime(fmt)
    except (ValueError, TypeError):
        return datetime(2024, 1, 1).strftime(fmt)


def _prefixed_id(col: Dict) -> str:
    prefix      = col.get("prefix", "ID")
    digit_len   = col.get("digit_length", 5)
    min_num     = col.get("min_num", 1)
    max_num     = col.get("max_num", 99999)
    num         = _RNG.randint(min_num, max_num)
    return f"{prefix}-{str(num).zfill(digit_len)}"


# ── Single value generator ─────────────────────────────────────────────────────

def generate_value(col: Dict, from_date: str, to_date: str) -> Any:
    """Generate one synthetic value for a single column."""

    # Nullable simulation
    if col["is_nullable"] and _RNG.random() < col["null_rate"]:
        return None

    base_type = col["base_type"]
    pattern   = col.get("pattern")

    # ENUM
    if col["is_enum"] and col["enum_values"]:
        return _RNG.choice(col["enum_values"])

    # Boolean
    if base_type == "boolean":
        return _RNG.choice(["true", "false"])

    # Integer
    if base_type == "integer":
        lo = col.get("min_value") or 0
        hi = col.get("max_value") or 9999
        return _RNG.randint(int(lo), int(hi))

    # Float
    if base_type == "float":
        lo = col.get("min_value") or 0.0
        hi = col.get("max_value") or 9999.99
        return round(_RNG.uniform(float(lo), float(hi)), 2)

    # Date / Datetime
    if base_type in ("date", "datetime"):
        fmt = col.get("date_format") or (
            "%Y-%m-%d" if base_type == "date" else "%Y-%m-%d %H:%M:%S"
        )
        return _random_date_in_range(from_date, to_date, fmt)

    # String
    if base_type == "string":
        if pattern == "prefixed_id":
            return _prefixed_id(col)
        if pattern == "uuid":
            return str(uuid.uuid4())
        min_len = col.get("min_length") or 3
        max_len = col.get("max_length") or 20
        return _random_string(min_len, max_len)

    # Fallback
    return _random_string(3, 12)


# ── Batch row generator ────────────────────────────────────────────────────────

def generate_rows(
    profile: List[Dict],
    num_records: int,
    from_date: str,
    to_date: str,
) -> List[Dict[str, Any]]:
    """
    Generate `num_records` synthetic rows from the given column profile.

    Parameters
    ----------
    profile     : column profile list from column_analyzer.analyze_columns()
    num_records : number of rows to produce
    from_date   : start of date range (YYYY-MM-DD)
    to_date     : end of date range (YYYY-MM-DD)

    Returns
    -------
    List of row dicts, keys = column names in ordinal order.
    """
    ordered = sorted(profile, key=lambda c: c["ordinal"])
    rows    = []

    for _ in range(num_records):
        row = {col["name"]: generate_value(col, from_date, to_date) for col in ordered}
        rows.append(row)

    return rows
