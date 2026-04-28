"""
Connection checker for DEAH Development Pod.

Parses connection_details from plan.json, tests each connection,
checks for missing env vars, and reports missing packages.
Triggered automatically after config generation when the plan contains
connection_details or the implementation doc mentions connection checks.
"""
from __future__ import annotations

import os
import re
import socket
from dataclasses import dataclass, field
from pathlib import Path


# ── Result ─────────────────────────────────────────────────────────────────────

@dataclass
class ConnectionCheckResult:
    service: str
    conn_type: str
    status: str                             # PASS | FAIL | SKIPPED
    message: str
    missing_packages: list[str] = field(default_factory=list)
    missing_env_vars: list[str] = field(default_factory=list)


# ── Package name normaliser ─────────────────────────────────────────────────────
# Maps stdlib / pip package names that appear in generated code to pip install targets.
# Used when an ImportError is detected to write the correct requirement.

_IMPORT_TO_PIP: dict[str, str] = {
    "google.cloud.bigquery":     "google-cloud-bigquery>=3.0.0",
    "google.cloud.storage":      "google-cloud-storage>=2.0.0",
    "google.cloud.pubsub_v1":    "google-cloud-pubsub>=2.0.0",
    "google.cloud.secretmanager":"google-cloud-secret-manager>=2.0.0",
    "google.cloud.composer":     "google-cloud-orchestration-airflow>=1.0.0",
    "google.cloud":              "google-cloud-core>=2.0.0",
    "pymysql":                   "pymysql>=1.1.0",
    "mysql":                     "pymysql>=1.1.0",
    "sqlalchemy":                "sqlalchemy>=2.0.0",
    "apache_beam":               "apache-beam>=2.50.0",
    "jaydebeapi":                "JayDeBeApi>=1.2.3",
}


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _get_field(cd, key: str, default: str = "") -> str:
    """Get a field from either a plain dict or a Pydantic model.

    The `or cd.get()` pattern is broken when the field value is '' (falsy) on a
    Pydantic model — getattr returns '' which triggers .get() which doesn't exist
    on Pydantic models.  This helper uses isinstance to branch cleanly.
    """
    if isinstance(cd, dict):
        return cd.get(key, default)
    return getattr(cd, key, default)


# ── Public API ─────────────────────────────────────────────────────────────────

def check_connections(
    connection_details: list,
    requirements_path: Path | None = None,
) -> list[ConnectionCheckResult]:
    """
    Test every entry in connection_details.

    - PASS  : connection reachable or client package importable
    - FAIL  : connection refused / ImportError / auth error
    - SKIPPED: not enough info to test (no host, no package to import, etc.)

    Side effects:
    - Missing packages are appended to requirements_path (if given).
    - Missing env vars are reported in the result.
    """
    results: list[ConnectionCheckResult] = []
    all_missing_packages: list[str] = []

    for cd in connection_details:
        # Support both Pydantic model and plain dict
        service   = _get_field(cd, "service")
        conn_type = _get_field(cd, "type")
        value     = _get_field(cd, "value")
        env_var   = _get_field(cd, "env_var")

        missing_env_vars = _extract_missing_env_vars(env_var)
        result = _test_connection(service, conn_type, value)
        result.missing_env_vars = missing_env_vars
        results.append(result)
        all_missing_packages.extend(result.missing_packages)

    if all_missing_packages and requirements_path and requirements_path.exists():
        _append_to_requirements(requirements_path, all_missing_packages)

    return results


def print_connection_report(results: list[ConnectionCheckResult]) -> None:
    """Print a human-readable connection check table."""
    icons = {"PASS": "✓", "FAIL": "✗", "SKIPPED": "~"}
    width = max((len(r.service) for r in results), default=30) + 2
    print()
    print("─" * 72)
    print("  CONNECTION CHECK")
    print("─" * 72)
    for r in results:
        icon = icons.get(r.status, "?")
        print(f"  {icon}  {r.service:<{width}}  [{r.status:<7}]  {r.message}")
        for pkg in r.missing_packages:
            print(f"       ↳ package added to requirements.txt  :  {pkg}")
        for var in r.missing_env_vars:
            print(f"       ↳ env var missing / not set          :  {var}")
    print("─" * 72)

    # Summary line
    counts = {"PASS": 0, "FAIL": 0, "SKIPPED": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    print(
        f"  PASSED: {counts['PASS']}   "
        f"FAILED: {counts['FAIL']}   "
        f"SKIPPED: {counts['SKIPPED']}"
    )
    print("─" * 72)


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _extract_missing_env_vars(env_var_str: str) -> list[str]:
    """Find env var names in the env_var field and return those not set in the environment."""
    if not env_var_str:
        return []
    # Match UPPER_CASE identifiers that look like env var names (e.g. MYSQL_PASSWORD, DB_PASSWORD)
    candidates = re.findall(r'\b[A-Z][A-Z0-9_]{2,}\b', env_var_str)
    return [v for v in candidates if not os.environ.get(v)]


def _test_connection(service: str, conn_type: str, value: str) -> ConnectionCheckResult:
    """Dispatch to the right check based on conn_type."""
    t = conn_type.lower()
    if t in ("jdbc", "mysql", "postgresql", "mssql"):
        return _check_db_tcp(service, conn_type, value)
    if t == "gcs":
        return _check_gcs(service, value)
    if t == "bq":
        return _check_bq(service, value)
    if t == "pubsub":
        return _check_pubsub(service, value)
    if t in ("api", "ftp", "sftp"):
        return ConnectionCheckResult(
            service=service, conn_type=conn_type, status="SKIPPED",
            message=f"No automated check for type '{conn_type}' — verify manually",
        )
    return ConnectionCheckResult(
        service=service, conn_type=conn_type, status="SKIPPED",
        message=f"Unknown connection type '{conn_type}' — verify manually",
    )


def _parse_kv(value: str) -> dict[str, str]:
    """Parse a comma-separated key=value string like 'host=x, port=3306, database=y'."""
    result: dict[str, str] = {}
    for pair in re.split(r",\s*", value):
        if "=" in pair:
            k, _, v = pair.partition("=")
            result[k.strip()] = v.strip()
    return result


def _check_db_tcp(service: str, conn_type: str, value: str) -> ConnectionCheckResult:
    """TCP reachability check for relational DB connections."""
    kv = _parse_kv(value)
    host = kv.get("host", "")
    port_str = kv.get("port", "3306")

    # key=value parsing found nothing — try bare host:port format (e.g. "34.70.79.163:3306")
    if not host:
        m = re.match(r"^([a-zA-Z0-9._-]+):(\d+)$", value.strip())
        if m:
            host = m.group(1)
            port_str = m.group(2)

    # Cloud SQL instance connection names look like "project:region:instance" —
    # they are not TCP endpoints; skip them gracefully.
    if not host or value.count(":") >= 2:
        return ConnectionCheckResult(
            service=service, conn_type=conn_type, status="SKIPPED",
            message=(
                "Cloud SQL instance name (not a TCP endpoint) — verify connectivity "
                "via Cloud SQL Auth Proxy or Cloud SQL Connector"
                if value.count(":") >= 2
                else "No host found in connection value — verify manually"
            ),
        )
    try:
        port = int(port_str)
    except ValueError:
        port = 3306

    try:
        sock = socket.create_connection((host, port), timeout=5)
        sock.close()
        return ConnectionCheckResult(
            service=service, conn_type=conn_type, status="PASS",
            message=f"TCP reachable at {host}:{port}",
        )
    except OSError as exc:
        return ConnectionCheckResult(
            service=service, conn_type=conn_type, status="FAIL",
            message=f"TCP unreachable {host}:{port} — {exc}",
        )


def _check_gcs(service: str, value: str) -> ConnectionCheckResult:
    """Check whether google-cloud-storage is importable and extract bucket name."""
    m = re.match(r"^gs://([^/]+)", value)
    bucket = m.group(1) if m else value

    try:
        from google.cloud import storage as _gcs  # noqa: F401
        return ConnectionCheckResult(
            service=service, conn_type="gcs", status="PASS",
            message=f"google-cloud-storage importable; target bucket: {bucket}",
        )
    except ImportError as exc:
        pkg = _IMPORT_TO_PIP["google.cloud.storage"]
        return ConnectionCheckResult(
            service=service, conn_type="gcs", status="FAIL",
            message=f"google-cloud-storage not installed — {exc}",
            missing_packages=[pkg],
        )


def _check_bq(service: str, value: str) -> ConnectionCheckResult:
    """Check whether google-cloud-bigquery is importable."""
    try:
        from google.cloud import bigquery as _bq  # noqa: F401
        return ConnectionCheckResult(
            service=service, conn_type="bq", status="PASS",
            message="google-cloud-bigquery importable",
        )
    except ImportError as exc:
        pkg = _IMPORT_TO_PIP["google.cloud.bigquery"]
        return ConnectionCheckResult(
            service=service, conn_type="bq", status="FAIL",
            message=f"google-cloud-bigquery not installed — {exc}",
            missing_packages=[pkg],
        )


def _check_pubsub(service: str, value: str) -> ConnectionCheckResult:
    """Check whether google-cloud-pubsub is importable."""
    try:
        from google.cloud import pubsub_v1 as _ps  # noqa: F401
        return ConnectionCheckResult(
            service=service, conn_type="pubsub", status="PASS",
            message="google-cloud-pubsub importable",
        )
    except ImportError as exc:
        pkg = _IMPORT_TO_PIP["google.cloud.pubsub_v1"]
        return ConnectionCheckResult(
            service=service, conn_type="pubsub", status="FAIL",
            message=f"google-cloud-pubsub not installed — {exc}",
            missing_packages=[pkg],
        )


def _append_to_requirements(req_path: Path, packages: list[str]) -> None:
    """Append missing packages to requirements.txt (skip already-present ones)."""
    existing = req_path.read_text(encoding="utf-8")
    to_add = []
    for pkg in packages:
        # Normalise: strip version specifier for existence check
        base = re.split(r"[>=<!]", pkg)[0].strip()
        if base not in existing:
            to_add.append(pkg)
    if to_add:
        block = "\n# Auto-added by connection checker\n" + "\n".join(to_add) + "\n"
        with req_path.open("a", encoding="utf-8") as f:
            f.write(block)
