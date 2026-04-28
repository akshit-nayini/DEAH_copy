# Architecture Decision Document — 5gcore

| Field | Value |
|---|---|
| **Project** | 5gcore |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Hybrid |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Cloud Composer + GCS Staging + BigQuery-Native Stored Procedure Pipeline
>
> **Why:** Option 2 achieves the highest weighted score of 7.45 by delivering the optimal balance across all five scoring dimensions for this specific workload profile. It is the only option that satisfies all three non-negotiable programme requirements simultaneously without bespoke engineering: (1) direct invocation of sp_mysqltobq_load.sql as the MERGE execution layer, (2) native DAG dependency enforcement of the historical-load gate via ExternalTaskSensor, and (3) stakeholder-accessible engineering-independent audit visibility via BigQuery audit tables and Looker Studio. GCS staging provides fault-tolerant retryability that no direct-write architecture can match at this pipeline reliability tier without additional complexity.
>
> **Score:** 7.45 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2 ✅ | Option 3  |
|---|---||---||---|
| **Name** | Dataflow JDBC-Native with Cloud Composer Orchestration | Cloud Composer + GCS Staging + BigQuery-Native Stored Procedure Pipeline | Cloud Scheduler + Cloud Run Jobs + BigQuery-Native Serverless Batch |
| **Pattern** | Hybrid | Hybrid | Batch |
| **Processing** | Apache Beam on Dataflow + BigQuery Stored Procedure | BigQuery LOAD DATA + Stored Procedure sp_mysqltobq_load.sql | BigQuery Storage Write API + Stored Procedure sp_mysqltobq_load.sql |
| **Storage** | BigQuery + GCS (Dataflow artefacts only) | GCS (staging) + BigQuery (verizon_data_dea + verizon_data_audit) | BigQuery (verizon_data_dea + verizon_data_audit) |
| **Weighted Score** | **5.95** | **7.45**  ✅ | **6.95** |

---

## Option 1 — Dataflow JDBC-Native with Cloud Composer Orchestration

**Pattern:** Hybrid

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 triggers Dataflow Flex Template jobs parameterised per table that extract MySQL tables from Cloud SQL (verizon-data:us-central1:mysql-druid-metadatastore) via JDBC connector; full or incremental load mode is selected based on watermark checkpoints persisted in a BigQuery control table. |
| Processing | Apache Beam pipelines on Dataflow apply in-flight schema validation, null checks, and datatype coercion transforms before writing; post-write MERGE logic is executed by invoking sp_mysqltobq_load.sql stored procedure via BigQueryInsertJobOperator in Composer. |
| Storage | BigQuery dataset verizon_data_dea as primary analytical store with 60-day partition expiry; no intermediate GCS staging required; a lightweight GCS bucket holds Dataflow staging artefacts only. |
| Consumption | Looker Studio dashboards backed by BigQuery audit and reconciliation tables; Cloud Monitoring alerting policies notify on Dataflow job failure or data quality threshold breach. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataflow Flex Template (JDBC-to-BigQuery) | 2.59 | Yes |
| Processing | Apache Beam on Dataflow + BigQuery Stored Procedure | 2.59 | Yes |
| Storage | BigQuery + GCS (Dataflow artefacts only) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.9) | 2.9 | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio | — | Yes |
| Iac | Terraform | 1.8 | No |

### Pros

- No GCS staging layer for data rows; direct MySQL-to-BigQuery write path eliminates partial-load state ambiguity
- Dataflow handles parallel table extraction natively, making future TB-scale volume expansion transparent without re-architecture
- In-flight Beam schema validation and datatype coercion intercept bad rows before they land in BigQuery
- Composer ExternalTaskSensor natively enforces the historical-load gate with zero custom state management code

### Cons

- Dataflow Flex Template authoring and JDBC connector tuning introduce significant engineering overhead disproportionate to the 5 GB medium-volume workload
- Dataflow job cold-start latency of 2-4 minutes per job makes hourly micro-batch incremental runs inefficient for small delta volumes
- Dataflow worker VMs billed per vCPU-hour even for short jobs; frequent small incremental runs make this the most expensive option
- JDBC parallelism against Cloud SQL can saturate database connections and requires careful per-table concurrency throttling

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | In-flight Beam transforms may silently drop malformed rows unless dead-letter sinks are explicitly configured; requires additional error pipeline branches beyond the core load path |
| Scaling | JDBC boundary query splitting must be tuned per table; unbounded auto-splitting on large MySQL tables can cause uneven worker distribution and job stalls |
| Latency | Cold-start overhead per Dataflow job means any tightening of the hourly SLA to sub-15-minute windows cannot be met without switching to streaming mode, conflicting with the batch-only requirement |
| Cost | Running Dataflow for 5 GB incremental micro-batches hourly results in a projected monthly Dataflow cost 3-5x higher than equivalent BigQuery-native processing at this data volume |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 4 | 9 | 3 | 8 | 7 | **5.95** |

---

## Option 2 — Cloud Composer + GCS Staging + BigQuery-Native Stored Procedure Pipeline ✅ Recommended

**Pattern:** Hybrid

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 DAGs execute Python operators that connect to Cloud SQL MySQL (agentichub) via Cloud SQL Auth Proxy and pymysql, extracting full or incremental record sets to a dedicated GCS staging bucket as delimited CSV; watermark checkpoints (max updated_date per table) are persisted in a BigQuery audit control table to drive incremental change detection. |
| Processing | BigQuery LOAD DATA from GCS CSV into a raw staging table, followed by invocation of sp_mysqltobq_load.sql stored procedure via BigQueryInsertJobOperator; the stored procedure executes MERGE on employee_id and updated_date keys enforcing upsert semantics; post-load Composer tasks run row count reconciliation, PK uniqueness checks, null constraint, and datatype assertions. |
| Storage | GCS bucket (gcs://5gcore-staging/agentichub/) for transient CSV staging files with object lifecycle policy auto-deleting after confirmed load; BigQuery dataset verizon_data_dea as analytical store with 60-day partition expiry on the employees table; BigQuery audit dataset verizon_data_audit hosting load_log, schema_drift_log, and reconciliation_log tables. |
| Consumption | Looker Studio dashboards connected directly to BigQuery verizon_data_audit tables enabling stakeholder self-service visibility into load history, record counts, schema drift events, and validation outcomes without engineering involvement; Cloud Monitoring alerting policies trigger email or webhook notifications on DAG failure, data quality assertion failures, or row count mismatches exceeding defined thresholds. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud SQL Auth Proxy + pymysql via Composer PythonOperator | — | Yes |
| Processing | BigQuery LOAD DATA + Stored Procedure sp_mysqltobq_load.sql | — | Yes |
| Storage | GCS (staging) + BigQuery (verizon_data_dea + verizon_data_audit) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.9) | 2.9 | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio | — | Yes |
| Iac | Terraform | 1.8 | No |

### Pros

- Directly aligns with the stated stored procedure requirement (sp_mysqltobq_load.sql): no translation layer or reimplementation needed; the stored proc drives all MERGE logic exactly as designed by the programme
- Cloud Composer ExternalTaskSensor natively enforces the historical-load gate, blocking incremental DAG activation until all three validation checkpoints pass and the BigQuery control flag historical_load_complete is set to TRUE
- GCS staging decouples extraction from loading: on any failure, individual stages retry independently without re-querying the MySQL source, protecting the production Cloud SQL instance
- BigQuery audit tables combined with Looker Studio dashboards provide fully stakeholder-accessible, engineering-independent visibility into load history, record counts, schema drift, and data quality outcomes — satisfying a primary non-negotiable programme requirement
- Cost-efficient at medium volume: GCS storage cost is negligible, BigQuery on-demand pricing for 5 GB plus 1 GB/month growth is minimal, and a Composer small environment is predictable and well-understood
- Hourly and daily scheduling cadences are natively supported via Composer DAG schedule_interval configured independently per table
- Schema drift detection is implementable as a dedicated pre-load Composer task comparing MySQL INFORMATION_SCHEMA against the registered BigQuery schema, with structured logging to schema_drift_log and a documented additive vs destructive column handling strategy

### Cons

- Cloud Composer incurs a fixed baseline cost of approximately $300-600 per month for a small environment regardless of pipeline execution frequency
- GCS staging introduces an intermediate hop and requires a GCS object lifecycle policy to prevent unbounded staging file accumulation over time
- Cloud SQL Auth Proxy must be reachable from Composer workers, requiring VPC network peering or Private Service Connect configuration confirmed before deployment
- CSV is not a schema-safe serialisation format; datatype fidelity for numeric precision, NULL representation, and special characters must be explicitly enforced at the LOAD DATA stage or via post-load constraint checks in the stored procedure

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | CSV export from MySQL may silently misrepresent NULL values, numeric precision, or delimiter-containing strings; mitigation is to enforce explicit field delimiters, quoting rules, and escape characters in the extraction query and validate post-load datatype compliance in the stored procedure |
| Scaling | At 1 GB/month sustained growth the architecture scales comfortably for three to five years before Composer or BigQuery load patterns require re-evaluation; GCS staging scales linearly at negligible cost |
| Latency | CSV extraction plus GCS staging adds five to ten minutes of pipeline overhead per run; this is acceptable given the hourly SLA has sufficient headroom but would not be acceptable if sub-minute latency requirements emerge in future |
| Cost | Cloud Composer fixed environment cost becomes proportionally expensive if the pipeline is paused or table count remains low; this is mitigated by Composer 2 autoscaling workers configured with minimum zero workers during idle periods |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 8 | 7 | 7 | 9 | **7.45** |

---

## Option 3 — Cloud Scheduler + Cloud Run Jobs + BigQuery-Native Serverless Batch

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Scheduler triggers Cloud Run Jobs on hourly or daily schedules per table; containerised Python using SQLAlchemy and the Cloud SQL Python Connector extracts full or incremental record sets directly from Cloud SQL MySQL; a BigQuery control table persists watermark checkpoints per table to drive incremental change detection. |
| Processing | BigQuery Storage Write API receives direct writes from the Cloud Run Job container; sp_mysqltobq_load.sql stored procedure is invoked via BigQuery API call within the job post-extraction, executing MERGE on employee_id and updated_date; post-load row count reconciliation and PK uniqueness validation run as a sequential step within the same job. |
| Storage | BigQuery dataset verizon_data_dea as analytical store with 60-day partition expiry; BigQuery audit dataset verizon_data_audit stores load_log and validation_log tables; no GCS staging layer. |
| Consumption | Looker Studio dashboards over BigQuery audit tables; Cloud Monitoring alerting policies on Cloud Run Job failure; Cloud Logging captures structured JSON execution logs per job run. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Run Jobs (Python + SQLAlchemy + Cloud SQL Python Connector) | — | Yes |
| Processing | BigQuery Storage Write API + Stored Procedure sp_mysqltobq_load.sql | — | Yes |
| Storage | BigQuery (verizon_data_dea + verizon_data_audit) | — | Yes |
| Orchestration | Cloud Scheduler + Cloud Run Jobs | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio | — | Yes |
| Iac | Terraform | 1.8 | No |

### Pros

- Serverless architecture eliminates always-on infrastructure cost; Cloud Run Jobs are billed only for actual vCPU-seconds of execution, making this the lowest-cost option for a medium-volume batch workload
- BigQuery Storage Write API provides direct transactional writes with exactly-once semantics, eliminating the GCS staging hop and associated lifecycle management overhead
- Simplified service dependency chain reduces the attack surface for configuration drift, credential rotation, and inter-service IAM management
- Cloud Run Job containers scale horizontally per table for parallel extraction and have sub-two-second cold-start latency, negligible for hourly batch cadences

### Cons

- Cloud Scheduler has no native DAG dependency semantics; enforcing the historical-load gate that blocks incremental loads until validation passes requires custom bespoke state management via a BigQuery control flag plus a Cloud Run gating job, introducing orchestration logic that Composer provides out of the box
- No visual workflow UI for operations or engineering teams; troubleshooting failed runs requires navigating Cloud Logging and Cloud Run job history, which is less intuitive and slower than Composer's Airflow task graph view
- Complex multi-step pipeline logic (extract, validate, load, reconcile, audit) must be encoded within a single Cloud Run container image, reducing separation of concerns and increasing image maintenance overhead as pipeline logic evolves
- Cross-table dependency management for the historical load gate across multiple tables requires custom fan-out and aggregation logic with no platform-native equivalent to Composer's ExternalTaskSensor

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | BigQuery Storage Write API direct writes bypass the GCS staging checkpoint; if a Cloud Run Job fails mid-stream, partial data may land in BigQuery unless pending write streams are explicitly committed or aborted via the Storage Write API commit protocol, requiring careful stream lifecycle management in the container code |
| Scaling | Cloud Scheduler has a project-level limit of 4096 jobs; as the table inventory expands beyond the current single-table scope, per-table per-cadence scheduler proliferation and management complexity grows without a native fan-out orchestration layer |
| Latency | Cloud Scheduler precision is plus-or-minus one minute; combined with container pull latency, hourly runs may experience minor schedule jitter; not a risk at the current SLA but requires monitoring if cadence tightens |
| Cost | While lowest in infrastructure execution cost, the additional engineering effort required to build and maintain a custom historical gate, bespoke orchestration state, and cross-table coordination partially offsets the infrastructure savings relative to Composer's managed orchestration layer |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 9 | 6 | 6 | 7 | 5 | **6.95** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Dataflow JDBC-Native with Cloud Composer Orchestration | 4 | 9 | 3 | 8 | 7 | **5.95** |
| Cloud Composer + GCS Staging + BigQuery-Native Stored Procedure Pipeline ✅ | 7 | 8 | 7 | 7 | 9 | **7.45** |
| Cloud Scheduler + Cloud Run Jobs + BigQuery-Native Serverless Batch | 9 | 6 | 6 | 7 | 5 | **6.95** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Composer + GCS Staging + BigQuery-Native Stored Procedure Pipeline**
**Weighted Score: 7.45**

**Justification:** Option 2 achieves the highest weighted score of 7.45 by delivering the optimal balance across all five scoring dimensions for this specific workload profile. It is the only option that satisfies all three non-negotiable programme requirements simultaneously without bespoke engineering: (1) direct invocation of sp_mysqltobq_load.sql as the MERGE execution layer, (2) native DAG dependency enforcement of the historical-load gate via ExternalTaskSensor, and (3) stakeholder-accessible engineering-independent audit visibility via BigQuery audit tables and Looker Studio. GCS staging provides fault-tolerant retryability that no direct-write architecture can match at this pipeline reliability tier without additional complexity.

**Why highest score:** The operability score of 9/10 reflects best-in-class stakeholder visibility through BigQuery audit tables and Looker Studio, which is a primary non-negotiable requirement explicitly called out in the business context for stakeholder-led review. The cost score of 7/10 reflects Composer's predictable pricing being proportionate to medium-volume hourly batch workloads. Scalability of 8/10 reflects BigQuery's serverless engine absorbing all projected data growth to several hundred GB without re-architecture. No single scoring dimension is critically sacrificed; Option 2 achieves the best aggregate balance across all five weighted criteria and is the only option where each dimension scores 7 or above.

**Trade-offs accepted:** Cloud Composer's fixed baseline cost of approximately $300-600 per month is accepted in exchange for native workflow dependency management, ExternalTaskSensor-based historical gate enforcement, and the operational maturity of the Airflow UI for pipeline troubleshooting. GCS staging overhead of five to ten minutes per run is accepted given the hourly SLA has ample headroom. CSV datatype fidelity risk is accepted with a documented mitigation of explicit extraction quoting rules and post-load constraint validation embedded in the stored procedure execution flow.

---

## Rejected Options

### Dataflow JDBC-Native with Cloud Composer Orchestration

Architectural over-engineering for a medium-volume structured replication use case. Dataflow's cost profile and JDBC cold-start overhead are disproportionate for a 5 GB initial load growing at 1 GB/month. The Beam pipeline complexity introduces a sustained maintenance burden without delivering latency or reliability benefits beyond what BigQuery-native stored procedure processing provides at this data scale. Complexity score of 3/10 reflects the highest engineering overhead of all three options.

### Cloud Scheduler + Cloud Run Jobs + BigQuery-Native Serverless Batch

Although Option 3 achieves the best cost score of 9/10 through its serverless architecture, it scores materially lower on operability (5/10) and scalability (6/10). The absence of native DAG dependency semantics requires custom bespoke state management code to enforce the historical-load gate, which is a hard functional requirement with zero tolerance for bypass. The operability deficit means stakeholder self-service visibility without engineering involvement is substantially harder to achieve and maintain without the Airflow UI and audit trail that Composer provides. The infrastructure cost savings do not justify the engineering complexity of re-implementing orchestration primitives that Cloud Composer delivers as a managed capability.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Data Completeness — Historical Load Baseline | The full historical load is the irreplaceable foundation for all subsequent incremental loads. Any gap in historical completeness caused by network interruption, MySQL query timeout, or partial CSV write would silently corrupt the analytical baseline if validation gates are not strictly enforced before incremental activation. | Implement a three-stage historical validation checkpoint in Composer before setting historical_load_complete: (1) exact row count match between MySQL COUNT(*) and BigQuery COUNT(*), (2) primary key uniqueness assertion confirming zero duplicate employee_id values, (3) null constraint verification against schema definitions. The incremental DAG uses an ExternalTaskSensor that passes only when all three checkpoints succeed and the BigQuery control flag is set exclusively by the Composer validation task. |
| Schema Drift — MySQL Source Schema Changes | MySQL source schema changes such as new columns, type changes, or column drops are not surfaced to the pipeline by default and can cause silent data truncation, LOAD DATA failures, or MERGE logic errors. | A pre-load schema validation Composer task fetches MySQL INFORMATION_SCHEMA and compares it against the registered BigQuery table schema before every load run. Drift is logged to schema_drift_log with full column-level diff. Additive changes trigger an automated BigQuery ALTER TABLE and a non-blocking warning alert. Destructive changes block the load task and raise a P1 alert requiring engineering sign-off before the run resumes. |
| Access Control — Stakeholder Data Exposure | Looker Studio dashboards backed by BigQuery require stakeholders to have BigQuery viewer access. Misconfigured IAM could expose sensitive employee records in verizon_data_dea beyond the intended audience if data sources are not scoped correctly. | Looker Studio data sources are restricted exclusively to the verizon_data_audit dataset containing load logs and reconciliation summaries; direct access to verizon_data_dea raw tables is not granted to stakeholder accounts. Column-level security policies are applied to sensitive employee fields in BigQuery. IAM access is reviewed quarterly and access changes are logged in Cloud Audit Logs. |
| Pipeline Gate Integrity — Historical Load Control Flag | If the BigQuery historical_load_complete control flag is manually set to TRUE without actual validation passing, the incremental pipeline would activate on an incomplete historical baseline, producing irrecoverable analytical errors. | The control flag is written exclusively by the validated Composer task using the Composer service account; direct BigQuery DML on the audit control table is blocked for all other identities via IAM Conditions. Every write to the control flag generates an audit entry in Cloud Logging, and any manual override triggers a P1 alert to the engineering lead. |
| Cost Governance — Composer Fixed Environment Cost | Cloud Composer 2 environment running continuously with low pipeline activity represents a fixed cost that may be disproportionate if the pipeline is paused for extended periods or the table count remains at one. | Configure Cloud Composer 2 with autoscaling workers (minimum zero workers, minimum one scheduler) to minimise idle cost. Set GCP budget alerts at 80% and 100% of the agreed monthly programme threshold. Conduct quarterly environment sizing reviews and evaluate downgrade to Cloud Scheduler plus Cloud Run Jobs if orchestration complexity reduces materially over time. |

---

## Assumptions

1. GCP project verizon-data exists with BigQuery, Cloud Composer, GCS, Cloud SQL Admin, Cloud Monitoring, and Looker Studio APIs enabled prior to deployment
2. Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore is network-reachable from Cloud Composer 2 worker nodes via VPC network peering or Private Service Connect; this connectivity must be validated before pipeline deployment
3. BigQuery dataset verizon_data_dea already exists in project verizon-data; a second dataset verizon_data_audit will be provisioned by Terraform IaC to house load_log, schema_drift_log, reconciliation_log, and the historical_load_complete control table
4. Stored procedure sp_mysqltobq_load.sql is fully authored, tested for idempotency, and approved prior to pipeline deployment; the architecture treats it as a stable, re-entrant MERGE execution unit safe to retry on DAG failure
5. The 60-day retention policy is implemented as a BigQuery table partition expiry on a date-partitioned employees table provisioned by IaC; it is not implemented as a scheduled DML DELETE job
6. IAM roles roles/bigquery.dataEditor, roles/cloudsql.client, and roles/storage.objectAdmin are granted to the Composer service account by Terraform before pipeline execution; stakeholder IAM is scoped to roles/bigquery.dataViewer on verizon_data_audit only
7. Source MySQL table employees has a reliable and consistently populated updated_date timestamp column and a unique employee_id primary key suitable for watermark-based incremental change detection
8. Pipeline status is draft and production deployment is blocked pending stakeholder review gate as described in the business context; no infrastructure will be provisioned until stakeholder sign-off is received
9. Latency tier declared as real-time in skill parameters conflicts with the requirements document which explicitly states hourly or daily scheduled incremental loads and not real-time; this architecture is designed to the documented requirements and treats the workload as near-batch hourly
10. New column handling strategy is: additive columns trigger an automated BigQuery ALTER TABLE ADD COLUMN via a schema reconciliation task and are logged as non-blocking warnings in schema_drift_log; breaking changes (column removal, type narrowing, rename) block the load and raise a P1 alert; this strategy must be reviewed and approved before first deployment

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud Composer 2 selected as orchestrator over Cloud Scheduler or Dataflow pipelines | Block incremental load pipeline from starting until full historical load validation is confirmed and passes; support hourly and daily scheduling cadences independently per table | hourly | 5 GB initial + 1 GB/month ongoing |
| GCS staging bucket retained as intermediate extraction layer between Cloud SQL and BigQuery | Perform row count reconciliation between MySQL and BigQuery after every load; pipeline must support retry at each stage without re-querying MySQL on partial failure | hourly | 5 GB initial + 1 GB/month ongoing |
| sp_mysqltobq_load.sql stored procedure retained as the MERGE execution layer invoked via BigQueryInsertJobOperator | Execute all load logic via stored procedure sp_mysqltobq_load.sql with merge key on employee_id and updated_date | — | — |
| BigQuery date-partitioned table with 60-day partition expiry provisioned via Terraform IaC | Enforce a 60-day data retention policy on the target BigQuery table | — | — |
| BigQuery audit dataset verizon_data_audit plus Looker Studio selected for stakeholder visibility layer | Provide stakeholder-accessible dashboards or log views enabling independent review of load success and execution history without engineering involvement | — | — |
| Cloud Monitoring alerting policies configured on Composer DAG failure and data quality assertion task failures | Send alerts promptly on any pipeline failure or data quality violation | — | — |
| Pre-load schema validation Composer task with schema_drift_log and documented additive vs destructive column handling strategy | Perform schema validation before each load with mismatch logging and a documented strategy for handling new MySQL columns | — | — |
| Post-load PK uniqueness assertion and null constraint check implemented as dedicated Composer tasks after every load run | Confirm primary key uniqueness post-load and verify null and datatype constraints against schema definitions | — | — |

---

## Open Questions — Action Required

1. Has VPC network connectivity from the Cloud Composer 2 environment to Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore been established via VPC peering or Private Service Connect? This is a hard deployment blocker and must be validated before any pipeline provisioning proceeds.
2. What is the full and approved list of MySQL tables in the agentichub database that require historical and incremental loads? The source_tables field lists only employees; the complete table inventory is required to design the Composer DAG fan-out pattern, size the GCS staging bucket, and determine per-table scheduling cadences.
3. Has sp_mysqltobq_load.sql been validated for idempotency on re-execution? If a Composer DAG retries after a partial failure, the MERGE must not produce duplicate records, corrupt updated_date watermarks, or apply out-of-order updates; a formal idempotency test must be documented before production deployment.
4. What is the approved notification channel for pipeline failure and data quality alerts? Cloud Monitoring notification channels (email distribution list, Slack webhook, PagerDuty integration key) must be provisioned and tested before the go-live gate.
5. What deployment environments are required? The architecture assumes production-bound based on stakeholder review gate language, but environment-specific IAM bindings, dataset naming conventions, and Composer environment sizing for dev and staging must be confirmed and included in the Terraform workspace configuration.
6. Who is the designated BigQuery data owner for verizon_data_dea and has column-level security classification for sensitive employee fields been reviewed and approved by the data governance team prior to provisioning stakeholder IAM access?
7. Is the 60-day retention policy a hard compliance or legal obligation, or a cost optimisation preference? If compliance-driven, BigQuery Data Access audit logs and load_log records must be retained independently for the full compliance audit period, which may exceed 60 days and requires a separate log sink and retention policy distinct from the table partition expiry.
