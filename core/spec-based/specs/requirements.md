# Requirements: Kafka to BigQuery Real-Time Ingestion Pipeline

**Date:** 2026-04-12
**Status:** Draft

---

## Goal
Build a real-time streaming ingestion pipeline that continuously reads JSON messages from a Kafka topic and writes them into a BigQuery table with low latency. The pipeline ensures data is available in BigQuery within seconds to minutes of being produced, enabling near-real-time analytics, monitoring, and reporting for downstream consumers.

## Inputs
- **Source system:** Apache Kafka
- **Topic:** Not specified — assumed a single configurable topic name (e.g. `events_topic`)
- **Format:** JSON
- **Schema:** Not specified — assumed a flat or semi-structured JSON object; schema to be confirmed before implementation
- **Frequency:** Continuous real-time streaming (event-driven, not scheduled)
- **Expected volume:** Not specified — assumed moderate (thousands to tens of thousands of messages per minute)

## Outputs
- **Destination:** Google BigQuery
- **Project/Dataset/Table:** Not specified — assumed configurable via environment variables (`BQ_PROJECT`, `BQ_DATASET`, `BQ_TABLE`)
- **Format:** Structured rows mapped from JSON fields, written via BigQuery Storage Write API (streaming)
- **Downstream consumers:** Not specified — assumed real-time dashboards, monitoring systems, and ad-hoc analytics queries

## Data Sources

| System | Type | Connection Method | Owner/Team |
|--------|------|-------------------|------------|
| Apache Kafka | Message queue | Kafka consumer (bootstrap servers + topic) | Not specified |
| Google BigQuery | Cloud data warehouse | BigQuery Storage Write API (streaming insert) | Not specified |

## SLAs & Performance
- **Data freshness:** Data must be available in BigQuery within seconds to minutes of being produced on the Kafka topic (end-to-end latency < 5 minutes target)
- **Latency:** Near-real-time; each message should be written to BigQuery as soon as it is consumed from Kafka
- **Throughput:** Must sustain continuous ingestion at assumed moderate volume (thousands–tens of thousands of messages per minute) without lag accumulation
- **Availability:** Pipeline must run continuously; automatic restart on failure is required
- **Deduplication:** Not specified — assumed at-least-once delivery; deduplication strategy to be defined if needed

## Constraints
- **Language:** Python 3.12
- **Pipeline framework:** To be determined in design phase (e.g. Apache Beam/Dataflow, Spark Structured Streaming, or custom consumer loop)
- **Cloud platform:** Google Cloud (BigQuery as target)
- **Security/compliance:** Not specified — assumed Kafka and BigQuery credentials managed via environment variables or a secrets manager
- **Existing systems:** Kafka cluster and BigQuery project assumed to be pre-existing; pipeline should not require infrastructure provisioning beyond the streaming job itself
- **No real DB/API connections in tests** — all external calls must be mocked

## Assumptions
1. A single Kafka topic is consumed continuously; topic name is externally configurable.
2. JSON messages have a consistent flat or semi-structured schema; schema drift handling is out of scope for v1.
3. BigQuery project, dataset, and table name are provided via environment variables.
4. The BigQuery target table is pre-created or will be created by the pipeline using the inferred schema.
5. Real-time means continuous streaming (not scheduled); messages are written to BigQuery as they arrive.
6. Message volume is moderate (thousands–tens of thousands per minute); the design must support sustained throughput without batching delays.
7. At-least-once delivery is acceptable; strict exactly-once semantics are not required for v1.
8. Kafka bootstrap server addresses and credentials are available as environment variables.
9. No PII masking, encryption at rest, or data governance controls are required for v1.
10. The pipeline runs in a Google Cloud environment with appropriate IAM permissions pre-configured.
11. The pipeline process is long-running and managed by a process supervisor or container orchestrator (e.g. Cloud Run, GKE).
