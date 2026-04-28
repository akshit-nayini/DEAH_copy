# Architecture Decision Document — Order Analytics Platform

| Field | Value |
|---|---|
| **Project** | Order Analytics Platform |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Hybrid |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Full Dataflow Lambda — Unified Apache Beam SDK for Streaming and Batch
>
> **Why:** Option 1 achieves the highest weighted score (7.85) by implementing the Lambda architecture using the stakeholder-mandated preferred tools (Dataflow, Cloud Composer) with zero deviation from the stated GCP technology stack. The unified Apache Beam programming model across both streaming and batch paths delivers the sub-60-second real-time latency SLA via Streaming Engine and BigQuery Storage Write API, while Cloud Composer enforces the 04:00 UTC batch completion deadline. The single-framework design minimises operational complexity, accelerates time-to-delivery, and provides a predictable cost profile relative to dual-framework alternatives.
>
> **Score:** 7.85 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1 ✅ | Option 2  | Option 3  |
|---|---||---||---|
| **Name** | Full Dataflow Lambda — Unified Apache Beam SDK for Streaming and Batch | Dataflow Streaming + Dataproc Spark Batch — Dual-Framework Lambda | Dataflow Streaming + Datastream CDC Reconciliation — Continuous Change-Capture Lambda |
| **Pattern** | Hybrid | Hybrid | Hybrid |
| **Processing** | Google Dataflow (Apache Beam SDK) | Google Dataflow (streaming) + Google Dataproc Spark (batch) | Google Dataflow (streaming) + BigQuery MERGE via Cloud Composer (batch reconciliation) |
| **Storage** | BigQuery + GCS | BigQuery + GCS | BigQuery + GCS |
| **Weighted Score** | **7.85**  ✅ | **5.95** | **6.95** |

---

## Option 1 — Full Dataflow Lambda — Unified Apache Beam SDK for Streaming and Batch ✅ Recommended

**Pattern:** Hybrid

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Streaming: Dataflow reads continuously from Pub/Sub topic orders.events (project: verizon-data) using the Apache Beam PubSubIO connector. Batch: Dataflow reads incrementally from PostgreSQL public.orders and public.order_items tables (host: orders-db.corp.com:5432, database: orders_db) via Apache Beam JdbcIO using the updated_at watermark column, triggered daily at 02:00 UTC by Cloud Composer 2. |
| Processing | Streaming path: Dataflow applies event-type parsing (order_placed, order_shipped, order_delivered, order_cancelled), JSON schema validation, per-key stateful deduplication on event_id using Beam State and Timer APIs, and direct write to BigQuery via Storage Write API in exactly-once mode. Batch path: Dataflow applies watermark-based incremental extraction, row-level deduplication on order_id via BigQuery MERGE, and reconciliation of any late-arriving or missed events against the existing verizon_orders_deah dataset. Both paths append execution metadata to pipeline_audit.pipeline_run_log on completion. |
| Storage | Both paths target the verizon_orders_deah dataset in BigQuery project verizon-data. Streaming path writes to order_events (partitioned by event_date). Batch path writes to orders and order_items (both partitioned by order_date). A GCS bucket serves as Dataflow temporary and staging storage. pipeline_audit.pipeline_run_log records run_id, pipeline_name, start_time, end_time, rows_processed, and status for every execution. |
| Consumption | Live operational dashboards consume the order_events table via the BigQuery streaming buffer, achieving sub-60-second visibility from Pub/Sub publish. Business reporting and historical analysis consume the fully reconciled orders and order_items tables after daily batch completion by the 04:00 UTC SLA. BigQuery BI Engine or Connected Sheets can be layered for self-service access. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Google Pub/Sub | — | Yes |
| Processing | Google Dataflow (Apache Beam SDK) | — | Yes |
| Storage | BigQuery + GCS | — | Yes |
| Orchestration | Cloud Composer 2 | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging | — | Yes |
| Iac | Terraform | 1.x | No |

### Pros

- Single unified processing framework (Apache Beam) across both streaming and batch paths eliminates dual-SDK maintenance, reduces onboarding cost, and allows shared utility libraries for schema validation and deduplication logic
- Dataflow auto-scaling (2–10 workers) natively absorbs the ~2,000 events/second peak throughput on the streaming path without manual capacity management
- Dataflow Streaming Engine paired with the BigQuery Storage Write API (exactly-once mode) delivers sub-60-second end-to-end latency from Pub/Sub publish to BigQuery row availability, directly satisfying the real-time SLA
- Beam stateful processing (State and Timer APIs) provides per-key deduplication on event_id within the streaming pipeline, minimising duplicate writes before data lands in BigQuery
- Cloud Composer 2 provides DAG-level SLA alerting, retry policies, and audit visibility to enforce the 04:00 UTC batch completion deadline and log results to pipeline_audit.pipeline_run_log
- Preferred tools (Dataflow, Cloud Composer) exactly match the stakeholder technology constraints, eliminating approval delays and skill-gap risk
- Terraform IaC covers all GCP resources (Pub/Sub subscriptions, Dataflow flex templates, BigQuery datasets and tables, Composer environments, IAM bindings) enabling repeatable environment provisioning

### Cons

- The always-on Dataflow streaming job incurs continuous compute cost regardless of event volume during low-throughput periods outside business hours
- Apache Beam JdbcIO for PostgreSQL batch ingestion requires careful tuning of withFetchSize, connection pool size, and query partitioning to avoid exhausting the source database connection quota on orders-db.corp.com
- Beam SDK version governance across streaming and batch pipelines must be actively managed; a version mismatch or breaking SDK upgrade can require coordinated redeployment of both jobs simultaneously

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Malformed or schema-invalid Pub/Sub messages can fail Dataflow record processing and stall pipeline progress if unhandled; mitigated by routing parse errors to a dedicated dead-letter Pub/Sub topic (orders.events.dlq) with Cloud Monitoring alerting on dead-letter message age exceeding 10 minutes. |
| Scaling | If the Pub/Sub subscription backlog spikes beyond the 10-worker autoscaling ceiling (e.g., upstream burst event), streaming throughput degrades and the 60-second latency SLA may be breached; mitigated by monitoring subscription/oldest_unacked_message_age metric with an alert threshold of 120 seconds and coordinating with upstream teams on burst traffic patterns. |
| Latency | Network latency or intermittent connectivity between GCP Dataflow workers and the on-premises PostgreSQL host (orders-db.corp.com) can delay batch job initialisation and risk the 04:00 UTC SLA; mitigated by provisioning a Cloud VPN HA tunnel or dedicated Cloud Interconnect VLAN attachment and configuring Cloud Composer DAG retry with exponential backoff on JDBC connection failures. |
| Cost | The persistent Dataflow streaming worker fleet represents a fixed daily cost floor; mitigated by enabling Dataflow Streaming Engine (eliminates persistent shuffle VMs) and using Flexible Resource Scheduling (FlexRS) for the batch Dataflow job to reduce batch compute cost by up to 40%. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 8 | 8 | 9 | 8 | **7.85** |

---

## Option 2 — Dataflow Streaming + Dataproc Spark Batch — Dual-Framework Lambda

**Pattern:** Hybrid

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Streaming: Dataflow reads continuously from Pub/Sub topic orders.events. Batch: Cloud Composer 2 provisions an ephemeral Dataproc cluster at 02:00 UTC and submits a PySpark job that reads from PostgreSQL via the Spark JDBC connector using an updated_at watermark. Raw extracted data is staged to GCS in Parquet format before BigQuery loading. |
| Processing | Streaming path: Dataflow (Apache Beam) parses, validates, deduplicates on event_id, and writes order events to BigQuery. Batch path: Dataproc Spark reads the GCS-staged Parquet, applies watermark-based incremental filtering, performs join-based deduplication across orders and order_items on order_id, and writes final output back to GCS Parquet for BigQuery load job ingestion. Audit log entries are written via a final Spark step using the BigQuery Spark connector. |
| Storage | Streaming writes directly to BigQuery order_events table (partitioned by event_date). Batch path uses GCS as an intermediate staging layer (raw Parquet, then processed Parquet) before BigQuery load jobs write to orders and order_items tables (partitioned by order_date). GCS lifecycle rules expire staging files after 7 days. Audit logs written to pipeline_audit.pipeline_run_log. |
| Consumption | Live dashboards consume BigQuery streaming buffer for real-time order event visibility. Reconciled transactional tables available after Dataproc job and BigQuery load complete by 04:00 UTC. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Google Pub/Sub + Dataproc Spark JDBC Connector | — | Yes |
| Processing | Google Dataflow (streaming) + Google Dataproc Spark (batch) | — | Yes |
| Storage | BigQuery + GCS | — | Yes |
| Orchestration | Cloud Composer 2 | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging | — | Yes |
| Iac | Terraform | 1.x | No |

### Pros

- Dataproc Spark provides a richer transformation API and native Parquet/GCS integration, making future expansion of batch reconciliation logic (e.g., complex multi-table joins, ML feature generation) straightforward without rewriting in Beam
- Ephemeral Dataproc cluster pattern (create–use–destroy per run) eliminates idle cluster costs outside the 02:00–04:00 UTC batch window
- Independent versioning and scaling of the streaming (Dataflow) and batch (Dataproc) engines allows each to be tuned, upgraded, or replaced without cross-path risk

### Cons

- Dual-framework architecture (Apache Beam + PySpark) doubles the engineering skill requirement, increasing hiring scope, code review overhead, and mean time to debug cross-framework issues
- Dataproc ephemeral cluster cold-start (3–5 minutes) consumes a meaningful portion of the 2-hour processing window, leaving less margin for data volume growth before the 04:00 UTC SLA is threatened
- The GCS staging hop (extract → GCS Parquet → Dataproc transform → GCS Parquet → BigQuery load) adds I/O latency, incremental storage cost, and two additional failure points relative to Option 1
- Dataproc is not included in the stakeholder's preferred tool set, introducing tool-approval risk and potentially delaying environment provisioning

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | GCS-staged Parquet files may contain partial or corrupted data if a Dataproc job fails mid-write; mitigated by enforcing atomic partition-level writes to GCS (write to temp prefix, rename on success) and including a Composer cleanup task that deletes orphaned partitions before retry. |
| Scaling | Ephemeral Dataproc cluster sizing must be declared at submission time; under-sizing causes processing to exceed the 2-hour window and breach the 04:00 UTC SLA, while over-sizing wastes budget; mitigated by enabling Dataproc autoscaling policies and profiling historical job runtimes to set adaptive worker floor/ceiling values. |
| Latency | Dataproc cluster cold-start (3–5 minutes) delays the effective start of batch processing; mitigated by optionally pre-warming clusters via a Composer task submitted 10 minutes before the 02:00 UTC extraction trigger, or by using Dataproc Serverless to eliminate cluster startup entirely. |
| Cost | Combined cost of always-on Dataflow streaming + ephemeral Dataproc cluster + dual GCS staging reads/writes exceeds the cost profile of Option 1; mitigated by applying GCS lifecycle expiry to staging buckets, right-sizing Dataproc worker type to n2-standard-4, and using preemptible secondary workers for the batch job. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 7 | 5 | 8 | 5 | **5.95** |

---

## Option 3 — Dataflow Streaming + Datastream CDC Reconciliation — Continuous Change-Capture Lambda

**Pattern:** Hybrid

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Streaming: Dataflow reads continuously from Pub/Sub topic orders.events. CDC Reconciliation: Datastream captures logical replication changes from PostgreSQL public.orders and public.order_items tables using PostgreSQL logical decoding (pgoutput plugin) and streams change events to GCS in Avro format continuously. Cloud Composer triggers a daily BigQuery MERGE reconciliation job at 02:00 UTC that consolidates the previous day's GCS change files. |
| Processing | Streaming path: Dataflow processes order status events with deduplication on event_id and writes to BigQuery in real-time via Storage Write API. CDC path: Datastream handles continuous change capture with no pipeline code; Cloud Composer orchestrates a BigQuery MERGE job that reads GCS Avro change files, applies last-write-wins merge on order_id, and reconciles the target orders and order_items tables. Audit log entries written via BigQuery DML within the Composer DAG. |
| Storage | Streaming writes to BigQuery order_events table (partitioned by event_date). Datastream continuously writes GCS Avro change files (partitioned by source table and date) which are consumed by the daily BigQuery MERGE into orders and order_items tables (partitioned by order_date). GCS bucket with 30-day lifecycle policy holds Datastream change file backlog. Audit logs written to pipeline_audit.pipeline_run_log. |
| Consumption | Live dashboards consume BigQuery streaming buffer for real-time order events. Reconciled transactional tables available after daily BigQuery MERGE completes by 04:00 UTC. Datastream's continuous CDC also enables near-real-time operational queries on the GCS change log for advanced use cases if required in future. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Google Pub/Sub + Datastream (PostgreSQL Logical Replication CDC) | — | Yes |
| Processing | Google Dataflow (streaming) + BigQuery MERGE via Cloud Composer (batch reconciliation) | — | Yes |
| Storage | BigQuery + GCS | — | Yes |
| Orchestration | Cloud Composer 2 | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Datastream Monitoring Dashboard | — | Yes |
| Iac | Terraform | 1.x | No |

### Pros

- Datastream provides fully managed PostgreSQL logical replication with built-in schema drift detection and automatic handling of DDL changes, eliminating JDBC watermark query management and connection pool tuning
- Continuous CDC reduces the theoretical risk of missed events between polling windows compared to updated_at watermark queries, improving reconciliation completeness for rows updated in rapid succession
- BigQuery native MERGE for daily reconciliation eliminates batch compute cluster cost entirely, as no Dataflow or Dataproc workers are required for the reconciliation execution path

### Cons

- Datastream requires enabling PostgreSQL logical replication (wal_level=logical, max_replication_slots configured) on orders-db.corp.com, necessitating DBA approval, a planned database restart, and ongoing WAL management oversight
- Datastream charges per GB processed on a continuous 24/7 basis; for a 10 GB/day change volume, continuous CDC cost exceeds the equivalent 2-hour daily Dataflow batch job cost by a significant margin given the always-on processing model
- PostgreSQL replication slot management is operationally sensitive: if Datastream falls behind or pauses, the replication slot prevents WAL segment cleanup on the source server, risking PostgreSQL disk exhaustion on orders-db.corp.com
- The GCS Avro intermediate format introduces schema management overhead (Avro schema evolution rules) and is not part of the stakeholder's preferred tool set, adding adoption and tooling approval risk
- Datastream is not listed in the stakeholder's preferred tool set, introducing potential approval friction

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Datastream may deliver out-of-order change events for the same row during high-write bursts on the PostgreSQL source; mitigated by ordering MERGE operations on a monotonic sequence number or transaction commit timestamp emitted by Datastream in the change event envelope. |
| Scaling | PostgreSQL replication slot lag can accumulate during high-write periods or Datastream connectivity interruptions, causing WAL disk usage to grow on orders-db.corp.com; mitigated by monitoring pg_replication_slots.confirmed_flush_lsn lag via Cloud Monitoring and configuring PostgreSQL max_slot_wal_keep_size as a safety backstop. |
| Latency | Datastream GCS flush latency (configurable, default 15 seconds) introduces a small delay before change files are available for the daily BigQuery MERGE; this does not impact the streaming path latency SLA and is well within the 2-hour daily reconciliation window. |
| Cost | Continuous Datastream processing charges for 10 GB/day of change volume accrue 24/7 regardless of the daily-only reconciliation schedule; mitigated by configuring Datastream stream pausing outside the business reconciliation window if change backlog capture permits, or by capping GCS destination file size to control per-event overhead. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 8 | 6 | 9 | 6 | **6.95** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Full Dataflow Lambda — Unified Apache Beam SDK for Streaming and Batch ✅ | 7 | 8 | 8 | 9 | 8 | **7.85** |
| Dataflow Streaming + Dataproc Spark Batch — Dual-Framework Lambda | 5 | 7 | 5 | 8 | 5 | **5.95** |
| Dataflow Streaming + Datastream CDC Reconciliation — Continuous Change-Capture Lambda | 6 | 8 | 6 | 9 | 6 | **6.95** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Full Dataflow Lambda — Unified Apache Beam SDK for Streaming and Batch**
**Weighted Score: 7.85**

**Justification:** Option 1 achieves the highest weighted score (7.85) by implementing the Lambda architecture using the stakeholder-mandated preferred tools (Dataflow, Cloud Composer) with zero deviation from the stated GCP technology stack. The unified Apache Beam programming model across both streaming and batch paths delivers the sub-60-second real-time latency SLA via Streaming Engine and BigQuery Storage Write API, while Cloud Composer enforces the 04:00 UTC batch completion deadline. The single-framework design minimises operational complexity, accelerates time-to-delivery, and provides a predictable cost profile relative to dual-framework alternatives.

**Why highest score:** Option 1 outscores all alternatives across cost (7), scalability (8), complexity (8), latency (9), and operability (8) because it eliminates the framework-switching overhead and GCS staging hops present in Option 2, and avoids the PostgreSQL replication slot operational risk and continuous CDC cost inefficiency of Option 3. The Dataflow Streaming Engine and BigQuery Storage Write API combination represents the lowest-latency, highest-reliability path from Pub/Sub to BigQuery available in GCP today, and the unified Beam SDK provides the highest operability score by reducing the number of distinct observability surfaces, deployment pipelines, and skill sets required.

**Trade-offs accepted:** The continuous cost of the always-on Dataflow streaming job is accepted given the 60-second real-time latency SLA, which cannot be achieved via micro-batch or scheduled polling. The dependency on JDBC network connectivity to on-premises orders-db.corp.com for the batch path is accepted under the assumption that a stable Cloud VPN or Cloud Interconnect path will be provisioned as part of infrastructure prerequisites. Per-key streaming deduplication provides best-effort exactly-once semantics on the streaming path; final authoritative deduplication is delegated to the daily BigQuery MERGE reconciliation, which is consistent with the Lambda architecture's batch-layer correctness guarantee.

---

## Rejected Options

### Dataflow Streaming + Dataproc Spark Batch — Dual-Framework Lambda

Option 2 scores 5.95 — 1.90 points below Option 1. The dual-framework architecture (Dataflow + Dataproc) introduces unnecessary operational complexity and cost for the defined requirements without delivering commensurate capability gains. The 3–5 minute Dataproc cluster cold-start materially threatens the 04:00 UTC SLA, the GCS staging hop adds two additional failure points absent in Option 1, and Dataproc falls outside the stakeholder-specified preferred tool set. For a 10 GB/day batch volume with standard incremental load and MERGE deduplication logic, Dataflow Batch with JdbcIO is operationally simpler, less expensive, and fully sufficient — the advanced Spark transformation capabilities offered by Option 2 are not warranted by the current functional requirements.

### Dataflow Streaming + Datastream CDC Reconciliation — Continuous Change-Capture Lambda

Option 3 scores 6.95 — 0.90 points below Option 1. While Datastream's managed CDC eliminates JDBC watermark query management, it introduces a material operational risk to the PostgreSQL source system via replication slot WAL accumulation — a failure mode that can cause source database disk exhaustion if Datastream falls behind, which represents an unacceptable blast radius for a production operational database. Additionally, enabling wal_level=logical on orders-db.corp.com requires a DBA-coordinated database restart, creating a delivery dependency outside the data engineering team's control. The continuous CDC cost model is disproportionate to a daily-only reconciliation use case, and Datastream is not in the stakeholder's preferred tool set. Option 1 achieves equivalent reconciliation completeness through a lower-risk, simpler JDBC watermark approach without touching source database replication configuration.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Network Connectivity | The PostgreSQL source database (orders-db.corp.com) is hosted on-premises. VPN tunnel instability, firewall policy changes, or DNS resolution failures will interrupt the daily batch ingestion path and risk breach of the 04:00 UTC SLA. | Provision a Cloud VPN HA tunnel (two tunnels across two Cloud Routers for 99.99% SLA) or a Cloud Interconnect dedicated connection to the corporate data centre. Configure Cloud Composer DAG retry with exponential backoff (3 retries, 15-minute intervals). Set a PagerDuty or email alert on DAG failure within 15 minutes of scheduled start time. |
| Deduplication Correctness | Both the streaming and batch paths write to the same BigQuery tables. Without coordinated deduplication logic, duplicate records on event_id and order_id will silently corrupt downstream analytics and business reports. | Use Dataflow Storage Write API exactly-once mode to prevent duplicate streaming inserts. Apply BigQuery MERGE statements in the batch reconciliation path keyed on event_id (order_events) and order_id (orders, order_items). Schedule a daily post-reconciliation data quality query that counts records with duplicate primary keys and triggers a Cloud Monitoring alert if count exceeds zero. |
| Schema Evolution | Unannounced changes to the Pub/Sub message schema or PostgreSQL table structure (new columns, type changes, column renames) can cause silent data truncation or pipeline failures affecting both streaming and batch paths. | Register Pub/Sub message schemas using the Pub/Sub Schema Registry feature (Avro or Protobuf). Implement Dataflow-side schema validation with parse errors routed to a dead-letter topic. Maintain a BigQuery schema contract as a JSON file in GCS; run a schema drift check in the Composer DAG before each batch extraction and alert on any deviation from the expected schema. |
| Audit Log Continuity | The pipeline_audit.pipeline_run_log requirement implies a continuous, tamper-evident audit trail. If audit logging fails silently — due to BigQuery write errors, IAM misconfiguration, or pipeline early exit — operational debugging and compliance obligations are compromised. | Write audit log entries as the penultimate step of each pipeline run (before final status update) using a dedicated BigQuery INSERT DML statement within the Composer DAG. Implement a Cloud Monitoring metric that alerts if no audit log entry is written within 30 minutes of a scheduled pipeline start time. Grant the pipeline service account write-only access to the audit table to prevent accidental data modification. |
| Cost Governance | The always-on Dataflow streaming job creates a continuous cost floor. Unbounded BigQuery on-demand slot consumption during large MERGE reconciliation operations on partitioned tables can produce unexpected cost spikes at month-end. | Enable Dataflow Streaming Engine to eliminate persistent shuffle VM cost. Use BigQuery reservations (slot commitments) for the reconciliation project to cap MERGE query cost. Configure GCP Billing Budget alerts at 80% and 100% of the agreed monthly cost threshold with email notifications to the project owner. Review Dataflow worker utilisation monthly and adjust autoscaling bounds accordingly. |
| Dead-Letter Event Handling | Malformed, schema-invalid, or unparseable events arriving on the Pub/Sub orders.events topic will be routed to a dead-letter topic. Without active monitoring and remediation, the dead-letter backlog will grow silently, causing data gaps in the order_events table that the batch reconciliation path cannot backfill (since batch reads PostgreSQL, not Pub/Sub). | Configure a Dataflow dead-letter sink writing to a GCS bucket for forensic replay. Set a Cloud Monitoring alert on dead-letter message count exceeding 100 within a 5-minute window. Define an on-call runbook for dead-letter triage, correction, and manual replay into the streaming pipeline or direct BigQuery INSERT. |

---

## Assumptions

1. Stable network connectivity exists between GCP Dataflow worker VMs and the on-premises PostgreSQL host (orders-db.corp.com:5432) via a Cloud VPN HA tunnel or Cloud Interconnect VLAN attachment; this is a hard prerequisite for the batch ingestion path
2. The BigQuery project verizon-data and dataset verizon_orders_deah already exist; target tables (order_events, orders, order_items) and the pipeline_audit.pipeline_run_log table will be created and schema-managed by Terraform IaC
3. The Pub/Sub topic orders.events in project verizon-data is already provisioned, receiving live order lifecycle events in a known schema (JSON or Avro), and a dedicated Dataflow pull subscription will be created by IaC
4. A dedicated GCP service account will be provisioned for pipeline execution with the following minimum IAM roles: roles/bigquery.dataEditor on verizon_orders_deah, roles/pubsub.subscriber on orders.events subscription, roles/dataflow.worker, roles/storage.objectAdmin on the Dataflow staging GCS bucket
5. The PostgreSQL user 'sa' on orders_db has SELECT privileges on public.orders and public.order_items and can support concurrent JDBC connections from Dataflow batch workers without exceeding the database's max_connections limit
6. The Dataflow streaming job runs as a persistent production job; the batch Dataflow job is launched on-demand by a Cloud Composer DAG operator (DataflowStartFlexTemplateOperator) at 02:00 UTC daily
7. BigQuery Storage Write API in exactly-once mode will be used for the streaming path to provide end-to-end deduplication guarantees; downstream BigQuery MERGE will serve as the authoritative deduplication layer for the batch reconciliation path
8. Data sensitivity classification and PII handling requirements for order and customer data are not yet defined; column-level security, VPC Service Controls, and CMEK encryption requirements are deferred to a subsequent security design review before production launch
9. Dataflow Flex Templates will be used for both streaming and batch jobs to support versioned, repeatable job deployment via Cloud Composer without relying on Classic Templates
10. All BigQuery tables will use DATE-based partitioning (event_date for order_events, order_date for orders and order_items) with partition expiration policy to be defined during detailed design

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Google Dataflow (Apache Beam) selected as the processing engine for both the streaming and batch paths | technology.preferred_tools: [Dataflow, Cloud Composer]; objective: Lambda architecture with both streaming and daily batch reconciliation paths | 60 seconds | 5 GB/day streaming + 10 GB/day batch |
| BigQuery Storage Write API (exactly-once mode) used for the streaming path ingestion into BigQuery | non_functional.latency: Data available in BigQuery within 60 seconds of Pub/Sub publish | 60 seconds | ~5 GB/day |
| Cloud Composer 2 selected as the orchestration layer with a 02:00 UTC daily DAG trigger for the batch path | non_functional.sla: Batch DAG must complete before 04:00 AM UTC; technology.preferred_tools: [Cloud Composer] | — | ~10 GB/day |
| Lambda architecture adopted with dual streaming and batch paths writing to the same verizon_orders_deah BigQuery dataset | objective: Both paths write to the same BigQuery dataset using a Lambda architecture; data_requirements.source_systems: Pub/Sub + PostgreSQL 13 | 60 seconds | ~15 GB/day total |
| BigQuery partitioning by event_date applied to order_events; partitioning by order_date applied to orders and order_items | functional_requirements: Partition all BigQuery target tables by event_date and order_date | — | — |
| Per-key stateful deduplication on event_id implemented in Dataflow streaming pipeline; BigQuery MERGE on order_id used for batch reconciliation deduplication | functional_requirements: Deduplicate records on event_id and order_id primary keys across both streaming and batch paths | — | — |
| Dataflow streaming job autoscaling configured between 2 and 10 workers | non_functional.scalability: Dataflow streaming job auto-scales between 2 and 10 workers based on load; non_functional.performance: ~2,000 events/second peak throughput | 60 seconds | ~2,000 events/second peak |
| PostgreSQL watermark-based incremental load (updated_at column) used for batch ingestion via JDBC instead of full table scan or CDC | functional_requirements: Perform daily incremental load from PostgreSQL orders and order_items tables using the updated_at watermark | — | ~10 GB/day |
| All pipeline execution results logged to pipeline_audit.pipeline_run_log in BigQuery | functional_requirements: Log pipeline execution results to pipeline_audit.pipeline_run_log for every run | — | — |
| Terraform selected as the IaC tool for all GCP resource provisioning across both streaming and batch infrastructure | technology.cloud_or_onprem: cloud; technology.environment: production | — | — |

---

## Open Questions — Action Required

1. What is the exact network path from GCP Dataflow workers to orders-db.corp.com — Cloud VPN HA, Cloud Interconnect, or public internet with SSL mutual TLS? The answer determines Dataflow worker network configuration, JDBC connection string parameters, and the security review scope for the batch ingestion path.
2. What is the authoritative schema (field names, types, nullability) for Pub/Sub orders.events messages — JSON with a fixed schema, Avro with a schema registry entry, or Protobuf? A formal schema contract is required before Dataflow streaming pipeline development can begin.
3. What is the acceptable deduplication semantics for the streaming path — best-effort at-least-once with downstream MERGE correction (simpler) or exactly-once guaranteed at ingest time via Storage Write API (higher cost)? This choice affects both Dataflow pipeline design and BigQuery write quota consumption.
4. Does the pipeline_audit.pipeline_run_log table reside in the verizon-data project within the verizon_orders_deah dataset, or in a separate centralised audit project? This determines the IAM permission scope for the pipeline service account and whether cross-project BigQuery writes are required.
5. Are there PII fields (customer names, delivery addresses, payment instrument data) in the PostgreSQL orders or order_items tables? If so, column-level BigQuery security policies, data masking transforms in Dataflow, and Cloud DLP scanning requirements must be scoped before production deployment.
6. What is the agreed data retention policy for BigQuery target tables? Specifically, should partition expiration be set on order_events (e.g., 90-day rolling window for live dashboards) separately from orders and order_items (longer retention for historical reporting)?
7. What is the expected cardinality and update frequency of late-arriving events — i.e., what percentage of daily PostgreSQL batch records are genuinely new versus corrections to events already captured by the streaming path? This informs the MERGE reconciliation strategy and helps quantify the business value of the batch path.
8. Is John (primary stakeholder) the BigQuery dataset owner responsible for approving schema changes, or is there a separate data governance process (e.g., data contract review board) that must approve target table schema definitions before IaC deployment?
