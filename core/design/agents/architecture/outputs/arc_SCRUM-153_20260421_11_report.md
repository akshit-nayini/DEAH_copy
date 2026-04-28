# Architecture Decision Document — 5gcore

| Field | Value |
|---|---|
| **Project** | 5gcore |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Batch |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Cloud SQL Export to GCS → BigQuery Load Job → Stored Procedure MERGE (Cloud Composer Orchestrated)
>
> **Why:** Option 2 is the optimal architecture for the 5gcore employees pipeline given the medium data volume (5 GB initial, ~1 GB/month growth), daily batch cadence, single-source single-table scope, and strong operability and stakeholder-visibility requirements. It uses exclusively GCP-native managed services with no custom distributed compute engine, keeping cost, complexity, and operational burden to a minimum while fully satisfying all functional, data quality, audit, SLA, and retention requirements defined in the specification.
>
> **Score:** 7.85 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2 ✅ | Option 3  |
|---|---||---||---|
| **Name** | Dataflow JDBC Beam Pipeline with Cloud Composer Orchestration | Cloud SQL Export to GCS → BigQuery Load Job → Stored Procedure MERGE (Cloud Composer Orchestrated) | Datastream CDC Replication + BigQuery Direct Destination + Cloud Composer Validation Layer |
| **Pattern** | Batch | Batch | Hybrid |
| **Processing** | Apache Beam 2.x on Cloud Dataflow (inline schema-validation transforms, watermark-based incremental filter, BigQuery staging write) | BigQuery Load Jobs (GCS → BQ staging table, free for GCS-sourced loads) + BigQuery Stored Procedure sp_mysqltobq_load.sql (serverless MERGE upsert on employee_id + updated_date composite key) | BigQuery Stored Procedure sp_mysqltobq_load.sql (MERGE from Datastream CDC change table to analytical target) + Cloud Composer validation tasks (schema check, row count reconciliation, PK uniqueness) |
| **Storage** | BigQuery (target table + staging table + audit log table) + GCS (Dataflow staging and audit log bucket) | BigQuery (target table + staging table + audit log table, 60-day dataset expiry) + GCS (staging bucket with 3-day lifecycle) | BigQuery (Datastream CDC destination dataset + analytical target table + audit log table) |
| **Weighted Score** | **6.80** | **7.85**  ✅ | **6.25** |

---

## Option 1 — Dataflow JDBC Beam Pipeline with Cloud Composer Orchestration

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer triggers a Dataflow Flex Template job; Dataflow reads the employees table from Cloud SQL MySQL via JDBC over a Cloud SQL Auth Proxy sidecar, parallelising reads across configurable worker count |
| Processing | Apache Beam pipeline performs inline schema validation (field name, data type, null-constraint, and new-column-addition checks); on full load it writes the entire dataset to a BigQuery staging table; on incremental load it filters by an updated_date watermark before writing to staging; stored procedure sp_mysqltobq_load.sql is then invoked via BigQuery Jobs API to MERGE staging into the target table on composite key (employee_id, updated_date), enforcing upsert semantics and deduplication |
| Storage | BigQuery target table verizon-data.verizon_data_dea.employees (date-partitioned on updated_date, clustered on employee_id, 60-day partition expiry via dataset default_table_expiration_ms); GCS bucket used for Dataflow staging artefacts and structured JSONL audit logs; BigQuery audit log table verizon_data_dea.pipeline_audit_log |
| Consumption | Analysts query verizon_data_dea.employees directly via BigQuery Studio or connected BI tools; stakeholders access pipeline health via Cloud Monitoring dashboards and a Looker Studio report backed by the BigQuery audit log table |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Dataflow Flex Template with JDBC source (Cloud SQL Auth Proxy sidecar connector) | — | Yes |
| Processing | Apache Beam 2.x on Cloud Dataflow (inline schema-validation transforms, watermark-based incremental filter, BigQuery staging write) | — | Yes |
| Storage | BigQuery (target table + staging table + audit log table) + GCS (Dataflow staging and audit log bucket) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x — DataflowStartFlexTemplateOperator, BigQueryInsertJobOperator) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Alerting Policies (email/PagerDuty channels) + Looker Studio (stakeholder dashboard) | — | Yes |
| Iac | Terraform (google provider: Dataflow Flex Template GCS artefact, Composer environment, BigQuery datasets/tables, GCS buckets, IAM bindings, Monitoring alert policies) | — | No |

### Pros

- Apache Beam provides composable, in-pipeline schema validation and data quality transforms within the execution graph, avoiding external pre-load validation scripts
- Dataflow autoscaling handles the initial 5 GB historical load and accommodates the 1 GB/month growth trajectory without pipeline redesign
- Cloud SQL Auth Proxy integration is natively supported within GCP Dataflow templates, minimising custom connectivity code
- Flex Templates allow parameterised execution (full vs incremental mode) from a single reusable artefact stored in GCS and versioned in source control
- Dataflow Shuffle Service offloads memory-intensive join and sort operations, protecting pipeline stability under large incremental windows
- Full separation of ingestion, transformation, and merge stages provides independently auditable pipeline steps

### Cons

- Operational complexity is highest of the three options: team requires Apache Beam and Dataflow expertise to author, debug, tune, and operate pipeline code
- Dataflow worker cold-start latency (2–4 minutes) adds fixed overhead to every daily job regardless of data volume, disproportionate for a single-table medium-volume workload
- Dataflow per-vCPU-hour billing significantly exceeds the cost of BigQuery-native load jobs for a 5 GB daily batch at current and projected volume
- Watermark-based incremental filtering requires monotonically increasing updated_date values; any back-dated updates in MySQL will be silently missed without additional logic
- MERGE stored procedure execution must be triggered as a separate Airflow task after Dataflow writes to staging, creating a sequential dependency that complicates failure recovery

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Schema drift in MySQL not detected between Dataflow job runs may allow structurally incompatible records to reach BigQuery staging before the MERGE executes; Beam schema enforcement requires pipeline redeployment to accommodate new source fields |
| Scaling | Dataflow autoscaling has a configurable maximum worker cap; sustained high-growth months that exceed provisioned worker ceiling will increase job duration and may breach daily SLA windows |
| Latency | Worker provisioning cold-start means every job incurs a 2–4 minute overhead irrespective of payload size; acceptable under daily cadence but a hard constraint if SLA tightens to hourly |
| Cost | Over-provisioned worker parallelism for small daily incremental payloads (post-initial-load) will inflate per-run compute costs without corresponding throughput benefit unless worker count is dynamically tuned |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 9 | 5 | 7 | 7 | **6.80** |

---

## Option 2 — Cloud SQL Export to GCS → BigQuery Load Job → Stored Procedure MERGE (Cloud Composer Orchestrated) ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer DAG triggers Cloud SQL Admin API to export the employees table from the agentichub database on instance verizon-data:us-central1:mysql-druid-metadatastore to a dated GCS prefix (gs://verizon-5gcore-staging/employees/YYYY-MM-DD/) in CSV format with UTF-8 encoding; for incremental runs, a SQL WHERE clause on updated_date restricts the export to the delta window since the last successful load; Cloud SQL Admin API export is a server-side GCP operation requiring no Cloud SQL Auth Proxy |
| Processing | Cloud Composer executes sequential tasks: (1) pre-load schema validation compares MySQL INFORMATION_SCHEMA columns against the BigQuery staging table schema, checking field names, data types, nullability, and detecting new column additions — any mismatch blocks execution and raises a Cloud Monitoring alert; (2) BigQuery load job imports GCS CSV into transient staging table verizon_data_dea.employees_staging; (3) row count reconciliation task executes COUNT(*) against MySQL source and BigQuery staging and compares results, blocking progression on mismatch; (4) stored procedure sp_mysqltobq_load.sql is invoked via BigQuery Jobs API to MERGE staging into target table verizon_data_dea.employees on composite key (employee_id, updated_date), enforcing upsert semantics and deduplication; (5) primary key uniqueness check verifies no duplicate employee_id values exist in the target post-MERGE; (6) structured audit log record is written to verizon_data_dea.pipeline_audit_log capturing load type, row counts, validation outcomes, and execution timestamp |
| Storage | Primary target: BigQuery table verizon-data.verizon_data_dea.employees (date-partitioned on updated_date, clustered on employee_id); BigQuery dataset verizon_data_dea configured with default_table_expiration_ms = 5184000000 (60 days) enforcing the retention policy; GCS staging bucket with 3-day object lifecycle deletion policy; BigQuery audit log table verizon_data_dea.pipeline_audit_log with independent 365-day retention for compliance |
| Consumption | Analysts query verizon_data_dea.employees directly via BigQuery Studio or connected BI tools; stakeholders access a Looker Studio dashboard connected to verizon_data_dea.pipeline_audit_log for self-serve pipeline health visibility (load status, row counts, last successful run timestamp, and failure history) without engineering involvement |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud SQL Admin API export (server-side GCS export via Cloud Composer CloudSQLExportOperator) | — | Yes |
| Processing | BigQuery Load Jobs (GCS → BQ staging table, free for GCS-sourced loads) + BigQuery Stored Procedure sp_mysqltobq_load.sql (serverless MERGE upsert on employee_id + updated_date composite key) | — | Yes |
| Storage | BigQuery (target table + staging table + audit log table, 60-day dataset expiry) + GCS (staging bucket with 3-day lifecycle) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x — CloudSQLExportOperator, BigQueryInsertJobOperator, BigQueryCheckOperator, ExternalTaskSensor for historical load gate) | — | Yes |
| Monitoring | Cloud Monitoring (metric-based alerting on Composer task failures and schema validation alerts) + Cloud Logging (structured pipeline execution logs) + Looker Studio (stakeholder self-serve health dashboard backed by pipeline_audit_log) | — | Yes |
| Iac | Terraform (google provider: BigQuery dataset with expiry config + tables, GCS buckets with lifecycle rules, Composer 2 environment, IAM bindings for service accounts, Cloud Monitoring alert policies and notification channels) | — | No |

### Pros

- Zero custom distributed compute engine required: Cloud SQL export and BigQuery load jobs are fully server-side GCP operations with no worker provisioning overhead or startup latency
- Lowest cost profile of the three options: Cloud SQL Admin API export is included in Cloud SQL pricing, BigQuery load jobs sourced from GCS are free, and only Composer environment runtime and BQ storage or query costs apply
- Stored procedure sp_mysqltobq_load.sql executes natively inside BigQuery's serverless compute engine, co-locating MERGE logic with storage and eliminating separate compute layer costs
- Cloud Composer Airflow operators (CloudSQLExportOperator, BigQueryInsertJobOperator, BigQueryCheckOperator) provide first-class GCP integration with built-in retry semantics, SLA miss alerting, and task-level audit trails
- Pre-load schema validation and post-load row count reconciliation are implemented as native SQL tasks callable from Airflow without additional frameworks or runtime dependencies
- Historical load gate is natively implementable via Airflow ExternalTaskSensor or XCom-based DAG branching, providing a hard block on incremental execution until full load validation passes
- Looker Studio dashboard connected directly to BigQuery pipeline_audit_log delivers zero-engineering stakeholder visibility into pipeline health, load success/failure history, and row count metrics
- 60-day retention enforced automatically via BigQuery dataset default_table_expiration_ms and GCS lifecycle rules with no recurring operational toil
- Architecture is fully reproducible and auditable via Terraform IaC with no proprietary pipeline runtime to manage

### Cons

- Cloud SQL Admin API export does not guarantee point-in-time snapshot consistency for tables under active write load; rows written during the export window may be included or excluded non-deterministically without a read lock or read replica
- Incremental delta extraction depends entirely on accurate, monotonically increasing updated_date values in MySQL; hard-deleted rows are not captured and will persist in BigQuery until the 60-day retention policy expires
- GCS staging introduces an intermediate file artefact that requires lifecycle management and adds sequential latency compared to a direct database-to-BigQuery read path
- Cloud Composer 2 environment incurs a minimum cost baseline even when idle; for a single daily DAG at this data volume, a Cloud Scheduler + Cloud Functions approach could reduce infrastructure cost further, though at the expense of orchestration features
- CSV export from Cloud SQL has limited control over NULL representation, boolean encoding, and datetime formatting; explicit load configuration (null_marker, quote, encoding) must be aligned between Cloud SQL export settings and BigQuery load job schema

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | CSV delimiter or encoding conflicts in free-text employee fields (e.g., names with commas or special characters) could silently corrupt records during BigQuery load; mitigation: enforce UTF-8 encoding, use a non-conflicting delimiter (pipe-separated), or switch to Avro export format which is schema-embedded and encoding-safe |
| Scaling | Cloud SQL Admin API export is single-threaded per export operation; as the employees table grows beyond several tens of GB, export duration may approach daily SLA windows; mitigation: switch to partitioned date-range exports or Avro format as volume exceeds 20 GB |
| Latency | End-to-end pipeline executes sequential steps (export → GCS write → BQ load → schema validation → row count check → MERGE → audit log write); total elapsed time for 5 GB is estimated at 15–30 minutes, well within daily SLA, but would require optimisation if cadence shifts to hourly |
| Cost | Repeated full historical reloads triggered by schema fixes or re-initialisations will incur Cloud SQL export and BigQuery load costs for the full 5 GB dataset each time; mitigation: gate full reloads behind a manual approval task in Cloud Composer to prevent accidental re-execution |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 9 | 7 | 8 | 6 | 9 | **7.85** |

---

## Option 3 — Datastream CDC Replication + BigQuery Direct Destination + Cloud Composer Validation Layer

**Pattern:** Hybrid

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Datastream stream configured with MySQL as source (Cloud SQL verizon-data:us-central1:mysql-druid-metadatastore, binlog_format=ROW required) and BigQuery as direct destination; initial backfill executes a full historical snapshot of the employees table without a separate export pipeline; ongoing INSERT and UPDATE change events are replicated continuously to a Datastream-managed BigQuery change table in a designated CDC destination dataset |
| Processing | Cloud Composer DAG runs on daily schedule to execute: (1) schema validation comparing MySQL INFORMATION_SCHEMA against the Datastream BigQuery destination schema; (2) invocation of stored procedure sp_mysqltobq_load.sql to MERGE from the Datastream change table into the analytical target table verizon_data_dea.employees on (employee_id, updated_date) composite key; (3) post-MERGE row count reconciliation between MySQL and the BigQuery target; (4) primary key uniqueness check on employee_id; (5) structured audit log write to pipeline_audit_log; Datastream handles CDC event ordering and deduplication natively via internal sequence numbers |
| Storage | BigQuery Datastream CDC destination dataset (raw change events, schema managed by Datastream service); BigQuery analytical target table verizon-data.verizon_data_dea.employees (date-partitioned, 60-day expiry); BigQuery audit log table verizon_data_dea.pipeline_audit_log (365-day retention) |
| Consumption | Analysts consume verizon_data_dea.employees via BigQuery Studio; stakeholders access Looker Studio dashboard backed by pipeline_audit_log; the Datastream CDC destination table is optionally available as a low-latency data source for future near-real-time use cases |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Datastream (MySQL CDC → BigQuery direct destination, binlog-based row-level replication with native backfill) | — | Yes |
| Processing | BigQuery Stored Procedure sp_mysqltobq_load.sql (MERGE from Datastream CDC change table to analytical target) + Cloud Composer validation tasks (schema check, row count reconciliation, PK uniqueness) | — | Yes |
| Storage | BigQuery (Datastream CDC destination dataset + analytical target table + audit log table) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) for daily validation, MERGE trigger, and audit; Datastream service manages continuous replication autonomously | — | Yes |
| Monitoring | Cloud Monitoring (Datastream stream health metrics: throughput, latency, error rate) + Cloud Logging + Alerting Policies + Looker Studio (stakeholder dashboard) | — | Yes |
| Iac | Terraform (google provider: Datastream connection profiles, stream configuration, BigQuery datasets/tables, Composer environment, IAM bindings, Monitoring alert policies) | — | No |

### Pros

- Datastream CDC with BigQuery direct destination eliminates GCS intermediate staging entirely, reducing pipeline steps and potential intermediate failure points
- Binlog-based replication captures all row-level changes including high-frequency updates without polling, making the architecture forward-compatible if analytics SLA tightens below daily
- Datastream native backfill handles the initial full historical load without requiring a separate export or load pipeline artefact
- Near-real-time data availability in the Datastream CDC destination dataset enables future low-latency analytical use cases not possible under Options 1 or 2
- Cloud Monitoring Datastream integration provides out-of-the-box stream health, throughput, and error-rate dashboards with minimal configuration

### Cons

- Requires MySQL binary logging (binlog_format=ROW) to be enabled on the Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore; enabling binlog is a non-trivial infrastructure change requiring DBA involvement and a Cloud SQL instance restart with associated downtime
- Datastream incurs continuous per-GB-processed replication billing even during periods of zero change activity, making it structurally more expensive than event-driven batch exports for a low-change-frequency employees table
- Architecture has the highest operational complexity of the three options: Datastream stream management, BigQuery direct destination schema management, and the Cloud Composer validation and MERGE layer are independent failure domains requiring coordinated monitoring across two separate GCP services
- Hard deletes in MySQL are not propagated as BigQuery row deletions via Datastream binlog replication without additional Soft Delete stream configuration and compensating MERGE logic beyond the standard sp_mysqltobq_load.sql
- Datastream BigQuery direct destination manages its own schema evolution independently and may produce schema conflicts with the intended target table schema, requiring careful schema mapping and exclusion rule configuration at stream setup time

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Binlog event replication gaps or duplicated events during Datastream stream pause, resume, or backfill cycles may produce data inconsistencies in the CDC destination table before the daily MERGE executes; Datastream provides at-least-once delivery guarantees, not exactly-once, requiring idempotent MERGE logic |
| Scaling | Datastream replication throughput is bounded by the MySQL binlog read throughput and Cloud SQL instance IOPS limits; high write-frequency operational periods may cause replication lag, delaying data availability for the daily MERGE window and potentially triggering SLA breaches |
| Latency | The daily MERGE job introduces a batch window for the analytical target table despite near-real-time CDC replication in the destination dataset; the primary latency benefit of Datastream is not realised under the current batch MERGE architecture, making its cost premium unjustified |
| Cost | Datastream continuous replication billing combined with Cloud Composer environment costs and BigQuery storage produces the highest total monthly cost of the three options for a low-change-frequency employees table with a confirmed daily batch analytics SLA |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 8 | 4 | 9 | 6 | **6.25** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Dataflow JDBC Beam Pipeline with Cloud Composer Orchestration | 6 | 9 | 5 | 7 | 7 | **6.80** |
| Cloud SQL Export to GCS → BigQuery Load Job → Stored Procedure MERGE (Cloud Composer Orchestrated) ✅ | 9 | 7 | 8 | 6 | 9 | **7.85** |
| Datastream CDC Replication + BigQuery Direct Destination + Cloud Composer Validation Layer | 5 | 8 | 4 | 9 | 6 | **6.25** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud SQL Export to GCS → BigQuery Load Job → Stored Procedure MERGE (Cloud Composer Orchestrated)**
**Weighted Score: 7.85**

**Justification:** Option 2 is the optimal architecture for the 5gcore employees pipeline given the medium data volume (5 GB initial, ~1 GB/month growth), daily batch cadence, single-source single-table scope, and strong operability and stakeholder-visibility requirements. It uses exclusively GCP-native managed services with no custom distributed compute engine, keeping cost, complexity, and operational burden to a minimum while fully satisfying all functional, data quality, audit, SLA, and retention requirements defined in the specification.

**Why highest score:** Option 2 achieves the highest weighted score (7.85) because its cost (9/10) and operability (9/10) ratings — the two dimensions most material to this workload profile — are both the strongest in the field. The low-complexity score (8/10) reflects the complete absence of a distributed compute framework or custom transform runtime. The moderate scalability (7/10) and latency (6/10) scores are appropriate and accepted trade-offs: scalability is more than sufficient for the projected 12-month volume horizon, and a 15–30 minute end-to-end elapsed time is structurally irrelevant under a daily batch SLA.

**Trade-offs accepted:** Accepted: (1) Hard-delete invisibility — rows deleted in MySQL will not be propagated as deletes to BigQuery; this limitation is documented in the data contract and mitigated by the 60-day retention policy and a future soft-delete reconciliation query if required. (2) Export consistency window — the Cloud SQL Admin API export is not guaranteed to be point-in-time consistent under active write load; mitigated by scheduling exports during the agreed low-activity window (02:00–04:00 UTC) or via a Cloud SQL read replica. (3) Single-threaded Cloud SQL export — adequate for current volume but will require architectural revisit at approximately 30–50 GB table size, providing a clear, documented scaling trigger.

---

## Rejected Options

### Dataflow JDBC Beam Pipeline with Cloud Composer Orchestration

Dataflow introduces disproportionate cost and operational complexity for a medium-volume (5 GB initial, ~1 GB/month growth), daily-batch, single-table pipeline. Worker startup overhead, Beam expertise requirements, and per-vCPU billing are not justified by the workload characteristics. Option 2 achieves identical functional outcomes at materially lower cost and complexity using exclusively BigQuery-native load jobs and Cloud SQL export, with no distributed compute engine required.

### Datastream CDC Replication + BigQuery Direct Destination + Cloud Composer Validation Layer

Datastream CDC is architecturally over-engineered for the 5gcore employees pipeline. The workload specifies a daily batch analytics SLA, so Datastream's primary strength — near-real-time low-latency replication — delivers no current business value. The prerequisite of enabling MySQL binary logging on a shared Cloud SQL instance (implied by the druid-metadatastore instance name) is a non-trivial infrastructure risk. Continuous billing for a low-change-frequency table, the highest complexity score of the three options, and the need to extend sp_mysqltobq_load.sql with supplementary delete-handling logic collectively make this option inappropriate for the stated requirements, team profile, and cost constraints.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| PII Data Security | The employees table contains personally identifiable information (names, contact details, employment records). Unrestricted BigQuery dataset access, unencrypted GCS staging files, or over-broad IAM bindings could result in unauthorised data exposure or a compliance violation. | Apply BigQuery column-level security policies (BigQuery Policy Tags) on identified PII fields before pipeline go-live; enforce GCS bucket encryption with CMEK or Google-managed keys; restrict dataset access via IAM to named service accounts and explicitly authorised analyst groups; document data classification and access controls in the security design artefact |
| Schema Drift | MySQL schema changes (new columns, renamed columns, data type widening or narrowing) applied to the employees table without prior notice will cause BigQuery load job failures or silent data corruption if the column-addition handling strategy is not enforced. | Implement automated pre-load schema validation as a blocking Airflow task before every load execution; configure a Cloud Monitoring alert to fire immediately when schema validation detects any mismatch; enforce the documented column-addition handling strategy as a mandatory go-live gate approved by stakeholder yash |
| Cloud SQL Instance Contention | The Cloud SQL instance naming convention (mysql-druid-metadatastore) implies the instance may serve other operational workloads concurrently. Heavy read load from Admin API export operations during peak hours could degrade performance for other consumers of the shared instance. | Schedule Cloud SQL export operations during an agreed low-activity window (e.g., 02:00–04:00 UTC); confirm with the DBA team whether a Cloud SQL read replica should be provisioned for analytics export isolation; add the scheduling window to the SLA documentation |
| Hard Delete Invisibility | Rows physically deleted from the MySQL employees table are not propagated to BigQuery via the CSV export and MERGE approach; deleted employee records will persist in the BigQuery target until the 60-day retention expiry removes them, potentially causing overstated headcount or inaccurate reporting. | Document the hard-delete limitation explicitly in the data contract with analytics consumers; implement a periodic soft-delete reconciliation query (e.g., LEFT JOIN between BigQuery target and MySQL source on employee_id to identify orphaned rows) if delete propagation is confirmed as a business requirement by stakeholder yash |
| Incremental Load Gate Bypass | If the historical load validation gate is misconfigured, bypassed by an operator, or fails silently, incremental loads may execute against an incomplete or structurally invalid BigQuery target, producing incorrect analytical results that are difficult to detect after the fact. | Implement the historical validation gate as a mandatory blocking ExternalTaskSensor in the incremental DAG with no bypass path; record gate status in pipeline_audit_log; require an explicit manual reset task executed by an authorised operator if the gate must be overridden for recovery purposes |
| Audit and Compliance Continuity | Without durable, structured audit logs for every load execution, it is impossible to demonstrate regulatory compliance, reconstruct data lineage, or diagnose data quality issues for PII employee records under an audit or data subject access request. | Enforce audit log writes to verizon_data_dea.pipeline_audit_log as an atomic, non-optional step within the Airflow DAG; configure BigQuery data access audit logs via Cloud Audit Logs to capture all read and write operations on the verizon_data_dea dataset; set pipeline_audit_log table expiration to 365 days independently of the 60-day employees table retention |

---

## Assumptions

1. Cloud SQL Admin API export operations are executed by a dedicated GCP service account holding roles/cloudsql.viewer on the Cloud SQL instance and roles/storage.objectCreator on the GCS staging bucket; no application-level Cloud SQL Auth Proxy is required for server-side Cloud SQL Admin API export calls
2. The stored procedure sp_mysqltobq_load.sql is authored or reviewed as part of this initiative and encapsulates all MERGE, upsert, and deduplication logic for both full-load (insert-overwrite or full merge) and incremental-load (delta merge) execution modes
3. The composite merge key (employee_id + updated_date) is confirmed by the source system owner to uniquely identify each version of an employee record and is sufficient for change detection and deduplication in the MERGE operation
4. BigQuery dataset verizon_data_dea exists in project verizon-data and the pipeline service account holds roles/bigquery.dataEditor on that dataset and roles/bigquery.jobUser on the project
5. 60-day data retention is enforced via BigQuery dataset default_table_expiration_ms = 5184000000 (60 days in milliseconds) applied to the verizon_data_dea dataset, covering the employees target table and staging table; the pipeline_audit_log table is exempted with an independent 365-day retention for compliance purposes
6. Cloud Composer 2 environment will be provisioned in the same GCP project (verizon-data) and region (us-central1) as the Cloud SQL instance and BigQuery dataset to minimise network latency and eliminate cross-region egress charges
7. Stakeholder yash is the designated business owner with sign-off authority for requirements, acceptance criteria, the column-addition handling strategy, and pipeline go-live approval
8. The incremental load cadence is confirmed as daily per the stakeholder-agreed requirement; the architecture natively supports hourly cadence without redesign if the requirement changes
9. A formal column-addition handling strategy document must be produced and approved by stakeholder yash before pipeline go-live; the default behaviour until approval is to block load execution on detection of any new column in MySQL INFORMATION_SCHEMA and raise a Cloud Monitoring alert to the engineering team
10. Employee data is classified as PII; column-level security policies, access control design, and any required masking or tokenisation will be addressed in a separate security design artefact and are out of scope for this architecture decision document
11. A GCS staging bucket (e.g., gs://verizon-5gcore-staging) is created within project verizon-data with Uniform Bucket-Level Access enabled and a 3-day object lifecycle deletion rule applied to the employees/ prefix
12. Terraform is the approved IaC toolchain for provisioning all GCP resources in the verizon-data project and a remote state backend (GCS bucket) is available for state file storage

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud SQL Admin API export to GCS selected over JDBC direct read (Dataflow) for ingestion layer | Source: MySQL Cloud SQL verizon-data:us-central1:mysql-druid-metadatastore; functional requirement: Load employees table into BigQuery; constraint: prefer managed services with no custom compute | daily batch | 5 GB initial, 1 GB/month incremental growth |
| BigQuery stored procedure sp_mysqltobq_load.sql on composite key (employee_id + updated_date) used for all MERGE and upsert operations | Apply stored procedure sp_mysqltobq_load.sql with merge key logic on employee_id and updated_date to upsert records and prevent duplicates | daily batch | — |
| Cloud Composer 2 (Airflow 2.x) selected as orchestration layer for DAG scheduling, task dependency management, and SLA alerting | Implement scheduled incremental loads; configure pipeline monitoring and failure alerting for all scheduled runs; ensure incremental pipeline activates only after full historical load validation | daily batch | — |
| Pre-load schema validation implemented as a mandatory blocking Airflow task executed before every full and incremental load | Perform pre-load schema validation to detect data type mismatches, null violations, field name discrepancies, and new column additions in MySQL; violations must block load completion | — | — |
| Post-load row count reconciliation (MySQL COUNT(*) vs BigQuery staging COUNT(*)) and primary key uniqueness check (COUNTIF of duplicate employee_id) implemented as blocking quality gate tasks | Perform row count reconciliation between MySQL source and BigQuery target after every full and incremental load; verify primary key uniqueness on employee_id post-load; verify null and datatype constraints before marking any load as successful | — | — |
| BigQuery dataset verizon_data_dea configured with default_table_expiration_ms = 5184000000 (60 days in ms) to enforce the retention policy automatically | Enforce 60-day data retention policy on the BigQuery target dataset; 60-day retention policy must be enforced continuously | — | 60-day rolling retention window |
| Looker Studio dashboard connected to BigQuery pipeline_audit_log selected as stakeholder-accessible pipeline health visibility layer | Provide stakeholder-accessible visibility into pipeline health and load success via logs or dashboard without requiring engineering involvement | — | — |
| Structured audit log table verizon_data_dea.pipeline_audit_log with 365-day independent retention created for all load execution records scoped to sp_mysqltobq_load.sql runs | Maintain structured audit logs for every load execution (full and incremental) scoped to sp_mysqltobq_load.sql executions | — | — |
| Incremental DAG gated by Airflow ExternalTaskSensor or XCom flag requiring confirmed successful historical load before first incremental execution is permitted | Ensure incremental pipeline activates only after full historical load validation is confirmed successful; incremental loads must not start until historical validation passes | — | — |
| GCS staging bucket configured with a 3-day object lifecycle deletion policy on the employees/ prefix to control intermediate artefact retention | 60-day retention must be enforced in BigQuery target; no retention requirement specified for GCS staging artefacts — minimum safe retention window of 3 days selected to allow one retry cycle | — | — |
| Terraform selected as IaC toolchain for all GCP resource provisioning including BigQuery dataset and tables, GCS buckets, Composer environment, IAM bindings, and Monitoring alert policies | Constraint: cloud = GCP; preference for reproducible, auditable infrastructure; SCRUM-153 initiative scope requires end-to-end deliverable | — | — |

---

## Open Questions — Action Required

1. Are there specific PII fields in the employees table (e.g., national ID, date of birth, salary, home address) that require column-level masking, tokenisation, or BigQuery Policy Tag enforcement before data can land in the analytical dataset?
2. Has the formal column-addition handling strategy document been drafted and approved by stakeholder yash? This is documented as a hard go-live blocker — what is the target approval date relative to the SCRUM-153 delivery timeline?
3. Is the Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore shared with Apache Druid or other operational workloads? If yes, what is the agreed export window and maximum allowable read load to avoid contention with other consumers?
4. Should hard-deleted employee records in MySQL be propagated as logical deletes to BigQuery? If yes, this requires an additional reconciliation step in the DAG and an extension to the sp_mysqltobq_load.sql merge logic beyond the current specification.
5. What is the confirmed alerting channel for pipeline failure notifications (email group, PagerDuty service, Slack webhook, or Cloud Pub/Sub topic)? This is required to configure Cloud Monitoring alerting policy notification channels before go-live.
6. Is binary logging (binlog_format=ROW) currently enabled on the Cloud SQL instance? This determines whether Option 3 (Datastream CDC) is technically feasible as a future upgrade path without infrastructure changes.
7. Does an existing Cloud Composer 2 environment exist in the verizon-data project that this pipeline can share, or does a new dedicated environment need to be provisioned and accounted for in the cost baseline?
8. Is there an existing Looker Studio workspace, data source, or BI reporting layer within the verizon-data project that the stakeholder pipeline health dashboard should be published to and access-controlled within?
