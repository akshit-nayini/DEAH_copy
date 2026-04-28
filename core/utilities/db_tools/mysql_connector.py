"""MySQL connector — queries information_schema via direct IP or Cloud SQL."""
from __future__ import annotations

import os
import re
from typing import Any

_TABLE_NAME_RE = re.compile(r'^[A-Za-z0-9_]+$')

_SCHEMA_QUERY = """
    SELECT
        LOWER(TABLE_NAME)  AS table_name,
        COLUMN_NAME        AS column_name,
        DATA_TYPE          AS data_type,
        COLUMN_TYPE        AS column_type,
        IS_NULLABLE        AS is_nullable,
        COLUMN_KEY         AS column_key,
        EXTRA              AS extra
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = '{database}'
      AND LOWER(TABLE_NAME) IN ({placeholders})
    ORDER BY TABLE_NAME, ORDINAL_POSITION
"""


def get_schema(source_connections: list[dict], source_tables: list[str]) -> list[dict]:
    """Return information_schema rows for the requested tables across all connections."""
    for t in source_tables:
        if not _TABLE_NAME_RE.match(t):
            raise ValueError(f"Table name {t!r} contains invalid characters.")

    password = os.environ.get("DB_PASSWORD")
    if not password:
        raise EnvironmentError("DB_PASSWORD environment variable is not set.")

    source_tables_lower = [t.lower() for t in source_tables]

    rows = []
    for conn in source_connections:
        tables = [t.lower() for t in conn.get("source_tables", []) if t.lower() in source_tables_lower]
        if not tables:
            continue
        database = conn.get("database", "").lower().strip().lower()
        if not database:
            raise ValueError(
                "source_connections entry for mysql is missing 'database'. "
                "Check the requirements extraction."
            )
        rows.extend(_query(conn, tables, password))
    return rows


def _query(conn: dict, tables: list[str], password: str) -> list[dict]:
    from sqlalchemy import create_engine, text

    host     = conn.get("host", "")
    port     = conn.get("port", "3306")
    user     = conn.get("username", "")
    database = conn.get("database", "").lower()

    url    = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    engine = create_engine(url)

    placeholders = ", ".join(f"'{t}'" for t in tables)
    query = _SCHEMA_QUERY.format(database=database, placeholders=placeholders)

    rows = []
    with engine.connect() as connection:
        result = connection.execute(text(query))
        cols = result.keys()
        for row in result:
            rows.append(dict(zip(cols, row)))
    return rows
