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

> **Build with:** Cloud Run Jobs + Cloud Composer + BigQuery Stored Procedure MERGE (Recommended)
>
> **Why:** Cloud Run Jobs combined with Cloud Composer orchestration and BigQuery stored procedure MERGE is the optimal architecture for this workload. The pay-per-execution Cloud Run model eliminates idle compute cost entirely, making it the most cost-efficient choice for hourly and daily batch cadence on a medium-volume dataset of 5 GB growing at 1 GB per month. Python-native ETL logic using SQLAlchemy and the BigQuery client directly supports the sp_mysqltobq_load.sql MERGE pattern with minimal impedance, reduces time to production, and keeps the operational skill floor accessible. Cloud Composer's ExternalTaskSensor satisfies the hard historical-load gating constraint as a first-class orchestration primitive. The architecture fulfills every functional requirement stated in the brief — full historical load, gated incremental load, schema validation, per-load data quality checks, audit logging, stakeholder dashboard, and new-column hold-and-alert — without over-engineering for capabilities not required by the current workload profile.
>
> **Score:** 7.75 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2 ✅ | Option 3  |
|---|---||---||---|
| **Name** | Dataflow (Apache Beam) + Cloud Composer Managed Batch Pipeline | Cloud Run Jobs + Cloud Composer + BigQuery Stored Procedure MERGE (Recommended) | Datastream CDC + BigQuery Direct Destination + Cloud Composer Validation Gate |
| **Pattern** | Batch | Batch | Hybrid |
| **Processing** | Dataflow (Apache Beam 2.x) | Cloud Run Jobs (schema validation and data quality) + BigQuery MERGE via sp_mysqltobq_load.sql stored procedure | BigQuery MERGE stored procedure (sp_mysqltobq_load.sql) triggered via Cloud Composer |
| **Storage** | BigQuery (date-partitioned, clustered) + GCS (Avro staging) | BigQuery (date-partitioned, clustered on employee_id) + GCS (Parquet staging, 60-day lifecycle) | BigQuery (staging dataset for CDC events + production dataset for analytics) + GCS (optional Datastream intermediary for replay) |
| **Weighted Score** | **6.20** | **7.75**  ✅ | **7.40** |

---

## Option 1 — Dataflow (Apache Beam) + Cloud Composer Managed Batch Pipeline

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud SQL MySQL (verizon-data:us-central1:mysql-druid-metadatastore, agentichub.employees) → Cloud SQL Auth Proxy sidecar → Dataflow JDBC source connector reads full snapshot (historical load) or timestamp/PK-filtered delta (incremental); raw records written to GCS staging bucket as Avro files |
| Processing | Dataflow Apache Beam pipeline performs: (1) pre-load schema validation against BigQuery target schema, (2) type coercion and null-handling normalization, (3) row deduplication on employee_id, (4) audit metadata enrichment per record; incremental runs filtered by updated_date watermark or employee_id high-watermark boundary |
| Storage | GCS staging bucket (Avro, 60-day lifecycle policy) → BigQuery date-partitioned target table agentichub.employees; separate BigQuery audit_log table captures per-run execution_time, records_extracted, records_loaded, validation_status, and error_details |
| Consumption | BigQuery tables queried via Looker Studio for stakeholder dashboards and SQL clients for ad-hoc analytics; Cloud Logging surfaces audit trail; Data Catalog registers table lineage and schema for governance |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud SQL Auth Proxy + Dataflow JDBC Connector (Apache Beam ReadFromJdbc) | — | Yes |
| Processing | Dataflow (Apache Beam 2.x) | 2.x | Yes |
| Storage | BigQuery (date-partitioned, clustered) + GCS (Avro staging) | — | Yes |
| Orchestration | Cloud Composer (Apache Airflow 2.x) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Dataflow Monitoring UI | — | Yes |
| Iac | Terraform (hashicorp/google provider) | ~> 5.0 | No |

### Pros

- Fully managed, autoscaling Dataflow workers handle both the 5 GB historical load and future volume growth without infrastructure changes
- Apache Beam provides built-in exactly-once semantics and a native BigQuery sink supporting both streaming inserts and file-load modes
- JDBC connector natively supports MySQL Cloud SQL via Cloud SQL Auth Proxy — no custom network configuration required
- Dataflow runner handles retry logic, checkpointing, and fault tolerance out of the box, reducing custom error-handling code
- Cloud Composer provides centralized DAG-based orchestration with ExternalTaskSensor gating incremental runs behind historical load validation
- Dataflow Monitoring UI surfaces step-level throughput metrics, worker utilization, and per-element error attribution for deep observability

### Cons

- Dataflow worker startup latency (2-5 minutes) is significant overhead for small hourly incremental loads processing less than 100 MB delta per cycle
- Dataflow and Cloud Composer combined monthly cost is the highest among all three options for a medium-volume batch workload
- Apache Beam SDK has a steep learning curve; JDBC connector configuration and schema evolution handling require specialist Beam expertise
- Substantially over-engineered for the current 5 GB plus 1 GB per month volume profile — Dataflow horizontal scaling headroom is largely unused
- Stored procedure sp_mysqltobq_load.sql merge logic is harder to integrate with Dataflow's functional pipeline model compared to direct BigQuery SQL execution in Options 2 and 3

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | JDBC batching may produce partial reads if MySQL transactions span batch boundaries; mitigate with REPEATABLE READ isolation level on Cloud SQL connections to ensure consistent snapshots during extraction |
| Scaling | JDBC source is single-threaded per table by default; parallel read requires manual table-splitting strategy using employee_id range partitioning, adding implementation complexity |
| Latency | Dataflow job startup overhead of 2-5 minutes creates SLA risk for hourly incremental windows on small payloads; mitigate with Dataflow FlexRS warm pool pre-warming or reserved workers |
| Cost | Dataflow workers billed per vCPU-hour even during idle pipeline phases; for low-volume hourly runs, monthly Dataflow cost will exceed Cloud Run by an estimated 3-5x based on comparable workload benchmarks |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 9 | 4 | 7 | 6 | **6.20** |

---

## Option 2 — Cloud Run Jobs + Cloud Composer + BigQuery Stored Procedure MERGE (Recommended) ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud SQL MySQL (verizon-data:us-central1:mysql-druid-metadatastore, agentichub.employees, host 34.70.79.163:3306) → Cloud SQL Auth Proxy (Unix socket, IAM authentication) → Cloud Run Job (Python, SQLAlchemy and PyMySQL) reads full snapshot for historical load or timestamp and PK watermark-filtered delta for incremental runs; records serialized to Parquet via PyArrow and uploaded to GCS staging bucket partitioned by load_date |
| Processing | Cloud Run Job (validation stage) executes: (1) pre-load schema validation covering type mismatch detection, null constraint inconsistencies, and field mapping gaps between MySQL and BigQuery schemas; (2) row count reconciliation against MySQL source count for the extraction window; (3) PK uniqueness check on employee_id in staging data; (4) new-column detection with hold-and-alert policy; validated Parquet files loaded to BigQuery staging table via BigQuery Storage Write API; Cloud Composer triggers BigQuery stored procedure sp_mysqltobq_load.sql executing MERGE into production table using composite merge key employee_id and updated_date |
| Storage | GCS staging bucket (Parquet files, 60-day object lifecycle expiration policy aligned with retention SLA) → BigQuery production table agentichub.employees (date-partitioned on updated_date, clustered on employee_id); BigQuery pipeline_audit_log table records execution_timestamp, job_id, records_extracted, records_merged, validation_status, schema_diff_detected, and error_details for every run |
| Consumption | BigQuery production tables consumed by analytics team via Looker Studio pre-built stakeholder dashboard showing load status, record counts, last refresh timestamp, and validation pass or fail per run without engineering involvement; SQL clients for ad-hoc queries; Cloud Monitoring alerts on job failure or schema drift; Cloud Logging provides full audit trail accessible to stakeholders |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Run Jobs + Cloud SQL Auth Proxy (Python 3.11, SQLAlchemy, PyMySQL, PyArrow) | — | Yes |
| Processing | Cloud Run Jobs (schema validation and data quality) + BigQuery MERGE via sp_mysqltobq_load.sql stored procedure | — | Yes |
| Storage | BigQuery (date-partitioned, clustered on employee_id) + GCS (Parquet staging, 60-day lifecycle) | — | Yes |
| Orchestration | Cloud Composer (Apache Airflow 2.x) with ExternalTaskSensor gating incremental DAG on historical load validation SUCCESS state | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio (stakeholder audit dashboard connected to pipeline_audit_log BigQuery table) | — | Yes |
| Iac | Terraform (hashicorp/google provider) | ~> 5.0 | No |

### Pros

- Cloud Run Jobs are billed per vCPU-second of actual execution with zero idle cost, making this the lowest total cost of ownership for hourly and daily batch cadence on medium-volume workloads
- Python-native ETL logic using SQLAlchemy, PyArrow, and the BigQuery Python client is widely understood across data engineering teams, accelerating development and reducing onboarding friction
- BigQuery stored procedure sp_mysqltobq_load.sql executes MERGE natively inside BigQuery's massively parallel SQL engine with zero data movement for upsert logic, directly satisfying the stated merge key requirement
- Cloud SQL Auth Proxy handles IAM-based authentication and TLS 1.3 encryption natively, eliminating manual certificate management and securing the MySQL connection channel
- Cloud Composer ExternalTaskSensor enforces the hard gating constraint: the incremental pipeline DAG cannot trigger until the historical load validation task reaches SUCCESS state in the Airflow metadata database
- GCS Parquet staging provides a replayable, schema-preserving intermediate layer enabling full data recovery by replaying staged files without re-querying MySQL source
- Looker Studio dashboard connected to BigQuery pipeline_audit_log table gives stakeholders self-service visibility into load status, record counts, and validation results without engineering involvement
- New-column detection in the Cloud Run validation stage implements hold-and-alert policy, automatically pausing the load and firing a Cloud Monitoring alert to the pipeline owner for schema review before any data is written
- Cloud Run Jobs support independent CPU and memory configuration per job, allowing the 5 GB historical load job to be tuned with higher resources separately from lightweight incremental delta jobs

### Cons

- Cloud Run Jobs do not provide built-in distributed processing; single-table volumes exceeding approximately 20 GB will require a manual chunking strategy using employee_id range partitioning to avoid memory limits
- PyArrow Parquet serialization adds an intermediate staging step that Dataflow's direct BigQuery sink and Datastream's native connector avoid
- Cloud Composer introduces fixed environment cost of approximately 300 to 400 dollars per month regardless of DAG execution frequency; evaluate shared or Small SKU environments to control this cost
- Custom Python ETL code requires unit testing, container image maintenance, and periodic dependency patching versus fully managed connector services in Options 1 and 3

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Watermark drift risk if updated_date is not consistently populated on all MySQL write paths including bulk inserts and backfills; mitigate by confirming MySQL-side index and application-level enforcement of updated_date on every row modification, and implement a weekly full reconciliation job comparing BigQuery and MySQL record counts |
| Scaling | Cloud Run Job memory cap of 32 GiB per instance is sufficient for the current volume trajectory through approximately year two; implement employee_id range chunking now as a pattern to avoid emergency refactor when single-table volume approaches 20 GB |
| Latency | Cloud Run Job cold start under five seconds for pre-built container images is negligible against hourly and daily cadence windows; no SLA risk identified at current or projected volume |
| Cost | GCS Parquet staging at 60-day retention adds marginal storage cost well under one dollar per month at current volume; Cloud Composer environment fixed cost dominates ongoing spend and should be shared with other pipelines where possible to amortize |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 7 | 8 | 8 | 8 | **7.75** |

---

## Option 3 — Datastream CDC + BigQuery Direct Destination + Cloud Composer Validation Gate

**Pattern:** Hybrid

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Datastream (GCP fully managed CDC service) connects to Cloud SQL MySQL via Private Connectivity or Public IP allowlisting; Datastream replication user reads MySQL binary log (binlog) for continuous change event capture; Datastream built-in backfill feature performs the one-time historical load by reading current table snapshot and writing directly to BigQuery staging dataset without a separate pipeline |
| Processing | Datastream writes change events continuously to BigQuery staging dataset; Cloud Composer DAG triggered on hourly or daily schedule executes: (1) historical load completion sensor; (2) row count and PK uniqueness validation queries against BigQuery staging; (3) BigQuery MERGE stored procedure sp_mysqltobq_load.sql applying composite merge key employee_id and updated_date to production table; (4) audit log INSERT capturing merge run metadata; new-column events from Datastream trigger schema evolution alerts via Cloud Monitoring |
| Storage | BigQuery Datastream staging dataset (raw CDC events, append-only) → BigQuery production table agentichub.employees (date-partitioned on updated_date, clustered on employee_id); GCS used as optional intermediary Datastream destination for replay capability; BigQuery pipeline_audit_log table records per-merge execution metadata |
| Consumption | BigQuery production tables for analytics team; Looker Studio stakeholder dashboard for load status visibility; Datastream console and Cloud Monitoring for pipeline health observability; Cloud Logging for full audit trail |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Datastream (GCP managed CDC for MySQL binary log replication with built-in BigQuery destination) | — | Yes |
| Processing | BigQuery MERGE stored procedure (sp_mysqltobq_load.sql) triggered via Cloud Composer | — | Yes |
| Storage | BigQuery (staging dataset for CDC events + production dataset for analytics) + GCS (optional Datastream intermediary for replay) | — | Yes |
| Orchestration | Cloud Composer (Apache Airflow 2.x) for validation gating, scheduled MERGE execution, and audit logging | 2.x | Yes |
| Monitoring | Cloud Monitoring + Datastream console + Cloud Logging | — | Yes |
| Iac | Terraform (hashicorp/google provider) | ~> 5.0 | No |

### Pros

- Datastream is fully managed and serverless — zero infrastructure to provision, patch, or scale for the ingestion and change capture layer
- Native BigQuery destination in Datastream eliminates custom ingestion code, intermediate staging complexity, and data serialization logic
- Built-in backfill capability handles the one-time historical load without a separate pipeline, reducing initial development effort and eliminating a second ingestion codebase
- Continuous CDC capture future-proofs the architecture for latency tightening without re-architecting if business requirements evolve from daily to near-real-time freshness
- Automatic schema evolution handling in Datastream reduces manual intervention surface area for new column detection events from the MySQL source

### Cons

- Datastream continuous CDC streaming is architecturally mismatched with a batch-only hourly and daily cadence requirement, paying for streaming infrastructure that adds no business value beyond what Option 2 delivers at lower cost
- MySQL binary logging must be explicitly enabled on the Cloud SQL instance, which is not enabled by default and requires an instance configuration change and restart to activate
- Datastream requires a dedicated MySQL replication user with REPLICATION SLAVE and REPLICATION CLIENT privileges, adding IAM and MySQL user management overhead not required in Options 1 or 2
- Gating the MERGE stored procedure on a Cloud Composer schedule introduces artificial batch behavior layered on top of a streaming ingestion layer, negating the primary value proposition of CDC architecture
- Datastream pricing based on GB processed continuously may exceed Cloud Run batch execution cost by 2 to 3 times for a low-churn 1 GB per month incremental profile where most hours produce minimal change volume

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | CDC event ordering issues during network interruptions or Datastream reconnection may cause out-of-order MERGE operations; mitigate with idempotent MERGE logic using updated_date as a tie-breaker and validate final BigQuery row counts against MySQL source after each scheduled MERGE run |
| Scaling | Datastream scales automatically as a fully managed GCP service; BigQuery MERGE performance scales with table size under the BigQuery engine; no scaling risk identified at current or projected volume |
| Latency | MySQL binary log retention gap risk: if binlog expires before Datastream reconnects after an outage, CDC events are permanently lost causing data gaps in BigQuery; mitigate by setting binlog_expire_logs_seconds to a minimum of 172800 seconds (48 hours) on the Cloud SQL instance and configuring Datastream staleness breach alerts at 30-minute threshold |
| Cost | Datastream charges per GB of data processed continuously including heartbeat events and low-change-volume periods; for a 1 GB per month incremental profile with sporadic updates, monthly Datastream cost may exceed Cloud Run batch job cost by 2 to 3 times; cost modeling against actual MySQL change event frequency is required before committing |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 9 | 6 | 9 | 8 | **7.40** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Dataflow (Apache Beam) + Cloud Composer Managed Batch Pipeline | 5 | 9 | 4 | 7 | 6 | **6.20** |
| Cloud Run Jobs + Cloud Composer + BigQuery Stored Procedure MERGE (Recommended) ✅ | 8 | 7 | 8 | 8 | 8 | **7.75** |
| Datastream CDC + BigQuery Direct Destination + Cloud Composer Validation Gate | 6 | 9 | 6 | 9 | 8 | **7.40** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Run Jobs + Cloud Composer + BigQuery Stored Procedure MERGE (Recommended)**
**Weighted Score: 7.75**

**Justification:** Cloud Run Jobs combined with Cloud Composer orchestration and BigQuery stored procedure MERGE is the optimal architecture for this workload. The pay-per-execution Cloud Run model eliminates idle compute cost entirely, making it the most cost-efficient choice for hourly and daily batch cadence on a medium-volume dataset of 5 GB growing at 1 GB per month. Python-native ETL logic using SQLAlchemy and the BigQuery client directly supports the sp_mysqltobq_load.sql MERGE pattern with minimal impedance, reduces time to production, and keeps the operational skill floor accessible. Cloud Composer's ExternalTaskSensor satisfies the hard historical-load gating constraint as a first-class orchestration primitive. The architecture fulfills every functional requirement stated in the brief — full historical load, gated incremental load, schema validation, per-load data quality checks, audit logging, stakeholder dashboard, and new-column hold-and-alert — without over-engineering for capabilities not required by the current workload profile.

**Why highest score:** Achieves the highest weighted score of 7.75 by dominating the two highest-weight scoring dimensions: Cost at 8 out of 10 with weight 0.30 contributing 2.40 points, and Complexity at 8 out of 10 with weight 0.20 contributing 1.60 points, for a combined 4.00 points from the top two dimensions alone. Option 1 contributes only 2.30 points from those same dimensions and Option 3 contributes 2.40 plus 1.20 equals 3.60 points. Cloud Run's pay-per-execution billing model is decisively cheaper than Dataflow worker-hour billing for short-lived medium-volume batch jobs, and Python-native simplicity scores higher on complexity than Datastream's prerequisite MySQL binary log configuration and replication user setup. Remaining dimensions Scalability, Latency, and Operability all score 7 or 8, confirming this option is well-rounded rather than winning on a single dimension at the expense of others.

**Trade-offs accepted:** Three trade-offs are explicitly accepted: (1) Slightly lower theoretical horizontal scalability ceiling compared to Dataflow — acceptable because 1 GB per month growth is well within Cloud Run memory limits and a pre-implemented employee_id range chunking pattern covers edge cases through at least year two. (2) No real-time CDC capability compared to Datastream — acceptable because the requirements explicitly define hourly and daily batch cadence with no sub-minute latency SLA, and no functional requirement references near-real-time freshness. (3) Custom Python ETL code requires testing and maintenance — mitigated by Python's broad ecosystem familiarity within GCP data engineering practices, Cloud Run's serverless operational model eliminating infrastructure maintenance, and the small codebase surface area for a single-table pipeline.

---

## Rejected Options

### Dataflow (Apache Beam) + Cloud Composer Managed Batch Pipeline

Rejected due to the highest operational cost among all three options (Dataflow worker billing combined with Cloud Composer environment costs), the highest implementation complexity (Apache Beam SDK expertise, JDBC connector tuning, schema evolution handling in a functional pipeline model), and startup latency overhead that creates SLA risk for hourly incremental runs. Dataflow's primary value — horizontal distributed processing at terabyte scale — is not realized on a medium-volume 5 GB plus 1 GB per month workload, making this option a poor cost-to-value match for the stated requirements.

### Datastream CDC + BigQuery Direct Destination + Cloud Composer Validation Gate

Rejected because Datastream's continuous CDC model is architecturally mismatched with the explicitly batch-only hourly and daily cadence requirement, resulting in unnecessary streaming infrastructure cost and operational prerequisites for a workload that does not require sub-minute latency. MySQL binary logging prerequisites — enabling binlog on Cloud SQL requiring instance restart, configuring a dedicated replication user with elevated privileges, and enforcing binlog retention policy — introduce pre-deployment configuration risk and operational surface area not present in Option 2. Although Datastream scores higher than Option 2 on Scalability (9 vs. 7) and Latency (9 vs. 8), those dimensions are not constraints for this workload given its batch cadence and medium volume profile. Option 2 achieves a higher weighted score of 7.75 versus 7.40 by optimizing the Cost and Complexity dimensions that carry the greatest combined weight of 0.50 in the scoring model.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Schema Drift | MySQL source schema may evolve through new column additions, data type changes, column renames, or column removals without advance notification to the pipeline team, causing load failures or silent data truncation in the BigQuery target table | Pre-load schema validation in the Cloud Run Job detects type mismatches and missing fields before every load execution; new-column detection triggers the hold-and-alert policy halting the load and notifying the pipeline owner via Cloud Monitoring; BigQuery schema definitions are managed as Terraform resources enabling controlled schema migration through code review and approval workflows |
| Historical Load Data Loss | The one-time full historical load from MySQL at 5 GB may experience a partial failure mid-execution, resulting in an incomplete BigQuery target table without clear visibility into which record ranges were successfully loaded versus which require reprocessing | Implement idempotent chunked extraction partitioned by employee_id range with per-chunk row count validation; store chunk completion state in a BigQuery pipeline_control_log table keyed by chunk range and load_run_id; design re-run logic to resume from the last successfully completed chunk, avoiding re-loading completed ranges and preventing duplicate data |
| Watermark Accuracy and Incremental Completeness | Incremental loads relying solely on updated_date watermark will miss records where updated_date is not refreshed on write, including bulk insert operations, legacy application writes that bypass ORM update logic, and backfilled historical corrections applied directly to the database | Confirm MySQL-side application enforcement of updated_date on all write paths before go-live; implement a weekly reconciliation Cloud Run Job that compares BigQuery and MySQL total record counts and a random sample checksum; alert via Cloud Monitoring when discrepancy exceeds a configurable threshold such as 0.1 percent of total row count |
| Cloud Composer Availability and DAG Failures | Cloud Composer environment downtime, misconfigured DAG dependencies, or Airflow worker exhaustion will cause missed scheduled load windows, resulting in data staleness in BigQuery and potential loss of the incremental gating guarantee | Deploy Cloud Composer with high-availability scheduler configuration; set catchup=True on all pipeline DAGs to automatically backfill missed run windows on recovery; configure Cloud Monitoring uptime checks and DAG failure alert policies with a maximum notification latency of 15 minutes; document manual re-trigger runbook for stakeholders |
| Credential and Access Security | MySQL credentials for user sa connecting to host 34.70.79.163 on port 3306 stored insecurely in environment variables or container images could expose the production Cloud SQL instance to unauthorized access or credential exfiltration | Enforce Secret Manager as the exclusive credential store; Cloud Run Jobs retrieve credentials via Secret Manager API using Workload Identity at runtime with no secrets in images or DAG code; implement 90-day automatic credential rotation via Secret Manager rotation functions; restrict Cloud SQL Auth Proxy service account to roles/cloudsql.client scope only with no direct database admin privileges |

---

## Assumptions

1. MySQL Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore is accessible from GCP compute services via Cloud SQL Auth Proxy using IAM database authentication; no custom VPN or Cloud Interconnect is required
2. The agentichub.employees table contains both an employee_id primary key column and an updated_date timestamp column that is reliably updated on every row modification, sufficient to support watermark-based incremental change tracking without full table re-scans
3. BigQuery target dataset will be provisioned in us-central1 to match the Cloud SQL instance region, minimizing inter-region egress costs and network latency
4. A dedicated GCP service account for Cloud Run Jobs and Cloud Composer will be granted the following IAM roles: roles/cloudsql.client on the Cloud SQL instance, roles/bigquery.dataEditor and roles/bigquery.jobUser on the target project, and roles/storage.objectAdmin on the designated GCS staging bucket
5. GCS staging bucket will have a 60-day object lifecycle expiration rule applied at bucket creation time, consistent with the stated 60-day data retention SLA
6. The BigQuery stored procedure sp_mysqltobq_load.sql defining MERGE logic with composite merge key employee_id and updated_date will be deployed to the target BigQuery dataset before any incremental load runs are permitted
7. Historical load validation is defined as all three conditions passing: BigQuery target row count matches MySQL source row count, zero duplicate employee_id values in the BigQuery target table, and zero unexpected null values in non-nullable fields
8. The incremental pipeline Cloud Composer DAG is hard-gated via ExternalTaskSensor referencing the historical load validation task; the incremental DAG cannot enter a running state until the historical load validation task registers SUCCESS in the Airflow metadata database
9. New column detection policy is hold-and-alert: if the Cloud Run validation stage detects a column present in the MySQL source schema that is absent from the registered BigQuery target schema, the load halts before writing any data, a Cloud Monitoring alert fires to the pipeline owner, and no auto-mapping or schema mutation occurs without explicit approval
10. Data sensitivity classification has not been provided; this architecture assumes GCP default encryption at rest with AES-256 and in transit with TLS 1.2 or higher; CMEK, BigQuery column-level security, and VPC Service Controls perimeter will be added post-classification if the employees table is confirmed to contain PII or regulated data
11. MySQL credentials for the service account user sa will be stored in Secret Manager and accessed by Cloud Run Jobs at runtime via the Secret Manager API; no credentials will be embedded in container images, environment variables, or source code
12. This initiative is currently in draft pending stakeholder review by Shruthi B; architecture decisions documented here may be revised following stakeholder feedback before implementation begins

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Incremental pipeline Cloud Composer DAG is hard-gated via ExternalTaskSensor and cannot trigger until historical load validation task reaches SUCCESS state | functional_requirements[3]: Gate incremental loads so they cannot begin until the full historical load has been validated and confirmed complete | — | 5 GB one-time historical load baseline |
| Incremental change tracking uses updated_date timestamp watermark and employee_id primary key high-watermark; full table re-scans are prohibited | constraints.technical_limitations: Incremental loads must not begin until historical load validation has passed; change tracking must use timestamps or primary keys — full table re-scans are not permitted | batch — hourly or daily per-table cadence | 1 GB per month incremental growth |
| MERGE upsert logic uses composite merge key of employee_id and updated_date executed via BigQuery stored procedure sp_mysqltobq_load.sql | assumptions[1]: Merge key for upsert/merge operations is employee_id and updated_date, executed via stored procedure sp_mysqltobq_load.sql; functional_requirements[9]: Apply merge key logic using employee_id and updated_date for upsert/merge operations via stored procedure sp_mysqltobq_load.sql | — | — |
| GCS staging bucket applies 60-day object lifecycle expiration policy; BigQuery table partition expiration aligned to same 60-day window | non_functional.sla: data retention period is 60 days; assumptions[2]: Data retention period is 60 days | — | — |
| Pre-load schema validation stage in Cloud Run Job checks type mismatches, null constraint inconsistencies, and field mapping gaps before every load execution | functional_requirements[4]: Implement pre-load schema validation that detects type mismatches, null handling inconsistencies, and field mapping issues between MySQL and BigQuery schemas | — | — |
| New column detection policy is hold-and-alert: load halts and Cloud Monitoring alert fires when unrecognized columns appear in MySQL source schema | functional_requirements[5]: Define and implement a strategy for handling new columns that appear in the MySQL source (e.g., alert and hold, or auto-map with review) | — | — |
| BigQuery pipeline_audit_log table captures execution_timestamp, job_id, records_extracted, records_merged, validation_status, and error_details for every load run | functional_requirements[7]: Maintain audit logs for all load executions capturing execution time, record counts, validation results, and any errors | — | — |
| Looker Studio dashboard connected to BigQuery pipeline_audit_log table provides stakeholder-facing load status visibility without requiring engineering team involvement | functional_requirements[8]: Provide stakeholder visibility into load success through accessible logs or a dashboard without requiring engineering involvement | — | — |
| Cloud Run Jobs selected over Dataflow for batch extraction and validation given medium volume and batch-only cadence requirement | data_requirements.volume: 5 GB initial load; growth rate of 1 GB per month; non_functional.scalability: Architecture must scale to support ongoing 1 GB per month data growth beyond the 5 GB initial baseline | batch — hourly or daily per-table cadence | 5 GB baseline growing at 1 GB per month |

---

## Open Questions — Action Required

1. Latency SLA not specified: no maximum acceptable data lag is defined for either hourly or daily cadence tables. If any table requires near-real-time freshness of under five minutes, Option 3 Datastream should be revisited and the pattern_type classification updated from batch to hybrid. Confirm acceptable lag per table with Shruthi B before architecture is finalized.
2. Table expansion scope: requirements identify a single source table agentichub.employees. If additional tables in agentichub or other databases on the Cloud SQL instance will be onboarded, the architecture must account for per-table watermark column identification, schema validation configuration registries, Composer DAG parameterization by table, and a table onboarding runbook. Confirm the complete agreed-upon table list before implementation begins.
3. Data sensitivity classification: no classification such as PII, PCI-DSS scope, or internal confidential has been provided for the employees table. If employee records contain personally identifiable information including names, contact details, national identifiers, or compensation data, CMEK encryption, BigQuery column-level security policies, and a VPC Service Controls perimeter are required and must be designed before the pipeline is deployed to production.
4. Budget envelope: no budget constraint or approved spend range is specified. The Cloud Composer environment at approximately 300 to 400 dollars per month in fixed environment cost is the dominant ongoing expense in this architecture. Confirm whether a shared Cloud Composer environment exists in the target project, whether a dedicated environment is in scope, or whether Cloud Composer Small SKU should be evaluated to minimize fixed costs for a single-pipeline deployment.
5. Schema validation failure behavior for type mismatches: requirements specify hold-and-alert for new columns but do not define behavior when a type mismatch or null constraint violation is detected in pre-load validation. Confirm whether type mismatch should halt the load and alert (safe default preventing silent data corruption) or log-and-continue with type coercion (faster recovery but carries silent corruption risk). This decision must be made before the validation stage is coded.
6. sp_mysqltobq_load.sql current state: the stored procedure is referenced in requirements as the MERGE execution vehicle but its current state is not confirmed as existing in BigQuery, in development, or to be created as part of this initiative. Clarify ownership, the target BigQuery dataset and project for deployment, and whether procedure creation is in scope for this pipeline engagement.
7. Cloud SQL binary logging and connection capacity: confirm that the Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore has sufficient max_connections headroom to absorb Cloud Run Job connections during the 5 GB historical load and peak hourly incremental windows without impacting concurrent production MySQL workloads on the same instance.
