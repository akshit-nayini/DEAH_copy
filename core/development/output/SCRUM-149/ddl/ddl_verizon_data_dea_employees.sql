-- ============================================================
-- File    : ddl_verizon_data_dea_employees.sql
-- Purpose : DDL — table definition
-- Project : 5gcore | Sprint: 
-- Ticket  : SCRUM-149
-- ============================================================
-- Version History:
--   v1.0  2026-04-21  SCRUM-149  Initial creation
-- ============================================================
CREATE OR REPLACE TABLE `verizon-data`.`verizon_data_dea`.`employees`
(
    employee_id     INT64       NOT NULL
    , first_name    STRING      NOT NULL  -- PII: apply BigQuery column-level policy tag before production load
    , last_name     STRING      NOT NULL  -- PII: apply BigQuery column-level policy tag before production load
    , email         STRING      NOT NULL  -- PII: apply BigQuery column-level policy tag before production load
    , phone_number  STRING                -- PII: apply BigQuery column-level policy tag before production load
    , hire_date     DATE        NOT NULL
    , job_id        STRING      NOT NULL
    , salary        NUMERIC     NOT NULL
    , commission_pct NUMERIC
    , manager_id    INT64
    , department_id INT64
    , status        STRING      NOT NULL
    , created_date  TIMESTAMP   NOT NULL
    , updated_date  TIMESTAMP
)
PARTITION BY DATE(updated_date)
CLUSTER BY employee_id, department_id, job_id, status
OPTIONS (
    description             = "Target employee table partitioned by updated_date (DAY, 60-day expiry), clustered on employee_id/department_id/job_id/status; MERGE target for sp_mysqltobq_load on composite key (employee_id, updated_date).",
    require_partition_filter = false,
    partition_expiration_days = 60
);