"""
agents/validator/connectors.py
-------------------------------
Loads the latest test case CSV/XLSX from the generator output folder
via the common GitService.
"""

from __future__ import annotations
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import GENERATOR_OUTPUT_DIR
from services.git_service import GitService
from storage.local_storage import read_file


class ValidatorConnector:
    """Pulls the latest test cases file from the generator output folder."""

    def __init__(self):
        self._git = GitService()

    def load_latest(self) -> dict:
        """
        Pull from Git, find the newest CSV or XLSX in agents/generator/output/.

        Returns
        -------
        dict with keys:
            filename  : name of the file
            file_path : full path string
            row_count : number of rows
            columns   : list of column names
            records   : list of dicts (rows)
        """
        self._git.soft_pull()

        latest = self._git.latest_file(GENERATOR_OUTPUT_DIR, "*.csv", "*.xlsx", "*.xls")
        if not latest:
            raise FileNotFoundError(f"No CSV/Excel files found in {GENERATOR_OUTPUT_DIR}")

        df = read_file(latest)
        return {
            "filename":  latest.name,
            "file_path": str(latest),
            "row_count": len(df),
            "columns":   list(df.columns),
            "records":   df.to_dict("records"),
        }

    def load_from_path(self, path: str) -> dict:
        """Load test cases from an explicit file path."""
        p  = Path(path)
        df = read_file(p)
        return {
            "filename":  p.name,
            "file_path": str(p),
            "row_count": len(df),
            "columns":   list(df.columns),
            "records":   df.to_dict("records"),
        }
