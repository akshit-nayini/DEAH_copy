import os
from logging.config import fileConfig
from pathlib import Path
from sqlalchemy import pool
from alembic import context

# Import models so metadata is populated
from core.requirements_pod.db.models import Base
from core.utilities.db_tools.base_db import load_db_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Set GCS SA key for Cloud SQL auth if not already set
_KEY = Path(__file__).resolve().parents[1] / "credentials" / "gcs-sa-key.json"
if _KEY.exists() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_KEY)

_cfg = load_db_config("metadata_db")


def _make_engine():
    """Cloud SQL Connector (no IP whitelist) → direct TCP fallback."""
    from sqlalchemy import create_engine
    try:
        from google.cloud.sql.connector import Connector
        _connector = Connector()

        def _get_conn():
            return _connector.connect(
                "verizon-data:us-central1:mysql-druid-metadatastore",
                "pymysql",
                user=_cfg["user"],
                password=_cfg["password"],
                db=_cfg["database"],
            )
        return create_engine("mysql+pymysql://", creator=_get_conn, poolclass=pool.NullPool)
    except ImportError:
        url = (
            f"mysql+pymysql://{_cfg['user']}:{_cfg['password']}"
            f"@{_cfg['host']}:{_cfg.get('port', '3306')}/{_cfg['database']}"
        )
        return create_engine(url, connect_args={"connect_timeout": 10}, poolclass=pool.NullPool)


def run_migrations_offline() -> None:
    # Build direct TCP URL for offline mode (generates SQL, no real connection)
    url = (
        f"mysql+pymysql://{_cfg['user']}:{_cfg['password']}"
        f"@{_cfg['host']}:{_cfg.get('port', '3306')}/{_cfg['database']}"
    )
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = _make_engine()
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
