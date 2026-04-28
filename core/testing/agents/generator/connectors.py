"""
agents/generator/connectors.py
-------------------------------
Reads the latest ICD (CSV) and Acceptance Criteria (md) from the DEAH repo
via the common GitService.
"""

from __future__ import annotations
import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import ICD_DIR, AC_DIR, GENERATOR_OUTPUT_DIR
from services.git_service import GitService


def _datehr_key(path: Path) -> str:
    """Extract YYYYMMDD_HH from filename for reliable sorting; falls back to '00000000_00'."""
    m = re.search(r'(\d{8}_\d{2})', path.name)
    return m.group(1) if m else "00000000_00"


def _scrum_id(path: Path) -> str | None:
    m = re.search(r'(SCRUM-\d+)', path.name, re.IGNORECASE)
    return m.group(1).upper() if m else None


class GeneratorConnector:
    """Pulls the latest ICD and AC files from the DEAH Git repo."""

    def __init__(self):
        self._git = GitService()

    def load_latest(self) -> dict:
        """
        Pull from Git, find the newest ICD CSV by filename date+hour,
        then find the newest AC markdown for the same SCRUM ID.

        Returns
        -------
        dict with keys:
            icd_file  : filename of the ICD CSV
            ac_file   : filename of the AC markdown
            icd       : raw CSV text
            ac        : extracted Acceptance Criteria section text
        """
        self._git.soft_pull()

        # ICD: latest CSV sorted by date+hour in filename (not filesystem mtime)
        icd_files = sorted(ICD_DIR.glob("*.csv"), key=_datehr_key, reverse=True)
        if not icd_files:
            raise FileNotFoundError(f"No CSV files found in {ICD_DIR}")
        icd_path = icd_files[0]
        icd_text = icd_path.read_text(encoding="utf-8")

        # AC: latest .md for the same SCRUM ID; fall back to overall latest
        scrum = _scrum_id(icd_path)
        ac_candidates = sorted(AC_DIR.glob("*.md"), key=_datehr_key, reverse=True)
        if not ac_candidates:
            raise FileNotFoundError(f"No .md files found in {AC_DIR}")

        if scrum:
            matched = [f for f in ac_candidates if _scrum_id(f) == scrum]
            ac_path = matched[0] if matched else ac_candidates[0]
        else:
            ac_path = ac_candidates[0]

        md_content = ac_path.read_text(encoding="utf-8")
        ac_match = re.search(r"## Acceptance Criteria\n(.*?)(?=\n## |\Z)", md_content, re.DOTALL)
        ac_text  = ac_match.group(1).strip() if ac_match else md_content.strip()

        return {
            "icd_file": icd_path.name,
            "ac_file":  ac_path.name,
            "icd":      icd_text,
            "ac":       ac_text,
        }

    def list_icd_files(self) -> list[dict]:
        """
        Return all ICD CSV files in the design pod output, newest first
        (sorted by date+hour in filename, not filesystem mtime).

        Each entry:
            filename : str
            scrum_id : str | None   (e.g. "SCRUM-42")
            icd_dthr : str | None   (e.g. "20260411_21")
            mtime    : float
        """
        self._git.soft_pull()
        files = sorted(ICD_DIR.glob("*.csv"), key=_datehr_key, reverse=True)
        result = []
        for f in files:
            m = re.search(r'(SCRUM-\d+)_(\d{8}_\d{2})', f.name, re.IGNORECASE)
            result.append({
                "filename": f.name,
                "scrum_id": m.group(1).upper() if m else None,
                "icd_dthr": m.group(2)         if m else None,
                "mtime":    f.stat().st_mtime,
            })
        return result

    def load_by_filename(self, icd_filename: str) -> dict:
        """
        Load a specific ICD CSV by filename (no git pull — file must already be local).
        Pairs it with the latest AC file for the same SCRUM ID.
        """
        icd_path = self._git.file_by_name(ICD_DIR, icd_filename)
        if not icd_path:
            raise FileNotFoundError(f"ICD file not found: {icd_filename} in {ICD_DIR}")
        icd_text = icd_path.read_text(encoding="utf-8")

        scrum = _scrum_id(icd_path)
        ac_candidates = sorted(AC_DIR.glob("*.md"), key=_datehr_key, reverse=True)
        if not ac_candidates:
            raise FileNotFoundError(f"No .md files found in {AC_DIR}")

        if scrum:
            matched = [f for f in ac_candidates if _scrum_id(f) == scrum]
            ac_path = matched[0] if matched else ac_candidates[0]
        else:
            ac_path = ac_candidates[0]

        md_content = ac_path.read_text(encoding="utf-8")
        ac_match   = re.search(r"## Acceptance Criteria\n(.*?)(?=\n## |\Z)", md_content, re.DOTALL)
        ac_text    = ac_match.group(1).strip() if ac_match else md_content.strip()

        return {
            "icd_file": icd_path.name,
            "ac_file":  ac_path.name,
            "icd":      icd_text,
            "ac":       ac_text,
        }

    def source_icd_info(self) -> dict | None:
        """
        Inspect the latest test cases file in GENERATOR_OUTPUT_DIR.
        Extract the SCRUM ID + ICD date+hour embedded in its filename.

        Returns None if no test cases file exists or filename has no SCRUM stamp.
        Returns dict: {tc_filename, scrum_id, icd_dthr, original_icd_filename_pattern}
        """
        csvs = sorted(GENERATOR_OUTPUT_DIR.glob("*.csv"),
                      key=lambda f: f.stat().st_mtime, reverse=True)
        if not csvs:
            return None
        tc_file = csvs[0]
        m = re.search(r'(SCRUM-\d+)_(\d{8}_\d{2})', tc_file.name, re.IGNORECASE)
        if not m:
            return None
        scrum_id = m.group(1).upper()
        icd_dthr = m.group(2)
        return {
            "tc_filename":               tc_file.name,
            "scrum_id":                  scrum_id,
            "icd_dthr":                  icd_dthr,
            "original_icd_name_pattern": f"*{scrum_id}_{icd_dthr}*",
        }
