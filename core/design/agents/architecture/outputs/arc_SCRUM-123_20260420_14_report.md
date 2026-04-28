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

> **Build with:** Cloud Composer + Cloud Run Jobs (Pragmatic Containerized Batch)
>
> **Why:** Option 2 achieves the highest weighted score (7.40) by delivering the optimal balance of cost efficiency, operational simplicity, and functional completeness for a batch pipeline of unknown volume loading a single MySQL table on a daily or hourly cadence. Cloud Run Jobs eliminate idle compute cost entirely, Python-based processing logic is maintainable without specialist SDK knowledge, BigQuery Storage Write API COMMITTED streams provide exactly-once write semantics without external dedup infrastructure, and BigQuery MERGE enforces PK uniqueness as a native SQL operation. The Cloud Composer orchestration layer satisfies the critical mandatory gating requirement — incremental pipeline activation blocked until historical validation passes and is signed off — while the Looker Studio plus BigQuery audit_log combination fulfills stakeholder-independent visibility for Yash at zero marginal tooling cost.
>
> **Score:** 7.40 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2 ✅ | Option 3  |
|---|---||---||---|
| **Name** | Cloud Composer + Dataflow (Enterprise ETL Pipeline) | Cloud Composer + Cloud Run Jobs (Pragmatic Containerized Batch) | Datastream + Cloud Composer Validation Layer (Native CDC Replication) |
| **Pattern** | Batch | Batch | Hybrid |
| **Processing** | Apache Beam on Cloud Dataflow (schema validation transforms, CoGroupByKey PK dedup, audit side-output) | Cloud Run Jobs (Python-based schema validation, type coercion, null checks) + BigQuery SQL MERGE (PK dedup and upsert enforcement) | BigQuery SQL (MERGE for upsert and delete propagation, INFORMATION_SCHEMA schema checks) + Cloud Composer 2 (post-land validation DAG orchestrating BigQuery SQL operators) |
| **Storage** | BigQuery (date-partitioned, PK-clustered target table + audit_log + run_state) + GCS (Dataflow temp/staging) | BigQuery Storage Write API COMMITTED stream (target table, date-partitioned by load_date, PK-clustered) + BigQuery audit_log table + BigQuery run_state table + GCS (optional run artifact export) | BigQuery (Datastream-native staging table with CDC events + curated MERGE target table, date-partitioned, PK-clustered) + GCS (Datastream checkpoints, Composer artifacts) |
| **Weighted Score** | **6.40** | **7.40**  ✅ | **7.15** |

---

## Option 1 — Cloud Composer + Dataflow (Enterprise ETL Pipeline)

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Dataflow job reads from Cloud SQL MySQL (agentichub.employees) via JdbcIO over Cloud SQL Auth Proxy or VPC Private Service Connect; on historical load, executes a full unbounded read; on incremental runs, executes a watermark-filtered read using the maximum updated_at or PK value persisted in a BigQuery run-state table from the prior successful run. |
| Processing | Apache Beam pipeline on Dataflow performs in-flight schema compatibility checks (INFORMATION_SCHEMA type mapping, null constraint validation, new-column detection with configurable halt/add/cast strategy), row count accumulation, and PK-based deduplication via CoGroupByKey; audit log records are emitted as a side output and written transactionally to a BigQuery audit_log table in verizon_data_deah. |
| Storage | Processed records are written via Dataflow BigQuery sink directly to date-partitioned, PK-clustered BigQuery tables in verizon_data_deah; GCS serves as Dataflow temp and staging area; a separate BigQuery run_state table persists watermark values for incremental continuity. |
| Consumption | Analytics and reporting teams query BigQuery directly via authorized views or dataset-level IAM grants; a Looker Studio dashboard backed by the BigQuery audit_log and run_state tables provides Yash and other stakeholders with load health, row count trends, and failure history without developer involvement. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Dataflow (Apache Beam JdbcIO + Cloud SQL Auth Proxy) | — | Yes |
| Processing | Apache Beam on Cloud Dataflow (schema validation transforms, CoGroupByKey PK dedup, audit side-output) | — | Yes |
| Storage | BigQuery (date-partitioned, PK-clustered target table + audit_log + run_state) + GCS (Dataflow temp/staging) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow — DAG-based sequencing, historical validation gate, incremental activation lock) | 2.x | Yes |
| Monitoring | Cloud Monitoring (Dataflow job metrics, alerting policies) + Cloud Logging (structured pipeline logs) + Looker Studio (BigQuery-backed stakeholder dashboard) | — | Yes |
| Iac | Terraform | ~> 5.0 | No |

### Pros

- Dataflow auto-scales workers horizontally to accommodate any data volume, making this option future-proof as additional tables are onboarded and row counts grow unpredictably.
- Apache Beam's native PCollection model supports row-level schema validation, null checks, PK deduplication via CoGroupByKey, and audit side-outputs within a single unified pipeline graph.
- Cloud Composer provides a full DAG-based orchestration layer for sequencing historical load, validation gating, sign-off check, and incremental activation, with complete task-level audit trails and retries.
- Dataflow's built-in metrics (elements processed, bytes written, error counts) integrate natively with Cloud Monitoring for SLA-bound alerting and Looker Studio dashboards at no additional tooling cost.
- Mature, battle-tested enterprise stack with extensive GCP documentation, IAM integration, VPC Service Controls support, and a large practitioner community.

### Cons

- Cloud Composer 2 carries a baseline cost of approximately $300–$500 per month even when idle, making it disproportionately expensive for a low-frequency single-table pipeline at unknown volume.
- Apache Beam SDK introduces significant engineering complexity: JdbcIO configuration, side-output patterns, CoGroupByKey dedup, and Dataflow runner tuning require specialist knowledge not present in a general Python engineering team.
- Dataflow job startup latency of 2–5 minutes consumes a meaningful fraction of tight hourly batch windows and adds unpredictable wall-clock duration to the historical load.
- JdbcIO parallel reads from Cloud SQL require careful connection pool and parallelism configuration to avoid source contention or max_connections exhaustion on the Cloud SQL instance.
- Initial provisioning across Dataflow, Composer, GCS, BigQuery, Cloud SQL Auth Proxy, and VPC network policies is operationally heavy and requires coordinated IAM role assignments.

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Schema drift in MySQL (column additions or type changes) may not be caught at the JdbcIO read boundary; requires an explicit schema registry comparison step in the Beam pipeline before record emission to prevent silent type coercion or field truncation errors propagating to BigQuery. |
| Scaling | Without confirmed data volume, Dataflow worker count and machine type cannot be pre-sized; under-provisioning may cause job timeouts during the one-time historical load, while over-provisioning inflates cost; requires volume profiling before production sizing decisions. |
| Latency | Dataflow job startup overhead (2–5 min) and Composer DAG scheduling delay may compress the usable processing window within a tight hourly SLA if the employees table grows significantly over time. |
| Cost | Cloud Composer 2 environment costs accumulate continuously regardless of pipeline frequency; combined Dataflow worker cost plus Composer baseline may be economically unjustifiable for a single-table pipeline until volume and table count justify the infrastructure investment. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 9 | 4 | 7 | 8 | **6.40** |

---

## Option 2 — Cloud Composer + Cloud Run Jobs (Pragmatic Containerized Batch) ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Run Job (containerized Python 3.12 service using SQLAlchemy 2.x and PyMySQL) connects to Cloud SQL MySQL via Cloud SQL Auth Proxy sidecar over VPC; on historical load, executes a paginated full SELECT using keyset pagination (ORDER BY pk LIMIT N OFFSET cursor) to bound per-page memory; on incremental runs, executes a watermark-filtered SELECT using the maximum updated_at or PK value recorded in a BigQuery run_state table from the prior successful run, ensuring no gap or overlap across cycles. |
| Processing | Within the Cloud Run Job, a Python processing layer executes sequentially: (1) pre-load schema compatibility check by comparing MySQL INFORMATION_SCHEMA.COLUMNS definitions against BigQuery table schema via the BigQuery REST API; (2) null constraint validation against defined NOT NULL columns before write; (3) type coercion and mapping to BigQuery-compatible types (e.g., MySQL DATETIME to BQ TIMESTAMP, DECIMAL to NUMERIC); (4) new-column detection with a configurable strategy (halt-and-alert recommended); (5) source row count accumulation; after write, a BigQuery MERGE statement enforces PK uniqueness and upserts records; post-load row count is validated against source count and delta is asserted to zero; null violation counts are logged before marking the run complete. |
| Storage | Records are written directly to BigQuery via the BigQuery Storage Write API using COMMITTED stream mode for atomic, exactly-once write semantics, eliminating duplicate-write risk on retry; a dedicated BigQuery audit_log table in verizon_data_deah records every run's execution status, source row count, target row count, schema diff result, null violation counts, watermark values, new columns detected, and wall-clock duration; a run_state table persists the last successful watermark per table for incremental continuity. |
| Consumption | Analytics and reporting teams access BigQuery directly via dataset-level IAM or authorized views; a Looker Studio dashboard connected to the audit_log and run_state BigQuery tables provides Yash and other stakeholders with real-time load health, row count trends, schema change history, and failure events without requiring developer involvement; Cloud Monitoring alert policies notify on-call engineers via PagerDuty or email when Cloud Run Job exit code is non-zero. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Run Jobs (Python 3.12 + SQLAlchemy 2.x + PyMySQL + Cloud SQL Auth Proxy sidecar) | 2nd Gen | Yes |
| Processing | Cloud Run Jobs (Python-based schema validation, type coercion, null checks) + BigQuery SQL MERGE (PK dedup and upsert enforcement) | 2nd Gen | Yes |
| Storage | BigQuery Storage Write API COMMITTED stream (target table, date-partitioned by load_date, PK-clustered) + BigQuery audit_log table + BigQuery run_state table + GCS (optional run artifact export) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow — DAG-based gating: historical validation and sign-off SensorOperator gates incremental activation; BranchOperator handles schema-change halt path; audit log write tasks on success and failure) | 2.x | Yes |
| Monitoring | Cloud Monitoring (Cloud Run Job exit code alerting policies, latency metrics) + Cloud Logging (structured JSON logs from Cloud Run container) + Looker Studio (BigQuery-backed stakeholder dashboard on audit_log and run_state) | — | Yes |
| Iac | Terraform | ~> 5.0 | No |

### Pros

- Cloud Run Jobs are fully serverless with zero idle cost: billing accrues only during active job execution, making this the most cost-efficient option for daily or hourly cadences at unknown volume.
- Python-based processing logic is straightforward to implement, unit-test, and extend; the engineering barrier is significantly lower than Apache Beam SDK, enabling a broader pool of maintainers and faster iteration.
- BigQuery Storage Write API COMMITTED stream provides exactly-once write semantics, eliminating duplicate-record risk during job retries without requiring external deduplication logic or idempotency keys.
- BigQuery MERGE statement for PK dedup enforcement is a native, serverless SQL operation requiring no additional compute beyond BigQuery slot allocation, and executes atomically against the target table.
- Looker Studio connected to the BigQuery audit_log table provides a zero-additional-cost stakeholder dashboard that fulfills the independent visibility requirement for Yash with no custom portal development.
- Cloud Composer gating logic — historical validation sign-off gate blocking incremental activation — is cleanly expressible as a short linear Airflow DAG with SensorOperators checking audit_log run status, satisfying the gating functional requirement without custom state management.
- Incremental watermark state is persisted in a BigQuery run_state table, making state recovery after failure deterministic, auditable, and inspectable by any team member with BigQuery access.
- Keyset pagination on the Cloud Run extraction query bounds per-page memory consumption regardless of total table size, providing a natural scaling mechanism without architectural redesign.

### Cons

- Cloud Run Jobs have a maximum execution timeout of 24 hours and a maximum memory of 32 GiB per task instance; very large historical loads (multi-billion rows or hundreds of GB) may require manual horizontal sharding across parallel Cloud Run tasks with PK range partitioning.
- Cloud Run does not provide native distributed processing; large-volume incremental loads with high parallelism requirements demand custom sharding logic (PK range splits across N parallel tasks), adding implementation surface area compared to Dataflow's auto-parallelism.
- Cloud Composer 2 baseline cost (~$300–$500 per month) may be disproportionate if orchestration logic remains minimal; however, it is a mandatory dependency given the historical-to-incremental gating requirement that cannot be expressed in Cloud Scheduler alone.
- Python-based schema comparison against BigQuery table metadata is custom code rather than a framework-native feature, creating a maintenance surface that must be kept aligned with both MySQL and BigQuery schema evolution patterns.
- Cloud SQL connection pool configuration on Cloud Run must account for the maximum parallel task count to avoid exhausting Cloud SQL's max_connections limit under concurrent historical load shard executions.

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Watermark-based incremental strategy will miss records that are back-dated (updated_at set to a past value) or soft-deleted without an updated_at bump; a periodic full-table-scan reconciliation job should be scheduled weekly or monthly to detect and close any gaps introduced by non-standard write patterns on the MySQL source. |
| Scaling | Cloud Run Job memory and CPU caps constrain single-task throughput; if the employees table grows to hundreds of millions of rows, the single-job architecture requires refactoring to parallel sharded tasks with PK range splits, representing future technical debt that must be budgeted at the point of volume confirmation. |
| Latency | Large result sets transferred over the Cloud SQL Auth Proxy introduce serialization and network overhead; keyset pagination with configurable page size (recommended 10,000–50,000 rows per page) is mandatory to prevent OOM on the Cloud Run container and must be tuned against confirmed volume before production cutover. |
| Cost | At confirmed low volume, this is the lowest-cost option; however, if run frequency escalates to sub-hourly across many tables or Cloud Run task parallelism increases significantly, invocation counts and BigQuery Storage Write API streaming costs may require a cost review and potential migration to Option 1 for bulk-write efficiency. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 7 | 7 | 7 | 8 | **7.40** |

---

## Option 3 — Datastream + Cloud Composer Validation Layer (Native CDC Replication)

**Pattern:** Hybrid

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Datastream connection profile targets Cloud SQL MySQL instance (verizon-data:us-central1:mysql-druid-metadatastore) using MySQL binlog CDC with binlog_format=ROW and binlog_row_image=FULL; a Datastream backfill operation captures 100% of existing employees rows as the initial historical load using a consistent snapshot; after backfill completes, ongoing CDC events (INSERT, UPDATE, DELETE) are captured from the MySQL binary log continuously and delivered to the Datastream BigQuery-native destination. |
| Processing | Datastream writes raw change events including _metadata columns (_change_type, _change_sequence_number, _source_timestamp) to a BigQuery staging table in verizon_data_deah; a Cloud Composer DAG, triggered on the defined hourly or daily schedule, executes a post-landing processing sequence via BigQuery SQL operators: (1) schema evolution check via INFORMATION_SCHEMA comparison; (2) MERGE statement applying upserts and hard-delete propagation from the staging table to the curated target table using _change_sequence_number ordering; (3) source row count query via Cloud SQL export or a Cloud Run probe job; (4) post-MERGE row count validation against BigQuery curated table; (5) null violation check; (6) audit log INSERT recording run outcome. |
| Storage | Datastream delivers change events to a BigQuery-native destination without a GCS staging hop; the raw staging table retains CDC events with _metadata for a configurable retention window; the curated BigQuery table in verizon_data_deah receives the post-MERGE deduplicated and delete-applied view suitable for analytics consumption; GCS stores Datastream stream state checkpoints and Composer DAG artifacts only. |
| Consumption | Analytics teams query the curated BigQuery table via standard IAM grants; Datastream's built-in GCP Console stream monitoring combined with a Looker Studio dashboard on the BigQuery audit_log table provides stakeholder-facing load health visibility; Datastream native metrics (events delivered, replication lag, errors) are surfaced in Cloud Monitoring for alerting. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Datastream (MySQL binlog CDC + backfill snapshot, BigQuery-native destination) | — | Yes |
| Processing | BigQuery SQL (MERGE for upsert and delete propagation, INFORMATION_SCHEMA schema checks) + Cloud Composer 2 (post-land validation DAG orchestrating BigQuery SQL operators) | — | Yes |
| Storage | BigQuery (Datastream-native staging table with CDC events + curated MERGE target table, date-partitioned, PK-clustered) + GCS (Datastream checkpoints, Composer artifacts) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow — scheduled post-land validation DAG, historical backfill completion gate, incremental activation lock, audit log writes) | 2.x | Yes |
| Monitoring | Cloud Monitoring (Datastream stream health metrics, replication lag, event throughput, error rate alerting) + Cloud Logging + Looker Studio (Datastream metrics + BigQuery audit_log stakeholder dashboard) | — | Yes |
| Iac | Terraform | ~> 5.0 | No |

### Pros

- Datastream handles the full replication mechanics natively — backfill, ongoing CDC, schema mapping, and BigQuery delivery — reducing custom extraction code to near zero and eliminating the need to author JDBC connection management logic.
- Near-real-time CDC delivery (seconds to low minutes end-to-end) far exceeds the hourly or daily batch SLA, providing significant headroom for future latency tightening without an architecture change.
- Datastream's BigQuery-native destination eliminates the GCS staging hop and BQ load job, reducing pipeline components and potential failure points between source and destination.
- Automatic schema evolution: new columns added to MySQL are propagated to the BigQuery staging table by Datastream without pipeline downtime, reducing the schema drift surface area for new-column scenarios.
- Datastream's GCP Console provides out-of-the-box stream health monitoring, throughput charts, and error drill-down, supplementing the stakeholder dashboard requirement with a native observability layer.

### Cons

- Requires MySQL binary logging enabled on the Cloud SQL instance (binlog_format=ROW, binlog_row_image=FULL); this is a prerequisite that may require Cloud SQL instance flag changes, a database restart, and explicit DBA or platform team approval, creating a hard deployment blocker not present in Options 1 or 2.
- Datastream is architecturally a CDC-first continuous replication tool; adapting it to serve discrete scheduled batch validation gates with exact row-count checkpoints introduces semantic friction — the tool was not designed for transactional batch-window semantics.
- The Datastream staging table accumulates raw CDC events (including _metadata and change-type columns), requiring a custom MERGE SQL statement to produce a clean deduplicated curated table; this MERGE logic must handle INSERT, UPDATE, and DELETE _change_type values correctly across all edge cases.
- Post-MERGE row count validation between MySQL source and BigQuery curated table requires an auxiliary source-count query mechanism (Cloud Run probe or Cloud SQL export) because Datastream does not expose a real-time source row count API, adding a component not present in the Datastream native flow.
- Hard-delete propagation requires explicit MERGE predicate logic to remove rows from the curated table when _change_type = 'DELETE'; incorrect MERGE design may result in ghost rows persisting in the curated table or, conversely, valid rows being incorrectly deleted.

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Datastream backfill completeness depends on a consistent snapshot at the point of stream creation; if the MySQL instance experiences heavy write load during backfill, interleaved CDC events and backfill rows may produce transient duplicates in the staging table that the MERGE must resolve using _change_sequence_number ordering — requiring careful MERGE key design validation before production sign-off. |
| Scaling | High-churn employees tables (frequent bulk UPDATEs) generate large CDC event volumes in BigQuery staging, inflating storage costs and MERGE processing time proportionally to event rate rather than row count; staging table retention policy must be defined and enforced to prevent unbounded growth. |
| Latency | This option over-delivers on latency (near-real-time versus the daily or hourly batch requirement), introducing binlog-based CDC infrastructure complexity without a corresponding business benefit in a batch consumption context; the architectural mismatch between continuous replication and discrete batch validation gates is a structural risk. |
| Cost | Datastream pricing is volume-based (per GB of data processed); combined with BigQuery staging table growth from accumulated CDC events and the retention of change history, total cost at moderate-to-high update rates may exceed Option 2; cost modeling requires confirmed event rate data from the MySQL workload before production sizing. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 8 | 5 | 9 | 7 | **7.15** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Dataflow (Enterprise ETL Pipeline) | 5 | 9 | 4 | 7 | 8 | **6.40** |
| Cloud Composer + Cloud Run Jobs (Pragmatic Containerized Batch) ✅ | 8 | 7 | 7 | 7 | 8 | **7.40** |
| Datastream + Cloud Composer Validation Layer (Native CDC Replication) | 7 | 8 | 5 | 9 | 7 | **7.15** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Composer + Cloud Run Jobs (Pragmatic Containerized Batch)**
**Weighted Score: 7.40**

**Justification:** Option 2 achieves the highest weighted score (7.40) by delivering the optimal balance of cost efficiency, operational simplicity, and functional completeness for a batch pipeline of unknown volume loading a single MySQL table on a daily or hourly cadence. Cloud Run Jobs eliminate idle compute cost entirely, Python-based processing logic is maintainable without specialist SDK knowledge, BigQuery Storage Write API COMMITTED streams provide exactly-once write semantics without external dedup infrastructure, and BigQuery MERGE enforces PK uniqueness as a native SQL operation. The Cloud Composer orchestration layer satisfies the critical mandatory gating requirement — incremental pipeline activation blocked until historical validation passes and is signed off — while the Looker Studio plus BigQuery audit_log combination fulfills stakeholder-independent visibility for Yash at zero marginal tooling cost.

**Why highest score:** Option 2 outscores Option 1 by 1.00 point, driven by a 3-point cost advantage and a 3-point complexity advantage; the 2-point scalability concession is an accepted and reversible trade-off given unconfirmed-large volume. Option 2 outscores Option 3 by 0.25 points, driven by a 2-point complexity advantage and a 1-point operability advantage; Option 3's 2-point latency advantage is architecturally irrelevant because the requirement explicitly specifies batch (daily or hourly), not near-real-time CDC. Option 2 is the only option that scores 7 or above across all five scoring dimensions simultaneously, confirming it as the balanced choice across the full scoring criteria.

**Trade-offs accepted:** The primary trade-off accepted is scalability (score 7 vs. 9 for Option 1): Cloud Run Jobs cannot auto-distribute processing across nodes the way Dataflow can, meaning that if the employees table grows to hundreds of millions of rows or dozens of tables are onboarded concurrently, this architecture will require a sharding refactor or migration to Option 1. This is accepted because data volume is currently unknown and unconfirmed to be large, the migration path to Dataflow is well-defined and the audit_log schema is portable, and the cost and complexity savings in the near term outweigh the speculative scaling risk. Cloud Composer's baseline idle cost is additionally accepted as a mandatory infrastructure expense required to fulfill the historical-load gating functional requirement — it cannot be substituted with Cloud Scheduler without losing the sign-off gate capability.

---

## Rejected Options

### Cloud Composer + Dataflow (Enterprise ETL Pipeline)

Option 1 achieves the lowest weighted score (6.40) of the three options despite its superior scalability ceiling. The primary detractors are high complexity (score 4) and disproportionate cost (score 5) relative to a single-table batch pipeline of unknown and unconfirmed-large volume. The Beam SDK's steep learning curve, Dataflow startup latency overhead, and Cloud Composer's baseline idle cost make this option over-engineered for the current scope. It should be re-evaluated when data volume is confirmed multi-GB or multi-billion rows, when 10 or more tables are onboarded concurrently, or when sub-hourly SLAs with distributed processing requirements are formally imposed.

### Datastream + Cloud Composer Validation Layer (Native CDC Replication)

Option 3 scores 7.15, trailing Option 2 by 0.25 points. Its latency advantage (score 9 versus 7 for Option 2) is architecturally irrelevant because the requirement explicitly specifies batch (daily or hourly) — near-real-time CDC over-delivers without business justification and introduces binlog management complexity that adds a hard prerequisite deployment blocker not present in Option 2. Its lower complexity score (5 versus 7) reflects not simplicity but the compounded burden of binlog flag prerequisites, CDC-to-batch semantic friction, staging-to-curated MERGE logic, DELETE propagation edge cases, and an auxiliary row-count probe mechanism. Option 3 should be re-evaluated as the preferred architecture if business requirements shift to sub-minute data freshness SLAs, if audit trail requirements demand event-level CDC granularity, or if the MySQL binlog prerequisite is already satisfied and confirmed by the DBA team.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Data Volume Unknown | The absence of row count and uncompressed GB volume data for the employees table makes it impossible to validate Cloud Run Job memory sizing, keyset page size tuning, BigQuery slot consumption estimates, or cost projections. Under-sizing may cause OOM failures or job timeouts on the historical load; over-sizing inflates cost unnecessarily. | Execute a volume profiling query (SELECT COUNT(*) AS row_count, ROUND(SUM(LENGTH(col1) + LENGTH(col2) + ...) / 1073741824, 2) AS size_gb FROM agentichub.employees) before infrastructure provisioning. Gate all sizing decisions — Cloud Run task memory, keyset page size, Composer parallelism, BigQuery slot reservation — on confirmed volume data. Design keyset pagination as the default extraction pattern to bound per-page memory consumption independently of total table size. |
| Incremental Strategy Validity | All options assume a reliable watermark column (updated_at timestamp or monotonically increasing PK) exists on the employees table for incremental delta extraction. If neither exists, every incremental run must execute a full table scan with hash-based diff, significantly increasing compute cost, latency, and implementation complexity. | Audit the employees table DDL (SHOW CREATE TABLE agentichub.employees) before design finalization. If no watermark column exists, add an updated_at column with DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP to the MySQL schema, or evaluate Option 3 (Datastream CDC) as the only reliable change-capture mechanism that does not depend on application-managed timestamp columns. |
| Monitoring SLA Undefined | The functional requirement states that monitoring alerts must trigger on pipeline failures within a defined SLA, but the specific duration is not quantified anywhere in the source requirements. Without a numeric SLA value, Cloud Monitoring alerting policies cannot be correctly configured and alert evaluation periods remain undefined. | Escalate to stakeholders (including Yash) to formally define the maximum acceptable time-to-alert for pipeline failures (e.g., alert within 15 minutes of job failure detection). Until a formal SLA is signed off, configure a conservative default evaluation period of 30 minutes for Cloud Monitoring alerting policies and document this default in the pipeline runbook. |
| Schema Evolution | MySQL schema changes in the employees table (new columns added, existing column type widened or narrowed, column renamed or dropped) may silently break the ingestion pipeline or cause data truncation, loss, or type coercion errors if pre-load schema checks do not detect and halt on schema drift before any records are written to BigQuery. | Implement a mandatory pre-load schema compatibility check on every run that compares MySQL INFORMATION_SCHEMA.COLUMNS against BigQuery table schema via the BigQuery REST API. Define and enforce an explicit new-column handling strategy (recommended: halt pipeline, emit a schema-change alert, apply ALTER TABLE to BigQuery schema manually after review, then resume); store schema version snapshots in a BigQuery schema_history table for historical diff tracking and audit. |
| Security and Compliance Unknowns | Data sensitivity classification, PII presence, and applicable compliance frameworks (HIPAA, GDPR, CCPA, SOX) for the employees table are unspecified in the requirements. Employee data commonly contains sensitive PII (names, SSNs, salary, contact information). Without classification, column-level masking policies, encryption requirements, and access audit logging cannot be properly designed. | Conduct a data classification review of all employees table columns before production deployment. Apply BigQuery column-level security policies using policy tags on PII columns. Enable CMEK if compliance mandates customer-managed encryption keys. Ensure Cloud Audit Logs (DATA_READ, DATA_WRITE) are enabled on the BigQuery verizon_data_deah dataset. Restrict Looker Studio dashboard access to named stakeholders via IAM to prevent inadvertent PII exposure. |

---

## Assumptions

1. The GCP project hosting the pipeline infrastructure has been granted the necessary IAM permissions to read from Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore and write to BigQuery dataset verizon_data_deah prior to deployment.
2. Cloud SQL Auth Proxy or VPC Private Service Connect is configured or will be provisioned to allow secure private connectivity between Cloud Run Jobs, Dataflow workers, and the Cloud SQL MySQL instance without public IP exposure.
3. The BigQuery dataset verizon_data_deah exists in the target GCP project and is located in us-central1; if it does not exist, Terraform IaC will create it as part of the infrastructure provisioning plan.
4. The MySQL employees table contains a reliable watermark column (e.g., updated_at TIMESTAMP with ON UPDATE CURRENT_TIMESTAMP semantics, or a monotonically increasing auto-increment primary key) suitable for watermark-based incremental delta extraction; this assumption must be validated against the actual DDL before production deployment.
5. Data volume for the employees table is unknown at architecture time; all pipeline sizing recommendations (Cloud Run memory, Dataflow worker count, keyset page size) must be validated against actual row counts and GB volume before production cutover.
6. The historical full load is a one-time, manually triggered operation that must complete successfully and pass row-count and PK uniqueness validation before the incremental pipeline is permitted to activate; the Cloud Composer gating DAG enforces this sequencing constraint.
7. No cross-cloud connectivity is required; all pipeline components are deployed within GCP in us-central1 to minimize network latency to the source Cloud SQL instance and to remain within the same VPC network.
8. IAM service accounts for each pipeline component follow least-privilege principles: Cloud Run Jobs service account receives roles/cloudsql.client, roles/bigquery.dataEditor on verizon_data_deah, and roles/storage.objectAdmin on the designated GCS bucket only.
9. Cloud Composer 2 (Airflow 2.x) is the designated orchestration tier; substitution with Cloud Scheduler is insufficient and rejected for this initiative due to the mandatory stateful gating requirement between the historical load validation sign-off and incremental pipeline activation.
10. Standard MySQL column types (INT, BIGINT, VARCHAR, TEXT, DATETIME, TIMESTAMP, DECIMAL, FLOAT, BOOLEAN) are assumed for the employees table; exotic or non-standard types (GEOMETRY, JSON, BLOB, ENUM) require explicit type mapping review and may necessitate custom coercion logic not addressed in this architecture.

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud Composer 2 selected as mandatory orchestration layer for all options to enforce stateful historical-to-incremental gating | Gate incremental load activation: incremental pipeline must not begin until historical load validation is fully passed and signed off | — | — |
| BigQuery audit_log table with Looker Studio dashboard selected as stakeholder visibility layer | Implement a monitoring dashboard or log-based visibility layer enabling stakeholders to independently review load success without developer involvement | — | — |
| Pre-load schema compatibility check implemented as a mandatory step before every load execution | Perform pre-load schema compatibility checks covering data types, null handling, field names, and new column handling strategy before each load execution | — | — |
| Post-load row count validation between MySQL source and BigQuery target mandated for every load cycle with zero-delta assertion | Perform post-load row count validation between MySQL source and BigQuery target for every load cycle | — | — |
| BigQuery MERGE statement (Option 2) or Beam CoGroupByKey dedup (Option 1) applied after every load to enforce PK uniqueness; Datastream staging MERGE with _change_sequence_number ordering (Option 3) | Enforce primary key uniqueness in BigQuery after every load execution | — | — |
| Watermark-based incremental strategy (updated_at timestamp or PK delta) selected as default; full-table-scan fallback documented for tables without watermark columns | Track incremental changes using timestamp-based or primary key delta strategies, consistently applied across all runs | daily | — |
| Cloud Monitoring alerting policies configured on job exit codes and completion status with a default 30-minute evaluation period pending formal SLA definition | Trigger monitoring alerts on pipeline failures within a defined SLA | — | — |
| Null constraint violations are logged and counted in the audit_log table before any run is marked complete; violations above a configurable threshold halt the run | Log and report null constraint violations before marking any load as complete | — | — |
| BigQuery Storage Write API COMMITTED stream mode selected for exactly-once write semantics; MERGE dedup prevents duplication; watermark-gated incremental windows prevent gaps | Prevent data duplication and gaps across all incremental load cycles | — | — |
| All pipeline components deployed in GCP us-central1 region to co-locate with the source Cloud SQL instance | Source: MySQL — agentichub database, employees table, hosted on GCP Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore | daily | — |

---

## Open Questions — Action Required

1. What is the approximate row count and uncompressed data volume (GB) of the employees table? Required to validate Cloud Run Job memory sizing, confirm whether keyset sharding across parallel tasks is needed, and produce an initial cost estimate.
2. Does the employees table contain a reliable updated_at TIMESTAMP column with ON UPDATE CURRENT_TIMESTAMP semantics, or a monotonically increasing auto-increment primary key? If neither exists, the incremental delta strategy must be redesigned before architecture sign-off.
3. Is MySQL binary logging currently enabled on the Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore with binlog_format=ROW and binlog_row_image=FULL? This is a hard prerequisite only for Option 3 (Datastream) but should be confirmed to fully close that option's feasibility.
4. What is the quantified SLA duration for monitoring alert triggers (e.g., alert within 15 minutes of job failure)? Required to set Cloud Monitoring alerting policy evaluation periods and notification channel routing rules.
5. What is the target GCP project ID for pipeline infrastructure deployment? Required to scope Terraform provider configurations, IAM role bindings, and BigQuery dataset ownership.
6. Does the employees table contain PII or sensitive data (names, SSNs, salaries, contact information) requiring BigQuery column-level policy tags, CMEK encryption, or compliance with GDPR, HIPAA, CCPA, or other regulatory frameworks?
7. Should the BigQuery target table support hard deletes (rows deleted in MySQL are deleted in BigQuery), or should MySQL DELETEs be surfaced as a soft-delete flag column with a deleted_at timestamp? This decision determines the MERGE statement predicate design.
8. What is the defined new-column handling strategy when a previously unknown column appears in MySQL: (a) halt pipeline, alert, and require manual schema review before resuming; (b) automatically add the column to BigQuery with NULL backfill for historical rows; or (c) map new columns to a catch-all STRING extras column? A policy decision is required before implementation.
9. What specific metrics, KPIs, and filter dimensions should the Looker Studio stakeholder dashboard (for Yash) surface? Candidate fields: last run status, source vs. target row count delta, schema change events, null violation counts, load duration trend, and watermark value per table.
10. Is there an existing VPC Shared Network, VPC Service Controls perimeter, or Private Service Connect endpoint already provisioned for Cloud SQL access, or does one need to be planned and provisioned as a prerequisite infrastructure dependency for this initiative?
