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

> **Build with:** GCP Datastream (CDC Backfill + Incremental) + Cloud Composer Validation Gate + BigQuery
>
> **Why:** Option 3 is recommended as the primary architecture for the MySQL to BigQuery Data Ingestion Pipeline. GCP Datastream delivers a fully managed, binlog-based CDC ingestion layer that eliminates custom extraction code and natively satisfies the full historical load, incremental sync, and schema evolution requirements under a single managed service boundary. The Cloud Composer two-phase orchestration cleanly enforces the historical load gate requirement via an audit_log sensor with no workarounds. BigQuery MERGE-based upserts enforce PK uniqueness and idempotency natively. The Looker Studio plus audit_log design gives stakeholder Yash independent, developer-free pipeline health visibility — a first-class requirement explicitly called out in the business context. All components operate under Google-managed SLAs, minimizing operational toil and providing a defensible reliability foundation as additional tables are onboarded to the same Datastream stream.
>
> **Score:** 4.10 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2  | Option 3 ✅ |
|---|---||---||---|
| **Name** | Cloud Composer + Apache Beam/Dataflow JDBC Batch ETL | Cloud Composer + Cloud Run Jobs (Python Micro-Batch ETL) | GCP Datastream (CDC Backfill + Incremental) + Cloud Composer Validation Gate + BigQuery |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Apache Beam SDK (Python or Java) on Dataflow Runner | Python ETL script (google-cloud-bigquery SDK, pandas optional) within Cloud Run Job container | BigQuery (MERGE SQL for dedup and upsert, schema check SQL via INFORMATION_SCHEMA) + Cloud Composer Airflow operators |
| **Storage** | BigQuery (target + audit_log) + GCS (state, quarantine, schema snapshots) | BigQuery (target + audit_log + metadata control table) + GCS (state, quarantine, schema snapshots) | BigQuery (target employees table + audit_log + schema_registry) + GCS (Datastream landing zone, Avro change event files) |
| **Weighted Score** | **3.15** | **4.00** | **4.10**  ✅ |

---

## Option 1 — Cloud Composer + Apache Beam/Dataflow JDBC Batch ETL

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer DAG triggers a Dataflow job using the Apache Beam JDBC IO connector to read from Cloud SQL MySQL (verizon-data:us-central1:mysql-druid-metadatastore, agentichub.employees) via Cloud SQL Auth Proxy or VPC-native IP. Full load reads all rows with pagination; incremental load reads rows where updated_at or id exceeds the last watermark value stored in a GCS control file. |
| Processing | Apache Beam pipeline performs: (1) pre-load schema compatibility validation against the registered BigQuery target schema, flagging type mismatches and new columns per a defined policy; (2) data type coercion and null constraint violation logging; (3) PK deduplication using a CoGroupByKey transform; (4) post-load row count audit written to a BigQuery audit_log table. Historical load uses WRITE_TRUNCATE; incremental load uses WRITE_APPEND followed by a BigQuery MERGE deduplicate step. |
| Storage | Processed records are written to BigQuery (verizon_data_deah dataset) via the BigQuery Storage Write API. GCS stores pipeline state files, schema snapshots, and quarantined records for failed rows. A BigQuery audit_log table is the single audit source of truth per run. |
| Consumption | Analytics and reporting teams query BigQuery directly. Stakeholder Yash accesses a Looker Studio dashboard connected to the BigQuery audit_log table for self-service pipeline health visibility. Cloud Monitoring alerting policies fire on Dataflow job failures and non-zero error element counts. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | GCP Dataflow with Apache Beam JDBC IO Connector | — | Yes |
| Processing | Apache Beam SDK (Python or Java) on Dataflow Runner | — | Yes |
| Storage | BigQuery (target + audit_log) + GCS (state, quarantine, schema snapshots) | — | Yes |
| Orchestration | Cloud Composer 2 (managed Apache Airflow) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio (audit_log dashboard) | — | Yes |
| Iac | Terraform (GCP provider) | — | No |

### Pros

- Petabyte-scale horizontal autoscaling via Dataflow worker parallelism — handles any future table volume growth without structural re-architecture
- Apache Beam BigQuery Storage Write API provides exactly-once delivery semantics, preventing duplicate records during retries or worker restarts
- Mature production-tested ecosystem: JDBC IO, BigQuery IO, and GCS IO connectors have extensive community and GCP support coverage
- Cloud Composer DAG can enforce the historical load gate by holding the incremental DAG in a paused state with an Airflow sensor polling the audit_log for a successful full load sign-off
- Dataflow job-level metrics (elements processed, error rate, throughput, worker count) are natively exported to Cloud Monitoring, enabling precise SLA-bound alerting

### Cons

- Apache Beam requires specialized engineering expertise; building and maintaining JDBC-based pipelines with custom schema validation, null logging, and PK dedup logic imposes a steep learning curve and high maintenance surface
- Dataflow worker cold start latency of 2 to 4 minutes is non-trivial for hourly batch windows and may consume a material fraction of the processing window for modest change volumes
- Cloud Composer 2 plus Dataflow worker costs make this the most expensive option, particularly at unknown or low data volumes where autoscaling does not amortize fixed overhead
- Debugging Beam pipeline failures mid-bundle (e.g., type coercion errors on specific rows) requires understanding distributed execution semantics and is significantly harder than debugging sequential Python code
- JDBC IO connector from Cloud SQL requires either a Cloud SQL Auth Proxy sidecar or VPC-native connectivity configuration, adding network and security setup complexity before any pipeline code is written

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Beam bundle retries may produce partial writes if the Storage Write API stream is not finalized atomically; an incorrect watermark checkpoint written after a partial incremental run can cause record gaps or duplicates on the next execution cycle |
| Scaling | If the employees table contains LOB columns (LONGTEXT, BLOB, JSON), JDBC IO split estimation may produce severely skewed bundles causing worker OOM failures; explicit split field and bundle size tuning is required before production use |
| Latency | Dataflow cold start overhead of 2 to 4 minutes means a nominal 60-minute incremental window may have only 50 to 55 minutes of actual processing time, which may not be sufficient for large delta sets without pre-warmed workers |
| Cost | Dataflow charges per vCPU-hour and per GB shuffled; without a known data volume for the employees table, cost cannot be estimated and over-provisioned worker counts will inflate monthly spend significantly for small tables |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 2 | 5 | 2 | 4 | 3 | **3.15** |

---

## Option 2 — Cloud Composer + Cloud Run Jobs (Python Micro-Batch ETL)

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer schedules Cloud Run Jobs on a daily (or hourly) cadence. Each job executes a Python ETL container that connects to Cloud SQL MySQL (agentichub.employees) via the Cloud SQL Python Connector using IAM-based authentication without a proxy sidecar. Full load fetches all rows with cursor-based pagination; incremental load reads rows where updated_at or primary key exceeds the last watermark value stored in a BigQuery metadata control table. |
| Processing | Python ETL script performs: (1) pre-load schema introspection by comparing MySQL INFORMATION_SCHEMA against BigQuery INFORMATION_SCHEMA and flagging type mismatches and new columns per a defined handling policy (auto-add, quarantine, or reject); (2) null constraint violation detection and logging before write; (3) BigQuery MERGE-based upsert for PK deduplication and idempotent incremental application; (4) post-load row count reconciliation via MySQL SELECT COUNT(*) versus BigQuery SELECT COUNT(*); (5) structured audit record written to the BigQuery audit_log table on completion or failure. |
| Storage | Records loaded into BigQuery (verizon_data_deah dataset) via the BigQuery Storage Write API in batch-committed mode. GCS stores watermark state files, schema snapshot JSON files per run, and quarantined rows for records that fail validation. BigQuery audit_log is the primary audit surface. |
| Consumption | Analytics and reporting teams query BigQuery directly. Stakeholder Yash accesses a Looker Studio dashboard connected to the BigQuery audit_log table for self-service load health visibility covering status, row counts, detected schema changes, and failure details. Cloud Monitoring alerting policies fire on Cloud Run Job non-zero exit codes within a configurable SLA window. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Run Jobs (Python, Cloud SQL Python Connector + SQLAlchemy) | — | Yes |
| Processing | Python ETL script (google-cloud-bigquery SDK, pandas optional) within Cloud Run Job container | — | Yes |
| Storage | BigQuery (target + audit_log + metadata control table) + GCS (state, quarantine, schema snapshots) | — | Yes |
| Orchestration | Cloud Composer 2 (managed Apache Airflow) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio (audit_log dashboard) | — | Yes |
| Iac | Terraform (GCP provider) | — | No |

### Pros

- Python-based implementation is broadly understood across data engineering teams, reducing onboarding time, debugging complexity, and long-term maintenance overhead compared to distributed Beam pipelines
- Cloud Run Jobs are fully serverless with per-execution billing and zero idle cost, making this significantly cheaper than Cloud Composer plus Dataflow at low-to-medium data volumes
- Cloud SQL Python Connector provides IAM-authenticated, connection-pool-safe access to Cloud SQL without a proxy sidecar process, simplifying both local development and production deployment
- Cloud Composer sensor on the BigQuery audit_log cleanly enforces the historical load gate: the incremental DAG remains paused until a successful full load sign-off record is detected, satisfying the gating requirement natively in Airflow
- Looker Studio dashboard connected to the BigQuery audit_log table provides stakeholder Yash independent, real-time visibility into load status, row counts, schema drift alerts, and failure reasons without developer involvement
- BigQuery MERGE upsert pattern is idempotent and safe to re-run, naturally enforcing PK uniqueness as part of the merge key without a separate deduplication pass

### Cons

- Cloud Run Job execution is bounded by a 24-hour timeout; an extremely large historical load on a single wide table may require explicit chunked execution logic to stay within this limit
- Python single-process memory is bounded by the Cloud Run Job container memory ceiling (maximum 32 GB); very high-cardinality or wide-schema exports require explicit cursor-based chunked fetch logic to avoid OOM failures
- Cloud Run Jobs do not provide native horizontal fan-out for parallel table shards; parallelism across multiple tables or date partitions must be implemented via Composer task-level fan-out, adding DAG complexity
- Schema drift handling (new column detection and policy enforcement) relies entirely on custom Python logic rather than a managed schema registry service, requiring disciplined implementation and regression testing to prevent silent data loss
- Cloud Composer 2 environment incurs a baseline infrastructure cost of approximately $300 to $500 per month regardless of job frequency, which may not be cost-justified for a single-table daily pipeline without additional workloads sharing the environment

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Watermark-based incremental strategy depends on a reliable updated_at timestamp or monotonic primary key in the employees table; if the source lacks such a column or records can be backdated by source application writes, incremental loads will miss updates silently without any error signal |
| Scaling | Cloud Run Job container memory ceiling limits in-memory processing of extremely large result sets in a single execution; absent chunked pagination logic, tables exceeding available memory will produce OOM failures that require re-architecture of the fetch layer |
| Latency | Cloud Run Job cold start is typically under 10 seconds for pre-built Python containers, which is negligible for daily cadence; however, if hourly cadence is adopted with tight end-to-end SLAs, the combined Composer trigger, job spin-up, and execution time must be profiled against available window |
| Cost | Cloud Composer 2 small environment costs $300 to $500 per month at minimum; for a single daily table load this fixed orchestration overhead may not be cost-justified and should be evaluated against the number of additional pipelines planned to share the environment |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 4 | 4 | 4 | 4 | 4 | **4.00** |

---

## Option 3 — GCP Datastream (CDC Backfill + Incremental) + Cloud Composer Validation Gate + BigQuery ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | GCP Datastream is configured with a MySQL source connection to Cloud SQL (verizon-data:us-central1:mysql-druid-metadatastore, agentichub.employees) using binary log CDC mode. A Datastream backfill job executes the one-time full historical load, writing all existing rows as change events to a GCS landing bucket in Avro format. Ongoing incremental CDC events are written to the same GCS bucket on a configurable staleness window aligned to the daily (or hourly) batch cadence. |
| Processing | Cloud Composer orchestrates a two-phase pipeline. Phase 1 (Historical Gate): a BigQuery batch load job ingests the GCS backfill Avro files into a BQ staging table; a Composer SQL operator executes pre-load schema compatibility checks comparing MySQL INFORMATION_SCHEMA against BigQuery INFORMATION_SCHEMA for type mismatches and new columns; a Cloud SQL hook executes SELECT COUNT(*) on the source and compares against BigQuery COUNT(*) for 100% row completeness validation; null constraint violations are logged to the audit_log table; a BigQuery MERGE statement deduplicates on PK and writes to the target employees table; a sign-off audit record is written to the BigQuery audit_log marking the historical load as validated. Incremental loads are gated by a Composer ExternalTaskSensor polling the audit_log for the historical sign-off record. Phase 2 (Incremental): on each scheduled cycle, a Composer task triggers a BigQuery load job from the GCS Datastream landing prefix for the cycle window into a staging table, executes the same schema check, row count delta validation, MERGE upsert, and audit write sequence. |
| Storage | GCS landing bucket receives all Datastream Avro change event files partitioned by stream and timestamp. BigQuery (verizon_data_deah dataset) holds: the target employees table (deduplicated and upserted via MERGE on PK), audit_log table (one record per pipeline execution with status, row counts, schema snapshot delta, failure details), and schema_registry table (column-level snapshot per run for drift detection and alerting). BigQuery is the single query surface for all analytics consumption. |
| Consumption | Analytics and reporting teams query BigQuery (verizon_data_deah.employees) directly. Stakeholder Yash accesses a Looker Studio dashboard connected to the BigQuery audit_log table for independent, developer-free visibility into load health including run status, source-to-target row count comparison, detected schema changes, last successful run timestamp, and failure root cause. Cloud Monitoring alerting policies trigger on Datastream stream errors, Datastream lag exceeding threshold, Cloud Composer task failures, and BigQuery load job errors within the configured SLA notification window. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | GCP Datastream (MySQL CDC with backfill, GCS destination) | — | Yes |
| Processing | BigQuery (MERGE SQL for dedup and upsert, schema check SQL via INFORMATION_SCHEMA) + Cloud Composer Airflow operators | — | Yes |
| Storage | BigQuery (target employees table + audit_log + schema_registry) + GCS (Datastream landing zone, Avro change event files) | — | Yes |
| Orchestration | Cloud Composer 2 (managed Apache Airflow) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio (BigQuery audit_log dashboard) | — | Yes |
| Iac | Terraform (GCP provider) | — | No |

### Pros

- Datastream is a fully managed serverless CDC service — no custom ingestion code, no JDBC connectors, no connection pool management; the ingestion layer maintenance surface is reduced to stream configuration only
- Datastream backfill natively handles the one-time full historical load under the same service boundary as incremental CDC, eliminating the need for a separate historical extraction tool and ensuring consistent delivery semantics across both phases
- Datastream auto-detects new columns added to the MySQL source and propagates them to the BigQuery destination table, satisfying the new-column handling requirement with configurable policy (auto-add with notification) rather than fragile custom detection code
- BigQuery MERGE-based upsert is idempotent: re-running an incremental cycle on the same GCS prefix produces identical results, naturally enforcing PK uniqueness and preventing duplicates without a separate deduplication pass
- Cloud Composer ExternalTaskSensor or audit_log polling sensor cleanly enforces the historical load gate requirement: the incremental DAG is held in a paused or blocked state until the Phase 1 sign-off audit record is written, with zero custom gating code beyond a SQL condition
- All components operate under Google-managed SLAs — Datastream 99.9%, BigQuery 99.99%, GCS 99.9%, Cloud Composer 99.9% — minimizing operational toil and providing a defensible SLA foundation for stakeholder commitments
- Datastream stream lag metrics are natively exported to Cloud Monitoring, enabling precise alerting on CDC pipeline health without custom log parsing or metric instrumentation

### Cons

- Datastream requires MySQL binary logging to be enabled on the Cloud SQL instance with binlog_row_image set to FULL and binlog_format set to ROW; these settings must be confirmed and configured before any pipeline work can begin and require Cloud SQL instance restart in some versions
- Datastream CDC requires a dedicated MySQL replication user with REPLICATION SLAVE, REPLICATION CLIENT, and SELECT privileges; this is a security configuration step requiring DBA coordination and may face organizational approval latency
- The GCS-to-BigQuery MERGE chain introduces a multi-step pipeline: Datastream writes to GCS, Composer triggers a BQ load job, then a MERGE executes; this adds 5 to 15 minutes of end-to-end lag beyond Datastream write latency, which is acceptable for daily SLAs but must be validated for hourly cadence targets
- Datastream pricing is per GB of CDC data processed; for high-churn tables with frequent bulk updates, CDC byte volume may exceed initial estimates and inflate costs relative to a daily full-snapshot approach
- Datastream does not natively provide a source-to-target row count reconciliation mechanism; post-load COUNT(*) validation against the MySQL source must be implemented as a Cloud Composer task using a Cloud SQL operator hook, adding a custom validation component to an otherwise code-minimal architecture

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Datastream CDC depends on MySQL binlog retention continuity; if the Datastream stream falls behind due to a Composer environment outage or GCS bottleneck and the Cloud SQL binlog is purged before all events are consumed, a full resync backfill is required, creating a temporary data gap in BigQuery during the resync window |
| Scaling | High-velocity tables with millions of change events per day will generate large numbers of small Avro files in the GCS landing bucket; without Composer-triggered file compaction or an appropriate Datastream batch interval, BigQuery load job performance may degrade and GCS object count may grow unbounded |
| Latency | The GCS landing plus BigQuery load plus MERGE chain introduces an additional 5 to 15 minutes of processing lag beyond Datastream write latency; this is within daily batch SLAs but must be explicitly measured for the hourly cadence path to confirm the end-to-end window is achievable given employees table change volume |
| Cost | Datastream charges approximately $0.50 per GB of CDC data processed; without a known row count and change rate for the employees table, monthly Datastream cost cannot be bounded — a high-churn table or large initial backfill volume could exceed budget expectations relative to a simpler snapshot-based approach |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 3 | 5 | 4 | 5 | 4 | **4.10** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Apache Beam/Dataflow JDBC Batch ETL | 2 | 5 | 2 | 4 | 3 | **3.15** |
| Cloud Composer + Cloud Run Jobs (Python Micro-Batch ETL) | 4 | 4 | 4 | 4 | 4 | **4.00** |
| GCP Datastream (CDC Backfill + Incremental) + Cloud Composer Validation Gate + BigQuery ✅ | 3 | 5 | 4 | 5 | 4 | **4.10** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**GCP Datastream (CDC Backfill + Incremental) + Cloud Composer Validation Gate + BigQuery**
**Weighted Score: 4.10**

**Justification:** Option 3 is recommended as the primary architecture for the MySQL to BigQuery Data Ingestion Pipeline. GCP Datastream delivers a fully managed, binlog-based CDC ingestion layer that eliminates custom extraction code and natively satisfies the full historical load, incremental sync, and schema evolution requirements under a single managed service boundary. The Cloud Composer two-phase orchestration cleanly enforces the historical load gate requirement via an audit_log sensor with no workarounds. BigQuery MERGE-based upserts enforce PK uniqueness and idempotency natively. The Looker Studio plus audit_log design gives stakeholder Yash independent, developer-free pipeline health visibility — a first-class requirement explicitly called out in the business context. All components operate under Google-managed SLAs, minimizing operational toil and providing a defensible reliability foundation as additional tables are onboarded to the same Datastream stream.

**Why highest score:** Option 3 achieves the highest weighted score (4.10) by scoring 5 out of 5 on both scalability and latency — the two criteria that determine long-term architectural fitness for a growing analytics platform. Its complexity score of 4 out of 5 reflects the minimal custom code surface enabled by Datastream managed CDC and BigQuery native schema evolution, compared to custom Python or Beam pipelines. While its cost score of 3 out of 5 is lower than Option 2 (4 out of 5) due to Datastream per-GB pricing uncertainty, the operational savings from eliminating custom ingestion maintenance, the superior latency headroom enabling future sub-hourly cadences without re-architecture, and the managed schema evolution capability that reduces long-term drift-handling debt justify the cost delta. As additional tables are onboarded, each new table is added to the existing Datastream stream with no new infrastructure, amortizing the fixed overhead across a growing workload portfolio.

**Trade-offs accepted:** The following trade-offs are explicitly accepted under this recommendation: (1) Datastream per-GB pricing introduces cost uncertainty at unknown data volumes — mitigated by enabling Cloud Billing budget alerts and a Cloud Monitoring alert on Datastream bytes-processed metric before go-live; (2) MySQL binlog must be enabled with row-image format FULL on the Cloud SQL instance — accepted as a one-time DBA configuration step with low ongoing operational risk and a well-documented Cloud SQL procedure; (3) the GCS landing zone adds a processing hop versus direct BigQuery streaming — accepted given the batch SLA requirement and the replay capability this hop provides in the event of downstream failures; (4) native row-count reconciliation between MySQL source and BigQuery target must be implemented as a custom Cloud Composer task — accepted as a small, well-bounded validation component that does not affect the core ingestion architecture and is testable in isolation.

---

## Rejected Options

### Cloud Composer + Apache Beam/Dataflow JDBC Batch ETL

Despite best-in-class scalability, this option incurs the highest implementation complexity and operational cost. With an unknown data volume and a single-table starting scope, Dataflow horizontal autoscaling is overengineered. The Apache Beam expertise requirement and JDBC connector setup overhead create unnecessary delivery risk for a batch pipeline with a simple source schema. Option 3 matches or exceeds scalability with significantly lower complexity, managed schema evolution, and comparable total cost of ownership. Option 2 is the recommended fallback if Datastream CDC is unavailable.

### Cloud Composer + Cloud Run Jobs (Python Micro-Batch ETL)

A strong, balanced option that scores uniformly well across all criteria and is the recommended fallback if GCP Datastream CDC is unavailable (e.g., binlog not enabled on the Cloud SQL instance or replication privileges cannot be granted). However, it falls short of Option 3 on both scalability (4 vs 5) and latency headroom (4 vs 5). As the number of source tables grows, the custom Python validation and schema drift logic accumulates technical debt that Option 3 avoids via managed schema evolution in Datastream. Option 3 is preferred for greenfield implementations where binlog access can be confirmed.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Credential Exposure | The MySQL connection credentials including host IP 34.70.79.163, port 3306, and username sa are specified in plaintext in the architecture requirements document. Propagating these values into pipeline configuration files, Terraform variables, or environment variables without a secrets management layer creates a persistent credential exposure risk across all development, staging, and production environments. | Store all MySQL credentials including password in GCP Secret Manager before any pipeline component is provisioned. Configure Datastream and Cloud Composer to reference Secret Manager resource IDs rather than plaintext values. Enforce Secret Manager access via dedicated service account with minimal IAM scope. Rotate the sa password before first production deployment and implement a 90-day rotation policy. |
| Data Completeness — Missing Change Indicator | If the agentichub.employees table lacks a reliable updated_at timestamp or monotonically increasing primary key, incremental loads cannot reliably identify changed or updated records, creating silent data gaps between MySQL source and BigQuery target that accumulate undetected over time. | Perform a schema audit of the employees table before pipeline design is finalized to confirm the presence and reliability of an incremental change indicator. If absent, implement a full table reload strategy (daily TRUNCATE plus INSERT OVERWRITE) as an interim measure until a proper change tracking column is added to the source schema by the owning application team. |
| Binlog Retention Gap | Datastream CDC depends on continuous MySQL binlog availability. If the Datastream stream falls behind due to a Cloud Composer environment outage, GCS connectivity issue, or extended maintenance window, and the Cloud SQL binlog is purged before all outstanding change events are consumed, those events are permanently lost and a full resync backfill is required, causing a temporary data gap in BigQuery during the resync period. | Configure Cloud SQL binlog retention to a minimum of 7 days using the binlog_expire_logs_seconds parameter. Implement a Cloud Monitoring alert on Datastream stream lag exceeding 50 percent of the binlog retention window to trigger an operations response before events are at risk of expiry. Document the resync runbook and include it in the operational handover package. |
| Schema Drift — Consumer Impact | New columns added to the MySQL employees table will be auto-detected by Datastream and propagated to the BigQuery target table. While this satisfies the new-column handling requirement, downstream analytics queries, Looker Studio reports, and dbt models built on a fixed schema may break silently or produce incorrect results if column additions are not communicated to consumers before propagation. | Implement a schema change notification in Cloud Composer: compare the BigQuery INFORMATION_SCHEMA column snapshot for each run against the previous run stored in the schema_registry table, and trigger a Cloud Monitoring alert plus stakeholder email notification on any detected column addition, removal, or type change before the affected load cycle is marked complete. |
| Cost Overrun — Unknown Volume | Data volume and change rate for the employees table are unspecified. If the table has very high row churn due to frequent bulk application updates, Datastream CDC byte volume and BigQuery load job costs may significantly exceed initial estimates, causing monthly GCP billing to spike without a cost ceiling in place. | Configure a Cloud Billing budget alert at 80 percent, 100 percent, and 120 percent of the estimated monthly cost baseline before go-live. Enable a Cloud Monitoring alert on Datastream cumulative bytes-processed per day with a threshold calibrated to the acceptable cost ceiling. If CDC byte volume proves excessive, evaluate switching the employees table to a daily full-snapshot approach using Option 2 as a cost-controlled fallback for that specific table. |
| Stakeholder Visibility — Single Channel Dependency | Stakeholder Yash requires independent visibility into pipeline health without developer involvement. If the Looker Studio dashboard becomes unavailable due to IAM misconfiguration, service disruption, or BigQuery audit_log table deletion, the stakeholder has no alternative visibility channel and cannot determine pipeline health without developer escalation, violating a first-class business requirement. | Implement a secondary email-based daily pipeline health summary delivered via Cloud Monitoring notification channel directly to stakeholder Yash, independent of the Looker Studio layer. The email should include run status, source and target row counts, last successful run timestamp, and any active alert conditions, ensuring visibility continuity even when BI tooling is unavailable. |

---

## Assumptions

1. MySQL binary logging (binlog) is either already enabled or can be enabled on Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore with binlog_format=ROW and binlog_row_image=FULL — a hard prerequisite for Option 3 (Datastream CDC); if this cannot be confirmed, Option 2 (Cloud Run Jobs) is the fallback
2. The agentichub.employees table contains at least one reliable incremental change indicator — either an updated_at timestamp column, a created_at timestamp column, or a monotonically increasing integer primary key — enabling consistent watermark-based delta identification for incremental load cycles
3. Data volume for the employees table is unknown at architecture design time; all three options are designed to scale from thousands to hundreds of millions of rows without structural re-architecture, with cost scaling linearly under each option's respective pricing model
4. The BigQuery dataset verizon_data_deah already exists in the target GCP project, or will be provisioned as part of Terraform IaC execution before pipeline deployment; the target employees table schema will be derived from the MySQL source schema using documented MySQL-to-BigQuery type mapping rules
5. IAM permissions in the target GCP project allow creation and configuration of Datastream streams, Cloud SQL connections, Cloud Composer 2 environments, BigQuery datasets and tables, and GCS buckets in the us-central1 region
6. Stakeholder Yash has been granted read-only access to the Looker Studio dashboard and the BigQuery verizon_data_deah.audit_log table; no elevated IAM roles are required for stakeholder monitoring access beyond BigQuery Data Viewer on the audit dataset
7. Network connectivity between Datastream, Cloud Composer, and the Cloud SQL instance is resolvable via VPC-native private IP, Private Service Connect, or authorized public IP access; the listed public IP 34.70.79.163 is assumed to be reachable with appropriate Cloud SQL authorized network configuration
8. No column-level data classification, PII masking, or tokenization requirement has been specified in the source requirements; if the employees table contains PII (names, SSNs, contact details, email addresses), a masking layer must be added before BigQuery storage and is explicitly out of scope for this architecture document
9. The SLA duration for pipeline failure alert notification is assumed to be 30 minutes from failure event detection, inferred from the analytics team dependency and business context; this assumption must be confirmed with stakeholder Yash before Cloud Monitoring alert threshold configuration
10. The incremental load cadence is assumed to default to daily as the primary schedule, with hourly available as an upgrade path requiring only Cloud Composer schedule interval adjustment and Datastream staleness window tuning with no structural pipeline changes
11. All MySQL connection credentials including the password for username sa will be stored in GCP Secret Manager before any pipeline component is provisioned; no credentials will be stored in plaintext in Terraform state files, Composer DAG code, or GCS configuration objects
12. The GCP project billing account has sufficient quota for Datastream stream creation, Cloud Composer 2 environment provisioning, and BigQuery slot allocation in the us-central1 region; no quota increase requests are assumed to be pending

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| GCP Datastream selected as ingestion layer with GCS landing zone and Cloud Composer-triggered BigQuery MERGE for incremental sync | Implement a scheduled incremental data load pipeline that continuously syncs new and updated records from MySQL employees table to BigQuery on a per-table cadence (hourly or daily) | daily (primary cadence); hourly (optional upgrade path) | — |
| Datastream backfill job used for one-time full historical load of agentichub.employees, writing all existing rows as change events to GCS landing bucket before CDC stream activation | Execute a one-time full historical load of the MySQL employees table (agentichub) into BigQuery verizon_data_deah dataset with 100% data completeness and no data loss | — | — |
| Cloud Composer ExternalTaskSensor polling BigQuery audit_log for historical load sign-off record gates incremental DAG activation | Gate incremental load activation: incremental pipeline must not begin until historical load validation is fully passed and signed off | — | — |
| BigQuery MERGE statement on primary key used for all incremental load cycles into verizon_data_deah.employees | Enforce primary key uniqueness in BigQuery after every load execution; prevent data duplication and gaps across all incremental load cycles | — | — |
| Pre-load schema compatibility check implemented as a Cloud Composer SQL operator comparing MySQL INFORMATION_SCHEMA against BigQuery INFORMATION_SCHEMA with configurable new-column handling policy | Perform pre-load schema compatibility checks covering data types, null handling, field names, and new column handling strategy before each load execution | — | — |
| Post-load row count reconciliation implemented as a Cloud Composer task executing SELECT COUNT(*) on the MySQL source via Cloud SQL operator and comparing against BigQuery SELECT COUNT(*) after each load cycle | Perform post-load row count validation between MySQL source and BigQuery target for every load cycle | — | — |
| BigQuery audit_log table populated by Cloud Composer after each pipeline execution with status, row counts, schema snapshot, and failure details; Looker Studio dashboard connected to audit_log for stakeholder self-service access | Generate and store audit logs for every load execution, accessible after each run; implement a monitoring dashboard or log-based visibility layer enabling stakeholders to independently review load success without developer involvement | — | — |
| Cloud Monitoring alerting policies configured on Datastream stream errors, Datastream lag threshold, Cloud Composer task failures, and BigQuery load job errors with notification channels targeting operations team and stakeholder Yash | Trigger monitoring alerts on pipeline failures within a defined SLA | 30-minute assumed SLA notification window — unconfirmed, must be validated with stakeholder Yash | — |
| Null constraint violation detection implemented as a Cloud Composer SQL operator querying staging table for NULL values in NOT NULL target columns before MERGE execution; violations logged to audit_log before load is marked complete | Log and report null constraint violations before marking any load as complete | — | — |
| All MySQL credentials stored in GCP Secret Manager; Datastream source connection and Cloud Composer Cloud SQL hook reference Secret Manager resource IDs exclusively | Source connection to Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore with credentials specified in source_connections | — | — |
| Watermark stored in BigQuery metadata control table tracking last successfully processed updated_at value or primary key per table, read at the start of each incremental cycle and updated only on successful audit_log sign-off | Track incremental changes using timestamp-based or primary key delta strategies, consistently applied across all runs | — | — |
| Terraform used for IaC provisioning of all GCP resources including Datastream stream, Cloud Composer environment, BigQuery datasets and tables, GCS buckets, IAM bindings, and Secret Manager secrets | Pipeline must be reliable and scalable to support ongoing scheduled loads, potential additional tables, and both hourly and daily cadences | — | — |

---

## Open Questions — Action Required

1. Is MySQL binary logging currently enabled on Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore with binlog_format=ROW and binlog_row_image=FULL? If not, does the DBA team have authority and an estimated timeline to enable it? This is a hard prerequisite for Option 3 (Datastream) and must be confirmed before any pipeline implementation begins.
2. Can a dedicated MySQL replication user with REPLICATION SLAVE, REPLICATION CLIENT, and SELECT privileges be created on the agentichub database for Datastream use? If organizational policy prohibits replication-level grants, Option 2 (Cloud Run Jobs with standard read-only user) is the required fallback.
3. What is the approximate current row count of the agentichub.employees table and what is the estimated daily change rate (INSERT, UPDATE, and DELETE operations per day)? These figures are required to estimate Datastream processing costs, BigQuery load job sizing, and to determine whether a daily full-snapshot approach is more cost-effective than CDC.
4. Does the employees table contain a reliable updated_at timestamp column or a monotonically increasing integer primary key that can serve as the incremental watermark? If neither exists, what is the source application team's plan and timeline to add one, and should the initial implementation use daily full-snapshot as an interim strategy?
5. What is the quantified SLA duration for pipeline failure alert notification? The requirement states alerts must trigger within a defined SLA but does not specify a duration. This document assumes 30 minutes — please confirm or provide the correct value so Cloud Monitoring alert evaluation windows can be configured accurately.
6. What is the defined handling policy for new columns appearing in the MySQL employees table before they are loaded into BigQuery? The three standard options are: (a) auto-add the column to the BigQuery target table and send a schema change notification; (b) quarantine rows containing the new column and block load completion pending review; (c) reject the load entirely and halt pipeline execution until the schema change is reviewed and approved. This decision must be made before implementation.
7. Does the agentichub.employees table contain Personally Identifiable Information such as full names, email addresses, phone numbers, Social Security Numbers, date of birth, or compensation data? If yes, data classification, masking, tokenization, and access control requirements must be defined before pipeline deployment and will require an architecture amendment.
8. What GCP project ID and billing account should Datastream, Cloud Composer 2, BigQuery, GCS, and Secret Manager resources be provisioned under? No project ID is specified in the requirements and this is required before any Terraform configuration can be written.
9. Is the Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore accessible via VPC-native private IP from the target GCP project using VPC peering or Private Service Connect? If only the public IP 34.70.79.163 is available, authorized network configuration and TLS enforcement requirements must be defined before connectivity can be established.
10. Are there additional MySQL tables in the agentichub database beyond employees that are planned for onboarding to this pipeline within the next 6 months? The answer determines whether the Datastream stream should be scoped to the employees table only or to the full agentichub database schema from day one, which affects both cost and schema management strategy.
11. Who is the designated approver for the historical load Phase 1 sign-off gate? Is stakeholder Yash the human approver who must explicitly confirm the row count and schema validation results before incremental loads activate, or is this an automated validation-only gate that self-approves on passing all checks? This determines whether a manual approval step (Airflow pause + external trigger) or a fully automated sensor pattern is implemented.
