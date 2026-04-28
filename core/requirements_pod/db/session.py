import os
from pathlib import Path
from core.utilities.db_tools.base_db import load_db_config
from core.utilities.database.session import make_get_db
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

# Reuse GCS SA key for Cloud SQL auth if GOOGLE_APPLICATION_CREDENTIALS not already set
_KEY = Path(__file__).resolve().parents[1] / "credentials" / "gcs-sa-key.json"
if _KEY.exists() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_KEY)

_cfg = load_db_config("metadata_db")


def _build_engine():
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
        return create_engine("mysql+pymysql://", creator=_get_conn)
    except ImportError:
        # Fallback: direct TCP (works on VM / whitelisted IPs)
        url = (
            f"mysql+pymysql://{_cfg['user']}:{_cfg['password']}"
            f"@{_cfg['host']}:{_cfg.get('port', '3306')}/{_cfg['database']}"
        )
        return create_engine(url, connect_args={"connect_timeout": 10})


engine = _build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
get_db = make_get_db(SessionLocal)
