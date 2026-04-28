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

> **Build with:** Cloud Composer + Cloud Run Jobs (Orchestrated Serverless ETL)
>
> **Why:** Option 2 delivers the optimal balance of orchestration integrity, operational transparency, cost efficiency, and implementation complexity for this use case. Cloud Composer satisfies the hard gating requirement (incremental pipeline cannot activate before historical load validation sign-off) natively through DAG task dependencies — no custom state management code required. Cloud Run Jobs provide a cost-efficient, fully serverless processing layer that handles all defined validation steps (schema check, row count, PK dedup, null logging, audit trail) in standard Python without requiring Apache Beam expertise. Stakeholder Yash's first-class self-service visibility requirement is met by the Airflow DAG run history UI for operational monitoring plus a Looker Studio dashboard on the BigQuery audit_log table for business-level reporting, both deployable without custom application code.
>
> **Score:** 6.85 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2 ✅ | Option 3  |
|---|---||---||---|
| **Name** | Cloud Composer + Apache Beam Dataflow (Enterprise ETL) | Cloud Composer + Cloud Run Jobs (Orchestrated Serverless ETL) | Cloud Scheduler + Cloud Run Jobs (Serverless Minimal) |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Google Cloud Dataflow (Apache Beam 2.x) | Cloud Run Jobs (Python 3.11, google-cloud-bigquery SDK, BigQuery Storage Write API) | Cloud Run Jobs (Python 3.11, google-cloud-bigquery SDK, BigQuery Storage Write API) |
| **Storage** | BigQuery + Google Cloud Storage | BigQuery + Google Cloud Storage + Artifact Registry | BigQuery + Google Cloud Storage |
| **Weighted Score** | **6.15** | **6.85**  ✅ | **6.75** |

---

## Option 1 — Cloud Composer + Apache Beam Dataflow (Enterprise ETL)

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 triggers Dataflow jobs via DataflowStartFlexTemplateOperator; Dataflow reads from Cloud SQL MySQL (agentichub.employees) using Apache Beam JDBC I/O through Cloud SQL Auth Proxy sidecar; full load issues an unbounded SELECT with server-side cursor pagination; incremental load queries WHERE updated_at > last_watermark value stored in a BigQuery control_watermarks table |
| Processing | Apache Beam pipeline applies explicit MySQL-to-BigQuery type coercion transforms, executes schema compatibility check (column names, types, nullability, new-column detection) against BigQuery table metadata, deduplicates on primary key via CoGroupByKey, counts source and target rows for post-load validation, logs null constraint violations per column to Cloud Logging; incremental upsert applied via BigQuery MERGE DML; structured audit record written to BQ audit_log table on every job completion or failure |
| Storage | BigQuery verizon_data_deah dataset with employees table date-partitioned by load_date and clustered by employee primary key; control_watermarks and audit_log tables in same dataset; GCS bucket provides Dataflow temp path, staging area for Flex Template artifacts, and intermediate AVRO staging files |
| Consumption | Analytics and reporting teams query BigQuery via SQL, Looker Studio, or BigQuery Studio; stakeholder Yash accesses Cloud Monitoring custom dashboard built on log-based metrics derived from Dataflow structured job logs and Airflow task-level logs; Cloud Monitoring alerting policy triggers PagerDuty or email notification on job failure within the defined SLA window |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud SQL Auth Proxy + Apache Beam JDBC I/O via Dataflow Flex Template | — | Yes |
| Processing | Google Cloud Dataflow (Apache Beam 2.x) | — | Yes |
| Storage | BigQuery + Google Cloud Storage | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio | — | Yes |
| Iac | Terraform (hashicorp/google provider) | — | No |

### Pros

- Dataflow autoscaling handles any future data volume growth including TB-scale payloads and multi-table expansion with no infrastructure changes
- Apache Beam JDBC I/O provides native fault-tolerant reads from Cloud SQL with built-in retry semantics and job-level checkpointing
- Cloud Composer natively enforces the historical-load gate as a DAG TaskGroup dependency — incremental pipeline activation requires explicit validation sensor task success, satisfying the hard gating requirement without custom state management
- Dataflow per-step element counters provide granular row count metrics directly inside the pipeline, enabling precise source-to-target validation without a separate post-load query
- Strongest enterprise audit story: Dataflow job execution graph, Airflow task-level logs, and BigQuery audit_log table provide full end-to-end lineage and traceability

### Cons

- Highest infrastructure cost floor: Cloud Composer 2 requires an always-on GKE Autopilot cluster (~$200-400/month minimum); Dataflow charges per vCPU-hour and per GB shuffled even for small tables
- Highest engineering complexity: requires Apache Beam SDK expertise for JDBC pipeline authoring, Dataflow Flex Template packaging, Artifact Registry setup, and Airflow DAG development
- Dataflow worker cold-start provisioning (2-4 minutes) consumes a meaningful fraction of an hourly execution window before any data movement begins
- Architectural overkill for a single-table pipeline with unknown and likely modest data volume; ROI on Dataflow complexity only realized at confirmed high-volume or multi-table scale

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | JDBC I/O type coercion between MySQL and BigQuery (e.g., DECIMAL precision loss, DATETIME timezone semantics, TINYINT(1) to BOOL mapping) must be explicitly implemented in Beam transforms; silent truncation or type mismatch risk is high if schema check step does not validate every column type before load |
| Scaling | Dataflow maxWorkers must be explicitly capped to prevent runaway cost if a source query returns an unexpectedly large result set; without a cap, an uncontrolled full-table scan on a large employees table could incur significant per-worker-hour charges |
| Latency | Dataflow worker startup adds 2-4 minutes of overhead to every job invocation; for hourly incremental cadence this is acceptable, but it means the effective data freshness window is the cadence interval plus startup time |
| Cost | Without confirmed data volume, Dataflow cost is unpredictable; a large historical load without maxWorkers and BQ slot reservation guardrails could generate an unbounded cost spike on first execution |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 4 | 10 | 3 | 7 | 8 | **6.15** |

---

## Option 2 — Cloud Composer + Cloud Run Jobs (Orchestrated Serverless ETL) ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 triggers parameterized Cloud Run Jobs via GCPCloudRunJobExecuteAsyncOperator on defined DAG schedules; containerized Python job connects to Cloud SQL MySQL (agentichub.employees) via Cloud SQL Auth Proxy sidecar using pymysql with server-side cursor and paginated chunk extraction; full load issues a paginated SELECT across the full table; incremental load queries WHERE updated_at > last_watermark, with watermark value read from and written to a BigQuery control_watermarks table at job start and on successful completion |
| Processing | Cloud Run Job container sequentially executes: (1) pre-load schema compatibility check comparing MySQL information_schema column definitions against BigQuery table schema API response, flagging type mismatches, new columns, and null constraint conflicts; (2) paginated data extraction with explicit Python type mapping to BigQuery field types; (3) BigQuery Storage Write API batch write using COMMITTED mode for atomicity; (4) post-load row count comparison between MySQL COUNT(*) and BigQuery SELECT COUNT(*) for the load window; (5) PK uniqueness enforcement via BigQuery MERGE DML (DELETE duplicate keys then keep latest); (6) null constraint violation report logged as structured JSON to Cloud Logging; (7) structured audit record written to BigQuery audit_log table with status, row counts, schema diff, duration, and watermark values |
| Storage | BigQuery verizon_data_deah dataset; employees table date-partitioned by load_date, clustered by employee primary key; control_watermarks table stores last successful watermark per table; audit_log table stores every execution record; GCS bucket holds transient AVRO staging files and Cloud Run Job container images via Artifact Registry |
| Consumption | Analytics and reporting teams query BigQuery via SQL, Looker Studio, or BigQuery Studio; stakeholder Yash independently accesses Airflow DAG run history UI for visual run status and task-level logs, plus a Looker Studio dashboard on the BigQuery audit_log table showing per-run health, row count trends, last successful timestamp, and validation outcomes; Cloud Monitoring alerting policies on Cloud Logging log-based metrics fire email or PagerDuty alerts on Cloud Run Job failure events within the defined SLA evaluation window |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud SQL Auth Proxy sidecar + pymysql in Cloud Run Jobs container | — | Yes |
| Processing | Cloud Run Jobs (Python 3.11, google-cloud-bigquery SDK, BigQuery Storage Write API) | — | Yes |
| Storage | BigQuery + Google Cloud Storage + Artifact Registry | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio | — | Yes |
| Iac | Terraform (hashicorp/google provider) | — | No |

### Pros

- Cloud Composer natively enforces the historical-load gate as an Airflow TaskGroup sensor dependency — the incremental DAG cannot be triggered until the historical validation task returns a SUCCESS state, satisfying the hard gating requirement without fragile custom state management
- Cloud Run Jobs are fully serverless and pay-per-execution with zero idle cost, making the processing layer significantly cheaper than Dataflow for sub-hour batch windows without sacrificing reliability
- Python container gives complete flexibility to implement all validation requirements (schema check, row count, PK uniqueness, null logging, type mapping) using standard BigQuery client library with no Beam SDK expertise required
- Airflow DAG run history UI provides stakeholder Yash with a self-service visual view of pipeline run history, per-task success/failure, execution duration, and structured logs without any developer involvement
- Container-based parameterization simplifies future multi-table onboarding: each additional MySQL table becomes a new Cloud Run Job invocation with a table-config JSON argument, orchestrated by the same table-config-driven Composer DAG
- Cloud Run Job startup is under 30 seconds, imposing negligible overhead on hourly incremental execution windows compared to Dataflow worker provisioning

### Cons

- Cloud Composer 2 carries a minimum infrastructure cost of approximately $200-400/month for the always-on GKE Autopilot cluster, even for lightweight single-table DAGs
- Cloud Run Jobs enforce a 24-hour maximum execution timeout per job run, which constrains extremely large historical loads; mitigated by paginated chunked extraction with resumable checkpointing via GCS offset files
- BigQuery MERGE DML for PK deduplication generates transaction costs and consumes BigQuery slot capacity; for very large incremental batches, MERGE performance and slot contention must be actively monitored
- Schema evolution handling (new MySQL columns appearing before BigQuery schema update) must be explicitly coded in the container and tested end-to-end; a missing column mapping can cause load failures on the next schema drift event

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | pymysql cursor returns Python-native types; explicit field-level type mapping (MySQL DECIMAL to BQ NUMERIC with precision, DATETIME with UTC normalization, TINYINT(1) to BOOL) must be implemented in container code to prevent silent coercion on Storage Write API ingestion |
| Scaling | Cloud Run Job memory default is 512MB with a maximum of 32GB per instance; large employees tables must use server-side cursor with configurable chunk size to stay within memory limits; very wide rows or BLOB columns require explicit size profiling before setting job memory allocation |
| Latency | Hourly incremental jobs are well within Cloud Run Job execution characteristics (sub-minute startup, sub-hour runtime for expected volume); the only latency risk is if a MySQL Cloud SQL read replica lag introduces watermark staleness relative to the primary instance |
| Cost | BigQuery Storage Write API costs scale with bytes written; for high-frequency incremental loads, AVRO-format writes via the Storage Write API are preferred over JSON insertAll to reduce per-byte cost and improve throughput; Storage Write API COMMITTED mode avoids double-billing on retry |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 8 | 6 | 7 | 8 | **6.85** |

---

## Option 3 — Cloud Scheduler + Cloud Run Jobs (Serverless Minimal)

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Scheduler fires cron-based HTTP triggers targeting Cloud Run Job HTTP endpoints on defined hourly or daily schedules; separate Cloud Run Job definitions exist for full historical load and incremental load; Python container connects to Cloud SQL MySQL (agentichub.employees) via Cloud SQL Auth Proxy using pymysql; incremental watermark is stored as a JSON record in a BigQuery control_watermarks table; historical-load gate is enforced by a GCS sentinel object written only after all validation steps pass — incremental job reads this sentinel at startup and aborts if absent |
| Processing | Single Cloud Run Job container sequentially executes all ETL and validation steps: schema compatibility check against BigQuery table schema API, paginated row extraction, BigQuery Storage Write API batch write, post-load row count comparison, PK deduplication via MERGE DML, null constraint violation logging to Cloud Logging, and structured audit record insertion into BigQuery audit_log table; all orchestration logic (retry policy, step sequencing, error propagation) is implemented inside application code with no external workflow engine |
| Storage | BigQuery verizon_data_deah dataset; employees table date-partitioned by load_date; audit_log and control_watermarks tables in same dataset; GCS bucket stores watermark state JSON, staging files, and the historical-load gate sentinel object |
| Consumption | Analytics teams query BigQuery directly; stakeholder monitoring via Looker Studio dashboard built on BigQuery audit_log table showing per-run status, row counts, validation outcomes, and last successful timestamp; Cloud Monitoring alerting policies on Cloud Logging log-based metrics for Cloud Run Job failure events; no orchestration UI available — all operational visibility is dashboard-only |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud SQL Auth Proxy sidecar + pymysql in Cloud Run Jobs container | — | Yes |
| Processing | Cloud Run Jobs (Python 3.11, google-cloud-bigquery SDK, BigQuery Storage Write API) | — | Yes |
| Storage | BigQuery + Google Cloud Storage | — | Yes |
| Orchestration | Cloud Scheduler + GCS sentinel state management + BigQuery control table | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio | — | Yes |
| Iac | Terraform (hashicorp/google provider) | — | No |

### Pros

- Lowest infrastructure cost of all three options: Cloud Scheduler charges fractions of a cent per trigger execution; Cloud Run Jobs are pure pay-per-execution with zero idle infrastructure cost and no always-on cluster required
- Minimal GCP component surface area reduces the operational blast radius; fewer managed services means fewer potential failure modes at the infrastructure layer
- Cloud Run Job container is fully self-contained, independently unit-testable, and deployable with no orchestration framework dependency or learning curve
- Fastest time-to-bootstrap for proof-of-concept: no Cloud Composer environment provisioning (15-20 minute setup) required; Cloud Scheduler and Cloud Run Jobs can be created and executing in under 10 minutes via Terraform

### Cons

- No native workflow orchestration: the historical-load gate must be implemented as a GCS sentinel object check inside the incremental Cloud Run Job startup — this is a brittle, non-self-healing pattern that fails silently if the sentinel is accidentally deleted, overwritten, or written prematurely before all validation steps complete
- No orchestration UI: stakeholder Yash cannot visually inspect pipeline run history, per-step success or failure states, or re-trigger specific failed runs without developer assistance — fully custom Looker Studio development is required to compensate, adding build cost that partially negates the infrastructure cost savings
- Multi-step validation workflow (schema check → extract → load → row count → PK dedup → null log → audit write) is serialized inside a single container with no step-level visibility, partial retry capability, or mid-pipeline resume on failure
- Cloud Scheduler has no native retry-with-backoff on downstream job failure; a failed Cloud Run Job leaves the pipeline in a failed state until manually re-triggered or a secondary Cloud Function watchdog is built
- All orchestration, gating, retry, state management, and alert routing logic must be written, tested, and maintained as application code, shifting complexity from infrastructure to the codebase

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | GCS sentinel-based gate introduces a correctness risk: if the sentinel object is written before all validation sub-steps (row count check, PK uniqueness, null violation report) are confirmed complete, the incremental pipeline may activate against an incompletely validated historical load; this risk is difficult to eliminate without a proper orchestration framework with explicit task state management |
| Scaling | Without step-level checkpointing, a Cloud Run Job failure during a large historical load requires a full restart from row zero; for large tables, this means repeated full scans of the MySQL source and repeated Storage Write API costs on each failed attempt |
| Latency | Cloud Scheduler trigger execution is best-effort and may fire up to 1 minute late relative to the defined cron expression; for strict hourly SLAs, this introduces a small but non-deterministic latency jitter that cannot be eliminated without migrating to Cloud Tasks for precise scheduling |
| Cost | While per-execution infrastructure cost is lowest, the absence of orchestration tooling increases mean time to diagnose and recover from failures; a silent data gap that goes undetected until a downstream analyst reports it may require a costly full re-load of the historical dataset, representing a significant hidden OPEX cost |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 9 | 6 | 5 | 7 | 5 | **6.75** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Apache Beam Dataflow (Enterprise ETL) | 4 | 10 | 3 | 7 | 8 | **6.15** |
| Cloud Composer + Cloud Run Jobs (Orchestrated Serverless ETL) ✅ | 6 | 8 | 6 | 7 | 8 | **6.85** |
| Cloud Scheduler + Cloud Run Jobs (Serverless Minimal) | 9 | 6 | 5 | 7 | 5 | **6.75** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Composer + Cloud Run Jobs (Orchestrated Serverless ETL)**
**Weighted Score: 6.85**

**Justification:** Option 2 delivers the optimal balance of orchestration integrity, operational transparency, cost efficiency, and implementation complexity for this use case. Cloud Composer satisfies the hard gating requirement (incremental pipeline cannot activate before historical load validation sign-off) natively through DAG task dependencies — no custom state management code required. Cloud Run Jobs provide a cost-efficient, fully serverless processing layer that handles all defined validation steps (schema check, row count, PK dedup, null logging, audit trail) in standard Python without requiring Apache Beam expertise. Stakeholder Yash's first-class self-service visibility requirement is met by the Airflow DAG run history UI for operational monitoring plus a Looker Studio dashboard on the BigQuery audit_log table for business-level reporting, both deployable without custom application code.

**Why highest score:** Option 2 achieves the highest weighted score (6.85) by balancing all five scoring dimensions. It outscores Option 1 on Cost (6 vs 4) and Complexity (6 vs 3) without a material Scalability penalty (8 vs 10 — sufficient for the defined single-table batch scope at unknown but likely sub-TB volume). It outscores Option 3 on Scalability (8 vs 6) and Operability (8 vs 5) — dimensions that directly map to the two first-class non-functional requirements of this project: reliable multi-table expansion and stakeholder self-service visibility. The weighted score reflects that Cost (0.30 weight) is important but cannot override the hard functional requirement for proper orchestration that Options 3 fails to natively satisfy.

**Trade-offs accepted:** The Cloud Composer infrastructure cost floor (~$200-400/month for the GKE Autopilot cluster) is consciously accepted over Option 3's pure serverless model for three reasons: (1) proper workflow orchestration is a hard functional requirement for the historical-load gate and cannot be safely approximated with a GCS sentinel file; (2) the Airflow UI provides the stakeholder self-service monitoring visibility Yash requires without custom development effort; (3) the Composer cost is amortized across the expected multi-table expansion as this pipeline matures beyond the initial employees table. The scalability ceiling of Cloud Run Jobs relative to Dataflow is accepted because data volume is unknown and assumed to be sub-100GB; if volume is confirmed to exceed Cloud Run Job memory or timeout limits, the processing layer can be swapped to Dataflow Flex Templates with the Composer orchestration layer and all DAG logic remaining unchanged.

---

## Rejected Options

### Cloud Composer + Apache Beam Dataflow (Enterprise ETL)

Dataflow's enterprise-scale processing capabilities are architecturally disproportionate for a single-table batch pipeline of unknown but likely modest volume. The cost floor of Cloud Composer plus Dataflow is the highest of all options and is not justified without confirmed high-volume or multi-table requirements. Engineering complexity is the highest of all three options (score 3 out of 10), increasing time-to-delivery and operational risk. Option 2 delivers equivalent orchestration integrity, identical gating enforcement, and comparable monitoring quality at materially lower cost and complexity.

### Cloud Scheduler + Cloud Run Jobs (Serverless Minimal)

Despite the lowest infrastructure cost, Option 3 structurally fails to address two first-class project requirements. First, the historical-load gate cannot be enforced natively without a workflow orchestration layer — a GCS sentinel object is a fragile workaround that introduces a data correctness risk if the sentinel is written before validation is fully complete, which directly violates the requirement that 'incremental pipeline must not begin until historical load validation is fully passed and signed off.' Second, stakeholder Yash's independent visibility requirement cannot be adequately met without an orchestration UI — the absence of Airflow DAG run history forces 100% of operational monitoring through a custom-built Looker Studio dashboard, adding development cost that significantly erodes the infrastructure cost advantage. The operability score of 5 (lowest of all options) reflects these structural gaps. The cost delta between Option 2 and Option 3 (primarily the Composer cluster overhead) is outweighed by the orchestration integrity and stakeholder transparency that are explicitly mandated as non-negotiable requirements of this project.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Data Correctness | MySQL and BigQuery have materially different type systems: MySQL DATETIME is timezone-naive while BigQuery DATETIME is also timezone-naive but TIMESTAMP is UTC; DECIMAL precision and scale may differ; TINYINT(1) is commonly used as BOOLEAN in MySQL but has no automatic mapping in BigQuery; TEXT and BLOB columns have no direct BigQuery equivalent. Silent data loss or type coercion errors are possible without an explicit column-level mapping registry. | Implement a deterministic MySQL-to-BigQuery column type mapping registry as a configuration artifact in the Cloud Run Job container; enforce this mapping in the pre-load schema check step; log and alert on any column whose MySQL type has no registered BigQuery mapping before the load proceeds |
| Incremental Completeness | Timestamp-based incremental strategy depends entirely on the application consistently populating the updated_at column on every data-modifying operation. If any MySQL INSERT or UPDATE omits this field, or if the column does not exist, affected rows will be permanently missed by the incremental pipeline with no automatic detection. | Audit the MySQL employees table schema and application write patterns to confirm updated_at reliability before go-live; implement a supplementary post-incremental anomaly check that compares the expected row delta (based on historical average) against the actual rows loaded, alerting on significant deviations; document a quarterly full-table reconciliation procedure |
| Security and Credential Management | MySQL credentials (username: sa, host: 34.70.79.163) and the Cloud SQL connection string are sensitive secrets that must not be stored in container images, Terraform state files, Composer DAG code, or environment variable plaintext. The public IP address of the Cloud SQL instance is exposed in the source connection configuration. | Store all MySQL credentials and the Cloud SQL instance connection name in Google Secret Manager; inject secrets at runtime via Cloud Run Jobs secret environment variable bindings and Composer's SecretManagerBackend; rotate MySQL password and service account keys on a defined schedule; evaluate migration to Private IP connectivity for Cloud SQL to eliminate public internet exposure |
| Operational Observability | Without a defined alert SLA duration, Cloud Monitoring alerting policies cannot be precisely configured, leaving the failure notification window undefined. Stakeholder Yash's requirement for independent visibility cannot be fully validated until the Looker Studio dashboard is built and accepted. | Define the alert SLA duration as the first agenda item in project kickoff before any pipeline deployment; involve stakeholder Yash in dashboard design review prior to go-live to confirm the Looker Studio layout meets the self-service visibility requirement; include dashboard sign-off as a gate before production cutover |
| Schema Evolution | New columns added to the MySQL employees table without advance notice can cause pipeline failures if the BigQuery target table schema does not yet include those columns, or silent data loss if new columns are ignored without alerting. The handling strategy for new columns is a stated functional requirement with no predefined policy documented in the source requirements. | Define and document the new-column handling policy during design phase — recommended default is auto-add as NULLABLE STRING with a simultaneous alert to the data engineering team for type review; implement schema drift detection in the pre-load check step comparing MySQL information_schema.COLUMNS against BigQuery table.schema; any net-new column triggers a human-reviewable alert before the load proceeds |

---

## Assumptions

1. The Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore is accessible from Cloud Composer 2 and Cloud Run Jobs via Cloud SQL Auth Proxy using a GCP service account with the Cloud SQL Client IAM role
2. The BigQuery dataset verizon_data_deah already exists or will be created via Terraform prior to first pipeline execution; the dataset is in the same GCP project or accessible via cross-project IAM binding
3. The MySQL employees table contains at least one reliable watermark column (e.g., updated_at or created_at of type TIMESTAMP or DATETIME) that is consistently populated on every INSERT and UPDATE operation to support timestamp-based incremental extraction
4. A primary key column exists on the MySQL employees table and will be used as the deduplication key in BigQuery MERGE operations
5. Data volume is assumed to be small-to-medium scale (millions of rows, sub-100GB table size) given the single Cloud SQL source instance; Dataflow-class distributed processing is not required at current state
6. Hard deletes on the MySQL employees table are out of scope for the initial implementation; soft deletes via a deleted_at or is_deleted column will be propagated as standard incremental updates; this assumption must be confirmed with the source application team
7. The GCP project has billing enabled and sufficient regional quota for Cloud Composer 2 (GKE Autopilot in us-central1), Cloud Run Jobs, BigQuery, GCS, Cloud Monitoring, and Secret Manager
8. No column-level encryption, BigQuery authorized views, or data masking is required at the pipeline layer for initial delivery; this assumption must be validated against the organization's data classification policy given that an employees table likely contains PII
9. The specific SLA duration for pipeline failure alerting will be defined and agreed upon during project kickoff; the architecture supports any configurable evaluation window in Cloud Monitoring alerting policies
10. Terraform state will be stored remotely in a GCS backend bucket with versioning enabled; no local state files will be used in production deployment

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud Composer 2 selected as orchestration layer to enforce historical-load gate as a native Airflow DAG task dependency with explicit TaskGroup sensor pattern | Gate incremental load activation: incremental pipeline must not begin until historical load validation is fully passed and signed off | — | — |
| BigQuery audit_log table plus Cloud Monitoring dashboard and Airflow DAG run history UI selected to fulfill stakeholder self-service visibility requirement without developer involvement | Implement a monitoring dashboard or log-based visibility layer enabling stakeholders to independently review load success without developer involvement | — | — |
| Timestamp-based watermark strategy using updated_at column with watermark value persisted in BigQuery control_watermarks table selected as the incremental change tracking mechanism | Track incremental changes using timestamp-based or primary key delta strategies, consistently applied across all runs | hourly or daily per table | — |
| Cloud Run Jobs (Python, google-cloud-bigquery SDK) selected as processing layer over Dataflow due to unknown but likely sub-100GB data volume, lower cost, and elimination of Apache Beam SDK complexity | Pipeline must be reliable and scalable to support ongoing scheduled loads, potential additional tables, and both hourly and daily cadences | daily primary schedule; hourly per-table where required | unknown — assumed sub-100GB single table; Dataflow upgrade path preserved |
| BigQuery MERGE DML executed after each load cycle to enforce primary key uniqueness and eliminate duplicate rows introduced by retry or overlap in incremental windows | Enforce primary key uniqueness in BigQuery after every load execution | — | — |
| Pre-load schema compatibility check implemented in Cloud Run Job container comparing MySQL information_schema.COLUMNS against BigQuery Table.schema API response before each load execution | Perform pre-load schema compatibility checks covering data types, null handling, field names, and new column handling strategy before each load execution | — | — |
| Post-load row count validation implemented as a mandatory step inside Cloud Run Job comparing MySQL COUNT(*) for the load window against BigQuery SELECT COUNT(*) in the target partition before the audit record is written as SUCCESS | Perform post-load row count validation between MySQL source and BigQuery target for every load cycle | — | — |
| Cloud Monitoring alerting policy with log-based metric on Cloud Run Job failure log entries selected to trigger pipeline failure alerts within the defined SLA | Trigger monitoring alerts on pipeline failures within a defined SLA | — | — |

---

## Open Questions — Action Required

1. What is the approximate row count, total data size (GB), and daily row delta of the MySQL employees table? This is required to size Cloud Run Job memory limits (default 512MB, max 32GB), determine whether paginated chunked extraction is required for the historical load, and produce a meaningful BigQuery storage and processing cost estimate before deployment.
2. Does the MySQL employees table have an updated_at or equivalent TIMESTAMP column that is reliably populated on every INSERT and UPDATE operation? If this column does not exist or is not consistently maintained, the entire incremental extraction strategy must be redesigned using a primary key range scan or a full-table hash comparison approach.
3. Are hard deletes performed on the MySQL employees table, or are records soft-deleted via a deleted_at or is_active flag? Hard deletes are invisible to timestamp-based incremental extraction and will cause the BigQuery copy to retain rows that have been deleted at source, leading to data divergence over time.
4. What is the agreed SLA duration for pipeline failure alert notification? (e.g., alert must fire within 15 minutes of failure, or within 1 hour of the scheduled execution window) This value is required to configure the Cloud Monitoring alerting policy evaluation period and is currently unquantified in the source requirements.
5. Has the BigQuery dataset verizon_data_deah been created and does an existing employees table schema exist? If a target schema is already defined, it must be used as the authoritative schema for the pre-load compatibility check rather than being inferred from MySQL information_schema.
6. Is the Cloud SQL instance accessible from Cloud Composer 2 and Cloud Run Jobs via Private IP over VPC peering, or must all connections go through Cloud SQL Auth Proxy over the public IP address (34.70.79.163)? The connectivity model affects network architecture, latency, and security posture of the pipeline.
7. What is the data sensitivity classification of the employees table? If the table contains PII (names, emails, salaries, national IDs), column-level encryption, BigQuery authorized views, and data masking rules may be required before the analytics and reporting teams can be granted direct query access.
8. Who is the designated sign-off authority for the historical load validation gate? Is stakeholder Yash the approver who signs off before incremental activation, or does this require a formal data engineering team review? The answer determines whether the gate is implemented as an Airflow ExternalTaskSensor awaiting a manual approval flag or as an automated validation result check.
