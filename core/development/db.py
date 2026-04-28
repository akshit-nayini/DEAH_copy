"""
db.py — Development Pod database helper.

Provides build_metadata_engine() using the Cloud SQL Python Connector
(preferred for GCP Cloud SQL instances) with fallback to direct TCP.

Connection details and engine logic come exclusively from core/utilities —
this module only wires them for use within the development pod.

Why this exists:
    core/utilities/db_tools/agent_output_metadata._build_metadata_engine()
    builds a direct TCP engine (mysql+pymysql://host:port/db).  That path
    requires IP whitelisting on the Cloud SQL instance and fails with
    MySQL error 2003 when the client IP is not authorised.

    core/utilities/'DB connection setup.py' provides _get_mysql_engine()
    which tries Cloud SQL Python Connector first — no IP whitelisting
    needed, just a valid GOOGLE_APPLICATION_CREDENTIALS credential.
    This module delegates to that function.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_db_connection_setup():
    """
    Load core/utilities/'DB connection setup.py' via importlib.
    importlib.util is required because the filename contains a space.
    """
    utils_dir = Path(__file__).resolve().parent.parent / "utilities"
    mod_path = utils_dir / "DB connection setup.py"
    spec = importlib.util.spec_from_file_location("db_connection_setup", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _vm_has_cloud_sql_scope() -> bool:
    """
    Query the GCE metadata server to check if this VM's service account
    has the OAuth scopes required by the Cloud SQL Python Connector
    (cloud-platform or sqlservice.admin).

    Returns True  → connector can auth; proceed with Cloud SQL Connector.
    Returns False → scope missing; skip connector and use direct TCP.
    Returns True  → non-GCE env (metadata unreachable); let connector try.
    """
    import urllib.request
    import urllib.error

    _REQUIRED = {
        "https://www.googleapis.com/auth/cloud-platform",
        "https://www.googleapis.com/auth/sqlservice.admin",
    }
    try:
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance"
            "/service-accounts/default/scopes",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=1) as resp:
            granted = set(resp.read().decode().splitlines())
        return bool(_REQUIRED & granted)
    except Exception:
        # Not on GCE, metadata unreachable, or any other error — let the
        # connector try (it will surface a clear error if auth fails).
        return True


def build_metadata_engine():
    """
    Return a SQLAlchemy engine for the metadata DB (agentichub on Cloud SQL).

    Tries Cloud SQL Python Connector first if the VM's OAuth scopes allow it.
    Falls back to direct TCP when:
      - The connector package is not installed, OR
      - The GCE metadata server reports the Cloud SQL / cloud-platform scope
        is absent (avoids the noisy 403 traceback from the connector's
        background refresh tasks).

    GCP auth: set GOOGLE_APPLICATION_CREDENTIALS to a service-account key,
              or run:
                gcloud auth application-default login \
                  --scopes=https://www.googleapis.com/auth/cloud-platform
    """
    import logging
    import sqlalchemy

    logger = logging.getLogger(__name__)
    db_setup = _load_db_connection_setup()

    # Pre-check VM OAuth scopes so we can skip the connector before it spawns
    # background refresh tasks that print 403 tracebacks to stderr.
    if not _vm_has_cloud_sql_scope():
        logger.info(
            "GCE VM scope check: Cloud SQL / cloud-platform scope not present. "
            "Using direct TCP connection (no admin scope required)."
        )
        return db_setup._mysql_direct_engine()

    engine = db_setup._get_mysql_engine(prefer_cloud_sql=True)

    # Eagerly probe the connection so auth errors surface here rather than
    # bubbling up as a confusing SQLAlchemy pool error later.
    try:
        with engine.connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
        return engine
    except Exception as exc:
        exc_str = str(exc)
        is_auth_error = (
            "403" in exc_str
            or "insufficient authentication scopes" in exc_str.lower()
            or "Request had insufficient" in exc_str
        )
        if is_auth_error:
            logger.warning(
                "Cloud SQL Connector failed with a 403 auth-scope error. "
                "Falling back to direct TCP.\n"
                "Permanent fix — one of:\n"
                "  1. Set GOOGLE_APPLICATION_CREDENTIALS to a service-account "
                "key with roles/cloudsql.client.\n"
                "  2. Run: gcloud auth application-default login "
                "--scopes=https://www.googleapis.com/auth/cloud-platform\n"
                "  3. Add the Cloud SQL scope to the VM instance and restart it."
            )
            return db_setup._mysql_direct_engine()
        raise
