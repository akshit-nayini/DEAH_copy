"""
services/source_db_service.py
------------------------------
Source-database helper for the Testing POD.
Reads connection config from db_config.json via the common base_db utility.
Supports MySQL, Postgres, Oracle, MSSQL — whichever is configured.
"""

from __future__ import annotations
import importlib.util
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DEAH_ROOT

_BASE_DB_PATH = DEAH_ROOT / "core/utilities/db_tools/base_db.py"


def _load_base_db():
    spec = importlib.util.spec_from_file_location("base_db", _BASE_DB_PATH)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SourceDbService:
    """
    Wraps the DEAH common base_db utility for Testing POD use.
    Connection details are read from db_config.json (source_db section,
    or metadata_db as fallback) — no credentials in the UI.
    """

    def get_config(self) -> dict:
        """
        Return the active source DB config dict (no password).
        Falls back to metadata_db if source_db section is absent.
        """
        mod = _load_base_db()
        cfg = mod.load_db_config("source_db") or mod.load_db_config("metadata_db")
        return {k: v for k, v in cfg.items() if k != "password"}

    def test_connection(self) -> dict:
        """
        Test the configured source DB connection.

        Returns
        -------
        dict:
            ok      : bool
            message : human-readable result or error
            tables  : list[str]
            config  : dict (connection info, no password)
        """
        try:
            mod     = _load_base_db()
            cfg     = mod.load_db_config("source_db") or mod.load_db_config("metadata_db")
            if not cfg:
                return {
                    "ok":      False,
                    "message": "No source_db or metadata_db section found in db_config.json.",
                    "tables":  [],
                    "config":  {},
                }

            password = cfg.get("password")
            if not password:
                import os
                password = os.environ.get("DB_PASSWORD", "")
            if not password:
                return {
                    "ok":      False,
                    "message": "DB password not found in db_config.json or DB_PASSWORD env var.",
                    "tables":  [],
                    "config":  {},
                }

            db_type  = cfg.get("db_type", "mysql")
            host     = cfg.get("host", "")
            port     = cfg.get("port", 3306)
            user     = cfg.get("user") or cfg.get("username", "")
            database = cfg.get("database", "")

            from sqlalchemy import text
            engine = mod.build_engine(db_type, host, str(port), user, password, database)

            with engine.connect() as conn:
                if db_type.lower() == "mysql":
                    result = conn.execute(text("SHOW TABLES"))
                    tables = [row[0] for row in result]
                else:
                    result = conn.execute(text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :s ORDER BY table_name"
                    ), {"s": database})
                    tables = [row[0] for row in result]

            safe_cfg = {k: v for k, v in cfg.items() if k != "password"}
            return {
                "ok":      True,
                "message": (
                    f"Connected to {database}@{host}:{port} ({db_type.upper()}) — "
                    f"{len(tables)} table(s) found."
                ),
                "tables":  tables,
                "config":  safe_cfg,
            }

        except Exception as exc:
            return {"ok": False, "message": str(exc), "tables": [], "config": {}}

    def run_query(self, sql: str) -> list[dict]:
        """
        Run a SELECT query against the configured source database.
        Raises on error — callers should wrap in try/except.
        """
        from sqlalchemy import text

        mod      = _load_base_db()
        cfg      = mod.load_db_config("source_db") or mod.load_db_config("metadata_db")
        password = cfg.get("password")
        if not password:
            import os
            password = os.environ.get("DB_PASSWORD", "")

        engine = mod.build_engine(
            cfg.get("db_type", "mysql"),
            cfg.get("host", ""),
            str(cfg.get("port", 3306)),
            cfg.get("user") or cfg.get("username", ""),
            password,
            cfg.get("database", ""),
        )
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            cols = list(result.keys())
            return [dict(zip(cols, row)) for row in result]