-- ============================================================
-- File    : sp_mysqltobq_load.sql
-- Purpose : Stored procedure — MERGE employees_staging → employees
-- Project : 5gcore | Sprint:
-- Ticket  : SCRUM-149
-- ============================================================
-- Version History:
--   v1.0  2026-04-21  SCRUM-149  Initial creation
--   v1.1  2026-04-21  SCRUM-149  Code-review pass: truncated UPDATE SET
--                                 body completed; SAFE_CAST added for
--                                 commission_pct null-safe comparison;
--                                 partition pruning comment reinforced
-- ============================================================
-- ASSUMPTION: employees_staging.updated_date is of type DATE (or DATETIME
--             castable to DATE). VERIFY against DDL before deploy.
-- ASSUMPTION: employees_staging is NOT itself partitioned, so the WHERE
--             predicate below performs a full scan of the staging table.
--             If employees_staging is later partitioned on updated_date,
--             the CAST(updated_date AS DATE) predicate achieves pruning.
-- ASSUMPTION: commission_pct column type is FLOAT64 / NUMERIC.
--             VERIFY — affects null-safe comparison sentinel choice.
-- ============================================================

CREATE OR REPLACE PROCEDURE `verizon-data`.`verizon_data_dea`.`sp_mysqltobq_load`(
    IN p_load_date DATE
)
BEGIN

    /*
      MERGE from employees_staging into employees on composite key
      (employee_id, updated_date).

      p_load_date is used for partition pruning on the staging table when
      updated_date IS NOT NULL. Rows where updated_date IS NULL are included
      via the OR clause and land in the __NULL__ partition of employees.

      WHEN MATCHED fires only when at least one non-key column has changed,
      avoiding unnecessary write amplification on the partitioned target.
    */

    MERGE `verizon-data`.`verizon_data_dea`.`employees` AS target
    USING (
        SELECT
            employee_id
          , first_name      -- PII: apply BigQuery column-level policy tag
          , last_name       -- PII: apply BigQuery column-level policy tag
          , email           -- PII: apply BigQuery column-level policy tag
          , phone_number    -- PII: apply BigQuery column-level policy tag
          , hire_date
          , job_id
          , salary
          , commission_pct
          , manager_id
          , department_id
          , status
          , created_date
          , updated_date
        FROM `verizon-data`.`verizon_data_dea`.`employees_staging`
        WHERE CAST(updated_date AS DATE) = p_load_date
           OR updated_date IS NULL
    ) AS source
        ON  target.employee_id  = source.employee_id
        AND (
                target.updated_date = source.updated_date
             OR (target.updated_date IS NULL AND source.updated_date IS NULL)
            )

    WHEN MATCHED AND (
           target.first_name     != source.first_name
        OR target.last_name      != source.last_name
        OR target.email          != source.email
        OR IFNULL(target.phone_number,  'ø') != IFNULL(source.phone_number,  'ø')
        OR target.hire_date      != source.hire_date
        OR target.job_id         != source.job_id
        OR target.salary         != source.salary
        -- SAFE_CAST guards against unexpected non-numeric values in commission_pct
        OR IFNULL(SAFE_CAST(target.commission_pct AS STRING), 'ø')
               != IFNULL(SAFE_CAST(source.commission_pct AS STRING), 'ø')
        OR IFNULL(target.manager_id,    -1) != IFNULL(source.manager_id,    -1)
        OR IFNULL(target.department_id, -1) != IFNULL(source.department_id, -1)
        OR target.status         != source.status
        OR target.created_date   != source.created_date
    )
    THEN UPDATE SET
        target.first_name      = source.first_name
      , target.last_name       = source.last_name
      , target.email           = source.email
      , target.phone_number    = source.phone_number
      , target.hire_date       = source.hire_date
      , target.job_id          = source.job_id
      , target.salary          = source.salary
      , target.commission_pct  = source.commission_pct
      , target.manager_id      = source.manager_id
      , target.department_id   = source.department_id
      , target.status          = source.status
      , target.created_date    = source.created_date

    WHEN NOT MATCHED BY TARGET
    THEN INSERT (
        employee_id
      , first_name
      , last_name
      , email
      , phone_number
      , hire_date
      , job_id
      , salary
      , commission_pct
      , manager_id
      , department_id
      , status
      , created_date
      , updated_date
    )
    VALUES (
        source.employee_id
      , source.first_name
      , source.last_name
      , source.email
      , source.phone_number
      , source.hire_date
      , source.job_id
      , source.salary
      , source.commission_pct
      , source.manager_id
      , source.department_id
      , source.status
      , source.created_date
      , source.updated_date
    );

END;