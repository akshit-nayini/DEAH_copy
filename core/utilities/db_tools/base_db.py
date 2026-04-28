"""DBTool — dispatches schema queries to the appropriate database connector.

Usage (single db_type):
    tool = DBTool("mysql")
    rows = tool.get_schema(source_connections, source_tables)

Usage (mixed connection list):
    rows = get_schema(source_connections, source_tables)

Config file: core/utilities/db_tools/db_config.json
    metadata_db: connection for AGENT_OUTPUT_METADATA inserts
    source_db:   password (and optional db_type) for schema queries
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from functools import lru_cache

_TABLE_NAME_RE = re.compile(r'^[A-Za-z0-9_]+$')
_CONFIG_PATH = Path(__file__).resolve().parent / "db_config.json"


@lru_cache(maxsize=1)
def _load_json() -> dict:
    """Load db_config.json once. Returns empty dict if file is missing."""
    if not _CONFIG_PATH.exists():
        return {}
    import json
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f) or {}


def load_db_config(section: str) -> dict:
    """
    Return the config dict for a named section from db_config.json.
    Falls back to an empty dict if the file or section is absent.
    """
    return _load_json().get(section, {})


def get_schema(source_connections: list[dict], source_tables: list[str]) -> list[dict]:
    """
    Route each source connection to its appropriate DB connector and return
    a unified list of column rows across all connections.

    Password is read from db_config.yaml [source_db] → falls back to DB_PASSWORD env var.
    db_type per connection is read from the connection dict → falls back to
    db_config.yaml [source_db.db_type] → falls back to DB_TYPE env var → "mysql".
    """
    if not source_connections:
        raise ValueError("No source_connections provided.")

    for t in source_tables:
        if not _TABLE_NAME_RE.match(t):
            raise ValueError(f"Table name {t!r} contains invalid characters.")

    cfg = load_db_config("source_db") or load_db_config("metadata_db")
    password = cfg.get("password") or os.environ.get("DB_PASSWORD")
    if not password:
        raise EnvironmentError(
            "DB password not found. Set 'password' under metadata_db in db_config.yaml "
            "or set the DB_PASSWORD environment variable."
        )

    default_db_type = cfg.get("db_type") or os.environ.get("DB_TYPE", "mysql")

    source_tables_lower = [t.lower() for t in source_tables]

    rows = []
    for conn in source_connections:
        tables = [t.lower() for t in conn.get("source_tables", []) if t.lower() in source_tables_lower]
        if not tables:
            continue
        db_type = (conn.get("db_type") or default_db_type).lower()
        tool = DBTool(db_type)
        rows.extend(tool._backend._query(conn, tables, password))
    return rows


def build_engine(db_type: str, host: str, port: str, user: str, password: str, database: str):
    """Return a SQLAlchemy engine for the given db_type and connection params."""
    from sqlalchemy import create_engine

    dtype = db_type.lower()
    urls = {
        "mysql":    f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}",
        "postgres": f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}",
        "oracle":   f"oracle+oracledb://{user}:{password}@{host}:{port}/{database}",
        "mssql":    f"mssql+pyodbc://{user}:{password}@{host}:{port}/{database}",
    }
    if dtype not in urls:
        raise ValueError(
            f"Unsupported database type: {db_type!r}. "
            "Supported: ['mysql', 'postgres', 'oracle', 'mssql']"
        )
    return create_engine(urls[dtype], connect_args={"connect_timeout": 10})


class DBTool:
    """
    Pass db_type="mysql" (or any supported backend) and call get_schema().

    Supported backends: mysql, postgres, oracle, mssql
    """

    def __init__(self, db_type: str):
        dtype = db_type.lower()
        if dtype == "mysql":
            from . import mysql_connector as backend
        elif dtype == "postgres":
            from . import postgres_connector as backend
        elif dtype == "oracle":
            from . import oracle_connector as backend
        elif dtype == "mssql":
            from . import mssql_connector as backend
        else:
            raise ValueError(
                f"Unsupported database type: {db_type!r}. "
                "Supported: ['mysql', 'postgres', 'oracle', 'mssql']"
            )
        self._backend = backend

    def get_schema(
        self,
        source_connections: list[dict],
        source_tables: list[str],
    ) -> list[dict]:
        """Return information_schema rows for the requested tables."""
        return self._backend.get_schema(source_connections, source_tables)
