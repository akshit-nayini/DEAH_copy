"""
Migrate requirements_pod tables to MySQL (agentichub).

Uses Cloud SQL Python Connector (no IP whitelisting needed) with the
existing GCS service account key for GCP auth.

Run from the repo root:
    python migrate_to_mysql.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Reuse GCS SA key for Cloud SQL auth
_KEY = Path("core/requirements_pod/credentials/gcs-sa-key.json")
if _KEY.exists() and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_KEY.resolve())

from core.utilities.db_tools.base_db import load_db_config
from core.requirements_pod.db.models import Base


def _build_engine():
    from google.cloud.sql.connector import Connector
    from sqlalchemy import create_engine

    cfg = load_db_config("metadata_db")
    connector = Connector()

    def get_conn():
        return connector.connect(
            "verizon-data:us-central1:mysql-druid-metadatastore",
            "pymysql",
            user=cfg["user"],
            password=cfg["password"],
            db=cfg["database"],
        )

    return create_engine("mysql+pymysql://", creator=get_conn)


def main():
    from sqlalchemy import text

    print("\nConnecting to MySQL (agentichub) via Cloud SQL Connector ...")
    engine = _build_engine()

    with engine.connect() as conn:
        ver = conn.execute(text("SELECT VERSION()")).scalar()
        print(f"Connected       : OK  (MySQL {ver})")
        before = [r[0] for r in conn.execute(text("SHOW TABLES"))]
        print(f"Tables before   : {before}")

        # Drop old generic table names if they still exist (empty — safe to drop)
        for old_table in ["tasks", "source_files"]:
            if old_table in before:
                conn.execute(text(f"SET FOREIGN_KEY_CHECKS=0"))
                conn.execute(text(f"DROP TABLE IF EXISTS `{old_table}`"))
                conn.execute(text(f"SET FOREIGN_KEY_CHECKS=1"))
                conn.commit()
                print(f"Dropped old table: {old_table}")

    print("\nCreating requirements_pod tables (req_agent_input, req_agent_tasks) ...")
    Base.metadata.create_all(engine)

    with engine.connect() as conn:
        after = [r[0] for r in conn.execute(text("SHOW TABLES"))]
        print(f"Tables after    : {after}")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()
