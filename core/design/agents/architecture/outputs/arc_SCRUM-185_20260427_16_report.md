# Architecture Decision Document — mysql to bigquery data ingestion pipeline

| Field | Value |
|---|---|
| **Project** | mysql to bigquery data ingestion pipeline |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Batch |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Cloud Run Jobs + BigQuery Native MERGE (Serverless Batch)
>
> **Why:** Cloud Run Jobs combined with BigQuery Native MERGE achieves the highest weighted score of 7.90 by decisively winning on the two highest-weighted dimensions: cost efficiency (weight 0.30, score 9) and architectural simplicity (complexity weight 0.20, score 8). For a medium-volume batch pipeline processing 5 GB initially and growing at 1 GB per month with daily and hourly scheduling requirements, the serverless execution model eliminates infrastructure waste while BigQuery-native MERGE directly implements the stated sp_mysqltobq_load.sql stored procedure preference without adaptation. Cloud Composer 2 provides robust gating, scheduling, and audit logging that fulfills all ten functional requirements without requiring additional managed services.
>
> **Score:** 7.90 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2  | Option 3 ✅ |
|---|---||---||---|
| **Name** | Cloud Composer + Dataflow JDBC Managed Pipeline | Cloud Composer + Dataproc PySpark Batch Pipeline | Cloud Run Jobs + BigQuery Native MERGE (Serverless Batch) |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Google Cloud Dataflow (Apache Beam transforms with inline schema validation and dead-letter routing) | Apache Spark on Cloud Dataproc (PySpark DataFrames with schema validation and drift detection) | Google BigQuery Native (Load Job + CALL sp_mysqltobq_load MERGE stored procedure) + Python data quality module in Cloud Run Job |
| **Storage** | Google BigQuery (verizon_data_dea, date-partitioned) + Google Cloud Storage (temp and dead-letter) | Google BigQuery (verizon_data_dea, date-partitioned) + Google Cloud Storage (Parquet staging) | Google BigQuery (verizon_data_dea, date-partitioned + clustered, partition_expiration_days=60) + Google Cloud Storage (Parquet staging with 7-day lifecycle) |
| **Weighted Score** | **6.90** | **5.80** | **7.90**  ✅ |

---

## Option 1 — Cloud Composer + Dataflow JDBC Managed Pipeline

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Dataflow job reads MySQL agentichub tables from Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore via Apache Beam JDBC I/O connector routed through Cloud SQL Auth Proxy sidecar; full load reads all rows in bounded source; incremental load applies WHERE updated_date > max_watermark value fetched from BigQuery pipeline_audit_log table, eliminating full table re-scans |
| Processing | Apache Beam pipeline transforms apply inline schema validation (field mapping, type compatibility checks, null constraint enforcement), type casting, deduplication on employee_id, and schema drift detection by comparing extracted record schema against BigQuery target schema at runtime; records failing validation are routed to a dead-letter GCS path and trigger Cloud Monitoring alerts; validated records are forwarded to BigQuery Write transform |
| Storage | Validated records written to BigQuery dataset verizon_data_dea via Beam BigQueryIO using WRITE_APPEND to staging table for historical load; incremental records use WRITE_APPEND followed by invocation of sp_mysqltobq_load.sql MERGE stored procedure via BigQuery Jobs API on employee_id and updated_date composite key; GCS bucket gs://verizon-data-staging/ used for Dataflow temp and shuffle files; target BigQuery tables are date-partitioned with partition_expiration_days=60 |
| Consumption | Analytics team queries BigQuery verizon_data_dea via BigQuery console or Looker Studio; pipeline_audit_log table in BigQuery captures run_id, table_name, load_type, start_time, end_time, source_row_count, target_row_count, validation_status, and error_message per execution; Looker Studio dashboard provides stakeholder visibility without engineering involvement |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Google Cloud Dataflow with Apache Beam JDBC I/O + Cloud SQL Auth Proxy | 2.x (Beam 2.55+) | Yes |
| Processing | Google Cloud Dataflow (Apache Beam transforms with inline schema validation and dead-letter routing) | 2.x (Beam 2.55+) | Yes |
| Storage | Google BigQuery (verizon_data_dea, date-partitioned) + Google Cloud Storage (temp and dead-letter) | — | Yes |
| Orchestration | Google Cloud Composer 2 (Apache Airflow 2.7+) with gating sensor and audit log tasks | 2.x | Yes |
| Monitoring | Google Cloud Monitoring + Cloud Logging + Looker Studio dashboard on pipeline_audit_log | — | Yes |
| Iac | Terraform | 1.6+ | No |

### Pros

- Dataflow auto-scales horizontally with dynamic work rebalancing, providing built-in fault tolerance and exactly-once write semantics to BigQuery for reliable historical and incremental loads
- Native BigQueryIO sink in Apache Beam provides high-throughput optimized writes without requiring a separate GCS staging file step for the write path
- Inline Beam transforms enforce schema validation before any records reach BigQuery, preventing corrupt data from entering the target dataset
- Fully managed execution environment eliminates cluster lifecycle management; Dataflow provisions and decommissions workers automatically per job
- Cloud Composer gating sensor enforces strict DAG dependency: incremental load DAG cannot start until the historical load validation task completes and sets a success gate flag

### Cons

- Dataflow JDBC connector requires Cloud SQL Auth Proxy sidecar deployment or VPC direct peering configuration, adding network and credential management complexity beyond the pipeline itself
- Apache Beam pipeline development requires specialist expertise in the Beam programming model and runner semantics; steeper learning and maintenance curve than standard Python ETL scripts
- Dataflow job cold start of 3 to 5 minutes is overhead applied to every run; for hourly-scheduled tables this consumes 5 to 8 percent of the scheduling window before data extraction begins
- Per-vCPU-hour Dataflow billing is disproportionately expensive for small incremental deltas at hourly frequency; minimum worker allocation cannot scale below 1 worker even for sub-10 MB payloads
- sp_mysqltobq_load.sql stored procedure must be invoked as a separate BigQuery job step after Dataflow write completes, requiring an additional Composer task and adding end-to-end latency

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Schema drift in MySQL such as new columns or type changes is not automatically surfaced by the Beam JDBC I/O source; requires custom Beam transforms performing schema registry cross-validation before record emission to detect and halt the pipeline prior to corrupt records reaching BigQuery |
| Scaling | Dataflow autoscaling may over-provision workers for small incremental deltas producing sub-50 MB payloads, inflating per-run cost significantly; requires careful maxNumWorkers and Streaming Engine tuning to prevent runaway worker allocation |
| Latency | Dataflow job initialization latency of 3 to 5 minutes constrains the effective processing window for hourly-scheduled tables; if MySQL data availability is delayed by upstream application writes the scheduling window may be exhausted before extraction begins |
| Cost | Dataflow worker billing at approximately $0.056 per vCPU-hour for n1-standard-4 equivalent workers; hourly jobs across multiple tables can accumulate to $250 to $450 per month for medium volume, representing 3 to 5 times the estimated cost of Option 3 for equivalent throughput |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 9 | 5 | 7 | 8 | **6.90** |

---

## Option 2 — Cloud Composer + Dataproc PySpark Batch Pipeline

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 DAG triggers ephemeral Dataproc cluster creation via DataprocCreateClusterOperator; PySpark job connects to MySQL agentichub via JDBC driver (mysql-connector-java 8.x) using partitioned reads on employee_id primary key column for parallel extraction across Spark executors; full load reads all partitions across configurable lower and upper bounds; incremental load applies Spark filter on updated_date greater than max_watermark retrieved from BigQuery pipeline_audit_log; cluster is deleted immediately upon job completion to avoid idle billing |
| Processing | PySpark DataFrames apply schema validation by comparing extracted DataFrame schema against BigQuery table schema fetched via BigQuery API; type casting, null handling, and deduplication on employee_id are applied as DataFrame transformations; schema drift triggers SparkContext stop and Composer task failure with alert; validated DataFrames written to GCS staging bucket as Parquet files partitioned by table_name and load_date |
| Storage | GCS staging bucket gs://verizon-data-staging/spark-output/ stores intermediate Parquet files with 7-day lifecycle; BigQuery Load Job ingests Parquet from GCS into verizon_data_dea.employees_staging table; sp_mysqltobq_load.sql MERGE stored procedure is invoked via BigQuery Jobs API CALL statement to upsert into verizon_data_dea.employees on composite key employee_id and updated_date; BigQuery target tables are date-partitioned with partition_expiration_days=60 enforcing 60-day retention |
| Consumption | Analytics team queries BigQuery verizon_data_dea via BigQuery console or Looker Studio; Dataproc Job History Server provides Spark stage-level execution details for pipeline debugging; Cloud Logging captures Composer task audit records including job_id, run_id, duration, row counts, and validation results; Looker Studio dashboard on pipeline_audit_log surfaces load status for stakeholders |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Google Cloud Dataproc (PySpark 3.4 with MySQL JDBC Connector mysql-connector-java 8.x, ephemeral clusters) | 2.1 (Spark 3.4, Hadoop 3.3) | Yes |
| Processing | Apache Spark on Cloud Dataproc (PySpark DataFrames with schema validation and drift detection) | 3.4 | Yes |
| Storage | Google BigQuery (verizon_data_dea, date-partitioned) + Google Cloud Storage (Parquet staging) | — | Yes |
| Orchestration | Google Cloud Composer 2 (Apache Airflow 2.7+) with DataprocCreateClusterOperator, gating sensor, audit tasks | 2.x | Yes |
| Monitoring | Google Cloud Monitoring + Cloud Logging + Dataproc History Server + Looker Studio | — | Yes |
| Iac | Terraform | 1.6+ | No |

### Pros

- PySpark parallel JDBC reads with partitionColumn on employee_id and configurable numPartitions dramatically accelerate large historical loads by distributing MySQL extraction across multiple Spark executors simultaneously
- Rich PySpark DataFrame API supports complex schema validation, deduplication, null handling, and custom transformation logic entirely within the Spark execution context without external libraries
- Ephemeral Dataproc cluster lifecycle tied to job duration eliminates idle infrastructure cost; cluster is created at DAG task start and deleted at task end
- Spark native schema inference enables automatic DataFrame schema comparison against BigQuery table metadata for drift detection
- Well-documented integration pattern with extensive GCP reference architectures and open-source Spark BigQuery connector ecosystem support

### Cons

- Ephemeral Dataproc cluster initialization time of 3 to 5 minutes adds mandatory latency overhead to every pipeline run regardless of data volume, making hourly-scheduled tables structurally inefficient
- Architecturally over-engineered for a 5 to 6 GB workload; Spark performance advantages over sequential Python extraction only materialize at multi-hundred GB to TB scale
- Requires JDBC driver JAR management on cluster initialization scripts (init actions) introducing a deployment dependency that must be versioned and tested with each Dataproc image upgrade
- Cluster minimum sizing of 1 master plus 2 workers (n1-standard-4 default) is cost-inefficient for small incremental deltas where actual data movement is under 100 MB per run
- Higher operational burden: Spark executor memory, shuffle partition count, and JDBC fetch size tuning require specialist knowledge and iterative performance testing before production go-live

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | PySpark schema validation and data quality assertion logic must be authored and maintained entirely in application code with no managed DQ framework; incomplete assertion coverage or silent exception handling in PySpark can allow corrupted records to propagate to BigQuery staging table before the MERGE step |
| Scaling | Cluster auto-scaling misconfiguration or underestimated executor memory requirements can trigger OOM errors during historical load of large tables; over-provisioning to prevent OOM wastes budget; right-sizing requires multiple iterative tuning cycles against production data volumes |
| Latency | Total per-run pipeline latency of 8 to 12 minutes (cluster start plus Spark initialization plus job execution plus GCS write plus BigQuery Load plus MERGE) may violate tight hourly SLAs if upstream MySQL data availability is delayed or cluster resources are contended |
| Cost | Dataproc cluster cost for n1-standard-4 master plus 2 n1-standard-4 workers at approximately $0.096 per vCPU-hour; hourly jobs across multiple tables can reach $400 to $600 per month, representing 4 to 6 times the estimated serverless cost of Option 3 at equivalent throughput |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 8 | 4 | 6 | 6 | **5.80** |

---

## Option 3 — Cloud Run Jobs + BigQuery Native MERGE (Serverless Batch) ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 DAG triggers Cloud Run Job (Python 3.11 container) via Cloud Run Jobs API for each configured source table; Cloud Run Job connects to MySQL agentichub on instance verizon-data:us-central1:mysql-druid-metadatastore using Cloud SQL Python Connector with IAM service account authentication, eliminating hardcoded credentials and manual Auth Proxy management; full historical load reads all rows in configurable chunked batches of 50000 rows to respect Cloud Run Job memory ceiling; incremental load issues SELECT WHERE updated_date greater than max_watermark fetched from BigQuery pipeline_audit_log table, strictly avoiding full table re-scans; extracted data is written to GCS bucket gs://verizon-data-staging/ as Parquet files partitioned by table_name and load_date |
| Processing | Pre-load data quality module within Cloud Run Job performs: (1) schema drift check by comparing MySQL INFORMATION_SCHEMA.COLUMNS definitions against BigQuery table schema via BigQuery API; on mismatch, job exits with non-zero code triggering Composer task failure and Cloud Monitoring alert with alert-and-hold policy blocking the load; (2) source row count assertion by issuing MySQL COUNT(*) with same incremental WHERE predicate and recording expected count in audit log; (3) primary key null check on employee_id before writing Parquet. Post-extraction: BigQuery Load Job ingests Parquet from GCS into verizon_data_dea.employees_staging table; sp_mysqltobq_load.sql MERGE stored procedure is invoked via BigQuery Jobs API CALL statement performing ACID-compliant upsert on composite key (employee_id, updated_date) into target table verizon_data_dea.employees; post-MERGE reconciliation asserts target row count delta matches extracted source count within configurable tolerance |
| Storage | GCS bucket gs://verizon-data-staging/ with 7-day object lifecycle policy for Parquet staging files organized by table_name/load_date/; BigQuery dataset verizon_data_dea in project verizon-data as analytical target with date-partitioned tables using partition_expiration_days=60 enforcing 60-day rolling retention per SLA; clustering on employee_id on target tables to optimize MERGE partition pruning; BigQuery table pipeline_audit_log stores run_id, table_name, load_type (full or incremental), start_time, end_time, source_row_count, extracted_row_count, target_row_count_before, target_row_count_after, validation_status (pass or fail), schema_drift_detected (boolean), and error_message per execution cycle |
| Consumption | Analytics team queries BigQuery verizon_data_dea.employees and future onboarded tables via BigQuery console, Looker Studio, or connected BI tools using standard SQL; Looker Studio dashboard built on pipeline_audit_log table provides real-time load status, historical success and failure counts, row-level reconciliation metrics, and per-table freshness timestamps without requiring engineering involvement; stakeholder-accessible shared dashboard URL distributed post-go-live; Cloud Logging retains full Cloud Run Job execution logs and Composer task logs for 30 days for debugging and compliance |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Google Cloud Run Jobs (Python 3.11 + Cloud SQL Python Connector v1.x with IAM auth) | gen2 (Cloud Run Jobs API v1) | Yes |
| Processing | Google BigQuery Native (Load Job + CALL sp_mysqltobq_load MERGE stored procedure) + Python data quality module in Cloud Run Job | — | Yes |
| Storage | Google BigQuery (verizon_data_dea, date-partitioned + clustered, partition_expiration_days=60) + Google Cloud Storage (Parquet staging with 7-day lifecycle) | — | Yes |
| Orchestration | Google Cloud Composer 2 (Apache Airflow 2.7+) with historical load gating ExternalTaskSensor, per-table task groups, and audit log write tasks | 2.x | Yes |
| Monitoring | Google Cloud Monitoring + Cloud Logging + BigQuery pipeline_audit_log table + Looker Studio stakeholder dashboard | — | Yes |
| Iac | Terraform | 1.6+ | No |

### Pros

- Serverless Cloud Run Jobs billing is purely per vCPU-second of execution with zero idle cost, making this the most cost-efficient option for medium-volume daily and hourly batch workloads estimated at 60 to 80 percent lower monthly cost than Dataflow or Dataproc equivalents
- Direct native alignment with sp_mysqltobq_load.sql stored procedure: BigQuery CALL statement invokes the MERGE logic as authored, fulfilling the stated preferred tool requirement without adaptation or wrapper overhead
- BigQuery-native MERGE provides ACID-compliant upsert on composite key employee_id and updated_date with full execution metadata visible in BigQuery INFORMATION_SCHEMA.JOBS for independent audit trail
- Cloud SQL Python Connector with IAM service account authentication eliminates manual Cloud SQL Auth Proxy sidecar management and removes hardcoded credentials from pipeline code, satisfying security access control requirements
- Cloud Composer 2 gating ExternalTaskSensor or gate table check enforces strict dependency: incremental load DAG tasks cannot proceed until historical load validation task sets a success state, satisfying the stated gating constraint with zero custom code
- Simplest and most maintainable architecture: adding new source tables requires only a new table configuration entry in a YAML or BigQuery config table, not new pipeline code or infrastructure changes
- BigQuery pipeline_audit_log table with Looker Studio dashboard directly satisfies functional requirements for stakeholder-accessible load visibility without engineering involvement
- Date-partitioned target tables with partition_expiration_days=60 enforce 60-day retention at the storage layer without application-level deletion jobs or scheduled cleanup tasks

### Cons

- Cloud Run Job maximum memory of 32 GB per container requires chunked extraction logic for very large single-table historical loads to prevent OOM; chunk size and concurrency must be tuned per table volume
- Python-based extraction is inherently sequential within a single Cloud Run Job container; multi-table concurrent loads require Composer DAG-level fan-out launching parallel Cloud Run Jobs, adding DAG complexity as table count grows
- Cloud Run Jobs does not provide native exactly-once delivery guarantees; idempotency of the extraction and load cycle must be explicitly designed into checkpoint tracking in pipeline_audit_log and BigQuery MERGE upsert semantics
- No managed data quality framework is included; all DQ checks are custom Python assertions that must be authored, tested, and maintained as MySQL schema evolves; coverage gaps introduce silent data quality risk

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Custom Python DQ module lacks the governed rule catalog, lineage tracking, and alerting of a managed framework such as Dataplex Data Quality; incomplete assertion coverage or exception swallowing in error handling can allow records with type inconsistencies or null primary keys to reach the BigQuery staging table before the MERGE step; mitigate by adopting Dataplex Data Quality scans on BigQuery staging table as a post-load gate in a future iteration |
| Scaling | Sequential table processing within a single Cloud Run Job container extends total pipeline window linearly as table count grows; Composer DAG fan-out with configurable max_active_tasks must be implemented to parallelize across tables; beyond 20 tables, Cloud Run Job concurrency limits and BigQuery slot contention require capacity planning |
| Latency | Cloud Run Job container cold start is 10 to 30 seconds for Python 3.11 gen2 containers, which is negligible for daily and hourly batch windows; BigQuery MERGE execution on 60-day partitioned target tables is sub-5 minutes for projected volumes; no material latency risk identified for stated batch SLA |
| Cost | BigQuery MERGE and Load Job slot consumption on on-demand pricing at $5 per TB scanned can accumulate if MERGE statements perform full partition scans without partition pruning; mitigate by enforcing partition filter in MERGE WHERE clause targeting only recent partitions, clustering target tables on employee_id, and evaluating BigQuery Editions flat-rate pricing if monthly slot usage exceeds $150 |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 9 | 7 | 8 | 7 | 8 | **7.90** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Dataflow JDBC Managed Pipeline | 6 | 9 | 5 | 7 | 8 | **6.90** |
| Cloud Composer + Dataproc PySpark Batch Pipeline | 5 | 8 | 4 | 6 | 6 | **5.80** |
| Cloud Run Jobs + BigQuery Native MERGE (Serverless Batch) ✅ | 9 | 7 | 8 | 7 | 8 | **7.90** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Run Jobs + BigQuery Native MERGE (Serverless Batch)**
**Weighted Score: 7.90**

**Justification:** Cloud Run Jobs combined with BigQuery Native MERGE achieves the highest weighted score of 7.90 by decisively winning on the two highest-weighted dimensions: cost efficiency (weight 0.30, score 9) and architectural simplicity (complexity weight 0.20, score 8). For a medium-volume batch pipeline processing 5 GB initially and growing at 1 GB per month with daily and hourly scheduling requirements, the serverless execution model eliminates infrastructure waste while BigQuery-native MERGE directly implements the stated sp_mysqltobq_load.sql stored procedure preference without adaptation. Cloud Composer 2 provides robust gating, scheduling, and audit logging that fulfills all ten functional requirements without requiring additional managed services.

**Why highest score:** Option 3 outscores Options 1 and 2 across three of five dimensions: (1) Cost score of 9 versus 6 and 5: Cloud Run Jobs serverless billing eliminates idle worker costs entirely; estimated monthly execution cost for hourly and daily loads across projected table count is $40 to $80 versus $250 to $450 for Dataflow and $400 to $600 for Dataproc at equivalent throughput. (2) Complexity score of 8 versus 5 and 4: Python Cloud SQL Connector plus BigQuery Load plus MERGE is a standard, well-documented pattern requiring no specialist Beam or Spark expertise; onboarding new engineers or tables is straightforward. (3) Operability score of 8 shared with Option 1: Composer DAG visibility, BigQuery audit table, and Looker Studio dashboard fulfill all stakeholder observability requirements natively. Options 1 and 2 sacrifice cost and complexity scores for scalability advantages that provide no material benefit at sub-TB projected volumes within the 24-month planning horizon.

**Trade-offs accepted:** Option 3 accepts a scalability score of 7 versus Option 1 score of 9 and Option 2 score of 8. This trade-off is explicitly accepted because: (a) projected 24-month total volume of approximately 29 GB (5 GB initial plus 24 multiplied by 1 GB growth) remains well within Cloud Run Job capacity with chunked extraction at 50000 rows per batch; (b) multi-table parallel execution is achievable via Composer DAG fan-out without any architectural changes to the Cloud Run Job or BigQuery components; (c) if volume trajectory accelerates beyond 100 GB active window or table count exceeds 20 concurrent jobs, migration to Dataflow is a localized swap of the extraction compute layer only, since the BigQuery sink, GCS staging pattern, sp_mysqltobq_load.sql stored procedure, Composer orchestration, and monitoring stack remain entirely unchanged. Additionally, the absence of a managed DQ framework is accepted with the mitigation roadmap of adding Dataplex Data Quality scans as a post-load gate in the next engineering iteration.

---

## Rejected Options

### Cloud Composer + Dataflow JDBC Managed Pipeline

Dataflow introduces disproportionate cost and operational complexity for a medium-volume (5 to 6 GB active window) daily and hourly batch use case. The 3 to 5 minute job cold start overhead, Beam specialist expertise requirement, and per-vCPU-hour billing model are unjustified when Cloud Run Jobs can achieve equivalent reliability and data integrity at 60 to 80 percent lower execution cost. Beam's horizontal scalability advantage is architecturally irrelevant at sub-TB data volumes projected over a 24-month horizon for this workload.

### Cloud Composer + Dataproc PySpark Batch Pipeline

Dataproc with PySpark is the weakest option on both cost (score 5) and complexity (score 4), the two highest-weighted scoring dimensions. The architecture is over-engineered for a medium-volume batch workload projected at under 30 GB total within 24 months. Spark's parallelism and fault tolerance advantages are not realized at this scale but the full operational and financial overhead of cluster management is incurred on every run. Cluster cold start latency further undermines hourly scheduling reliability. Option 3 delivers equivalent data integrity guarantees at a fraction of the operational burden and cost.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Schema Drift | MySQL schema changes in agentichub such as new column additions, column type alterations, column renames, or column removals will break the BigQuery Load Job Parquet schema mapping and invalidate the sp_mysqltobq_load.sql MERGE statement column references, potentially causing pipeline failures or silent data truncation without alerting | Implement mandatory pre-load schema comparison step in Cloud Run Job: query MySQL INFORMATION_SCHEMA.COLUMNS and compare against BigQuery table schema fetched via BigQuery Tables API; on any mismatch abort the job with non-zero exit code triggering Composer task failure and Cloud Monitoring alert to on-call channel; enforce alert-and-hold as the default new column strategy (block pipeline, alert engineers for review) with documented runbook for column addition approval and BigQuery schema update procedure |
| Incremental Change Tracking Completeness | If updated_date is not consistently updated on all MySQL write paths such as bulk INSERT statements without updated_date assignment, application-layer bypasses of ORM triggers, or direct database writes, incremental loads will silently miss changed or new records producing data divergence between MySQL source and BigQuery target over time | Post-load row count reconciliation comparing MySQL COUNT(*) WHERE updated_date within the incremental window against BigQuery delta record count; add primary key range assertion comparing MAX(employee_id) in BigQuery against MySQL; raise Cloud Monitoring alert when delta discrepancy exceeds configurable threshold of 1 percent row count variance; document and enforce MySQL application-layer constraint that updated_date must be set on every INSERT and UPDATE operation |
| Network and IAM Connectivity | Cloud SQL Python Connector requires IAM service account with Cloud SQL Client role and Cloud SQL API enabled; misconfigured VPC Service Controls, missing IAM bindings, or API not enabled will cause silent runtime failures that are not surfaced at infrastructure deployment time via Terraform plan | Include Cloud SQL connectivity health check as the first Composer DAG task before any extraction begins using a lightweight Cloud Run Job test connection step; validate IAM role bindings and API enablement in Terraform configuration; configure Cloud Monitoring uptime check on Cloud SQL instance; alert on three consecutive connection failures within a 15-minute window |
| Historical Load Idempotency and Failure Recovery | Cloud Run Job OOM failure, network interruption, or GCS write error occurring mid-historical-load will produce a partial Parquet file set in GCS; re-running the historical load job without idempotency logic will append duplicate records to BigQuery staging table before the MERGE step, producing inflated row counts and corrupted target data | Partition historical load by primary key range using configurable chunk_size (default 50000 rows); use BigQuery WRITE_TRUNCATE on the staging table per load run to make it idempotent; track checkpoint as last_loaded_pk_value in pipeline_audit_log table to enable resume-from-last-checkpoint on job restart; require explicit Composer task operator retry with exponential backoff before triggering failure alert |
| BigQuery On-Demand Query Cost Overrun | BigQuery MERGE statements that perform full table scans on the target table without partition pruning will scan all data within the 60-day retention window on every incremental run, accumulating unexpected query costs at $5 per TB scanned; at steady-state target volume this represents significant unplanned spend | Enforce partition filter in sp_mysqltobq_load.sql MERGE WHERE clause restricting target table scan to recent partitions only (example: WHERE target._PARTITIONDATE >= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)); cluster target tables on employee_id to reduce bytes scanned per MERGE; monitor monthly BigQuery slot consumption in Cloud Billing and evaluate switching to BigQuery Editions flat-rate pricing if on-demand query costs exceed $150 per month |

---

## Assumptions

1. MySQL Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore is network-accessible from the GCP project VPC via Cloud SQL Python Connector using IAM service account authentication; direct IP connectivity to host 34.70.79.163 is not used in production to avoid static IP firewall rule sprawl and credential exposure
2. Source table employees in database agentichub contains an updated_date column of DATETIME or TIMESTAMP type and employee_id column designated as PRIMARY KEY; both columns are mandatory prerequisites for the incremental change tracking and upsert merge key strategy and must be confirmed present before pipeline deployment
3. BigQuery dataset verizon_data_dea already exists in project verizon-data; the pipeline service account is granted BigQuery Data Editor, BigQuery Job User, BigQuery Read Session User, and Storage Object Admin IAM roles at minimum before pipeline execution
4. sp_mysqltobq_load.sql is a BigQuery SQL script containing a MERGE statement targeting verizon_data_dea.employees on composite key (employee_id, updated_date); it will be deployed as a BigQuery Stored Procedure callable via CALL statement from the BigQuery Jobs API invocation in the Cloud Run Job post-load step
5. Data retention of 60 days is enforced at the BigQuery table partition level by setting partition_expiration_days=60 on all date-partitioned target tables; no application-level deletion jobs or scheduled purge processes are required
6. Additional source tables beyond employees in agentichub will be confirmed after stakeholder review; they will be onboarded using the same Cloud Run Job and BigQuery MERGE pattern by adding a new table configuration entry without requiring new pipeline code or infrastructure resources
7. No PII, PHI, or sensitive data classification has been provided for the employees table; GCP default envelope encryption at rest and TLS 1.2 in transit apply to all data; if PII columns are identified post-stakeholder review, BigQuery column-level security policies and Cloud DLP masking must be added before analytics team access is granted
8. Schedule interval is daily at the pipeline DAG level; individual tables configured for hourly frequency are managed via separate Composer DAG tasks with independent cron trigger schedules within the same Composer environment
9. Historical load validation is defined as all three conditions passing: (a) zero extraction errors in Cloud Run Job logs, (b) MySQL COUNT(*) equals BigQuery target COUNT(*) within zero tolerance, (c) zero duplicate employee_id values in target table post-load; all three must pass before the incremental load gate is released

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud Run Jobs selected as extraction and ingestion compute layer over Dataflow and Dataproc | technology.preferred_tools: sp_mysqltobq_load.sql; non_functional.performance: incremental loads must not perform full table re-scans; non_functional.scalability: reliable and scalable to accommodate 1 GB per month growth; constraints.budget: null requiring cost optimization | batch (daily and hourly per table configuration) | 5 GB initial historical load; 1 GB per month incremental growth; approximately 29 GB projected at 24 months |
| BigQuery Native MERGE via sp_mysqltobq_load.sql stored procedure for upsert on composite key employee_id and updated_date | functional_requirements[9]: Apply merge key logic using employee_id and updated_date for upsert/merge operations via stored procedure sp_mysqltobq_load.sql | — | — |
| Cloud Composer 2 historical load gating sensor enforcing incremental load dependency on validated historical load completion | functional_requirements[3]: Gate incremental loads so they cannot begin until the full historical load has been validated and confirmed complete | — | — |
| Timestamp (updated_date) watermark-based incremental change detection with primary key (employee_id) range assertion as secondary reconciliation check | functional_requirements[2]: Use timestamp-based or primary key-based change tracking to identify and load only new or changed records; non_functional.performance: incremental loads must not perform full table re-scans | batch | — |
| GCS Parquet staging layer between MySQL extraction and BigQuery Load Job as intermediate persistence checkpoint | functional_requirements[6]: Implement per-load data quality checks covering row count reconciliation, primary key uniqueness, and data type constraint verification; functional_requirements[7]: Maintain audit logs for all load executions capturing execution time, record counts, validation results, and errors | — | 5 GB initial load; sub-1 GB incremental deltas per hourly or daily window |
| Date-partitioned BigQuery target tables with partition_expiration_days equal to 60 | non_functional.sla: 60-day data retention must be enforced; data_requirements.volume: retention period 60 days | — | 60-day rolling retention window; estimated 65 GB steady-state active data at month 60 based on 1 GB per month growth rate |
| Pre-load schema validation step comparing MySQL INFORMATION_SCHEMA.COLUMNS against BigQuery table schema with alert-and-hold policy on mismatch | functional_requirements[4]: Implement pre-load schema validation that detects type mismatches, null handling inconsistencies, and field mapping issues; functional_requirements[5]: Define and implement a strategy for handling new columns that appear in MySQL source | — | — |
| Looker Studio dashboard built on BigQuery pipeline_audit_log table for stakeholder visibility without engineering involvement | functional_requirements[8]: Provide stakeholder visibility into load success through accessible logs or a dashboard without requiring engineering involvement | — | — |

---

## Open Questions — Action Required

1. Has the complete list of source tables in agentichub beyond the currently identified employees table been finalized post-stakeholder review? Final table count and estimated individual table volumes directly determine Composer DAG fan-out parallelism design and Cloud Run Job concurrency configuration before pipeline infrastructure can be sized.
2. Is sp_mysqltobq_load.sql a pre-existing BigQuery stored procedure that will be provided to the engineering team, or does it need to be authored as part of this initiative? If pre-existing, confirmation of the current MERGE predicate columns and whether the composite key (employee_id, updated_date) is already implemented is required before pipeline integration testing.
3. What constitutes a passing historical load validation for gate release? Is source-to-target row count equality within zero tolerance sufficient, or is a column-level hash or checksum comparison required for a subset of critical columns? This definition determines gate release criteria and validation runtime.
4. Are there PII, PHI, or sensitive data columns such as salary, SSN, date of birth, or contact information in the employees table that require column-level masking, tokenization via Cloud DLP, or BigQuery column-level access control policies before the analytics team is granted query access to verizon_data_dea?
5. What is the acceptable end-to-end SLA for hourly-configured tables measured from MySQL data availability to BigQuery queryability? Cloud Run Job extraction plus BigQuery Load plus MERGE typically completes in 3 to 8 minutes for sub-1 GB incremental deltas; stakeholder confirmation is required to validate this meets reporting freshness expectations.
6. Will Cloud Composer 2 be a dedicated environment provisioned for this project or shared with existing Airflow workloads in project verizon-data? Shared environment requires DAG namespace isolation, resource quota coordination, and pool configuration to prevent resource contention.
7. Is the new column handling strategy confirmed as alert-and-hold (block pipeline execution and alert engineers pending explicit review and approval) or auto-map-with-review (automatically add nullable column to BigQuery staging table, continue pipeline execution, and flag column addition for review)? This policy decision must be made before schema validation logic is implemented.
8. Latency SLA is not specified in the requirements; the inferred batch pattern of hourly and daily scheduling is assumed appropriate for all identified tables. Confirmation is required that no source table has a near-real-time or sub-15-minute latency requirement that would necessitate reclassification from batch to streaming using PubSub and Dataflow.
