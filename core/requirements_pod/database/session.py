import os
from core.utilities.db_tools.base_db import load_db_config
from core.utilities.database.session import make_get_db
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, text

# Use GCS_CREDENTIALS_PATH (exported on VM) for Cloud SQL auth if not already set
_creds = os.environ.get("GCS_CREDENTIALS_PATH") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if _creds and os.path.isfile(_creds) and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _creds

_cfg = load_db_config("metadata_db")


def _build_engine():
    # Try Cloud SQL Connector first — test connection immediately so any
    # auth failure (e.g. 403 scope error on VM) triggers the TCP fallback.
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

        engine = create_engine("mysql+pymysql://", creator=_get_conn)
        # Probe the connection now so fallback fires if Cloud SQL auth fails
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return engine
    except Exception:
        pass

    # Fallback: direct TCP (works on VM with whitelisted IP)
    url = (
        f"mysql+pymysql://{_cfg['user']}:{_cfg['password']}"
        f"@{_cfg['host']}:{_cfg.get('port', '3306')}/{_cfg['database']}"
    )
    return create_engine(url, connect_args={"connect_timeout": 10})


engine = _build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
get_db = make_get_db(SessionLocal)
