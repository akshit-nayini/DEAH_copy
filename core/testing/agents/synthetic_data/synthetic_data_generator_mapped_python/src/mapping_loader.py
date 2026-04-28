"""
mapping_loader.py
-----------------
Reads mapping CSV files produced by the design team and parses them
into a structured format grouped by target_table.

Mapping CSV columns used:
    target_table         → BQ table name (output SQL file name)
    target_column        → column name in BQ
    target_data_type     → BQ native type (INT64, STRING, NUMERIC, DATE, TIMESTAMP)
    transformation_logic → how the source is cast/transformed (e.g. CAST(EMAIL AS STRING))
    is_partition_column  → True/False — noted in SQL header
    is_cluster_column    → True/False — noted in SQL header
    notes                → human-readable description Claude uses to generate data

One mapping file can contain rows for multiple target_tables.
Each target_table produces its own independent SQL output file.
"""

import csv
import os
from collections import defaultdict
from typing import Dict, List


# ── Column definitions ─────────────────────────────────────────────────────────

REQUIRED_COLUMNS = {
    "target_table",
    "target_column",
    "target_data_type",
    "transformation_logic",
    "is_partition_column",
    "is_cluster_column",
    "notes",
}


# ── Data structures ────────────────────────────────────────────────────────────

def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")


def _clean_row(row: dict) -> dict:
    """Normalize a raw CSV row into a clean column definition dict."""
    return {
        "target_table":         row.get("target_table", "").strip(),
        "target_column":        row.get("target_column", "").strip(),
        "target_data_type":     row.get("target_data_type", "STRING").strip().upper(),
        "transformation_logic": row.get("transformation_logic", "").strip(),
        "is_partition_column":  _parse_bool(row.get("is_partition_column", "False")),
        "is_cluster_column":    _parse_bool(row.get("is_cluster_column", "False")),
        "notes":                row.get("notes", "").strip(),
        # Extra context columns (optional — used for Claude prompt enrichment)
        "source_system":        row.get("source_system", "").strip(),
        "source_table":         row.get("source_table", "").strip(),
        "source_column":        row.get("source_column", "").strip(),
        "source_data_type":     row.get("source_data_type", "").strip(),
    }


# ── Main loader ────────────────────────────────────────────────────────────────

def load_mapping_file(file_path: str) -> Dict[str, List[dict]]:
    """
    Load a mapping CSV file and return a dict grouped by target_table.

    Parameters
    ----------
    file_path : absolute path to the mapping CSV

    Returns
    -------
    {
        "stg_employees": [ {col_def}, {col_def}, ... ],
        "stg_departments": [ {col_def}, ... ],
        ...
    }

    Raises
    ------
    FileNotFoundError : file does not exist
    ValueError        : missing required columns or no valid rows
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Mapping file not found: {file_path}")

    rows_by_table: Dict[str, List[dict]] = defaultdict(list)

    with open(file_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        # Validate required columns exist
        actual_cols = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - actual_cols
        if missing:
            raise ValueError(
                f"Mapping file is missing required columns: {missing}\n"
                f"File: {file_path}\n"
                f"Found columns: {actual_cols}"
            )

        for i, row in enumerate(reader, start=2):  # start=2 (row 1 = header)
            cleaned = _clean_row(row)

            if not cleaned["target_table"]:
                print(f"  [mapping_loader] Warning: row {i} has empty target_table — skipped")
                continue
            if not cleaned["target_column"]:
                print(f"  [mapping_loader] Warning: row {i} has empty target_column — skipped")
                continue

            rows_by_table[cleaned["target_table"]].append(cleaned)

    if not rows_by_table:
        raise ValueError(f"Mapping file has no valid rows: {file_path}")

    # Print summary
    print(f"  [mapping_loader] Loaded: {os.path.basename(file_path)}")
    for table, cols in rows_by_table.items():
        partition_cols = [c["target_column"] for c in cols if c["is_partition_column"]]
        cluster_cols   = [c["target_column"] for c in cols if c["is_cluster_column"]]
        print(f"    → {table}  ({len(cols)} columns)")
        if partition_cols:
            print(f"       partition : {partition_cols}")
        if cluster_cols:
            print(f"       cluster   : {cluster_cols}")

    return dict(rows_by_table)


def get_mapping_file_name(file_path: str) -> str:
    """Return just the filename without extension for logging."""
    return os.path.splitext(os.path.basename(file_path))[0]
