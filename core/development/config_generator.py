"""
Pipeline config generator.

Generates a single pipeline_config.py file in output/<request_id>/config/.

The generated file has three clearly labelled sections — dev, uat, prod —
each with dataset_name, project_id and the other pipeline variables.
Connection details from plan.json (db_host, db_name, db_user, gcs_bucket, etc.)
are extracted and written in directly instead of leaving FILL_IN placeholders.

Switching environments:
    ENV=dev  python main.py ...   (default)
    ENV=uat  python main.py ...
    ENV=prod python main.py ...
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path


# ── Connection value extraction ────────────────────────────────────────────────

def _parse_kv(text: str) -> dict[str, str]:
    """Parse a comma-separated key=value string into a dict."""
    result: dict[str, str] = {}
    for pair in re.split(r",\s*", text):
        if "=" in pair:
            k, _, v = pair.partition("=")
            result[k.strip()] = v.strip()
    return result


def _get_cd_field(cd, key: str, default: str = "") -> str:
    """Get a field from either a plain dict or a Pydantic model.

    The `or cd.get()` pattern breaks when the field value is '' (falsy) on a
    Pydantic model — getattr returns '' which triggers .get() on an object that
    doesn't have it.  This helper uses isinstance to branch cleanly.
    """
    if isinstance(cd, dict):
        return cd.get(key, default)
    return getattr(cd, key, default)


def _extract_conn_values(
    connection_details: list,
    services: list | None = None,
) -> dict[str, str]:
    """
    Walk connection_details (list of ConnectionDetailSpec or dicts) and extract
    fields that map to pipeline_config.py variables.

    Also scans the optional services list for a MySQL/JDBC service whose
    connection string follows the pattern "host:port / db_name / user: username"
    to fill db_name and db_user that are not captured in connection_details.

    Returns a dict with keys: db_host, db_port, db_name, db_user,
    gcs_bucket, gcs_project_id.  Missing values are empty strings (caller
    falls back to FILL_IN).
    """
    out: dict[str, str] = {
        "db_host": "", "db_port": "", "db_name": "", "db_user": "",
        "gcs_bucket": "", "gcs_project_id": "",
    }

    for cd in connection_details:
        conn_type = _get_cd_field(cd, "type")
        value     = _get_cd_field(cd, "value")

        t = conn_type.lower()

        if t in ("jdbc", "mysql", "postgresql", "mssql"):
            kv = _parse_kv(value)
            if kv:
                # key=value format: host=x, port=y, database=z
                out["db_host"] = out["db_host"] or kv.get("host", "")
                out["db_port"] = out["db_port"] or kv.get("port", "")
                out["db_name"] = out["db_name"] or kv.get("database", "") or kv.get("db", "")
                out["db_user"] = out["db_user"] or kv.get("username", "") or kv.get("user", "")
            else:
                # host:port format — no key=value pairs in the value string
                host_port_m = re.match(r"^([^:]+):(\d+)$", value.strip())
                if host_port_m:
                    out["db_host"] = out["db_host"] or host_port_m.group(1)
                    out["db_port"] = out["db_port"] or host_port_m.group(2)

        elif t == "gcs":
            # Extract bucket from gs://bucket-name/...
            m = re.match(r"^gs://([^/]+)", value)
            if m and not out["gcs_bucket"]:
                out["gcs_bucket"] = m.group(1)
                # Derive project from bucket name convention (bucket often prefixed with project)
                # e.g. "verizon-data-etl-staging" → project hint "verizon-data"
                parts = out["gcs_bucket"].split("-")
                if len(parts) >= 2 and not out["gcs_project_id"]:
                    out["gcs_project_id"] = "-".join(parts[:2])

    # Extract db_name / db_user from services[].connection when not yet found.
    # Handles the common pattern: "host:port / db_name / user: username"
    if services and (not out["db_name"] or not out["db_user"]):
        for svc in services:
            svc_type = (_get_cd_field(svc, "type") if isinstance(svc, dict)
                        else getattr(svc, "type", "")).lower()
            svc_conn = (_get_cd_field(svc, "connection") if isinstance(svc, dict)
                        else getattr(svc, "connection", ""))
            if svc_type in ("storage", "jdbc", "mysql") and "/" in svc_conn:
                # e.g. "34.70.79.163:3306 / agentichub / user: sa"
                parts = [p.strip() for p in svc_conn.split("/")]
                if len(parts) >= 2 and not out["db_name"]:
                    out["db_name"] = parts[1]
                if len(parts) >= 3 and not out["db_user"]:
                    user_part = parts[2]
                    user_m = re.search(r"user[:\s]+(\S+)", user_part, re.IGNORECASE)
                    if user_m:
                        out["db_user"] = user_m.group(1)
                if out["db_name"] and out["db_user"]:
                    break

    return out


def generate_pipeline_config(
    out_dir: Path,
    project_id: str,
    dataset_id: str,
    environment: str,
    pipeline_name: str = "",
    region: str = "us-central1",
    connection_details: list | None = None,
    services: list | None = None,
) -> dict[str, Path]:
    """Write pipeline_config.py to out_dir/config/ and return {filename: path}.

    connection_details: list of ConnectionDetailSpec (or plain dicts) from the
    plan.  Values are parsed and written into the generated file directly so
    that db_host, db_name, gcs_bucket, etc. are not left as FILL_IN.

    services: list of ServiceSpec (or plain dicts) from the plan.  Used to
    extract db_name and db_user when they are not present in connection_details
    (e.g. MySQL connection string "host:port / db_name / user: username").
    """
    config_dir = out_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    slug = (
        pipeline_name.lower().replace(" ", "_").replace("/", "_")[:30]
        if pipeline_name else "pipeline"
    )

    conn_vals = _extract_conn_values(connection_details or [], services or [])

    path = config_dir / "pipeline_config.py"
    path.write_text(
        _render(project_id, dataset_id, environment, slug, region, conn_vals),
        encoding="utf-8",
    )
    return {"pipeline_config.py": path}


def _derive(base: str, current_env: str, target_env: str, separator: str) -> str:
    """Strip the current-env suffix from base and append the target-env suffix."""
    stripped = base.replace(f"{separator}{current_env}", "").rstrip(separator)
    return f"{stripped}{separator}{target_env}" if stripped else f"FILL_IN"


def _fill(value: str, fallback: str = "FILL_IN") -> str:
    """Return value if non-empty, else fallback."""
    return value.strip() if value and value.strip() else fallback


def _render(
    project_id: str,
    dataset_id: str,
    environment: str,
    slug: str,
    region: str,
    conn_vals: dict[str, str] | None = None,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cv = conn_vals or {}

    db_host = _fill(cv.get("db_host", ""))
    db_port = _fill(cv.get("db_port", ""), "3306")
    db_name = _fill(cv.get("db_name", ""))
    db_user = _fill(cv.get("db_user", ""))
    gcs_bucket     = _fill(cv.get("gcs_bucket", ""), "deah")
    gcs_project_id = _fill(cv.get("gcs_project_id", ""), "FILL_IN")

    def _proj(env: str) -> str:
        if env == environment:
            return project_id or "FILL_IN"
        return _derive(project_id, environment, env, "-") if project_id else "FILL_IN"

    def _ds(env: str) -> str:
        if env == environment:
            return dataset_id or f"{slug}_{env}"
        return _derive(dataset_id, environment, env, "_") if dataset_id else f"{slug}_{env}"

    return f'''\
"""
Pipeline config — {slug}
Generated by DEAH Development Pod on {now}

Connection details populated from plan.json (implementation doc + user inputs).
Fill in any remaining FILL_IN values before deploying.
Switch environments by setting the ENV variable:
    ENV=dev  python main.py ...   (default)
    ENV=uat  python main.py ...
    ENV=prod python main.py ...
"""
import os

# ── GCS — sourced from core/utilities/storage/gcs_provider.py env vars ─────────
# These match the defaults used by GCSStorageProvider so bucket config is
# consistent across the whole project.  Override by setting the env vars before
# running any DAG or pipeline script.
GCS_BUCKET_NAME      = os.environ.get("GCS_BUCKET_NAME", "{gcs_bucket}")
GCS_PROJECT_ID       = os.environ.get("GCS_PROJECT_ID", "{gcs_project_id}")
GCS_CREDENTIALS_PATH = os.environ.get("GCS_CREDENTIALS_PATH", "")

# ── dev ────────────────────────────────────────────────────────────────────────
DEV_PROJECT_ID     = "{_proj("dev")}"
DEV_DATASET_NAME   = "{_ds("dev")}"
DEV_ENV            = "dev"
DEV_REGION         = "{region}"
DEV_BQ_LOCATION    = "US"
DEV_RAW_BUCKET     = f"gs://{{GCS_BUCKET_NAME}}/dev/raw"
DEV_STAGING_BUCKET = f"gs://{{GCS_BUCKET_NAME}}/dev/staging"
DEV_AUDIT_DATASET  = "audit_dev"
DEV_DB_HOST        = "{db_host}"
DEV_DB_PORT        = "{db_port}"
DEV_DB_NAME        = "{db_name}"
DEV_DB_USER        = "{db_user}"

# ── uat ────────────────────────────────────────────────────────────────────────
UAT_PROJECT_ID     = "{_proj("uat")}"
UAT_DATASET_NAME   = "{_ds("uat")}"
UAT_ENV            = "uat"
UAT_REGION         = "{region}"
UAT_BQ_LOCATION    = "US"
UAT_RAW_BUCKET     = f"gs://{{GCS_BUCKET_NAME}}/uat/raw"
UAT_STAGING_BUCKET = f"gs://{{GCS_BUCKET_NAME}}/uat/staging"
UAT_AUDIT_DATASET  = "audit_uat"
UAT_DB_HOST        = "{db_host}"
UAT_DB_PORT        = "{db_port}"
UAT_DB_NAME        = "{db_name}"
UAT_DB_USER        = "{db_user}"

# ── prod ───────────────────────────────────────────────────────────────────────
PROD_PROJECT_ID     = "{_proj("prod")}"
PROD_DATASET_NAME   = "{_ds("prod")}"
PROD_ENV            = "prod"
PROD_REGION         = "{region}"
PROD_BQ_LOCATION    = "US"
PROD_RAW_BUCKET     = f"gs://{{GCS_BUCKET_NAME}}/prod/raw"
PROD_STAGING_BUCKET = f"gs://{{GCS_BUCKET_NAME}}/prod/staging"
PROD_AUDIT_DATASET  = "audit_prod"
PROD_DB_HOST        = "{db_host}"
PROD_DB_PORT        = "{db_port}"
PROD_DB_NAME        = "{db_name}"
PROD_DB_USER        = "{db_user}"

# ── Active config (selected by ENV env variable) ───────────────────────────────
_ENV = os.environ.get("ENV", "dev").lower()

_CONFIGS = {{
    "dev": {{
        "project_id":          DEV_PROJECT_ID,
        "dataset_name":        DEV_DATASET_NAME,
        "env":                 DEV_ENV,
        "region":              DEV_REGION,
        "bq_location":         DEV_BQ_LOCATION,
        "raw_bucket":          DEV_RAW_BUCKET,
        "staging_bucket":      DEV_STAGING_BUCKET,
        "audit_dataset":       DEV_AUDIT_DATASET,
        "db_host":             DEV_DB_HOST,
        "db_port":             DEV_DB_PORT,
        "db_name":             DEV_DB_NAME,
        "db_user":             DEV_DB_USER,
        "db_password":         os.environ.get("DB_PASSWORD", ""),
        "gcs_bucket_name":     GCS_BUCKET_NAME,
        "gcs_project_id":      GCS_PROJECT_ID,
        "gcs_credentials_path": GCS_CREDENTIALS_PATH,
    }},
    "uat": {{
        "project_id":          UAT_PROJECT_ID,
        "dataset_name":        UAT_DATASET_NAME,
        "env":                 UAT_ENV,
        "region":              UAT_REGION,
        "bq_location":         UAT_BQ_LOCATION,
        "raw_bucket":          UAT_RAW_BUCKET,
        "staging_bucket":      UAT_STAGING_BUCKET,
        "audit_dataset":       UAT_AUDIT_DATASET,
        "db_host":             UAT_DB_HOST,
        "db_port":             UAT_DB_PORT,
        "db_name":             UAT_DB_NAME,
        "db_user":             UAT_DB_USER,
        "db_password":         os.environ.get("DB_PASSWORD", ""),
        "gcs_bucket_name":     GCS_BUCKET_NAME,
        "gcs_project_id":      GCS_PROJECT_ID,
        "gcs_credentials_path": GCS_CREDENTIALS_PATH,
    }},
    "prod": {{
        "project_id":          PROD_PROJECT_ID,
        "dataset_name":        PROD_DATASET_NAME,
        "env":                 PROD_ENV,
        "region":              PROD_REGION,
        "bq_location":         PROD_BQ_LOCATION,
        "raw_bucket":          PROD_RAW_BUCKET,
        "staging_bucket":      PROD_STAGING_BUCKET,
        "audit_dataset":       PROD_AUDIT_DATASET,
        "db_host":             PROD_DB_HOST,
        "db_port":             PROD_DB_PORT,
        "db_name":             PROD_DB_NAME,
        "db_user":             PROD_DB_USER,
        "db_password":         os.environ.get("DB_PASSWORD", ""),
        "gcs_bucket_name":     GCS_BUCKET_NAME,
        "gcs_project_id":      GCS_PROJECT_ID,
        "gcs_credentials_path": GCS_CREDENTIALS_PATH,
    }},
}}

if _ENV not in _CONFIGS:
    raise ValueError(f"Unknown environment \\'{{_ENV}}\\'. Set ENV to dev, uat, or prod.")

config = _CONFIGS[_ENV]

# Direct imports — use these in DAGs and scripts
PROJECT_ID            = config["project_id"]
DATASET_NAME          = config["dataset_name"]
ENV                   = config["env"]
REGION                = config["region"]
BQ_LOCATION           = config["bq_location"]
RAW_BUCKET            = config["raw_bucket"]
STAGING_BUCKET        = config["staging_bucket"]
AUDIT_DATASET         = config["audit_dataset"]
DB_HOST               = config["db_host"]
DB_PORT               = config["db_port"]
DB_NAME               = config["db_name"]
DB_USER               = config["db_user"]
DB_PASSWORD           = config["db_password"]
GCS_BUCKET            = config["gcs_bucket_name"]
GCS_PROJECT           = config["gcs_project_id"]
GCS_CREDS_PATH        = config["gcs_credentials_path"]
'''
