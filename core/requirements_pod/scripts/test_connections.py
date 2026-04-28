# -*- coding: utf-8 -*-
"""
Connectivity test for MySQL (Cloud SQL), GCS, and Jira.

Run from repo root (DEAH/):
    Set-Item Env:GCS_CREDENTIALS_PATH ".\\core\\requirements_pod\\credentials\\gcs-sa-key.json"
    Set-Item Env:JIRA_EMAIL "your-email@prodapt.com"
    Set-Item Env:JIRA_API_KEY "your-jira-api-token"
    python core/requirements_pod/scripts/test_connections.py
"""
import os
import sys

# Make sure 'core' is importable regardless of working directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

PASS = "[PASS]"
FAIL = "[FAIL]"
INFO = "[INFO]"


# --------------------------------------------------------------------------
# 1. MySQL / Cloud SQL
# --------------------------------------------------------------------------

def test_mysql():
    print("\n--- MySQL / Cloud SQL ---")
    from core.utilities.db_tools.base_db import load_db_config
    cfg = load_db_config("metadata_db")
    if not cfg:
        print(FAIL, "metadata_db section missing from db_config.json")
        return False

    print(INFO, f"host={cfg.get('host')}  db={cfg.get('database')}  user={cfg.get('user')}")

    # Set GOOGLE_APPLICATION_CREDENTIALS from GCS_CREDENTIALS_PATH
    creds = os.environ.get("GCS_CREDENTIALS_PATH") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if creds and os.path.isfile(creds) and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = creds
        print(INFO, f"GOOGLE_APPLICATION_CREDENTIALS set from: {creds}")
    else:
        gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "NOT SET")
        print(INFO, f"GOOGLE_APPLICATION_CREDENTIALS = {gac}")

    # Try Cloud SQL Connector first
    try:
        from google.cloud.sql.connector import Connector
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool

        connector = Connector()

        def get_conn():
            return connector.connect(
                "verizon-data:us-central1:mysql-druid-metadatastore",
                "pymysql",
                user=cfg["user"],
                password=cfg["password"],
                db=cfg["database"],
            )

        engine = create_engine("mysql+pymysql://", creator=get_conn, poolclass=NullPool)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar()
        connector.close()
        print(PASS, f"Cloud SQL Connector - MySQL {version}")
        return True
    except Exception as e:
        print(INFO, f"Cloud SQL Connector failed ({type(e).__name__}: {e}), trying direct TCP...")

    # Fallback: direct TCP
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool
        url = (
            f"mysql+pymysql://{cfg['user']}:{cfg['password']}"
            f"@{cfg['host']}:{cfg.get('port', '3306')}/{cfg['database']}"
        )
        engine = create_engine(url, connect_args={"connect_timeout": 10}, poolclass=NullPool)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT VERSION()")).scalar()
        print(PASS, f"Direct TCP - MySQL {version}")
        return True
    except Exception as e:
        print(FAIL, f"Direct TCP also failed: {e}")
        return False


# --------------------------------------------------------------------------
# 2. GCS
# --------------------------------------------------------------------------

def test_gcs():
    print("\n--- Google Cloud Storage ---")
    creds = os.environ.get("GCS_CREDENTIALS_PATH")
    bucket = os.environ.get("GCS_BUCKET_NAME", "deah")
    project = os.environ.get("GCS_PROJECT_ID", "verizon-data")

    print(INFO, f"bucket={bucket}  project={project}")
    if not creds:
        print(FAIL, "GCS_CREDENTIALS_PATH not set")
        return False
    if not os.path.isfile(creds):
        print(FAIL, f"Credentials file not found: {creds}")
        return False

    print(INFO, f"credentials={creds}")
    try:
        from google.cloud import storage as gcs
        client = gcs.Client.from_service_account_json(creds, project=project)
        blobs = list(client.list_blobs(bucket, max_results=3))
        print(PASS, f"GCS connected - bucket '{bucket}' reachable ({len(blobs)} sample objects listed)")
        return True
    except Exception as e:
        print(FAIL, f"GCS connection failed: {e}")
        return False


# --------------------------------------------------------------------------
# 3. Jira
# --------------------------------------------------------------------------

def test_jira():
    print("\n--- Jira ---")
    base_url = "https://prodapt-deah.atlassian.net"
    email = os.environ.get("JIRA_EMAIL", "")
    api_key = os.environ.get("JIRA_API_KEY", "")
    project_key = os.environ.get("JIRA_PROJECT_KEY", "SCRUM")

    print(INFO, f"base_url={base_url}  project={project_key}  email={email or 'NOT SET'}")
    if not email or not api_key:
        print(FAIL, "JIRA_EMAIL or JIRA_API_KEY not set in environment")
        return False

    try:
        import httpx

        # Test 1: verify credentials via /myself
        r = httpx.get(f"{base_url}/rest/api/3/myself", auth=(email, api_key), timeout=15)
        if r.status_code == 200:
            me = r.json()
            print(PASS, f"Jira auth OK - logged in as '{me.get('displayName', email)}'")
        else:
            print(FAIL, f"Jira auth failed: HTTP {r.status_code} - {r.text[:200]}")
            return False

        # Test 2: verify project exists
        r2 = httpx.get(f"{base_url}/rest/api/3/project/{project_key}", auth=(email, api_key), timeout=15)
        if r2.status_code == 200:
            proj = r2.json()
            print(PASS, f"Jira project '{project_key}' exists - '{proj.get('name', '')}'")
        else:
            print(FAIL, f"Project '{project_key}' not found: HTTP {r2.status_code}")
            return False

        return True
    except Exception as e:
        print(FAIL, f"Jira connection failed: {e}")
        return False


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

if __name__ == "__main__":
    results = {
        "MySQL": test_mysql(),
        "GCS":   test_gcs(),
        "Jira":  test_jira(),
    }

    print("\n--- Summary ---")
    all_ok = True
    for name, ok in results.items():
        status = PASS if ok else FAIL
        print(f"  {status} {name}")
        if not ok:
            all_ok = False

    print()
    sys.exit(0 if all_ok else 1)
