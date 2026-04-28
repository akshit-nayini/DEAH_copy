-- ============================================================
-- File    : ddl_verizon_data_dea_pipeline_audit_log.sql
-- Purpose : DDL — table definition
-- Project : 5gcore | Sprint: 
-- Ticket  : SCRUM-149
-- ============================================================
-- Version History:
--   v1.0  2026-04-21  SCRUM-149  Initial creation
-- ============================================================
CREATE OR REPLACE TABLE `verizon-data`.`verizon_data_dea`.`pipeline_audit_log`
(
    run_id               STRING      NOT NULL
    , dag_id             STRING      NOT NULL
    , execution_timestamp TIMESTAMP  NOT NULL
    , status             STRING      NOT NULL
    , rows_extracted     INT64
    , rows_loaded        INT64
    , error_message      STRING
)
OPTIONS (
    description = "Pipeline execution audit log; one record per DAG run written with trigger_rule=ALL_DONE capturing run outcome, row counts, and error detail."
);