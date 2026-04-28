"""
services/audit_service.py
--------------------------
SQLite-backed audit log for FR-12 Audit & Traceability.

Schema
------
runs table   : one row per validation run
run_results  : one row per TC per run

Usage
-----
    from services.audit_service import AuditService
    AuditService().log_run(results, icd_filename, source_file, mode)
"""

from __future__ import annotations
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import REPO_ROOT

_DB_PATH = REPO_ROOT / "audit.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id       TEXT PRIMARY KEY,
            scrum_id     TEXT NOT NULL,
            mode         TEXT NOT NULL,
            icd_filename TEXT NOT NULL,
            source_file  TEXT NOT NULL,
            started_at   TEXT NOT NULL,
            total        INTEGER NOT NULL DEFAULT 0,
            passed       INTEGER NOT NULL DEFAULT 0,
            failed       INTEGER NOT NULL DEFAULT 0,
            skipped      INTEGER NOT NULL DEFAULT 0,
            pass_rate    REAL    NOT NULL DEFAULT 0.0
        );

        CREATE TABLE IF NOT EXISTS run_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT NOT NULL,
            scrum_id        TEXT NOT NULL,
            tc_id           TEXT NOT NULL,
            category        TEXT NOT NULL,
            test_name       TEXT NOT NULL,
            verdict         TEXT NOT NULL,
            actual_result   TEXT,
            expected_result TEXT,
            FOREIGN KEY (run_id) REFERENCES runs(run_id)
        );

        CREATE INDEX IF NOT EXISTS idx_run_results_run_id ON run_results(run_id);
        CREATE INDEX IF NOT EXISTS idx_run_results_scrum  ON run_results(scrum_id);
        CREATE INDEX IF NOT EXISTS idx_runs_scrum         ON runs(scrum_id);
    """)
    conn.commit()


def _extract_scrum(icd_filename: str, source_file: str) -> str:
    """Best-effort extraction of SCRUM ID from a filename like model_SCRUM-5_..."""
    import re
    for name in (icd_filename, source_file):
        m = re.search(r'(SCRUM[-_]\d+)', name, re.IGNORECASE)
        if m:
            return m.group(1).upper().replace("_", "-")
    return "UNKNOWN"


class AuditService:

    def __init__(self):
        self._conn = _connect()
        _init_db(self._conn)

    # ── Write ──────────────────────────────────────────────────────────────────

    def log_run(
        self,
        results: list[dict],
        icd_filename: str = "",
        source_file: str = "",
        mode: str = "synthetic",
    ) -> str:
        """Persist one validation run. Returns the generated run_id."""
        run_id   = str(uuid.uuid4())
        scrum_id = _extract_scrum(icd_filename, source_file)
        now      = datetime.now(timezone.utc).isoformat()

        verdicts = [str(r.get("verdict", "")).upper() for r in results]
        passed   = sum(1 for v in verdicts if v == "PASS")
        failed   = sum(1 for v in verdicts if v == "FAIL")
        skipped  = sum(1 for v in verdicts if v in ("SKIP", "SKIPPED", "N/A"))
        total    = passed + failed
        rate     = round(passed / total * 100, 1) if total > 0 else 0.0

        self._conn.execute(
            """INSERT INTO runs
               (run_id, scrum_id, mode, icd_filename, source_file,
                started_at, total, passed, failed, skipped, pass_rate)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, scrum_id, mode, icd_filename or "", source_file or "",
             now, total, passed, failed, skipped, rate),
        )

        rows = [
            (run_id, scrum_id,
             r.get("tc_id", ""), r.get("category", ""), r.get("test_name", ""),
             str(r.get("verdict", "")).upper(),
             str(r.get("actual_result", "") or ""),
             str(r.get("expected_result", "") or ""))
            for r in results
        ]
        self._conn.executemany(
            """INSERT INTO run_results
               (run_id, scrum_id, tc_id, category, test_name,
                verdict, actual_result, expected_result)
               VALUES (?,?,?,?,?,?,?,?)""",
            rows,
        )
        self._conn.commit()
        print(f"  [AuditService] logged run {run_id[:8]}… scrum={scrum_id} "
              f"pass_rate={rate}% ({passed}/{total})")
        return run_id

    # ── Read ───────────────────────────────────────────────────────────────────

    def get_history(self, scrum_id: str | None = None, limit: int = 50) -> list[dict]:
        """Return recent runs, newest first. Optionally filter by scrum_id."""
        if scrum_id:
            rows = self._conn.execute(
                """SELECT * FROM runs WHERE UPPER(scrum_id) = UPPER(?)
                   ORDER BY started_at DESC LIMIT ?""",
                (scrum_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_run_detail(self, run_id: str) -> list[dict]:
        """Return all TC results for a specific run."""
        rows = self._conn.execute(
            "SELECT * FROM run_results WHERE run_id = ? ORDER BY tc_id",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def compare_runs(self, run_id_a: str, run_id_b: str) -> dict:
        """
        Compare two runs and return a diff of verdict changes.
        Returns {"run_a", "run_b", "changes", "summary"}.
        """
        def _run(rid):
            r = self._conn.execute("SELECT * FROM runs WHERE run_id=?", (rid,)).fetchone()
            return dict(r) if r else {}

        def _tcs(rid):
            rows = self._conn.execute(
                "SELECT tc_id, test_name, category, verdict FROM run_results WHERE run_id=?",
                (rid,),
            ).fetchall()
            return {r["tc_id"]: dict(r) for r in rows}

        run_a  = _run(run_id_a)
        run_b  = _run(run_id_b)
        tcs_a  = _tcs(run_id_a)
        tcs_b  = _tcs(run_id_b)
        all_ids = sorted(set(tcs_a) | set(tcs_b))

        changes = []
        summary = {"improved": 0, "regressed": 0, "unchanged": 0, "new": 0}

        for tc_id in all_ids:
            a  = tcs_a.get(tc_id)
            b  = tcs_b.get(tc_id)
            va = a["verdict"] if a else None
            vb = b["verdict"] if b else None
            tc_name = (b or a or {}).get("test_name", "")
            tc_cat  = (b or a or {}).get("category", "")

            if va is None:
                direction = "new"
                summary["new"] += 1
            elif va == vb:
                direction = "unchanged"
                summary["unchanged"] += 1
            elif va == "FAIL" and vb == "PASS":
                direction = "improved"
                summary["improved"] += 1
            else:
                direction = "regressed"
                summary["regressed"] += 1

            if direction != "unchanged":
                changes.append({
                    "tc_id": tc_id, "test_name": tc_name, "category": tc_cat,
                    "verdict_a": va, "verdict_b": vb, "direction": direction,
                })

        return {"run_a": run_a, "run_b": run_b, "changes": changes, "summary": summary}

    def get_trend(self, scrum_id: str | None = None, limit: int = 20) -> list[dict]:
        """Return pass-rate trend (oldest first) for charting."""
        history = self.get_history(scrum_id=scrum_id, limit=limit)
        return list(reversed([
            {"run_id": r["run_id"][:8], "started_at": r["started_at"],
             "pass_rate": r["pass_rate"], "scrum_id": r["scrum_id"]}
            for r in history
        ]))
