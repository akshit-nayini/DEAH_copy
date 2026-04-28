# Architecture Decision Document — MySQL to BigQuery Data Ingestion Pipeline

| Field | Value |
|---|---|
| **Project** | MySQL to BigQuery Data Ingestion Pipeline |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Batch |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Cloud Run Jobs + BigQuery Native Load (Recommended)
>
> **Why:** Option 2 achieves the highest weighted score of 7.70 by optimizing across the three most heavily weighted criteria: cost efficiency (8/10) via Cloud Run Jobs pay-per-use billing, operational simplicity (8/10) via a standard Python stack and BigQuery-native processing with no specialized framework expertise required, and operability (9/10) via the BigQuery audit_log table and Looker Studio dashboard that directly and completely fulfills the stakeholder self-service visibility requirement as a first-class deliverable. All 13 functional requirements stated in the brief are addressable within this stack without introducing additional services or runtime dependencies.
>
> **Score:** 7.70 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2 ✅ | Option 3  |
|---|---||---||---|
| **Name** | Dataflow-Centric ETL Pipeline | Cloud Run Jobs + BigQuery Native Load (Recommended) | Dataproc Serverless Spark ETL Pipeline |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Dataflow (Apache Beam) | BigQuery Native LOAD JOB + MERGE + Cloud Run Jobs (Python validation logic) | Dataproc Serverless Spark (PySpark) + BigQuery Spark Connector |
| **Storage** | GCS (staging) + BigQuery (target + audit_log) | GCS (staging, 7-day lifecycle) + BigQuery (target + audit_log + watermark) | GCS (landing + Spark staging + checkpoint) + BigQuery (target + audit_log) |
| **Weighted Score** | **7.10** | **7.70**  ✅ | **6.25** |

---

## Option 1 — Dataflow-Centric ETL Pipeline

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer triggers a Dataflow job; Dataflow reads the MySQL employees table via Apache Beam JDBC IO connector through Cloud SQL Auth Proxy, writing raw extracted records to a GCS staging bucket as Avro or Parquet files partitioned by extraction run timestamp. |
| Processing | The Apache Beam pipeline performs sequential transform stages: pre-load schema compatibility check via MySQL information_schema comparison, data type coercion, null constraint violation detection and logging, PK-based deduplication, and MERGE-compatible upsert staging output to GCS. A post-load validation job computes source vs target row counts and writes audit records. |
| Storage | GCS serves as the ephemeral landing and staging zone with a 7-day lifecycle policy. BigQuery verizon_data_deah dataset is the authoritative analytical target. A dedicated BigQuery audit_log table records per-run metadata including run_id, table name, rows extracted, rows loaded, validation status, and execution timestamp. |
| Consumption | Analytics and reporting teams query BigQuery directly via SQL or connected BI tools. Stakeholder Yash accesses a Looker Studio dashboard built on the BigQuery audit_log table for self-service load-health visibility. Cloud Monitoring dashboards and alert policies provide operational observability for engineering teams. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataflow (Apache Beam JDBC IO + Cloud SQL Auth Proxy) | — | Yes |
| Processing | Dataflow (Apache Beam) | — | Yes |
| Storage | GCS (staging) + BigQuery (target + audit_log) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio | — | Yes |
| Iac | Terraform | ~> 1.7 | No |

### Pros

- Serverless auto-scaling Dataflow eliminates capacity planning for variable data volumes across tables and cadences
- Apache Beam SDK provides native support for schema validation, data type coercion, windowing, and MERGE-compatible output patterns within a single unified pipeline model
- Fully GCP-managed service stack from ingestion through monitoring reduces operational burden on engineering teams
- Native Cloud Monitoring integration provides fine-grained Dataflow job metrics (elements processed, worker CPU, error counts) and precise alert policies
- Dataflow Flex Templates enable versioned, repeatable pipeline deployments via IaC with parameterized full vs incremental load modes
- Horizontal worker scaling accommodates additional tables and volume growth without architectural redesign

### Cons

- Dataflow worker cold-start latency of 1 to 3 minutes adds measurable overhead to hourly cadence runs and increases end-to-end pipeline duration
- Apache Beam SDK has a steeper learning curve than standard Python ETL approaches, requiring Beam-specific expertise for maintenance and debugging
- Per-vCPU-hour Dataflow billing with a 1-minute minimum increment is disproportionately costly for small-to-medium employee table volumes relative to Cloud Run Jobs
- JDBC connector configuration for Cloud SQL requires careful Cloud SQL Auth Proxy socket or Private IP VPC peering setup with correct IAM binding
- Pipeline code maintenance and schema evolution handling require ongoing Beam expertise that may not be broadly available on the team

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Schema drift in MySQL (new columns, type changes, column removals) may silently truncate or fail Beam pipeline transforms if schema evolution is not explicitly handled within each DoFn; requires explicit schema registry or pre-run comparison logic. |
| Scaling | Unknown data volume means Dataflow autoscaling worker bounds cannot be pre-tuned; default maxWorkers settings may result in over- or under-provisioning on the first historical load run, requiring manual tuning iteration. |
| Latency | Dataflow worker startup adds 1 to 3 minutes of fixed overhead per run cycle; acceptable for daily cadence but constraining for any future sub-15-minute SLA requirements that may emerge. |
| Cost | Dataflow charges per vCPU-hour with shuffle storage costs for large pipelines; for a single-table daily batch load of moderate volume, costs may be 3 to 5 times higher than the Cloud Run Jobs alternative without proportional benefit. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 9 | 6 | 7 | 8 | **7.10** |

---

## Option 2 — Cloud Run Jobs + BigQuery Native Load (Recommended) ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer triggers a Cloud Run Job in two distinct modes: (1) Full historical load mode — containerized Python job connects to Cloud SQL MySQL via Cloud SQL Auth Proxy, executes an unbounded SELECT with PK ordering, streams results in configurable batch chunks to GCS staging bucket as Parquet files; (2) Incremental load mode — job executes a delta SELECT filtering on updated_at timestamp greater than the last successful watermark stored in a BigQuery watermark table, writes delta records to GCS staging. |
| Processing | Cloud Run Job performs ordered validation stages before and after load: pre-load schema compatibility check by comparing MySQL information_schema against BigQuery table schema (detecting new columns, type mismatches, nullable conflicts), null constraint violation scan with structured log output, and row count extraction from MySQL source. BigQuery native LOAD JOB ingests validated GCS Parquet files into a staging table. BigQuery MERGE statement applies upserts from staging to target table enforcing PK uniqueness. Post-load validation Cloud Run Job queries BigQuery row count against MySQL source count and writes reconciliation result to audit_log table. |
| Storage | GCS serves as an ephemeral staging zone with a 7-day object lifecycle policy enabling replay of failed loads without re-extracting from MySQL. BigQuery verizon_data_deah dataset is the authoritative analytical target store. A BigQuery watermark table persists the last successful incremental extraction timestamp per table. A BigQuery audit_log table records per-run metadata: run_id, pipeline_mode, table_name, rows_extracted, rows_loaded, validation_status, null_violations, schema_check_result, and run_timestamp. |
| Consumption | Analytics and reporting teams query BigQuery via SQL or connected BI tools such as Looker or Looker Studio. Stakeholder Yash accesses a dedicated Looker Studio dashboard connected directly to the BigQuery audit_log table, enabling self-service load health review including success or failure status, row count reconciliation results, and schema check outcomes for every run without developer involvement. Cloud Monitoring alert policies trigger on Composer DAG task failure and Cloud Run Job non-zero exit codes within the defined SLA window via email or PagerDuty notification channels. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Run Jobs (Python 3.12, mysql-connector-python, Cloud SQL Auth Proxy sidecar) | — | Yes |
| Processing | BigQuery Native LOAD JOB + MERGE + Cloud Run Jobs (Python validation logic) | — | Yes |
| Storage | GCS (staging, 7-day lifecycle) + BigQuery (target + audit_log + watermark) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio (audit_log dashboard) | — | Yes |
| Iac | Terraform | ~> 1.7 | No |

### Pros

- Cloud Run Jobs use sub-second billing granularity on actual CPU and memory consumption, making them the most cost-efficient compute option for daily batch loads of small-to-medium volume
- Standard Python stack with mysql-connector-python and google-cloud-bigquery SDK requires no specialized framework knowledge, reducing onboarding friction and maintenance burden
- BigQuery native LOAD JOB and MERGE are purpose-built, fully managed batch ingestion and upsert primitives delivering high throughput with zero operational overhead or tuning required
- The BigQuery audit_log table doubles as both a structured operational record and a Looker Studio data source, directly fulfilling the stakeholder self-service visibility requirement in a single artifact
- Cloud Composer DAG dependency graph enforces the historical load validation gate before incremental pipeline activation via task XCom signals or explicit sensor tasks, satisfying the gating requirement natively
- Cloud Run Jobs support configurable CPU (up to 8 vCPU) and memory (up to 32 GB) per execution and parallel task instances, providing headroom for additional tables without architectural changes
- Pre-load schema compatibility checks implemented via MySQL information_schema queries are straightforward in Python, with new column detection logic added as a first-class validation step
- GCS staging with lifecycle policies provides cost-controlled intermediary storage, enabling replay of failed loads and point-in-time audit trails without re-querying MySQL
- Watermark-based incremental state management in BigQuery is portable, inspectable, and correctable without specialist tooling
- Container images stored in Artifact Registry with Cloud Build CI enable versioned, reproducible deployments aligned to IaC lifecycle

### Cons

- Cloud Run Jobs default execution timeout is 60 minutes and must be explicitly extended to up to 24 hours for large historical loads; misconfiguration risks silent job termination mid-load
- Single-container extraction has no native parallelism; partitioned PK-range batching must be implemented manually if table volume approaches memory limits, adding implementation complexity
- Maintaining a Python container image requires a Dockerfile, Artifact Registry repository, and Cloud Build pipeline, introducing a small but real CI/CD surface area and image vulnerability management obligation
- BigQuery MERGE bytes-processed billing scales with table width and delta size; wide tables with large incremental batches may incur higher-than-expected query costs at scale

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Incremental delta logic depends on the presence of a reliable monotonically updated timestamp column such as updated_at in the MySQL employees table. Absence of such a column requires PK-range scanning, which risks gaps if PKs are non-sequential or if soft-deleted records are not tracked by an audit mechanism. |
| Scaling | Cloud Run Jobs maximum memory of 32 GB per container constrains full historical loads for very large tables. If the employees table exceeds this threshold, a partitioned parallel extraction pattern using multiple concurrent Cloud Run Job tasks with PK range splits must be introduced, adding implementation complexity not required at current assumed volume. |
| Latency | GCS Parquet write and BigQuery LOAD JOB execution add 2 to 5 minutes of fixed overhead per run cycle. This is well within daily cadence SLAs and acceptable for hourly cadence, but would be marginal for any future sub-10-minute refresh requirements. |
| Cost | If the employees table grows to hundreds of millions of rows or if the pipeline scope expands to many wide tables, BigQuery MERGE bytes-processed costs may eventually exceed Dataflow batch costs at scale. A cost ceiling review is recommended at the 6-month mark or upon scope expansion. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 7 | 8 | 7 | 9 | **7.70** |

---

## Option 3 — Dataproc Serverless Spark ETL Pipeline

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer triggers a Dataproc Serverless Spark batch session; PySpark reads the MySQL employees table via the Spark JDBC connector using Cloud SQL Private IP within the shared VPC, with configurable partitionColumn, lowerBound, upperBound, and numPartitions parameters enabling parallelized multi-partition extraction. Raw extracted DataFrames are written to GCS landing zone as Parquet files partitioned by extraction run ID. |
| Processing | PySpark transformation stages perform schema validation via explicit StructType schema enforcement, data type casting from MySQL JDBC types to BigQuery-compatible types, null constraint violation detection with structured output logging, PK deduplication using DataFrame dropDuplicates, and row count computation for audit. The BigQuery Spark connector writes the processed DataFrame directly to the BigQuery verizon_data_deah target table using WRITE_TRUNCATE for full load and a custom MERGE via staging table for incremental mode. A separate validation Spark job computes post-load row count reconciliation. |
| Storage | GCS serves as the Spark landing zone, checkpoint storage, and ephemeral staging area. BigQuery verizon_data_deah dataset is the authoritative analytical target. A BigQuery audit_log table records per-run metadata. GCS Dataproc staging bucket holds Spark job binaries and dependencies. |
| Consumption | Analytics teams query BigQuery via SQL or BI tools. Stakeholder Yash accesses a Looker Studio dashboard connected to the BigQuery audit_log table. Cloud Monitoring and Dataproc Job History UI provide engineering-level observability. Cloud Logging captures structured Spark application logs for debugging. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataproc Serverless Spark (PySpark JDBC + Cloud SQL Connector for Python) | — | Yes |
| Processing | Dataproc Serverless Spark (PySpark) + BigQuery Spark Connector | — | Yes |
| Storage | GCS (landing + Spark staging + checkpoint) + BigQuery (target + audit_log) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Dataproc Job History UI + Looker Studio | — | Yes |
| Iac | Terraform | ~> 1.7 | No |

### Pros

- PySpark distributed processing provides the highest throughput ceiling for very large table volumes and multi-table parallel extraction scenarios without single-container memory constraints
- Dataproc Serverless eliminates persistent cluster provisioning and management; sessions are ephemeral and auto-terminated on job completion
- Spark JDBC connector natively supports parallelized MySQL reads using partition column bounds, enabling efficient historical load of large tables without custom batching logic
- BigQuery Spark Connector provides an optimized direct write path from Spark DataFrames to BigQuery with automatic schema mapping
- Spark DataFrame API simplifies schema enforcement and type mapping logic with declarative StructType definitions

### Cons

- Dataproc Serverless has a minimum 2 DCU session with 30 to 90 second initialization latency, creating disproportionate startup overhead and cost for small-to-medium table volumes
- PySpark requires specialized Spark expertise for job authoring, tuning (fetchSize, numPartitions, shuffle configuration), and debugging that may not be present across the data engineering team
- Dataproc Serverless DCU-hour billing is significantly higher than Cloud Run Jobs CPU-second billing for batch workloads of moderate volume, making it the most expensive option at current assumed scale
- JDBC reads from Cloud SQL via Spark require careful tuning of connection pool size, fetchSize, and numPartitions to avoid exhausting MySQL connection limits on the source instance
- Post-run debugging requires access to Dataproc History Server or Spark UI forwarding; structured log analysis is more complex than Python-based Cloud Run Job logs in Cloud Logging

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Spark JDBC schema inference from MySQL may map ambiguous types inconsistently (e.g., TINYINT(1) to Boolean vs Integer, DECIMAL to Double vs Numeric), causing silent data corruption in BigQuery unless explicit StructType schema definitions are enforced at the DataFrame read stage. |
| Scaling | Dataproc Serverless resource allocation is automated but may over-provision executor count for small tables, driving unnecessary DCU-hour cost without volume-proportional benefit. Without defined resource limits, runaway sessions on large inputs can exceed budget ceilings. |
| Latency | Spark session initialization adds 30 to 90 seconds of fixed overhead per run. For daily cadence this is negligible, but for hourly cadence this represents 1 to 2.5 minutes of non-processing time per cycle. Any sub-15-minute SLA would be difficult to meet reliably. |
| Cost | Dataproc Serverless DCU-hour billing at assumed small-to-medium volume makes this the highest-cost option with the lowest cost score (5/10). For a single-table daily batch pipeline, Dataproc session costs are estimated to be 3 to 8 times higher than equivalent Cloud Run Jobs execution costs. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 9 | 5 | 6 | 6 | **6.25** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Dataflow-Centric ETL Pipeline | 6 | 9 | 6 | 7 | 8 | **7.10** |
| Cloud Run Jobs + BigQuery Native Load (Recommended) ✅ | 8 | 7 | 8 | 7 | 9 | **7.70** |
| Dataproc Serverless Spark ETL Pipeline | 5 | 9 | 5 | 6 | 6 | **6.25** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Run Jobs + BigQuery Native Load (Recommended)**
**Weighted Score: 7.70**

**Justification:** Option 2 achieves the highest weighted score of 7.70 by optimizing across the three most heavily weighted criteria: cost efficiency (8/10) via Cloud Run Jobs pay-per-use billing, operational simplicity (8/10) via a standard Python stack and BigQuery-native processing with no specialized framework expertise required, and operability (9/10) via the BigQuery audit_log table and Looker Studio dashboard that directly and completely fulfills the stakeholder self-service visibility requirement as a first-class deliverable. All 13 functional requirements stated in the brief are addressable within this stack without introducing additional services or runtime dependencies.

**Why highest score:** The combination of Cloud Run Jobs as the extraction compute layer and BigQuery native LOAD JOB plus MERGE as the processing layer eliminates the Apache Beam SDK learning curve of Option 1 and the Spark session overhead and DCU-hour billing of Option 3. Operability scores highest at 9/10 because the BigQuery audit_log table serves dual purpose as both the structured pipeline operational record and the Looker Studio dashboard data source, satisfying the stakeholder transparency requirement (stakeholder Yash independent visibility) with a single managed artifact and no additional monitoring service to operate. Cost scores 8/10 because Cloud Run Jobs bill only for actual CPU-seconds consumed per execution, making daily batch runs of moderate volume significantly cheaper than Dataflow workers or Dataproc sessions with their respective minimum billing increments.

**Trade-offs accepted:** Three trade-offs are explicitly accepted: (1) Scalability ceiling is 7/10 versus 9/10 for Dataflow and Dataproc — accepted because the probability that a single operational employees table will exceed Cloud Run single-container capacity (32 GB memory) is low at assumed volume, and a partitioned extraction pattern can be introduced incrementally if volume growth is confirmed at the 6-month review checkpoint. (2) Manual PK-range partitioning must be implemented if volume scales — accepted as a deferred complexity that does not affect initial delivery scope. (3) Incremental delta strategy requires confirmation of a reliable timestamp column in MySQL before implementation begins — flagged as a blocking open question that must be resolved in sprint 0 before any incremental pipeline code is written.

---

## Rejected Options

### Dataflow-Centric ETL Pipeline

Although Dataflow provides superior scalability headroom and a unified pipeline model, its per-vCPU billing, Beam SDK complexity, and worker cold-start overhead are architecturally disproportionate for a known single-table daily batch load at unquantified but likely moderate volume. Option 2 satisfies all 13 functional requirements at a lower cost score (8 vs 6), lower complexity score (8 vs 6), and equal or higher operability (9 vs 8), without requiring specialized Beam expertise on the team.

### Dataproc Serverless Spark ETL Pipeline

Dataproc Serverless Spark is architecturally overengineered for a known single-table daily batch load at unquantified but likely moderate volume. It scores lowest on cost (5/10) due to DCU-hour billing overhead, lowest on complexity (5/10) due to PySpark expertise requirements and JDBC tuning burden, and lowest on operability (6/10) due to Spark UI complexity and History Server dependency for debugging. This option is reserved for future consideration only if volume projections confirmed at the 6-month review exceed Cloud Run single-container capacity (greater than 32 GB extraction), or if the pipeline scope expands to 10 or more large tables requiring native parallelized partition reads.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Data Volume Unknown | The row count and data size of the MySQL agentichub.employees table are unspecified. If actual volume significantly exceeds the assumed small-to-medium threshold (greater than 50 million rows or greater than 20 GB), Cloud Run Jobs memory limits may be breached during the full historical load, and BigQuery MERGE costs may exceed initial projections. | Execute a row count and estimated data size query against MySQL (SELECT COUNT(*), AVG(LENGTH(CONCAT_WS(',', <columns>))) FROM employees) before architecture is finalized. If volume exceeds 20 GB, implement partitioned PK-range extraction with configurable batch size and parallel Cloud Run Job task instances. Schedule a formal volume review checkpoint at 6 months post-production. |
| Schema Drift | MySQL schema changes including new column additions, data type modifications, column renames, or column removals in the employees table can break downstream BigQuery LOAD JOB executions or introduce silent data quality regressions if not detected and handled pre-load. | Implement pre-load schema compatibility check as a mandatory non-skippable validation step in the Cloud Run Job that compares MySQL information_schema.COLUMNS against the BigQuery table schema. Define and document the new column handling policy before first production run: recommended policy is to automatically add new nullable columns to BigQuery with STRING type and alert on type mismatches, and to block load and page on-call on column removal or type narrowing. |
| Incremental Delta Strategy Dependency | The incremental load pipeline depends on the existence of a reliable updated_at or equivalent timestamp column in the MySQL employees table. Absence of such a column requires PK-range delta scanning, which risks data gaps on non-monotonic PKs and cannot track soft-deleted records without additional audit column support. | Confirm presence and reliability of a timestamp column via MySQL schema inspection in sprint 0. If no reliable timestamp column exists, evaluate options in priority order: (1) add an updated_at column with DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP to the MySQL schema, (2) enable MySQL binary log (binlog) capture via Datastream as a supplementary change detection mechanism, (3) implement full-table comparison using hash checksums as a fallback at higher cost. |
| Stakeholder Visibility Gap | Stakeholder Yash requires independent load health visibility without developer involvement. A deployment gap where the Looker Studio dashboard is not delivered before the first production incremental run would force developer-mediated status reporting, violating the first-class operability requirement. | Classify the BigQuery audit_log table schema and Looker Studio dashboard as mandatory sprint 1 deliverables with go or no-go criteria. Block production incremental pipeline activation on dashboard delivery and Yash access confirmation. Include dashboard URL and access verification in the historical load sign-off checklist. |
| SLA Not Quantified | The pipeline failure monitoring SLA is referenced in requirements but not assigned a numeric threshold. Without a defined alert trigger duration, Cloud Monitoring alert policies cannot be precisely configured and operational response expectations are ambiguous, risking either alert fatigue from over-triggering or missed failures from under-triggering. | Establish formal SLA thresholds with stakeholder sign-off before production deployment. Recommended defaults: 30-minute alert trigger window for daily cadence pipelines, 15-minute window for hourly cadence pipelines. Document thresholds in the runbook and configure Cloud Monitoring uptime check and log-based metric alert policies accordingly. |
| Data Security and PII Compliance | The employees table almost certainly contains personally identifiable information including names, employee IDs, contact details, compensation data, or HR-sensitive fields. No data sensitivity classification, access control policy, or compliance requirement (GDPR, CCPA, internal data governance) has been specified, creating regulatory and reputational risk. | Conduct a data classification assessment for all columns in the employees table before production data is loaded into BigQuery. Apply BigQuery column-level security policies and data masking for PII fields. Restrict verizon_data_deah dataset IAM to named analytics and reporting principals only. Engage the data governance and legal teams to confirm compliance posture before the historical load executes. |

---

## Assumptions

1. GCP Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore is accessible from GCP data services via Cloud SQL Auth Proxy sidecar or Private IP within a shared VPC network; network peering or Serverless VPC Access connector will be provisioned as part of IaC
2. BigQuery dataset verizon_data_deah exists in the target GCP project or will be created as part of Terraform IaC deployment before the first pipeline run
3. The MySQL agentichub.employees table contains a reliable monotonically updated timestamp column such as updated_at or created_at, or an auto-incrementing primary key, suitable for incremental delta extraction; this assumption is flagged as a blocking open question requiring confirmation in sprint 0
4. Service accounts will be provisioned with minimum required IAM roles: roles/cloudsql.client for Cloud SQL access, roles/bigquery.dataEditor and roles/bigquery.jobUser for BigQuery operations, roles/storage.objectAdmin for GCS staging bucket access, and roles/run.invoker for Cloud Composer to trigger Cloud Run Jobs
5. Data volume for the employees table is assumed to be small-to-medium (fewer than 50 million rows and under 20 GB uncompressed) consistent with a single operational HR-style table; this assumption drives the Cloud Run Jobs selection and will be validated before final architecture sign-off
6. The full historical load must complete successfully and pass all validation checks before any incremental pipeline run is permitted to execute; this gate is enforced via Cloud Composer DAG sensor task dependency and is non-negotiable per stated requirements
7. Deployment environment is assumed to be production or near-production given stakeholder review requirements and analytics team dependency; separate GCP projects per environment (dev, staging, prod) are assumed but not confirmed
8. Standard MySQL column types including VARCHAR, INT, BIGINT, DATETIME, TIMESTAMP, DECIMAL, FLOAT, BOOLEAN, and TEXT will require explicit mapping to BigQuery-compatible types (STRING, INTEGER, TIMESTAMP, NUMERIC, FLOAT64, BOOL, STRING) defined in a per-table configuration schema file before first run
9. No existing pipeline, ETL framework, or data integration tooling is in place for this source-target pair; this is a greenfield implementation with no migration of existing pipeline logic required
10. Looker Studio dashboard will be deployed and access granted to stakeholder Yash with viewer-level permissions before the first production incremental run; dashboard access does not require BigQuery IAM modifications beyond dataset read permissions on the audit_log table

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud Run Jobs in full historical load mode with unbounded SELECT and PK-ordered chunked writes to GCS Parquet staging | Execute a one-time full historical load of the MySQL employees table into BigQuery with 100% data completeness and no data loss | batch | unknown — assumed small-to-medium (fewer than 50 million rows) |
| BigQuery MERGE statement applied from GCS staging table to target table after each incremental Cloud Run Job extraction | Prevent data duplication and gaps across all incremental load cycles; enforce primary key uniqueness in BigQuery after every load execution | daily or hourly per table | unknown |
| Timestamp watermark stored in BigQuery watermark table used as delta filter in incremental Cloud Run Job SELECT query; PK-range fallback documented as alternative | Track incremental changes using timestamp-based or primary key delta strategies, consistently applied across all runs | daily or hourly per table | unknown |
| Pre-load schema compatibility check via MySQL information_schema.COLUMNS comparison to BigQuery table schema executed as first Cloud Run Job step before any data movement | Perform pre-load schema compatibility checks covering data types, null handling, field names, and new column handling strategy before each load execution | — | — |
| Post-load row count reconciliation query comparing BigQuery SELECT COUNT(*) to MySQL source count stored in audit_log table, executed as final Cloud Run Job step per run cycle | Perform post-load row count validation between MySQL source and BigQuery target for every load cycle | — | — |
| New column handling policy defined as: auto-add nullable STRING column to BigQuery schema, alert on type mismatch, block load on column removal; enforced in pre-load schema check step | Define and implement a predefined handling strategy for new columns appearing in MySQL before they are loaded into BigQuery | — | — |
| BigQuery audit_log table with mandatory fields (run_id, pipeline_mode, table_name, rows_extracted, rows_loaded, validation_status, null_violations, schema_check_result, run_timestamp) written by Cloud Run Job after every load cycle | Generate and store audit logs for every load execution, accessible after each run | — | — |
| Looker Studio dashboard connected to BigQuery audit_log table delivered as sprint 1 mandatory deliverable with viewer access granted to stakeholder Yash before first production incremental run | Implement a monitoring dashboard or log-based visibility layer enabling stakeholders to independently review load success without developer involvement | — | — |
| Cloud Monitoring alert policies on Cloud Composer DAG task failure and Cloud Run Job non-zero exit code with configurable notification channel (email or PagerDuty) and threshold set to 30 minutes for daily, 15 minutes for hourly cadence | Trigger monitoring alerts on pipeline failures within a defined SLA | — | — |
| Cloud Composer DAG dependency: historical load validation task must emit success signal (XCom or sensor) before incremental DAG is unpaused; enforced via Airflow task dependency graph and manual sign-off trigger | Gate incremental load activation: incremental pipeline must not begin until historical load validation is fully passed and signed off | — | — |
| Null constraint violation scan executed as a discrete Cloud Run Job validation step before any LOAD JOB is submitted; violations logged to audit_log with field names and counts; load is blocked and flagged as FAILED if violations exceed zero for NOT NULL columns | Log and report null constraint violations before marking any load as complete | — | — |
| Terraform IaC for all GCP resource provisioning including Cloud Run Job definitions, Artifact Registry repositories, GCS buckets with lifecycle policies, BigQuery datasets and table schemas, Cloud Composer environment, Cloud Monitoring alert policies, and IAM bindings | Pipeline must be reliable and scalable to support ongoing scheduled loads, potential additional tables, and both hourly and daily cadences | — | — |

---

## Open Questions — Action Required

1. What is the current row count and approximate uncompressed data size in GB of the MySQL agentichub.employees table? This is a blocking question that determines whether Cloud Run Jobs single-container extraction is sufficient or whether partitioned parallel extraction must be implemented from the outset.
2. Does the employees table have a reliable monotonically updated timestamp column such as updated_at or modified_at that is populated on every INSERT and UPDATE operation? If not, what audit or change-tracking mechanism exists on the table that could serve as a delta extraction basis?
3. What is the agreed numeric SLA duration for pipeline failure alert delivery — specifically, what is the maximum acceptable elapsed time from pipeline failure detection to stakeholder notification for daily cadence runs and for hourly cadence runs respectively?
4. Has a data classification assessment been performed on the employees table columns? Are there PII fields such as names, national identifiers, salary data, or contact information subject to GDPR, CCPA, or internal data governance and access control requirements?
5. Are there plans to expand the pipeline scope beyond the employees table to additional MySQL tables in the agentichub database within the next 6 to 12 months? The answer determines the degree of table-agnostic generalization required in the Cloud Run Job configuration framework.
6. What are the target deployment environments and GCP project topology — are separate GCP projects used for development, staging, and production, and does the verizon_data_deah dataset exist in a dedicated analytics project or in the same project as the Cloud SQL instance?
7. Who is the designated approver for the historical load sign-off gate — is stakeholder Yash the approver, or is there a separate data steward, data owner, or analytics lead role who must validate 100% completeness before incremental pipeline activation is authorized?
8. What is the formally agreed new column handling policy — should new MySQL columns be automatically added to the BigQuery target table as nullable fields, routed to a schema review queue requiring explicit approval before load, or cause the pipeline to block with an alert until an engineer manually extends the BigQuery schema?
