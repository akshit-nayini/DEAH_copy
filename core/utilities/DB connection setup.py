"""
Unified DB Connector Utility
=============================
Covers both databases used in this project:

  1. MySQL  — Cloud SQL (verizon-data:us-central1:mysql-druid-metadatastore)
              Database : agentichub  |  Tables : EMPLOYEES
  2. PostgreSQL — Direct TCP (146.148.88.186:5432)
              Database : ai_agent_db |  Tables : source_files, tasks

INSTALL:
    pip install cloud-sql-python-connector[pymysql] sqlalchemy pandas psycopg2-binary

CREDENTIALS:
    MySQL    : set DB_PASSWORD env-var  (default "sa")
    Postgres : reads from .env file in this folder, or set PG_PASSWORD env-var

GCP AUTH (for MySQL Cloud SQL):
    a) Service account key:
           setx GOOGLE_APPLICATION_CREDENTIALS "C:\\path\\to\\key.json"
    b) gcloud:
           gcloud auth application-default login

USAGE:
    # MySQL
    from db_connector import get_mysql_connection, run_mysql_query, get_employees

    # PostgreSQL
    from db_connector import get_pg_connection, run_pg_query, get_source_files, get_tasks

    # Test both
    from db_connector import test_mysql_connection, test_pg_connection
"""

from __future__ import annotations
import os
from pathlib import Path
from urllib.parse import quote_plus


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _load_env_file(filename: str = ".env"):
    """Load KEY=VALUE pairs from a .env file into os.environ (does not overwrite)."""
    env_path = Path(__file__).parent / filename
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


# Load project .env on import (picks up DATABASE_URL, PG_PASSWORD, etc.)
_load_env_file(".env")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — MySQL  (Cloud SQL via Cloud SQL Python Connector)
# ═══════════════════════════════════════════════════════════════════════════════

"""
AgenticHub MySQL Connector
==========================
Uses the Cloud SQL Python Connector (cloud-sql-python-connector[pymysql])
so no proxy binary or IP whitelisting is needed — just GCP credentials.

Instance : verizon-data:us-central1:mysql-druid-metadatastore
Database : agentichub
User     : sa
Tables   : EMPLOYEES

CREDENTIALS:
    Set the password in your environment:
        Windows : setx DB_PASSWORD "sa"
        Mac/Linux: export DB_PASSWORD="sa"

    GCP auth (one of):
        a) Service account key:
               setx GOOGLE_APPLICATION_CREDENTIALS "C:\\path\\to\\key.json"
        b) gcloud (if installed):
               gcloud auth application-default login
"""


def _load_gcp_env():
    """Read GOOGLE_APPLICATION_CREDENTIALS from gcp.env if not already set."""
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return
    search = [
        Path(__file__).parent / "gcp.env",
        Path(__file__).parent.parent / "Result Validation" / "gcp.env",
        Path(r"C:\Users\sruthi.kannan\Result Validation\gcp.env"),
    ]
    for env_file in search:
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip().lstrip("export").strip()
                if "GOOGLE_APPLICATION_CREDENTIALS" in line and "=" in line:
                    _, val = line.split("=", 1)
                    val = val.strip().strip('"').strip("'")
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = val
                    return


_load_gcp_env()


MYSQL_CONNECTION = {
    "db_type"                 : "mysql",
    "instance_connection_name": "verizon-data:us-central1:mysql-druid-metadatastore",
    "host"                    : "34.70.79.163",
    "port"                    : 3306,
    "database"                : "agentichub",
    "username"                : "sa",
    "source_tables"           : ["EMPLOYEES"],
}


def _mysql_password() -> str:
    return os.environ.get("DB_PASSWORD", "sa")


def _cloud_sql_engine():
    """Build a SQLAlchemy engine via Cloud SQL Python Connector."""
    from google.cloud.sql.connector import Connector
    from sqlalchemy import create_engine
    import pymysql  # noqa: F401

    connector = Connector()
    password  = _mysql_password()

    def get_conn():
        return connector.connect(
            MYSQL_CONNECTION["instance_connection_name"],
            "pymysql",
            user=MYSQL_CONNECTION["username"],
            password=password,
            db=MYSQL_CONNECTION["database"],
        )

    return create_engine("mysql+pymysql://", creator=get_conn)


def _mysql_direct_engine():
    """Build a SQLAlchemy engine via direct TCP (requires IP whitelisting)."""
    from sqlalchemy import create_engine
    pwd  = _mysql_password()
    user = MYSQL_CONNECTION["username"]
    host = MYSQL_CONNECTION["host"]
    port = MYSQL_CONNECTION["port"]
    db   = MYSQL_CONNECTION["database"]
    url  = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db}"
    return create_engine(url, connect_args={"connect_timeout": 10})


def _get_mysql_engine(prefer_cloud_sql: bool = True):
    if prefer_cloud_sql:
        try:
            return _cloud_sql_engine()
        except ImportError:
            print("[WARN] cloud-sql-python-connector not installed, falling back to direct IP.")
    return _mysql_direct_engine()


def get_mysql_connection(prefer_cloud_sql: bool = True):
    """Return a live SQLAlchemy connection to MySQL (agentichub)."""
    return _get_mysql_engine(prefer_cloud_sql).connect()


# Keep the original name as an alias so existing callers don't break
get_connection = get_mysql_connection


def run_mysql_query(sql: str, params: tuple = ()) -> "pd.DataFrame | list[dict]":
    """Run any SELECT on MySQL and return a pandas DataFrame (or list of dicts)."""
    from sqlalchemy import text
    try:
        import pandas as pd
        with get_mysql_connection() as conn:
            result = conn.execute(text(sql) if not params else text(sql), params or {})
            cols = result.keys()
            return pd.DataFrame([dict(zip(cols, r)) for r in result])
    except ImportError:
        with get_mysql_connection() as conn:
            result = conn.execute(text(sql))
            cols = result.keys()
            return [dict(zip(cols, r)) for r in result]


# Keep original name as alias
run_query = run_mysql_query


def get_employees(limit: int = 100):
    """Fetch rows from the MySQL EMPLOYEES table."""
    from sqlalchemy import text
    engine = _get_mysql_engine()
    try:
        import pandas as pd
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM EMPLOYEES LIMIT :lim"),
                {"lim": int(limit)}
            )
            cols = result.keys()
            return pd.DataFrame([dict(zip(cols, r)) for r in result])
    except ImportError:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM EMPLOYEES LIMIT :lim"),
                {"lim": int(limit)}
            )
            cols = result.keys()
            return [dict(zip(cols, r)) for r in result]


def get_mysql_schema(tables: list[str] | None = None) -> "pd.DataFrame | list[dict]":
    """Fetch column schema from information_schema for MySQL tables."""
    tables = tables or MYSQL_CONNECTION["source_tables"]
    placeholders = ", ".join(f"'{t}'" for t in tables)
    sql = f"""
        SELECT
            TABLE_NAME   AS table_name,
            COLUMN_NAME  AS column_name,
            DATA_TYPE    AS data_type,
            COLUMN_TYPE  AS column_type,
            IS_NULLABLE  AS is_nullable,
            COLUMN_KEY   AS column_key,
            EXTRA        AS extra
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = '{MYSQL_CONNECTION["database"]}'
          AND TABLE_NAME IN ({placeholders})
        ORDER BY TABLE_NAME, ORDINAL_POSITION
    """
    return run_mysql_query(sql)


# Keep original name as alias
get_schema = get_mysql_schema


def test_mysql_connection():
    """Run a quick connection test against MySQL (agentichub)."""
    print("\n=== AgenticHub MySQL — Connection Test ===")
    try:
        from sqlalchemy import text
        engine = _get_mysql_engine()
        with engine.connect() as conn:
            tables = [r[0] for r in conn.execute(text("SHOW TABLES"))]
            print(f"  Connected       : OK")
            print(f"  Tables          : {tables}")

            if any(t.upper() == "EMPLOYEES" for t in tables):
                cnt = conn.execute(text("SELECT COUNT(*) FROM EMPLOYEES")).scalar()
                print(f"  EMPLOYEES rows  : {cnt}")

                cols = conn.execute(text(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA='agentichub' AND TABLE_NAME='EMPLOYEES' "
                    "ORDER BY ORDINAL_POSITION"
                ))
                print(f"  EMPLOYEES cols  : {[r[0] for r in cols]}")

        print("\n  Result : PASS\n")
        return True
    except Exception as e:
        print(f"\n  Result : FAIL — {e}\n")
        if "cloud-sql-python-connector" in str(e) or "No module" in str(e):
            print("  Fix: pip install cloud-sql-python-connector[pymysql] sqlalchemy")
        elif "credentials" in str(e).lower() or "auth" in str(e).lower():
            print("  Fix: set GOOGLE_APPLICATION_CREDENTIALS to your service account key path")
        elif "Access denied" in str(e):
            print("  Fix: check DB_PASSWORD environment variable")
        return False


# Keep original name as alias
test_connection = test_mysql_connection


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — PostgreSQL  (Direct TCP — ai_agent_db)
# ═══════════════════════════════════════════════════════════════════════════════

"""
Requirements-POD PostgreSQL Connector
======================================
Direct TCP connection to the project's PostgreSQL instance.

Host     : 146.148.88.186
Port     : 5432
Database : ai_agent_db
User     : req_pod_agent
Tables   : source_files, tasks

CREDENTIALS:
    Reads DATABASE_URL from the project .env file automatically.
    Or set PG_PASSWORD env-var if you want to override just the password.
"""

PG_CONNECTION = {
    "db_type"      : "postgresql",
    "host"         : "146.148.88.186",
    "port"         : 5432,
    "database"     : "ai_agent_db",
    "username"     : "req_pod_agent",
    "source_tables": ["source_files", "tasks"],
}


def _pg_engine():
    """Build a SQLAlchemy engine for PostgreSQL (direct TCP)."""
    from sqlalchemy import create_engine

    # Prefer the full DATABASE_URL from .env if it points to postgres
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgresql"):
        return create_engine(db_url, connect_args={"connect_timeout": 10})

    # Fall back to individual fields; percent-encode the password for URL safety
    raw_pwd = os.environ.get("PG_PASSWORD", "")
    pwd     = quote_plus(raw_pwd) if raw_pwd else ""
    user    = PG_CONNECTION["username"]
    host    = PG_CONNECTION["host"]
    port    = PG_CONNECTION["port"]
    db      = PG_CONNECTION["database"]
    url     = f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db}"
    return create_engine(url, connect_args={"connect_timeout": 10})


def get_pg_connection():
    """Return a live SQLAlchemy connection to PostgreSQL (ai_agent_db)."""
    return _pg_engine().connect()


def run_pg_query(sql: str, params: dict | None = None) -> "pd.DataFrame | list[dict]":
    """
    Run any SELECT on PostgreSQL and return a pandas DataFrame (or list of dicts).

    Args:
        sql    : Query string. Use :param_name for named parameters.
        params : Dict of parameter values, e.g. {"status": "extracted"}.

    Example:
        df = run_pg_query("SELECT * FROM tasks WHERE status = :s", {"s": "extracted"})
    """
    from sqlalchemy import text
    try:
        import pandas as pd
        with get_pg_connection() as conn:
            result = conn.execute(text(sql), params or {})
            cols = result.keys()
            return pd.DataFrame([dict(zip(cols, r)) for r in result])
    except ImportError:
        with get_pg_connection() as conn:
            result = conn.execute(text(sql), params or {})
            cols = result.keys()
            return [dict(zip(cols, r)) for r in result]


def get_source_files(limit: int = 100) -> "pd.DataFrame | list[dict]":
    """Fetch rows from the source_files table."""
    return run_pg_query(
        "SELECT * FROM source_files ORDER BY upload_time DESC LIMIT :lim",
        {"lim": int(limit)},
    )


def get_tasks(
    status: str | None = None,
    user_name: str | None = None,
    limit: int = 200,
) -> "pd.DataFrame | list[dict]":
    """
    Fetch rows from the tasks table with optional filters.

    Args:
        status    : Filter by task status (e.g. "extracted", "pushed", "deleted").
        user_name : Filter by the user who created the task.
        limit     : Max rows to return.

    Example:
        df = get_tasks(status="extracted", user_name="pavithra")
    """
    conditions = ["status != 'deleted'"]
    params: dict = {"lim": int(limit)}

    if status:
        conditions.append("status = :status")
        params["status"] = status
    if user_name:
        conditions.append("user_name = :user_name")
        params["user_name"] = user_name

    where = " AND ".join(conditions)
    sql = f"SELECT * FROM tasks WHERE {where} ORDER BY created_at DESC LIMIT :lim"
    return run_pg_query(sql, params)


def get_pg_schema(tables: list[str] | None = None) -> "pd.DataFrame | list[dict]":
    """Fetch column schema from information_schema for PostgreSQL tables."""
    tables = tables or PG_CONNECTION["source_tables"]
    placeholders = ", ".join(f"'{t}'" for t in tables)
    sql = f"""
        SELECT
            table_name,
            column_name,
            data_type,
            udt_name,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name IN ({placeholders})
        ORDER BY table_name, ordinal_position
    """
    return run_pg_query(sql)


def test_pg_connection():
    """Run a quick connection test against PostgreSQL (ai_agent_db)."""
    print("\n=== Requirements-POD PostgreSQL — Connection Test ===")
    try:
        from sqlalchemy import text
        engine = _pg_engine()
        with engine.connect() as conn:
            tables = [
                r[0] for r in conn.execute(text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                ))
            ]
            print(f"  Connected       : OK")
            print(f"  Tables          : {tables}")

            for tbl in ["source_files", "tasks"]:
                if tbl in tables:
                    cnt = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
                    print(f"  {tbl:<20}: {cnt} rows")

                    cols = conn.execute(text(
                        "SELECT column_name FROM information_schema.columns "
                        f"WHERE table_schema='public' AND table_name='{tbl}' "
                        "ORDER BY ordinal_position"
                    ))
                    print(f"  {tbl} cols    : {[r[0] for r in cols]}")

        print("\n  Result : PASS\n")
        return True
    except Exception as e:
        print(f"\n  Result : FAIL — {e}\n")
        if "psycopg2" in str(e) or "No module" in str(e):
            print("  Fix: pip install psycopg2-binary")
        elif "password authentication" in str(e).lower():
            print("  Fix: check PG_PASSWORD env-var or DATABASE_URL in .env")
        elif "could not connect" in str(e).lower() or "Connection refused" in str(e):
            print("  Fix: check host/port reachability (146.148.88.186:5432)")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# Quick self-test — run both when executed directly
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "all"

    if target in ("mysql", "all"):
        test_mysql_connection()

    if target in ("pg", "postgres", "postgresql", "all"):
        test_pg_connection()
