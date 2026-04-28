"""
data_loader.py
--------------
Loads source table files (CSV or JSON) into a list of row dicts.
Used by both the scanner and the column analyzer.
"""

import csv
import json
import os
from typing import Any, Dict, List, Tuple


def load_file(file_path: str, max_rows: int = 1000) -> Tuple[List[Dict[str, Any]], str]:
    """
    Load a source file and return rows + detected format.

    Parameters
    ----------
    file_path : absolute path to the source file
    max_rows  : max rows to load (used for analysis sample)

    Returns
    -------
    (rows, file_format)  where file_format is 'csv' or 'json'
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".csv":
        return _load_csv(file_path, max_rows), "csv"
    elif ext == ".json":
        return _load_json(file_path, max_rows), "json"
    else:
        raise ValueError(f"Unsupported file type: {ext}")


def _load_csv(file_path: str, max_rows: int) -> List[Dict[str, Any]]:
    rows = []
    with open(file_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            rows.append(dict(row))
    if not rows:
        raise ValueError(f"CSV file is empty or has no data rows: {file_path}")
    return rows


def _load_json(file_path: str, max_rows: int) -> List[Dict[str, Any]]:
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for key in ("data", "rows", "records", "results"):
            if key in data and isinstance(data[key], list):
                rows = data[key]
                break
        else:
            raise ValueError(
                "JSON file has unsupported structure. "
                "Expected a list or dict with keys: data/rows/records/results"
            )
    else:
        raise ValueError("JSON file must contain an array of objects.")

    if not rows:
        raise ValueError(f"JSON file is empty: {file_path}")

    normalized = []
    for row in rows[:max_rows]:
        if isinstance(row, dict):
            normalized.append({k: str(v) if v is not None else "" for k, v in row.items()})
    return normalized
