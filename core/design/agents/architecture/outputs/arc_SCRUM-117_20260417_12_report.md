# Architecture Decision Document — Clickstream Analytics Platform

| Field | Value |
|---|---|
| **Project** | Clickstream Analytics Platform |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Streaming |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Dataflow Direct KafkaIO Streaming
>
> **Why:** Option 1 achieves the highest weighted score (7.90) and is the only option that satisfies all explicit technology requirements without architectural deviation. It uses Google Cloud Dataflow with Apache Beam KafkaIO exactly as stated in the preferred stack, delivers sub-30-second end-to-end latency with 2x headroom against the 60-second SLA, enforces zero-data-loss through exactly-once Storage Write API semantics, and meets all functional requirements including sliding-window deduplication, dead-letter Kafka routing, date partitioning, and audit logging within a single managed pipeline.
>
> **Score:** 7.90 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1 ✅ | Option 2  | Option 3  |
|---|---||---||---|
| **Name** | Dataflow Direct KafkaIO Streaming | Kafka to Pub/Sub Bridge then Dataflow to BigQuery | Confluent Cloud ksqlDB with BigQuery Sink Connector |
| **Pattern** | Streaming | Streaming | Streaming |
| **Processing** | Google Cloud Dataflow (Apache Beam 2.x Streaming Engine) | Google Cloud Dataflow (Apache Beam 2.x) | Confluent Cloud ksqlDB |
| **Storage** | Google BigQuery (Storage Write API — exactly-once) | Google BigQuery (Storage Write API) | Google BigQuery via Confluent BigQuery Sink Connector (Kafka Connect) |
| **Weighted Score** | **7.90**  ✅ | **6.55** | **6.25** |

---

## Option 1 — Dataflow Direct KafkaIO Streaming ✅ Recommended

**Pattern:** Streaming

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | KafkaIO connector (Apache Beam) authenticates to Confluent Kafka via SASL/PLAIN API key (credentials injected at runtime from GCP Secret Manager) and continuously polls 3 topics — clickstream.page_views, clickstream.user_events, clickstream.sessions — at up to 5,000 events/second peak throughput; consumer group offsets are checkpointed to Dataflow's durable state store to guarantee at-least-once read semantics |
| Processing | Dataflow Streaming job (Apache Beam) parses JSON payloads via a DoFn with null-safe field mapping, routes unparseable or schema-invalid records to the Confluent dead-letter topic (clickstream.dead_letter) without interrupting the pipeline, deduplicates valid records on event_id using a 10-minute sliding window with 1-minute slide interval via Beam stateful processing, and emits structured audit entries to pipeline_audit.pipeline_run_log in BigQuery after each window fires |
| Storage | BigQuery Storage Write API (exactly-once mode) appends validated, deduplicated records to date-partitioned tables (page_views, user_events, sessions) in dataset verizon_clickstream_deah within project verizon-data; tables partitioned by event_timestamp (DATE) and clustered on session_id; commit intervals tuned to 20 seconds to guarantee sub-60-second end-to-end delivery |
| Consumption | Looker connects directly to BigQuery via Standard SQL for real-time user behaviour dashboards and funnel analysis across page views, clicks, and session activity; an hourly reconciliation job validates BigQuery row counts against Kafka consumer group offsets to enforce the zero-data-loss SLA; Cloud Monitoring dashboards surface Dataflow worker health, per-topic consumer lag, and end-to-end latency percentiles |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Confluent Kafka + Apache Beam KafkaIO | — | Yes |
| Processing | Google Cloud Dataflow (Apache Beam 2.x Streaming Engine) | 2.x | Yes |
| Storage | Google BigQuery (Storage Write API — exactly-once) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Dataflow Native Metrics | — | Yes |
| Iac | Terraform | ~>1.7 | No |

### Pros

- Satisfies every explicit technology constraint without deviation — Dataflow, Apache Beam, Confluent Kafka, BigQuery, and Looker are all natively used as required
- KafkaIO with checkpointing combined with BigQuery Storage Write API exactly-once mode provides an end-to-end exactly-once delivery guarantee, directly enforcing the zero-data-loss SLA
- Dataflow Streaming Engine externalises window state management, enabling auto-scaling between 2 and 20 workers under load without OOM risk from 10-minute window state accumulation
- Single unified pipeline topology (one Dataflow job per topic or one multi-topic job) minimises operational surface area and reduces failure blast radius
- Sub-30-second achievable end-to-end latency provides 2x headroom against the 60-second SLA under normal and peak load conditions
- Cloud Monitoring and Dataflow built-in metrics expose consumer lag, system lag, worker CPU/memory, and per-step throughput with zero additional instrumentation
- Dataflow Flex Templates support repeatable, versioned job deployment via Cloud Build and Artifact Registry, enabling GitOps-style pipeline promotion across environments

### Cons

- KafkaIO consumer group offset behaviour under backpressure requires explicit tuning (maxReadTime, fetchMaxWaitMs) to avoid stalling or over-committing offsets before writes are confirmed
- 10-minute sliding window deduplication increases state store size; at 5,000 events/second this accumulates ~3 billion unique event_id keys per window slide at peak — Streaming Engine mitigates but requires validation during load testing
- Dataflow Flex Template pipeline requires containerised build and push to Artifact Registry, adding initial CI/CD setup effort versus Classic Templates
- Confluent Cloud egress charges apply for data transferred from Confluent to GCP Dataflow workers, even within the same GCP region

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | JSON schema drift between Kafka producers and Beam field-mapping logic can cause silent field drops or NullPointerExceptions in the DoFn; mitigate by adopting Confluent Schema Registry with backward-compatible JSON Schema or AVRO, and routing any record failing schema validation to the dead-letter topic with a structured error envelope containing the raw payload and failure reason |
| Scaling | Sustained 5,000 events/second with 10-minute window state may cause GC pressure on individual workers during auto-scale-out lag; set minWorkers=4 during peak business hours, use n2-standard-4 machine type, enable Streaming Engine, and load test at 2x peak (10,000 events/second) before production cutover to validate auto-scaling headroom |
| Latency | BigQuery Storage Write API flush interval is the primary latency risk; default flush can be up to 60 seconds — configure explicit commit interval to 20 seconds in the Beam sink to guarantee 60-second SLA with 40-second remaining budget for Kafka poll, processing, and network traversal; alert at 45 seconds to detect SLA risk before breach |
| Cost | At 20 workers (n2-standard-4) running continuously, Dataflow vCPU and memory costs reach approximately $800-1,200/month; right-size with scheduled worker floor reduction (e.g., minWorkers=2 overnight); set Cloud Billing budget alerts at 80% and 100% of monthly envelope; Streaming Engine adds a flat surcharge but reduces per-worker resource consumption by ~20% |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 9 | 7 | 9 | 8 | **7.90** |

---

## Option 2 — Kafka to Pub/Sub Bridge then Dataflow to BigQuery

**Pattern:** Streaming

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | A dedicated Dataflow Kafka-to-Pub/Sub bridge job (using the Google-provided template or a custom KafkaIO-to-Pub/Sub Beam pipeline) mirrors all 3 Confluent Kafka topics into corresponding Cloud Pub/Sub topics; SASL/PLAIN credentials are injected from Secret Manager; Pub/Sub provides a durable GCP-native buffer with configurable message retention |
| Processing | A second Dataflow Streaming job reads from Pub/Sub subscriptions, parses JSON payloads, performs 10-minute sliding window deduplication on event_id, routes invalid records to a Pub/Sub dead-letter topic (subsequently forwarded to the Confluent dead-letter Kafka topic via a third lightweight forwarding job or Pub/Sub push subscription), and writes audit entries to pipeline_audit.pipeline_run_log |
| Storage | BigQuery Storage Write API appends validated records to date-partitioned tables in verizon_clickstream_deah; Pub/Sub message acknowledgement provides at-least-once delivery, with Storage Write API exactly-once mode preventing duplicate BigQuery rows |
| Consumption | Looker dashboards connect to BigQuery; Pub/Sub dead-letter topic feeds Cloud Monitoring alerting and optional message replay; hourly row count reconciliation validates zero-data-loss against original Kafka consumer group offsets |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Confluent Kafka + Cloud Pub/Sub (Kafka-to-Pub/Sub Dataflow Bridge) | — | Yes |
| Processing | Google Cloud Dataflow (Apache Beam 2.x) | 2.x | Yes |
| Storage | Google BigQuery (Storage Write API) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Pub/Sub Metrics + Dataflow Metrics | — | Yes |
| Iac | Terraform | ~>1.7 | No |

### Pros

- Cloud Pub/Sub acts as a durable GCP-native buffer decoupling Confluent Kafka availability from the downstream Dataflow processing pipeline and providing message replay capability on Dataflow failures
- Future migration off Confluent Kafka is simplified — downstream pipeline only depends on Pub/Sub and is Kafka-agnostic once the bridge layer is changed
- Pub/Sub auto-scales natively to handle traffic bursts before they propagate to Dataflow, providing an additional elasticity buffer
- All components downstream of the bridge are fully GCP-native with no cross-platform dependencies

### Cons

- Two-hop architecture (Kafka to Pub/Sub to Dataflow) introduces 2-10 seconds of additional latency per hop, meaningfully reducing headroom against the 60-second SLA
- Requires two or three distinct Dataflow jobs (bridge, processing, optionally dead-letter forwarder), doubling operational surface area and increasing monthly compute cost by 30-50% versus Option 1
- Dead-letter flow is significantly more complex: invalid records must traverse a Pub/Sub dead-letter topic before being forwarded back to the Confluent Kafka dead-letter topic, requiring an additional pipeline component
- Pub/Sub subscription and storage costs are additive to Dataflow and BigQuery costs, with no performance or capability benefit at this volume and latency tier
- Message ordering within Pub/Sub is not guaranteed by default; session-level event ordering requires Pub/Sub Ordering Keys, adding configuration complexity

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Pub/Sub does not guarantee strict message ordering within a topic without Ordering Keys; if session event ordering is required for funnel analysis correctness, each topic must be configured with Ordering Keys keyed on session_id, which limits Pub/Sub throughput parallelism and must be validated against the 5,000 events/second peak |
| Scaling | Pub/Sub subscription backlog can grow unboundedly during Dataflow processing job downtime; while messages are retained for up to 7 days, a large backlog drain event may temporarily exceed the 60-second latency SLA as Dataflow processes the backlog; auto-scaling headroom must be sized for worst-case drain scenarios |
| Latency | Combined Kafka-to-Pub/Sub bridge latency (2-5 seconds) and Pub/Sub-to-BigQuery processing latency (5-15 seconds under load) leaves less than 40 seconds of remaining budget for JSON parsing, windowed deduplication, and BigQuery write flushing; this creates a tight SLA that is at risk under sustained peak load or during worker auto-scale-out events |
| Cost | Three Dataflow jobs (bridge, processor, dead-letter forwarder), Pub/Sub ingestion and egress charges, and additional BigQuery streaming insert or Storage Write API charges for audit records increase total monthly platform cost by an estimated 35-50% versus Option 1 for equivalent throughput with no functional improvement |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 8 | 5 | 7 | 7 | **6.55** |

---

## Option 3 — Confluent Cloud ksqlDB with BigQuery Sink Connector

**Pattern:** Streaming

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Events land natively on Confluent Kafka topics (clickstream.page_views, clickstream.user_events, clickstream.sessions); ksqlDB persistent CREATE STREAM AS SELECT queries reference the source topics directly with no additional ingestion layer required — processing begins at the Confluent Cloud layer |
| Processing | ksqlDB persistent queries on Confluent Cloud perform JSON payload parsing, field-to-schema mapping, and record filtering; invalid or unparseable records are routed to the clickstream.dead_letter topic via ksqlDB error handling configuration; deduplication is approximated using LATEST_BY_OFFSET or a ksqlDB TABLE materialised view keyed on event_id with 10-minute hopping window semantics — note that this does not provide exact sliding-window dedup semantics equivalent to Beam stateful processing |
| Storage | Confluent BigQuery Sink Connector (fully managed Kafka Connect on Confluent Cloud) writes from processed ksqlDB output topics to BigQuery tables in verizon_clickstream_deah; a separate sink connector writes audit records to pipeline_audit.pipeline_run_log; date-based partitioning is configured via BigQuery table decorator settings in the connector |
| Consumption | Looker connects to BigQuery for real-time dashboards; Confluent Control Center provides topic-level throughput and consumer lag monitoring; Cloud Monitoring ingests connector and BigQuery metrics via Confluent Cloud Metrics API for unified alerting |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Confluent Kafka (native topics) | — | Yes |
| Processing | Confluent Cloud ksqlDB | — | Yes |
| Storage | Google BigQuery via Confluent BigQuery Sink Connector (Kafka Connect) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | 2.x | Yes |
| Monitoring | Confluent Control Center + Cloud Monitoring (via Confluent Metrics API) | — | Yes |
| Iac | Terraform | ~>1.7 | No |

### Pros

- Eliminates Google Cloud Dataflow entirely, removing GCP stream processing compute costs for teams willing to consolidate processing within the Confluent platform
- ksqlDB is co-located with Confluent Kafka, removing network round-trip latency between event consumption and transformation — lowest raw processing latency of all three options
- Confluent BigQuery Sink Connector is a fully managed integration requiring no custom Beam pipeline code, reducing initial development effort
- Simplified architecture for teams already operating Confluent Platform with existing ksqlDB expertise

### Cons

- Directly contradicts the explicit technology requirement to use Google Cloud Dataflow with Apache Beam — adoption requires formal waiver of stated preferred tools
- ksqlDB does not natively support true 10-minute sliding window deduplication with exactly-once semantics equivalent to Beam stateful DoFn processing; hopping window TABLE materialisation is the closest approximation but has semantic gaps that may produce duplicate rows at window boundaries
- Confluent ksqlDB Streaming Processing Unit (SPU) licensing and managed BigQuery Sink Connector costs are additive to existing Confluent Kafka spend, resulting in 30-50% higher total platform cost versus Option 1
- Operational monitoring is fragmented across Confluent Control Center (ksqlDB metrics) and GCP Cloud Monitoring (BigQuery metrics), creating a split observability model with no unified SLA dashboard
- BigQuery Sink Connector default flush interval is 60 seconds — at default configuration this creates a direct risk of breaching the 60-second end-to-end SLA and requires non-default tuning to sub-30-second flush intervals
- Exactly-once delivery semantics for the BigQuery Sink Connector require specific Confluent Platform and BigQuery configurations that are not enabled by default and may impose throughput limitations

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | ksqlDB TABLE-based deduplication retains only the latest record per event_id key within a compacted changelog and does not implement true 10-minute sliding window deduplication; records with the same event_id arriving across two consecutive windows may both reach BigQuery, violating the deduplication requirement and requiring a compensating BigQuery MERGE reconciliation job |
| Scaling | ksqlDB scaling on Confluent Cloud is governed by Confluent Streaming Processing Units (SPUs), which scale in discrete increments rather than granular 1-worker steps; at peak load the coarse-grained scaling model may over-provision capacity, increasing cost, or under-provision, causing consumer lag that breaches the 60-second SLA |
| Latency | Confluent BigQuery Sink Connector batch commit interval defaults to 60 seconds and must be tuned to 20-25 seconds to guarantee sub-60-second end-to-end delivery; even with tuning, combined ksqlDB query materialisation delay and connector flush latency leaves minimal SLA headroom under sustained 5,000 events/second load |
| Cost | Confluent Cloud ksqlDB SPU licensing (estimated $0.45-0.60 per SPU-hour) combined with managed connector charges and BigQuery Storage Write API costs results in a total platform cost 30-50% higher than Option 1 at equivalent throughput, with no functional advantage |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 7 | 6 | 8 | 6 | **6.25** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Dataflow Direct KafkaIO Streaming ✅ | 7 | 9 | 7 | 9 | 8 | **7.90** |
| Kafka to Pub/Sub Bridge then Dataflow to BigQuery | 6 | 8 | 5 | 7 | 7 | **6.55** |
| Confluent Cloud ksqlDB with BigQuery Sink Connector | 5 | 7 | 6 | 8 | 6 | **6.25** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Dataflow Direct KafkaIO Streaming**
**Weighted Score: 7.90**

**Justification:** Option 1 achieves the highest weighted score (7.90) and is the only option that satisfies all explicit technology requirements without architectural deviation. It uses Google Cloud Dataflow with Apache Beam KafkaIO exactly as stated in the preferred stack, delivers sub-30-second end-to-end latency with 2x headroom against the 60-second SLA, enforces zero-data-loss through exactly-once Storage Write API semantics, and meets all functional requirements including sliding-window deduplication, dead-letter Kafka routing, date partitioning, and audit logging within a single managed pipeline.

**Why highest score:** Scores highest on scalability (9) and latency (9) — the two dimensions most critical to this real-time, zero-data-loss use case — while maintaining strong cost (7) and operability (8) through GCP-native managed services. The direct Confluent Kafka to Dataflow to BigQuery topology eliminates all unnecessary intermediary hops that would add latency, cost, and operational complexity without providing compensating benefits at the stated volume and latency tier.

**Trade-offs accepted:** Accepted: moderate initial CI/CD complexity from Dataflow Flex Template containerisation; increased state store size from 10-minute sliding window deduplication at peak throughput; Confluent Cloud egress charges for cross-platform data transfer. These are manageable one-time and steady-state costs that are significantly outweighed by the latency, reliability, and alignment-to-requirements benefits of this option.

---

## Rejected Options

### Kafka to Pub/Sub Bridge then Dataflow to BigQuery

Rejected because the Kafka-to-Pub/Sub intermediary hop introduces unnecessary architectural complexity (2-3 Dataflow jobs), inflates monthly cost by 35-50%, materially reduces latency headroom against the 60-second SLA, and creates a significantly more complex dead-letter routing path — none of which provides a compensating functional or reliability benefit at this volume and latency tier. KafkaIO in Option 1 directly satisfies all ingestion, processing, and delivery requirements without the Pub/Sub layer.

### Confluent Cloud ksqlDB with BigQuery Sink Connector

Rejected on three grounds: (1) directly violates the stated technology requirement to use Google Cloud Dataflow with Apache Beam; (2) introduces a functional gap in 10-minute sliding window deduplication semantics that cannot be precisely replicated in ksqlDB without a compensating BigQuery MERGE job; (3) fragments operational monitoring across Confluent and GCP platforms, increases total monthly cost by 30-50%, and requires non-default tuning to avoid breaching the 60-second SLA. The low-latency co-location benefit is insufficient to offset these trade-offs.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Data Loss | Consumer group offset commits may advance past unprocessed events during Dataflow job restarts, worker preemptions, or pipeline upgrades, causing event loss that directly violates the zero-data-loss SLA and invalidates the hourly Kafka-to-BigQuery row count reconciliation | Configure KafkaIO checkpointing aligned to Dataflow durable shuffle checkpoints so offsets are only committed after successful BigQuery Storage Write API exactly-once commit; set Kafka consumer group auto.offset.reset=earliest to replay from last committed offset on restart; implement hourly reconciliation Cloud Composer DAG that compares Kafka consumer group lag-adjusted offset counts against BigQuery row counts with alerting on discrepancy exceeding 0.01%; maintain minimum 24-hour Kafka topic retention to support replay windows |
| Schema Evolution | Upstream Kafka producers may add, rename, or remove JSON fields without coordination, causing silent data loss from field drops, NullPointerExceptions in Beam DoFn parsing logic, or schema mismatch errors at the BigQuery Storage Write API layer | Adopt Confluent Schema Registry with backward-compatible JSON Schema or AVRO evolution policy enforced at producer registration; implement null-safe field mapping in the Beam parsing DoFn with explicit fallback values for missing optional fields; route any record failing schema validation to the dead-letter topic with a structured error envelope (raw_payload, error_type, topic, partition, offset, timestamp); include schema_version in the pipeline_audit.pipeline_run_log for change traceability |
| Latency SLA Breach | Under sustained peak load of 5,000 events/second, Dataflow auto-scale-out lag (typically 2-3 minutes to provision new workers), BigQuery Storage Write API flush intervals, or Confluent-side consumer lag accumulation may cause end-to-end event latency to temporarily exceed 60 seconds | Enable Dataflow Streaming Engine; set Storage Write API commit interval to 20 seconds providing 40 seconds of remaining budget; configure Cloud Monitoring latency alert at 45 seconds (15-second early warning before SLA breach); set minWorkers=4 during defined business hours peak windows via Cloud Composer scheduled Dataflow job update; load test at 2x peak (10,000 events/second) pre-production to validate auto-scaling response time and establish latency baselines |
| Security and PII | Clickstream events likely contain user-identifiable behavioural data (user_id, session_id, IP-derived attributes, device fingerprints) that may be subject to GDPR, CCPA, or internal data governance policies, despite no explicit PII classification in the current requirements | Apply BigQuery column-level security policies and data masking on fields classified as PII or quasi-PII; enable Cloud DLP inspection jobs on the dead-letter topic before long-term storage; ensure Dataflow workers run in a Shared VPC with Private Google Access and no external IP addresses; rotate Confluent API keys on a 90-day cycle via Secret Manager versioning; conduct formal PII data classification review and document handling requirements before production launch |
| Operational Complexity | Sliding window deduplication state over 10-minute windows accumulating at 5,000 events/second generates a large in-flight state store; without Streaming Engine, individual Dataflow workers may experience GC pressure, JVM heap exhaustion, or state backend latency spikes causing pipeline slowdowns or OOM worker failures | Enable Dataflow Streaming Engine to externalise state to managed Google infrastructure, removing per-worker state store constraints; set worker machine type to n2-standard-4 (4 vCPU, 16 GB) minimum; define Cloud Monitoring worker memory utilisation alert at 80% threshold; establish a pre-production load test protocol at 2x peak throughput with 10-minute sustained duration before every major pipeline version deployment |
| Vendor Dependency | Dual platform dependency on Confluent Cloud and GCP means a Confluent Cloud incident (cluster unavailability, quota exhaustion, connectivity disruption) directly impacts pipeline ingestion regardless of GCP availability, and the pipeline has no fallback ingestion path | Configure Kafka topic retention to minimum 24 hours to enable full-backfill replay from last committed consumer offset following a Confluent recovery; define RTO (1 hour) and RPO (zero data loss, 24-hour replay window) targets for Confluent outage scenarios in the operational runbook; configure Kafka consumer lag alerting with a 5-minute lag threshold as an early warning before the 60-second SLA is impacted; establish a Confluent Cloud SLA review as part of vendor contract renewal |

---

## Assumptions

1. Confluent Kafka cluster endpoint (pkc-abc12.us-central1.gcp.confluent.cloud:9092) is hosted in GCP us-central1, co-located with the target Dataflow region, minimising cross-region network latency and Confluent Cloud egress costs
2. GCP Secret Manager stores the Confluent SASL/PLAIN API key and secret as versioned secrets; the Dataflow service account is granted the secretmanager.secretAccessor IAM role and credentials are never embedded in pipeline code or Flex Template metadata
3. BigQuery dataset verizon_clickstream_deah exists in project verizon-data and is pre-provisioned; table schemas for page_views, user_events, and sessions are defined, stable, and available at pipeline deployment time
4. A dedicated dead-letter Kafka topic (clickstream.dead_letter) is pre-provisioned in the Confluent Kafka cluster with a minimum 7-day retention policy to support replay and forensic analysis of failed records
5. The pipeline_audit.pipeline_run_log table exists in the verizon-data BigQuery project with a schema accommodating fields for job_id, pipeline_name, topic_name, window_start, window_end, records_read, records_written, records_dead_lettered, and run_timestamp
6. Dataflow Streaming Engine is enabled on the verizon-data GCP project to externalise window state management and reduce per-worker memory pressure for the 10-minute sliding window deduplication state store
7. The production Dataflow service account holds the BigQuery Data Editor, bigquery.tables.create, and bigquery.datasets.get IAM roles on the verizon-data project, scoped to the verizon_clickstream_deah and pipeline_audit datasets
8. A Cloud Build or equivalent CI/CD pipeline is available to build, tag, and push Dataflow Flex Template container images to Artifact Registry, enabling versioned and reproducible job deployment
9. Network connectivity between Dataflow VPC workers and the Confluent Cloud Kafka endpoint is established via Private Google Access or an allowlisted egress firewall rule; Dataflow workers are configured to use internal IPs only
10. Clickstream event data is assumed to contain PII-adjacent behavioural attributes (user_id, session_id, device identifiers) even though no explicit PII classification has been declared; a formal data classification and DLP assessment is expected before production go-live
11. Event schema is expected to remain backward-compatible (additive field changes only) during initial pipeline deployment; a schema change notification process with upstream producing teams will be established before launch
12. Deployment environment is production, inferred from the real-time Looker dashboard requirement, zero-data-loss SLA, and Confluent production cluster endpoint

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Use Cloud Dataflow Streaming with Apache Beam KafkaIO as the ingestion and processing engine | technology.preferred_tools: Google Cloud Dataflow, Apache Beam; functional_requirements[0]: Consume events in real-time from Confluent Kafka using Dataflow Streaming | 60 seconds | 50 GB/day; 5,000 events/second peak |
| Implement 10-minute sliding window deduplication on event_id using Beam stateful DoFn processing | functional_requirements[2]: Deduplicate events on event_id within a 10-minute sliding window | — | 5,000 events/second peak |
| Partition BigQuery target tables by event_timestamp (DATE) with session_id clustering | functional_requirements[3]: Partition BigQuery target tables by event_timestamp (DATE) | — | 50 GB/day |
| Route unparseable and schema-invalid events to a Confluent dead-letter Kafka topic (clickstream.dead_letter) rather than a BigQuery table | functional_requirements[4]: Route unparseable or schema-invalid events to a dead-letter Kafka topic; assumptions[3]: Dead-letter destination is a separate Kafka topic | — | — |
| Use BigQuery Storage Write API in exactly-once mode as the write path to enforce zero-data-loss SLA | non_functional.sla: Zero data loss; event count in Kafka must match BigQuery row count per hour | 60 seconds | 50 GB/day |
| Inject Confluent SASL/PLAIN API credentials from GCP Secret Manager at Dataflow job runtime | security.access_controls: Confluent Kafka authentication via SASL/PLAIN API key; assumptions[1]: SASL/PLAIN API key credentials will be securely injected at deployment time and are not embedded in pipeline code | — | — |
| Configure Dataflow auto-scaling between minWorkers=2 and maxWorkers=20 using Streaming Engine throughput-based scaling | non_functional.scalability: Dataflow job must auto-scale between 2 and 20 workers based on load | — | 5,000 events/second peak |
| Write pipeline run audit records to pipeline_audit.pipeline_run_log in BigQuery after each processing window | functional_requirements[5]: Log pipeline run results to pipeline_audit.pipeline_run_log | — | — |
| Target BigQuery dataset verizon_clickstream_deah in project verizon-data with tables page_views, user_events, sessions | source_connections[1]: db_type=bigquery, database=verizon_clickstream_deah, source_tables=[page_views, user_events, sessions]; assumptions[0]: BigQuery target project is verizon-data | 60 seconds | 50 GB/day |
| Consume from Confluent Kafka endpoint pkc-abc12.us-central1.gcp.confluent.cloud:9092 over port 9092 | source_connections[0]: db_type=kafka, host=pkc-abc12.us-central1.gcp.confluent.cloud, port=9092, source_tables=[clickstream.page_views, clickstream.user_events, clickstream.sessions] | 60 seconds | 5,000 events/second peak |

---

## Open Questions — Action Required

1. Is Confluent Schema Registry in use for the 3 Kafka topics? If AVRO or Protobuf schemas are registered, the Beam pipeline should use the Confluent Schema Registry Beam transform for deserialization rather than generic JSON parsing, providing compile-time schema enforcement and significantly improved parse performance.
2. What is the agreed schema evolution policy with upstream Kafka producers? Specifically, are field additions guaranteed to be backward-compatible, and is there a formal schema change notification process to alert the pipeline team before breaking changes are deployed to producers?
3. What retention period is configured on the dead-letter Kafka topic (clickstream.dead_letter)? The retention window determines the replay and forensic analysis window for malformed events, and should be a minimum of 7 days to support incident investigation and reprocessing after schema fixes.
4. Has a formal PII data classification been performed on clickstream event payloads? Fields such as user_id, device_id, session_id, and any IP-derived attributes may require column-level BigQuery security policies, Cloud DLP masking, or explicit data handling agreements under GDPR or CCPA before the pipeline can be approved for production.
5. What is the target BigQuery table retention policy for verizon_clickstream_deah? At 50 GB/day, a 365-day retention window accumulates approximately 18 TB of active storage; partition expiry policies and table lifecycle configurations should be agreed with data owners before deployment.
6. Should the Dataflow minWorkers value be dynamically scheduled — higher during defined peak business hours and lower overnight — to balance 60-second SLA headroom during peak against cost efficiency during off-peak periods? Cloud Composer can orchestrate scheduled Dataflow job updates to adjust this floor.
7. Is there a session event ordering requirement for funnel analysis correctness? KafkaIO does not guarantee strict partition-level ordering when multiple workers consume the same topic partition; if downstream Looker funnel queries depend on ordered event sequences within a session, this must be addressed via session_id-keyed windowing or an ORDER BY clause at query time.
8. What alerting and on-call channels (PagerDuty, Slack, email) should Cloud Monitoring use for pipeline health alerts including consumer lag threshold breaches, end-to-end latency warnings at 45 seconds, dead-letter topic write failures, and hourly row count reconciliation discrepancies?
