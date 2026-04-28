"""
scanner.py
----------
Resolves which source table files need to be processed.

When called from GitHub Actions, it receives a comma-separated list of
repo-relative paths (e.g. "core/.../source_tables/orders.csv,core/.../customers.csv").

It filters to only supported file types (.csv, .json) and returns a list
of absolute file paths ready for loading.
"""

import os
from typing import List


SUPPORTED_EXTENSIONS = {".csv", ".json"}


def resolve_files(
    changed_files_str: str,
    repo_root: str,
) -> List[str]:
    """
    Given a comma-separated string of repo-relative file paths (from GitHub Actions),
    return a list of absolute paths to valid source files that exist on disk.

    Parameters
    ----------
    changed_files_str : comma-separated repo-relative paths from git diff
    repo_root         : absolute path to the repository root

    Returns
    -------
    List of absolute file paths to process.
    """
    if not changed_files_str or not changed_files_str.strip():
        return []

    raw_paths = [p.strip() for p in changed_files_str.split(",") if p.strip()]
    resolved  = []

    for rel_path in raw_paths:
        _, ext = os.path.splitext(rel_path)
        if ext.lower() not in SUPPORTED_EXTENSIONS:
            print(f"  [scanner] Skipping unsupported file type: {rel_path}")
            continue

        abs_path = os.path.join(repo_root, rel_path)
        if not os.path.isfile(abs_path):
            print(f"  [scanner] File not found on disk (may have been deleted): {abs_path}")
            continue

        resolved.append(abs_path)
        print(f"  [scanner] Queued for processing: {rel_path}")

    return resolved


def get_table_name(file_path: str) -> str:
    """
    Extract the table name from a file path.
    Table name = filename without extension.

    e.g.  /path/to/source_tables/orders.csv  →  orders
    """
    return os.path.splitext(os.path.basename(file_path))[0]
