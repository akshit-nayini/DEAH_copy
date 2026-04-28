# ============================================================
# File    : dag_5gcore_employees_incremental_load.py
# Purpose : Airflow DAG — orchestration
# Project : 5gcore | Sprint:
# Ticket  : SCRUM-149
# ============================================================
# Version History:
#   v1.0  2026-04-21  SCRUM-149  Initial creation
#   v1.1  2026-04-21  SCRUM-149  Code-review optimisations applied
# ============================================================
"""
DAG: dag_5gcore_employees_incremental_load
Project: 5gcore | Ticket: SCRUM-149
Schedule: 0 2 * * * (daily at 2 AM)

Airflow Variables required:
  PROJECT_ID                     - GCP project ID
  DATASET_ID                     - BigQuery dataset (e.g. verizon_data_dea)
  RAW_BUCKET                     - GCS staging bucket name (without gs:// prefix)
  SOURCE_SECRET_NAME             - Airflow connection ID for MySQL source
  AUDIT_DATASET                  - BigQuery dataset for audit log (may equal DATASET_ID)
  ENV                            - Deployment environment (default: dev)
  historical_load_signoff_status - Must be exactly 'APPROVED' to allow execution
  last_successful_run            - ISO-8601 timestamp watermark; updated on success
  page_size                      - Extraction chunk size (default: 100000)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from airflow import DAG
from airflow.exceptions import AirflowFailException
from airflow.models import Variable
from airflow.operators.python import PythonOperator, ShortCircuitOperator
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import GCSToBigQueryOperator
from airflow.providers.google.cloud.transfers.mysql_to_gcs import MySQLToGCSOperator
from airflow.providers.mysql.hooks.mysql import MySqlHook

# ---------------------------------------------------------------------------
# Structured JSON logger
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
log = logging.getLogger(__name__)


def _structured_log(severity: str, message: str, **extra: Any) -> None:
    """Emit a structured JSON log entry compatible with Cloud Logging."""
    record = {
        "severity": severity.upper(),
        "message": message,
        "pipeline": _PIPELINE,
        **extra,
    }
    log.info(json.dumps(record))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DAG_ID = "dag_5gcore_employees_incremental_load"
_PIPELINE = "5gcore_employees_incremental"
_SOURCE_TABLE = "agentichub.employees"
_TARGET_TABLE = "employees"
_STAGING_TABLE = "employees_staging"
_AUDIT_TABLE = "pipeline_audit_log"
_GCS_PREFIX = "employees"

# 14 mapped columns — source MySQL (uppercase) -> target BigQuery (lowercase)
# ASSUMPTION: column order and names match the 14-column mapping CSV in SCRUM-149 — VERIFY before deploy
_BQ_COLUMNS = [
    "employee_id",
    "first_name",       # PII: apply BigQuery column-level policy tag
    "last_name",        # PII: apply BigQuery column-level policy tag
    "email",            # PII: apply BigQuery column-level policy tag
    "phone_number",     # PII: apply BigQuery column-level policy tag
    "hire_date",
    "job_id",
    "salary",
    "commission_pct",
    "manager_id",
    "department_id",
    "status",
    "updated_date",
    "created_date",
]

# Expected MySQL source column names (uppercase per mapping CSV)
_MYSQL_EXPECTED_COLUMNS = {c.upper() for c in _BQ_COLUMNS}

# ---------------------------------------------------------------------------
# Default args
# ---------------------------------------------------------------------------
default_args = {
    "owner": "data_engineering",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": True,
    "sla": timedelta(hours=2),
}


# ---------------------------------------------------------------------------
# Callable helpers
# ---------------------------------------------------------------------------

def _check_sign_off_gate(**context: Any) -> bool:
    """ShortCircuitOperator callable — returns True only when sign-off is APPROVED."""
    status = Variable.get("historical_load_signoff_status", default_var="")
    approved = status == "APPROVED"
    _structured_log(
        "INFO",
        "sign_off_gate evaluated",
        task="sign_off_gate",
        historical_load_signoff_status=status,
        gate_open=approved,
    )
    return approved


def _schema_drift_check(**context: Any) -> None:
    """
    Query MySQL INFORMATION_SCHEMA.COLUMNS for agentichub.employees and compare
    against the registered BigQuery column list.  Raises AirflowFailException on
    any added, removed, or renamed columns so the pipeline does not silently
    corrupt the target table.
    """
    mysql_conn_id = Variable.get("SOURCE_SECRET_NAME")
    hook = MySqlHook(mysql_conn_id=mysql_conn_id)

    rows = hook.get_records(
        """
        SELECT UPPER(COLUMN_NAME)
        FROM   information_schema.COLUMNS
        WHERE  TABLE_SCHEMA = 'agentichub'
          AND  TABLE_NAME   = 'employees'
        ORDER  BY ORDINAL_POSITION
        """
    )
    source_cols = {r[0] for r in rows}

    added   = source_cols - _MYSQL_EXPECTED_COLUMNS
    removed = _MYSQL_EXPECTED_COLUMNS - source_cols

    if added or removed:
        _structured_log(
            "ERROR",
            "Schema drift detected",
            task="schema_drift_check",
            columns_added=sorted(added),
            columns_removed=sorted(removed),
        )
        raise AirflowFailException(
            f"Schema drift detected — added={sorted(added)}, removed={sorted(removed)}"
        )

    _structured_log(
        "INFO",
        "Schema drift check passed — no drift detected",
        task="schema_drift_check",
    )


def _row_count_reconciliation(**context: Any) -> None:
    """
    Compare row count in employees_staging (rows loaded this run) against the
    rows extracted reported by MySQLToGCSOperator (pushed via XCom).
    Raises AirflowFailException if counts diverge.
    """
    dataset_id = Variable.get("DATASET_ID")
    project_id = Variable.get("PROJECT_ID")

    bq_hook = BigQueryHook(use_legacy_sql=False)
    result = bq_hook.get_first(
        f"SELECT COUNT(*) FROM `{project_id}.{dataset_id}.{_STAGING_TABLE}`"
    )
    rows_in_staging = result[0] if result else 0

    # MySQLToGCSOperator pushes row count via XCom key 'row_count'
    # ASSUMPTION: XCom key is 'row_count' from extract_incremental_to_gcs task — VERIFY before deploy
    rows_extracted = context["ti"].xcom_pull(
        task_ids="extract_incremental_to_gcs", key="row_count"
    )

    _structured_log(
        "INFO",
        "Row count reconciliation",
        task="row_count_reconciliation",
        rows_extracted=rows_extracted,
        rows_in_staging=rows_in_staging,
    )

    if rows_extracted is not None and int(rows_extracted) != int(rows_in_staging):
        raise AirflowFailException(
            f"Row count mismatch: extracted={rows_extracted}, staging={rows_in_staging}"
        )


def _pk_uniqueness_check(**context: Any) -> None:
    """
    Assert that the composite primary key (employee_id, updated_date) is unique
    in the target table after the MERGE.
    """
    dataset_id = Variable.get("DATASET_ID")
    project_id = Variable.get("PROJECT_ID")

    bq_hook = BigQueryHook(use_legacy_sql=False)
    result = bq_hook.get_first(
        f"""
        SELECT COUNT(*)
        FROM (
            SELECT employee_id, updated_date, COUNT(*) AS cnt
            FROM   `{project_id}.{dataset_id}.{_TARGET_TABLE}`
            GROUP  BY employee_id, updated_date
            HAVING cnt > 1
        )
        """
    )
    duplicates = result[0] if result else 0

    _structured_log(
        "INFO",
        "PK uniqueness check",
        task="pk_uniqueness_check",
        duplicate_pk_rows=duplicates,
    )

    if duplicates > 0:
        raise AirflowFailException(
            f"Composite PK uniqueness violation: {duplicates} duplicate (employee_id, updated_date) pairs found."
        )


def _null_constraint_check(**context: Any) -> None:
    """
    Assert that NOT NULL columns (employee_id, updated_date) contain no NULLs
    in the target table after the MERGE.
    """
    dataset_id = Variable.get("DATASET_ID")
    project_id = Variable.get("PROJECT_ID")

    bq_hook = BigQueryHook(use_legacy_sql=False)
    result = bq_hook.get_first(
        f"""
        SELECT COUNT(*)
        FROM   `{project_id}.{dataset_id}.{_TARGET_TABLE}`
        WHERE  employee_id  IS NULL
           OR  updated_date IS NULL
        """
    )
    null_rows = result[0] if result else 0

    _structured_log(
        "INFO",
        "NOT NULL constraint check",
        task="null_constraint_check",
        null_rows=null_rows,
    )

    if null_rows > 0:
        raise AirflowFailException(
            f"NOT NULL constraint violated: {null_rows} rows with NULL employee_id or updated_date."
        )


def _update_watermark(**context: Any) -> None:
    """
    On successful completion update the last_successful_run Airflow Variable
    to the current UTC execution timestamp.
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    Variable.set("last_successful_run", now_iso)
    _structured_log(
        "INFO",
        "Watermark updated",
        task="update_watermark",
        last_successful_run=now_iso,
    )


def _write_audit_log(**context: Any) -> None:
    """
    Insert one execution record into verizon_data_dea.pipeline_audit_log
    regardless of upstream task outcome (trigger_rule=ALL_DONE).
    """
    project_id   = Variable.get("PROJECT_ID")
    audit_dataset = Variable.get("AUDIT_DATASET")

    ti       = context["ti"]
    dag_run  = context["dag_run"]
    run_id   = dag_run.run_id

    # Determine overall status from upstream task states
    all_task_instances = dag_run.get_task_instances()
    failed = any(
        t.state in ("failed", "upstream_failed")
        for t in all_task_instances
        if t.task_id != "write_audit_log"
    )
    status = "FAILED" if failed else "SUCCESS"

    rows_extracted = ti.xcom_pull(task_ids="extract_incremental_to_gcs", key="row_count") or 0
    # ASSUMPTION: GCSToBigQueryOperator does not push loaded row count via XCom;
    # rows_loaded is derived from staging table count — VERIFY before deploy
    bq_hook = BigQueryHook(use_legacy_sql=False)
    result = bq_hook.get_first(
        f"SELECT COUNT(*) FROM `{project_id}.{audit_dataset}.{_STAGING_TABLE}`"
    )
    rows_loaded = result[0] if result else 0

    error_message = ""
    if failed:
        failed_tasks = [
            t.task_id
            for t in all_task_instances
            if t.state in ("failed", "upstream_failed") and t.task_id != "write_audit_log"
        ]
        error_message = f"Failed tasks: {failed_tasks}"

    execution_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    insert_sql = f"""
        INSERT INTO `{project_id}.{audit_dataset}.{_AUDIT_TABLE}`
            (run_id, dag_id, execution_timestamp, status, rows_extracted, rows_loaded, error_message)
        VALUES (
            '{run_id}',
            '{_DAG_ID}',
            TIMESTAMP('{execution_timestamp}'),
            '{status}',
            {int(rows_extracted)},
            {int(rows_loaded)},
            '{error_message}'
        )
    """

    bq_hook.run_query(insert_sql)

    _structured_log(
        "INFO",
        "Audit log written",
        task="write_audit_log",
        run_id=run_id,
        status=status,
        rows_extracted=rows_extracted,
        rows_loaded=rows_loaded,
    )


# ---------------------------------------------------------------------------
# SLA miss callback
# ---------------------------------------------------------------------------

def _sla_miss_callback(dag, task_list, blocking_task_list, slas, blocking_tis):  # noqa: ANN001
    _structured_log(
        "WARNING",
        "SLA miss detected",
        dag_id=dag.dag_id,
        blocking_tasks=[str(t) for t in blocking_task_list],
    )


# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

with DAG(
    dag_id=_DAG_ID,
    description="Daily incremental load: MySQL agentichub.employees → BigQuery verizon_data_dea.employees",
    schedule_interval="0 2 * * *",
    start_date=datetime(2026, 4, 21, tzinfo=timezone.utc),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    sla_miss_callback=_sla_miss_callback,
    tags=["5gcore", "employees", "incremental", "mysql", "bigquery", "SCRUM-149"],
    doc_md="""
## dag_5gcore_employees_incremental_load

**Ticket:** SCRUM-149  
**Schedule:** daily at 02:00 UTC

### Task flow