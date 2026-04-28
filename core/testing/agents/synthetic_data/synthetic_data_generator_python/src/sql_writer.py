"""
sql_writer.py
-------------
Writes generated synthetic rows as a single BigQuery-compatible
INSERT SQL file with one multi-row VALUES statement.

Output:
    INSERT INTO `project.dataset.table_name` (col1, col2, ...) VALUES
      (v1, v2, ...),
      ...
    ;
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional


# ── Value escaping ─────────────────────────────────────────────────────────────

def _escape(value: Any, base_type: str, is_enum: bool) -> str:
    """Convert a Python value to its BigQuery SQL literal."""
    if value is None or str(value).upper() in ("NULL", "NONE", ""):
        return "NULL"

    # ENUM → always string unless it's a numeric/boolean type
    if is_enum and base_type not in ("integer", "float", "boolean", "date", "datetime"):
        base_type = "string"

    if base_type == "boolean":
        return "TRUE" if str(value).lower() in ("true", "yes", "1") else "FALSE"

    if base_type == "integer":
        try:    return str(int(float(str(value))))
        except: return "NULL"

    if base_type == "float":
        try:    return str(round(float(str(value)), 2))
        except: return "NULL"

    if base_type == "date":
        return f"DATE('{str(value).strip()}')"

    if base_type == "datetime":
        return f"DATETIME('{str(value).strip()}')"

    # string
    v = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{v}'"


# ── SQL writer ─────────────────────────────────────────────────────────────────

def write_sql(
    rows: List[Dict[str, Any]],
    profile: List[Dict],
    table_name: str,
    output_dir: str,
    bq_project: str,
    bq_dataset: str,
    from_date: str,
    to_date: str,
    num_records: int,
) -> str:
    """
    Write a single .sql file for the given table.

    Parameters
    ----------
    rows        : generated synthetic rows
    profile     : column profile from column_analyzer
    table_name  : table name (= source filename without extension)
    output_dir  : where to write the .sql file
    bq_project  : GCP project name (from config)
    bq_dataset  : BigQuery dataset name (from config)
    from_date   : date range start (for header comment)
    to_date     : date range end (for header comment)
    num_records : requested record count (for header comment)

    Returns
    -------
    Absolute path to the written .sql file.
    """
    os.makedirs(output_dir, exist_ok=True)

    ordered     = sorted(profile, key=lambda c: c["ordinal"])
    col_list    = ", ".join(f"`{c['name']}`" for c in ordered)
    full_table  = f"`{bq_project}.{bq_dataset}.{table_name}`"
    output_file = os.path.join(output_dir, f"{table_name}.sql")
    now         = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    with open(output_file, "w", encoding="utf-8") as f:

        # Header
        f.write("-- ============================================================\n")
        f.write(f"-- Synthetic Data : {table_name}\n")
        f.write(f"-- Generated at  : {now}\n")
        f.write(f"-- Records       : {num_records}\n")
        f.write(f"-- Date range    : {from_date} → {to_date}\n")
        f.write(f"-- Source file   : {table_name}  (source_tables/)\n")
        f.write(f"-- Target table  : {full_table}\n")
        f.write(f"-- Trigger       : GitHub Actions (push to main)\n")
        f.write("-- ============================================================\n\n")

        # INSERT
        f.write(f"INSERT INTO {full_table}\n  ({col_list})\nVALUES\n")

        for i, row in enumerate(rows):
            vals = [
                _escape(row.get(c["name"]), c["base_type"], c.get("is_enum", False))
                for c in ordered
            ]
            comma = "," if i < len(rows) - 1 else ""
            f.write(f"  ({', '.join(vals)}){comma}\n")

        f.write(";\n")

    return output_file


def print_summary(output_file: str, num_rows: int, table_name: str) -> None:
    size_kb = os.path.getsize(output_file) / 1024
    print(f"  ✅  {table_name}.sql  —  {num_rows:,} rows  —  {size_kb:.1f} KB")
    print(f"      → {output_file}")
