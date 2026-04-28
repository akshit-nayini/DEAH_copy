# ============================================================
# File    : dataflow_pipeline_employees.py
# Purpose : Generated artifact: dataflow_pipeline_employees.py
# Project : Network 5G Core | Sprint:
# Ticket  : SCRUM-75
# ============================================================
# Version History:
#   v1.0  2026-04-16  SCRUM-75  Initial creation
# ============================================================
# Reviewed: 16th April 2026
# Load Pattern : Full WRITE_TRUNCATE — every run truncates and fully reloads
#                stg_employees. No incremental / CDC logic applied.
# Schedule     : Triggered daily at 01:00 UTC by Cloud Composer DAG
#                (cron: 0 1 * * *)
# GCS Staging  : gs://deah/data_build_pod

import datetime
import json
import logging
import os

import apache_beam as beam
from apache_beam.io.gcp.bigquery import BigQueryDisposition, WriteToBigQuery
from apache_beam.options.pipeline_options import (
    GoogleCloudOptions,
    PipelineOptions,
    StandardOptions,
    WorkerOptions,
)

# ---------------------------------------------------------------------------
# Structured JSON logging  (severity + message fields required by Cloud Logging)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format=(
        '{"severity":"%(levelname)s","message":"%(message)s",'
        '"pipeline":"dataflow_pipeline_employees","task":"%(funcName)s"}'
    ),
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment-sourced configuration — NO hardcoded literals
# ---------------------------------------------------------------------------
PROJECT_ID     = os.environ["PROJECT_ID"]          # e.g. verizon-data
DATASET_ID     = os.environ["DATASET_ID"]          # e.g. verizon_data_deah
STAGING_BUCKET = os.environ["STAGING_BUCKET"]      # gs://deah/data_build_pod
REGION         = os.environ.get("DATAFLOW_REGION", "us-central1")
DB_HOST        = os.environ["DB_HOST"]             # 34.70.79.163
DB_PORT        = os.environ.get("DB_PORT", "3306")
DB_NAME        = os.environ["DB_NAME"]             # agentichub
DB_USER        = os.environ["DB_USER"]             # -- PII: credential — keep in Secret Manager / env var
DB_PASSWORD    = os.environ["DB_PASSWORD"]         # -- PII: credential — keep in Secret Manager / env var

# ---------------------------------------------------------------------------
# JDBC configuration
# ---------------------------------------------------------------------------
JDBC_URL    = f"jdbc:mysql://{DB_HOST}:{DB_PORT}/{DB_NAME}"
JDBC_DRIVER = "com.mysql.cj.jdbc.Driver"

# Full extract — all columns, no date filter required for WRITE_TRUNCATE pattern
# ASSUMPTION: The SOURCE_QUERY below was truncated in the original artifact.
# The column list (EMPLOYEE_ID … DEPARTMENT_ID) is preserved exactly as supplied.
# Verify that no additional columns exist on the source table before deploying.
SOURCE_QUERY = """
    SELECT
        EMPLOYEE_ID,
        FIRST_NAME,      -- PII: apply BigQuery column-level policy tag
        LAST_NAME,       -- PII: apply BigQuery column-level policy tag
        EMAIL,           -- PII: apply BigQuery column-level policy tag
        PHONE_NUMBER,    -- PII: apply BigQuery column-level policy tag
        HIRE_DATE,
        JOB_ID,
        SALARY,          -- PII: apply BigQuery column-level policy tag
        COMMISSION_PCT,
        MANAGER_ID,
        DEPARTMENT_ID
    FROM employees
"""
# ASSUMPTION: Source table name is `employees` — the original artifact was
# truncated before the FROM clause appeared. VERIFY before deploy.