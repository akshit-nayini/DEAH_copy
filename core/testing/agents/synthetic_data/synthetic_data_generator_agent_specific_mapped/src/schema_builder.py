"""
schema_builder.py
-----------------
Builds a column profile directly from mapping CSV rows.

Unlike the previous version which analyzed sample data rows,
this version works purely from the mapping specification:
    - target_column        → column name
    - target_data_type     → BQ native type
    - transformation_logic → how data is cast/transformed
    - is_partition_column  → partition flag
    - is_cluster_column    → cluster flag
    - notes                → semantic description

BQ type → generator base_type mapping:
    INT64      → integer
    FLOAT64    → float
    NUMERIC    → float
    BIGNUMERIC → float
    STRING     → string
    BOOL       → boolean
    DATE       → date
    DATETIME   → datetime
    TIMESTAMP  → datetime
    TIME       → string
    BYTES      → string
    JSON       → string
"""

from typing import Dict, List


# ── BQ type → internal base_type mapping ──────────────────────────────────────

BQ_TYPE_MAP = {
    "INT64":      "integer",
    "INTEGER":    "integer",
    "INT":        "integer",
    "SMALLINT":   "integer",
    "BIGINT":     "integer",
    "TINYINT":    "integer",
    "BYTEINT":    "integer",
    "FLOAT64":    "float",
    "FLOAT":      "float",
    "NUMERIC":    "float",
    "BIGNUMERIC": "float",
    "DECIMAL":    "float",
    "BIGDECIMAL": "float",
    "STRING":     "string",
    "VARCHAR":    "string",
    "CHAR":       "string",
    "BYTES":      "string",
    "JSON":       "string",
    "BOOL":       "boolean",
    "BOOLEAN":    "boolean",
    "DATE":       "date",
    "DATETIME":   "datetime",
    "TIMESTAMP":  "datetime",
    "TIME":       "string",
}

# Default date formats per base_type
DATE_FORMAT_MAP = {
    "date":     "%Y-%m-%d",
    "datetime": "%Y-%m-%d %H:%M:%S",
}


def build_profile(columns: List[dict]) -> List[Dict]:
    """
    Convert a list of mapping column dicts into a column profile
    that generator_agent.py and sql_writer.py can consume.

    Parameters
    ----------
    columns : list of cleaned column dicts from mapping_loader

    Returns
    -------
    List of column profile dicts in ordinal order.
    Each dict contains:
        name, ordinal, base_type, bq_type,
        is_partition_column, is_cluster_column,
        transformation_logic, notes,
        date_format (for date/datetime columns)
    """
    profile = []

    for i, col in enumerate(columns):
        bq_type   = col["target_data_type"].upper().strip()
        base_type = BQ_TYPE_MAP.get(bq_type, "string")

        profile.append({
            "name":                col["target_column"],
            "ordinal":             i,
            "bq_type":             bq_type,
            "base_type":           base_type,
            "transformation_logic": col["transformation_logic"],
            "is_partition_column": col["is_partition_column"],
            "is_cluster_column":   col["is_cluster_column"],
            "notes":               col["notes"],
            "source_column":       col.get("source_column", ""),
            "source_data_type":    col.get("source_data_type", ""),
            "date_format":         DATE_FORMAT_MAP.get(base_type),
        })

    return profile


def print_profile(profile: List[Dict], table_name: str) -> None:
    """Pretty-print the column profile built from mapping."""
    print(f"\n{'='*65}")
    print(f"  COLUMN PROFILE for '{table_name}'  ({len(profile)} columns)")
    print(f"  Source: mapping file (no sample data)")
    print(f"{'='*65}")
    for col in profile:
        flags = []
        if col["is_partition_column"]: flags.append("PARTITION")
        if col["is_cluster_column"]:   flags.append("CLUSTER")
        flag_str = f"  [{', '.join(flags)}]" if flags else ""
        print(f"\n  [{col['ordinal']}] {col['name']}{flag_str}")
        print(f"      bq_type    : {col['bq_type']}")
        print(f"      base_type  : {col['base_type']}")
        print(f"      transform  : {col['transformation_logic']}")
        if col["notes"]:
            print(f"      notes      : {col['notes']}")
    print(f"\n{'='*65}\n")
