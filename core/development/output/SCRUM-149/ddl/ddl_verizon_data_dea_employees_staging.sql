-- ============================================================
-- File    : ddl_verizon_data_dea_employees_staging.sql
-- Purpose : DDL — table definition
-- Project : 5gcore | Sprint: 
-- Ticket  : SCRUM-149
-- ============================================================
-- Version History:
--   v1.0  2026-04-21  SCRUM-149  Initial creation
-- ============================================================
CREATE OR REPLACE TABLE `verizon-data`.`verizon_data_dea`.`employees_staging`
(
    employee_id      INT64
    , first_name     STRING  -- PII: apply BigQuery column-level policy tag before production load
    , last_name      STRING  -- PII: apply BigQuery column-level policy tag before production load
    , email          STRING  -- PII: apply BigQuery column-level policy tag before production load
    , phone_number   STRING  -- PII: apply BigQuery column-level policy tag before production load
    , hire_date      DATE
    , job_id         STRING
    , salary         NUMERIC
    , commission_pct NUMERIC
    , manager_id     INT64
    , department_id  INT64
    , status         STRING
    , created_date   TIMESTAMP
    , updated_date   TIMESTAMP
)
OPTIONS (
    description = "Transient staging table for employees; truncated (WRITE_TRUNCATE) and reloaded on every DAG execution before MERGE into verizon_data_dea.employees."
);