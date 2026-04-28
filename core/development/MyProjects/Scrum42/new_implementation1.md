cd # Implementation Plan: Customer 360 Data Platform

## ⚠️ Open Blockers

1. **Scalability requirements not specified** — what is the expected volume growth rate over 12–24 months? Impacts Dataflow worker sizing decisions.
2. **MySQL network connectivity to 34.70.79.163 (database: agentichub) not confirmed** — If not established from GCP, provisioning time must be factored into delivery timeline.
3. **Environment scope conflict** — description says 'Dev' only, but first comment says 'All'. Should QA and Prod be included in the current delivery scope?

## ⚠️ Risks & Mitigations

- **MySQL Connectivity**: Confirm Cloud SQL connectivity or VPN path to 34.70.79.163 before Dev pipeline development starts. Add a connectivity health-check task as the first step in the Airflow DAG.
- **MySQL JDBC Driver Compatibility**: Pin MySQL JDBC driver version in Beam pipeline dependencies. Add a type validation step post-extraction.
- **Security & Access Controls**: Confirm data classification with data owner before any data lands in BigQuery. Apply column-level security as default-on.

## Phase 1: Connectivity & Schema Setup

1. Test MySQL connectivity from Cloud Composer to `34.70.79.163:3306` using database `agentichub` with user `sa`
2. Validate access to source `EMPLOYEES` table and confirm column mapping
3. Create BigQuery staging dataset for `stg_employees` table
4. Deploy target schema with partitioning (monthly by `hire_date`) and clustering (`employee_id`, `job_id`, `department_id`)
5. Create GCS raw zone bucket structure: `gs://raw-zone/mysql/YYYY/MM/DD/HH/`
6. Configure GCS lifecycle policy for 30-day retention

## Phase 2: Data Ingestion Pipeline

1. Develop custom Airflow operator for MySQL JDBC extraction
2. Create Cloud Composer DAG with hourly schedule trigger
3. Implement MySQL to GCS extraction job writing Parquet files to dated partitions
4. Add connectivity health-check task as first step in DAG
5. Configure error handling and retry logic for database connection failures
6. Test end-to-end extraction to GCS raw zone

## Phase 3: Data Processing Pipeline

1. Develop Apache Beam pipeline for Dataflow processing
2. Implement schema validation transforms for all 14 columns
3. Add deduplication logic using `employee_id` as primary key
4. Configure type casting transforms (INT64, STRING, DATE, NUMERIC, TIMESTAMP)
5. Implement self-referencing relationship validation (`manager_id` → `employee_id`)
6. Configure Dataflow job to read from GCS Parquet and write to BigQuery staging
7. Pin MySQL JDBC driver version in pipeline dependencies

## Phase 4: Orchestration Integration

1. Integrate Dataflow job trigger into Cloud Composer DAG
2. Configure DAG dependencies: extraction → processing → validation
3. Implement monitoring and alerting via Cloud Monitoring
4. Add data quality checks post-processing
5. Configure failure notifications and escalation paths
6. Test complete pipeline orchestration end-to-end

## Phase 5: Testing

1. **Connectivity Test**: Input: DAG execution | Expected: Successful connection to MySQL `34.70.79.163:3306` with user `sa`
2. **Schema Validation Test**: Input: Employee record with invalid data types | Expected: Pipeline failure with clear error message
3. **Deduplication Test**: Input: Two records with same `employee_id` | Expected: Single record retained in `stg_employees`
4. **Self-Reference Test**: Input: Employee with `manager_id` = 999 (non-existent) | Expected: Validation warning logged, record processed
5. **Partitioning Test**: Input: Employees with hire dates in different months | Expected: Records correctly partitioned by month in BigQuery
6. **Volume Test**: Input: 10GB employee data extraction | Expected: Pipeline completes within 1-hour SLA
7. **Error Recovery Test**: Input: MySQL connection failure mid-extraction | Expected: DAG retries and completes successfully
8. **Data Quality Test**: Input: NULL values in non-nullable fields (`first_name`, `email`) | Expected: Pipeline rejection with data quality report

## Phase 6: Handover

1. Update runbook with pipeline design summary: hourly MySQL extraction via Cloud Composer → GCS raw zone → Dataflow processing → BigQuery staging
2. Document operational procedures: manual DAG triggers, monitoring dashboards, log locations in Cloud Logging
3. Record known risks: MySQL connectivity dependency, JDBC driver compatibility, 1-hour SLA constraint
4. Define escalation paths: L1 (DAG failures) → Data Engineering team, L2 (infrastructure) → Platform Engineering team
5. Confirm sign-off from data owner on security controls and column-level access
6. Validate handover checklist completion and obtain formal sign-off confirmation