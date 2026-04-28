# Architecture Decision Document — Customer360

| Field | Value |
|---|---|
| **Project** | Customer360 |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Batch |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Cloud Functions + Cloud Scheduler + BigQuery
>
> **Why:** Best fit for current requirements with 10GB hourly batches in dev environment, offering optimal cost-efficiency and operational simplicity
>
> **Score:** 7.05 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2 ✅ | Option 3  |
|---|---||---||---|
| **Name** | Cloud Composer + Cloud SQL Proxy + BigQuery | Cloud Functions + Cloud Scheduler + BigQuery | Datastream + Dataflow + BigQuery |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Dataflow | Cloud Functions | Dataflow |
| **Storage** | BigQuery | BigQuery | BigQuery |
| **Weighted Score** | **6.65** | **7.05**  ✅ | **6.15** |

---

## Option 1 — Cloud Composer + Cloud SQL Proxy + BigQuery

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer orchestrates Cloud SQL Proxy connections to extract MySQL data |
| Processing | Dataflow jobs transform and validate data with Python transforms |
| Storage | BigQuery tables store processed data with partitioning by date |
| Consumption | BigQuery native SQL interface for analytics and reporting |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud SQL Proxy | — | Yes |
| Processing | Dataflow | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.0 | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5 | No |

### Pros

- Native GCP integration with Cloud SQL Proxy for secure MySQL access
- Fully managed services reduce operational overhead
- Auto-scaling Dataflow handles variable data volumes
- BigQuery provides immediate analytics capabilities

### Cons

- Higher cost for small datasets due to Composer overhead
- Complex setup for simple extract-load requirements
- Potential network latency to external MySQL instance

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | No built-in data validation - requires custom Dataflow transforms |
| Scaling | Composer has minimum resource requirements regardless of workload size |
| Latency | Multi-service architecture may introduce delays under 1-hour SLA |
| Cost | Composer runs continuously even when not processing data |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 8 | 5 | 7 | 8 | **6.65** |

---

## Option 2 — Cloud Functions + Cloud Scheduler + BigQuery ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Scheduler triggers Cloud Functions to connect directly to MySQL |
| Processing | Cloud Functions execute SQL extracts and basic transforms in-memory |
| Storage | BigQuery receives data via streaming inserts or batch loads |
| Consumption | BigQuery native SQL interface for analytics and reporting |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Functions | 2nd gen | Yes |
| Processing | Cloud Functions | 2nd gen | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Scheduler | — | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5 | No |

### Pros

- Serverless architecture with pay-per-execution pricing
- Simple deployment and minimal operational overhead
- Fast startup times suitable for hourly schedules
- Direct MySQL connectivity without proxy overhead

### Cons

- Limited memory and execution time for large datasets
- No built-in retry or error handling for complex failures
- Manual scaling logic required for growing data volumes

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Limited transformation capabilities within function memory constraints |
| Scaling | Functions may timeout with datasets approaching 10GB limit |
| Latency | Single-threaded processing may struggle with SLA as data grows |
| Cost | Potential network egress costs for large data transfers |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 6 | 8 | 6 | 7 | **7.05** |

---

## Option 3 — Datastream + Dataflow + BigQuery

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Datastream replicates MySQL data to Cloud Storage in real-time |
| Processing | Scheduled Dataflow jobs process accumulated files from Cloud Storage |
| Storage | BigQuery tables store processed data with time-based partitioning |
| Consumption | BigQuery native SQL interface for analytics and reporting |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Datastream | — | Yes |
| Processing | Dataflow | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Scheduler | — | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5 | No |

### Pros

- Near real-time data replication with change data capture
- Robust handling of schema changes and data types
- Dataflow provides advanced transformation capabilities
- Future-proof architecture for streaming requirements

### Cons

- Over-engineered for simple batch hourly requirements
- Higher cost due to continuous Datastream replication
- Additional complexity managing intermediate Cloud Storage

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | CDC may introduce data consistency challenges during high-change periods |
| Scaling | Datastream pricing scales with database size, not just changed data |
| Latency | Batch processing of real-time feeds adds unnecessary complexity |
| Cost | Continuous replication costs regardless of actual data usage |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 9 | 4 | 8 | 6 | **6.15** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Cloud SQL Proxy + BigQuery | 6 | 8 | 5 | 7 | 8 | **6.65** |
| Cloud Functions + Cloud Scheduler + BigQuery ✅ | 8 | 6 | 8 | 6 | 7 | **7.05** |
| Datastream + Dataflow + BigQuery | 5 | 9 | 4 | 8 | 6 | **6.15** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Functions + Cloud Scheduler + BigQuery**
**Weighted Score: 7.05**

**Justification:** Best fit for current requirements with 10GB hourly batches in dev environment, offering optimal cost-efficiency and operational simplicity

**Why highest score:** Highest weighted score due to excellent cost efficiency (8/10) and low complexity (8/10) which outweighs moderate scalability concerns for current medium-volume requirements

**Trade-offs accepted:** Accepting potential future scaling limitations for current cost optimization and operational simplicity in dev environment

---

## Rejected Options

### Cloud Composer + Cloud SQL Proxy + BigQuery

Higher complexity and cost for the requirements scale

### Datastream + Dataflow + BigQuery

Over-engineered solution with unnecessary real-time capabilities and higher costs for batch requirements

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Security | MySQL credentials and network access require secure configuration | Use Secret Manager for credentials and Cloud SQL Proxy for secure connections |
| Data Quality | No explicit data validation requirements specified | Implement basic schema validation and data profiling in processing layer |
| Scalability | Solution may need re-architecture if data volume grows significantly beyond 10GB | Monitor data growth trends and plan migration to Dataflow-based solution |

---

## Assumptions

1. Dev environment has relaxed availability requirements compared to production
2. MySQL source system allows direct connections from GCP
3. EMPLOYEES table structure is relatively stable
4. 10GB represents peak data volume, not average

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Selected Cloud Functions for simplicity and cost | technology.preferred_tools | less than 1 hour | 10 GB |
| BigQuery as target storage | business_context | — | — |
| Hourly batch processing pattern | data_requirements.frequency | less than 1 hour | 10 GB |

---

## Open Questions — Action Required

1. What are the specific transformation requirements for EMPLOYEES data?
2. Are there data retention policies for the source MySQL system?
3. What is the expected growth rate for data volume beyond dev environment?
4. Are there specific data quality validation requirements?
