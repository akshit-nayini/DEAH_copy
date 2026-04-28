# ============================================================
# File    : dag_5gcore_employees_historical_load.py
# Purpose : Airflow DAG — orchestration
# Project : 5gcore | Sprint: 
# Ticket  : SCRUM-149
# ============================================================
# Version History:
#   v1.0  2026-04-21  SCRUM-149  Initial creation
# ============================================================
"""
DAG: dag_5gcore_employees_historical_load
Project: 5gcore | Ticket: SCRUM-149
Purpose: One-time full historical load of agentichub.employees (MySQL)
         → GCS staging → BQ employees_staging → BQ MERGE into employees.

Airflow Variables required:
  PROJECT_ID              : GCP project ID (e.g. verizon-data)
  DATASET_ID              : BQ dataset (e.g. verizon_data_dea)
  MYSQL_CONN_ID           : Airflow connection ID for the MySQL source
  GCS_STAGING_BUCKET      : GCS bucket name only (e.g. verizon-data-etl-staging)
  GCS_STAGING_PREFIX      : GCS object prefix (e.g. employees)
  PAGE_SIZE               : Rows per extraction chunk (default 100000)
  ENV                     : Deployment environment (default dev)

# ASSUMPTION: schedule_interval=None (manual trigger only) — the impl doc
#   describes this as a one-time execution with no recurring schedule.
#   VERIFY before deploy if @once is preferred instead.
# ASSUMPTION: dagrun_timeout set to 480 minutes (8 hours) to accommodate
#   full historical load of ~5 GB at 100 k rows/chunk. VERIFY against
#   actual row count once source schema blocker is resolved.
# ASSUMPTION: MYSQL_CONN_ID is stored as an Airflow connection (not a
#   plain Variable) because MySQLToGCSOperator requires a connection ID.
#   The password is stored inside the Airflow connection object, not
#   hardcoded here. VERIFY connection name with infrastructure team.
# ASSUMPTION: GCS file format is CSV. The impl doc mentions "CSV/Avro"
#   without a definitive selection. VERIFY format before deploy.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from airflow import DAG
from airflow.exceptions import AirflowFailException
from airflow.models import Variable
from airflow.operators.python import PythonOperator
from airflow.providers.google.cloud.operators.gcs import GCSToLocalFilesystemOperator
from airflow.providers.google.cloud.transfers.mysql_to_gcs import MySQLToGCSOperator
from airflow.providers.google.cloud.transfers.gcs_to_bigquery import GCSToBigQueryOperator
from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from airflow.providers.mysql.hooks.mysql import MySqlHook
from airflow.utils.state import State

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bq_fqn(project: str, dataset: str, table: str) -> str:
    return f"`{project}`.`{dataset}`.`{table}`"


# ---------------------------------------------------------------------------
# Task callables
# ---------------------------------------------------------------------------

def check_schema_drift(**context):
    """
    Queries MySQL INFORMATION_SCHEMA.COLUMNS for agentichub.employees and
    diffs against the known BigQuery target column list.
    Raises AirflowFailException on any mismatch.
    """
    mysql_conn_id = Variable.get("MYSQL_CONN_ID", default_var="mysql_agentichub")
    expected_columns = {
        "EMPLOYEE_ID", "FIRST_NAME", "LAST_NAME", "EMAIL", "PHONE_NUMBER",
        "HIRE_DATE", "JOB_ID", "SALARY", "COMMISSION_PCT", "MANAGER_ID",
        "DEPARTMENT_ID", "STATUS", "CREATED_DATE", "UPDATED_DATE",
    }
    hook = MySqlHook(mysql_conn_id=mysql_conn_id)
    rows = hook.get_records(
        """
        SELECT UPPER(COLUMN_NAME)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = 'agentichub'
          AND TABLE_NAME   = 'employees'
        """
    )
    source_columns = {row[0] for row in rows}
    missing = expected_columns - source_columns
    extra   = source_columns - expected_columns

    if missing or extra:
        diff_detail = json.dumps(
            {"missing_in_source": sorted(missing), "extra_in_source": sorted(extra)},
            indent=2,
        )
        log.error(
            '{"severity":"ERROR","message":"Schema drift detected",'
            '"diff":%s}',
            diff_detail,
        )
        raise AirflowFailException(f"Schema drift detected: {diff_detail}")

    log.info(
        '{"severity":"INFO","message":"Schema drift check passed",'
        '"columns_verified":%d}',
        len(source_columns),
    )


def count_source_rows(**context):
    mysql_conn_id = Variable.get("MYSQL_CONN_ID", default_var="mysql_agentichub")
    hook = MySqlHook(mysql_conn_id=mysql_conn_id)
    count = hook.get_first("SELECT COUNT(*) FROM `agentichub`.`employees`")[0]
    log.info('{"severity":"INFO","message":"Source row count","count":%d}', count)
    context["ti"].xcom_push(key="rows_extracted", value=count)


def count_target_rows(**context):
    project_id = Variable.get("PROJECT_ID")
    dataset_id = Variable.get("DATASET_ID")
    hook = BigQueryHook(gcp_conn_id="google_cloud_default")
    count = hook.get_first(
        f"SELECT COUNT(*) FROM `{project_id}`.`{dataset_id}`.`employees`"
    )[0]
    log.info('{"severity":"INFO","message":"Target row count","count":%d}', count)
    context["ti"].xcom_push(key="rows_loaded", value=count)


def check_row_count_reconciliation(**context):
    """
    Asserts that BQ employees COUNT(*) equals MySQL employees COUNT(*).
    Pulls the two counts from XCom rather than re-querying.
    """
    ti = context["ti"]
    rows_extracted = ti.xcom_pull(task_ids="count_source_rows",  key="rows_extracted") or 0
    rows_loaded    = ti.xcom_pull(task_ids="count_target_rows",  key="rows_loaded")    or 0

    log.info(
        '{"severity":"INFO","message":"Row count reconciliation",'
        '"source":%d,"target":%d}',
        rows_extracted, rows_loaded,
    )
    if rows_extracted != rows_loaded:
        raise AirflowFailException(
            f"Row count mismatch: source={rows_extracted}, target={rows_loaded}"
        )


def write_audit_log(**context):
    ti       = context["ti"]
    dag_run  = context["dag_run"]
    project_id = Variable.get("PROJECT_ID")
    dataset_id = Variable.get("DATASET_ID")

    task_instances = dag_run.get_task_instances()
    failed_tasks = [
        t for t in task_instances
        if t.task_id != "write_audit_log" and t.state == State.FAILED
    ]
    status         = "FAILED" if failed_tasks else "SUCCESS"
    rows_extracted = ti.xcom_pull(task_ids="count_source_rows", key="rows_extracted") or 0
    rows_loaded    = ti.xcom_pull(task_ids="count_target_rows",  key="rows_loaded")    or 0
    err_msg        = str(failed_tasks[0]) if failed_tasks else None
    err_sql        = f"'{err_msg}'" if err_msg else "NULL"

    fqn = f"`{project_id}`.`{dataset_id}`.`pipeline_audit_log`"
    sql = (
        f"INSERT INTO {fqn} "
        "(run_id, dag_id, execution_timestamp, status, rows_extracted, rows_loaded, error_message) "
        f"VALUES ('{context['run_id']}', '{context['dag'].dag_id}', CURRENT_TIMESTAMP(), "
        f"'{status}', {rows_extracted}, {rows_loaded}, {err_sql})"
    )

    hook = BigQueryHook(gcp_conn_id="google_cloud_default")
    hook.run(sql=sql)
    log.info(
        '{"severity":"INFO","message":"Audit log written","status":"%s",'
        '"rows_extracted":%d,"rows_loaded":%d}',
        status, rows_extracted, rows_loaded,
    )


# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

_ENV = Variable.get("ENV", default_var="dev")

default_args = {
    "owner": "data_engineering",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": True,
    # ASSUMPTION: email address list is managed via Airflow's smtp config /
    #   connection. No hardcoded addresses here. VERIFY before deploy.
}

with DAG(
    dag_id="dag_5gcore_employees_historical_load",
    default_args=default_args,
    description="SCRUM-149: One-time full historical load — agentichub.employees → BQ",
    schedule_interval=None,  # manual trigger only
    start_date=datetime(2026, 4, 20),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=480),  # ASSUMPTION: 8 h ceiling — VERIFY
    tags=[
        "team:data_engineering",
        f"env:{_ENV}",
        "pipeline:employees_historical",
    ],
) as dag:

    # 1 — Schema drift check
    task_schema_drift_check = PythonOperator(
        task_id="schema_drift_check",
        python_callable=check_schema_drift,
    )

    # 2 — Extract full table from MySQL → GCS (CSV, chunked)
    task_extract_to_gcs = MySQLToGCSOperator(
        task_id="extract_to_gcs",
        mysql_conn_id="{{ var.value.MYSQL_CONN_ID }}",
        sql="SELECT * FROM `agentichub`.`employees`",
        bucket="{{ var.value.GCS_STAGING_BUCKET }}",
        filename="{{ var.value.GCS_STAGING_PREFIX }}/{{ ds }}/employees_{}.csv",
        export_format="CSV",
        # ASSUMPTION: schema_fields omitted here — MySQLToGCSOperator infers
        #   schema from the query result when schema_fields is not provided.
        #   VERIFY once source schema blocker (Blocker 2) is resolved; supply
        #   explicit schema_fields list if inference is unreliable.
        approx_max_file_size_bytes=100_000_000,  # ~100 MB per shard
        retries=3,
        retry_delay=timedelta(minutes=2),
        sla=timedelta(minutes=20),
    )

    # 2a — Count source rows (for audit accuracy)
    task_count_source = PythonOperator(
        task_id="count_source_rows",
        python_callable=count_source_rows,
    )

    # 3 — Load GCS → BQ transient staging table (WRITE_TRUNCATE)
    task_load_gcs_to_staging = GCSToBigQueryOperator(
        task_id="load_gcs_to_staging",
        bucket="{{ var.value.GCS_STAGING_BUCKET }}",
        source_objects=["{{ var.value.GCS_STAGING_PREFIX }}/{{ ds }}/employees_*.csv"],
        destination_project_dataset_table=(
            "{{ var.value.PROJECT_ID }}.{{ var.value.DATASET_ID }}.employees_staging"
        ),
        source_format="CSV",
        skip_leading_rows=1,
        write_disposition="WRITE_TRUNCATE",
        create_disposition="CREATE_NEVER",
        autodetect=False,
        # ASSUMPTION: schema JSON file path follows project conventions.
        #   If no schema file is available, switch autodetect=True as a
        #   fallback. VERIFY before deploy.
        schema_fields=[
            {"name": "employee_id",    "type": "INT64",     "mode": "REQUIRED"},
            {"name": "first_name",     "type": "STRING",    "mode": "REQUIRED"},
            {"name": "last_name",      "type": "STRING",    "mode": "REQUIRED"},
            {"name": "email",          "type": "STRING",    "mode": "REQUIRED"},
            {"name": "phone_number",   "type": "STRING",    "mode": "NULLABLE"},
            {"name": "hire_date",      "type": "DATE",      "mode": "REQUIRED"},
            {"name": "job_id",         "type": "STRING",    "mode": "REQUIRED"},
            {"name": "salary",         "type": "NUMERIC",   "mode": "REQUIRED"},
            {"name": "commission_pct", "type": "NUMERIC",   "mode": "NULLABLE"},
            {"name": "manager_id",     "type": "INT64",     "mode": "NULLABLE"},
            {"name": "department_id",  "type": "INT64",     "mode": "NULLABLE"},
            {"name": "status",         "type": "STRING",    "mode": "REQUIRED"},
            {"name": "created_date",   "type": "TIMESTAMP", "mode": "REQUIRED"},
            {"name": "updated_date",   "type": "TIMESTAMP", "mode": "NULLABLE"},
        ],
        gcp_conn_id="google_cloud_default",
    )

    # 3a — Count target rows after load (for audit accuracy)
    task_count_target = PythonOperator(
        task_id="count_target_rows",
        python_callable=count_target_rows,
    )

    # 4 — Execute MERGE stored procedure
    task_run_merge_procedure = BigQueryInsertJobOperator(
        task_id="run_merge_procedure",
        configuration={
            "query": {
                "query": (
                    "CALL `{{ var.value.PROJECT_ID }}`"
                    ".`{{ var.value.DATASET_ID }}`"
                    ".`sp_mysqltobq_load`()"
                ),
                "useLegacySql": False,
            }
        },
        gcp_conn_id="google_cloud_default",
    )

    # 5 — Row count reconciliation assertion (uses XCom values via PythonOperator)
    task_row_count_reconciliation = PythonOperator(
        task_id="row_count_reconciliation",
        python_callable=check_row_count_reconciliation,
    )

    # 6 — Composite PK uniqueness check
    task_pk_uniqueness_check = BigQueryInsertJobOperator(
        task_id="pk_uniqueness_check",
        configuration={
            "query": {
                "query": """
                    DECLARE duplicate_count INT64;
                    SET duplicate_count = (
                        SELECT COUNT(*)
                        FROM (
                            SELECT employee_id, updated_date
                            FROM `{{ var.value.PROJECT_ID }}`.`{{ var.value.DATASET_ID }}`.`employees`
                            GROUP BY employee_id, updated_date
                            HAVING COUNT(*) > 1
                        )
                    );
                    IF duplicate_count > 0 THEN
                        RAISE USING MESSAGE = CONCAT(
                            'PK uniqueness violation: ',
                            CAST(duplicate_count AS STRING),
                            ' duplicate (employee_id, updated_date) combinations found'
                        );
                    END IF;
                """,
                "useLegacySql": False,
            }
        },
        gcp_conn_id="google_cloud_default",
    )

    # 7 — NOT NULL constraint check
    task_null_constraint_check = BigQueryInsertJobOperator(
        task_id="null_constraint_check",
        configuration={
            "query": {
                "query": """
                    DECLARE null_count INT64;
                    SET null_count = (
                        SELECT
                            COUNTIF(employee_id  IS NULL)
                          + COUNTIF(first_name   IS NULL)
                          + COUNTIF(last_name    IS NULL)
                          + COUNTIF(email        IS NULL)
                          + COUNTIF(hire_date    IS NULL)
                          + COUNTIF(job_id       IS NULL)
                          + COUNTIF(salary       IS NULL)
                          + COUNTIF(status       IS NULL)
                          + COUNTIF(created_date IS NULL)
                        FROM `{{ var.value.PROJECT_ID }}`.`{{ var.value.DATASET_ID }}`.`employees`
                    );
                    IF null_count > 0 THEN
                        RAISE USING MESSAGE = CONCAT(
                            'NOT NULL constraint violated: ',
                            CAST(null_count AS STRING),
                            ' NULL values found in mandatory columns'
                        );
                    END IF;
                """,
                "useLegacySql": False,
            }
        },
        gcp_conn_id="google_cloud_default",
    )

    # 8 — Audit log write (trigger_rule=ALL_DONE so it always runs)
    task_write_audit_log = PythonOperator(
        task_id="write_audit_log",
        python_callable=write_audit_log,
        trigger_rule="all_done",
    )

    # ---------------------------------------------------------------------------
    # Task dependencies
    # ---------------------------------------------------------------------------
    (
        task_schema_drift_check
        >> task_extract_to_gcs
        >> task_count_source
        >> task_load_gcs_to_staging
        >> task_count_target
        >> task_run_merge_procedure
        >> task_row_count_reconciliation
        >> task_pk_uniqueness_check
        >> task_null_constraint_check
        >> task_write_audit_log
    )