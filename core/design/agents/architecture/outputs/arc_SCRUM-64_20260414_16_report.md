# Architecture Decision Document — Verizon analytics platform

| Field | Value |
|---|---|
| **Project** | Verizon analytics platform |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Batch |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Dataflow with Cloud SQL Connector
>
> **Why:** Best balance of scalability and operability for handling both large historical loads and daily incremental syncs with robust error handling and monitoring
>
> **Score:** 6.85 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2 ✅ | Option 3  |
|---|---||---||---|
| **Name** | Cloud SQL Federated Queries with Composer | Dataflow with Cloud SQL Connector | Cloud SQL to GCS with BigQuery External Tables |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | dbt-bigquery | Dataflow + dbt-bigquery | BigQuery Scheduled Queries + dbt |
| **Storage** | BigQuery | BigQuery | GCS + BigQuery |
| **Weighted Score** | **6.65** | **6.85**  ✅ | **6.25** |

---

## Option 1 — Cloud SQL Federated Queries with Composer

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | BigQuery federated queries to Cloud SQL read replica |
| Processing | dbt transformations in BigQuery with UPSERT logic |
| Storage | BigQuery native tables with partitioning and clustering |
| Consumption | Direct BigQuery access for analytics workloads |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | BigQuery Federated Queries | — | Yes |
| Processing | dbt-bigquery | 1.7 | No |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.x | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.6 | No |

### Pros

- No data movement overhead - queries source directly
- Real-time data consistency with source
- Minimal infrastructure complexity
- Native BigQuery integration
- Built-in data validation through SQL

### Cons

- Network latency for large historical loads
- Limited to SQL transformations
- Potential connection pool exhaustion on read replica
- Query performance depends on network stability

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Network failures could cause incomplete loads |
| Scaling | Large historical queries may timeout or impact read replica |
| Latency | Cross-network queries slower than local processing |
| Cost | BigQuery slot usage for federated queries can be unpredictable |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 6 | 8 | 6 | 7 | **6.65** |

---

## Option 2 — Dataflow with Cloud SQL Connector ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Dataflow reads from Cloud SQL read replica using JDBC |
| Processing | Dataflow streaming pipeline with windowing for batch processing and UPSERT logic |
| Storage | BigQuery with date partitioning and employee_id clustering |
| Consumption | BigQuery for analytics with dbt for data marts |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataflow | — | Yes |
| Processing | Dataflow + dbt-bigquery | 1.7 | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.x | Yes |
| Monitoring | Cloud Monitoring + dbt docs | — | Yes |
| Iac | Terraform | 1.6 | No |

### Pros

- Auto-scaling for variable data loads
- Built-in error handling and retries
- Optimized for BigQuery writes with batch loading
- Can handle large historical loads efficiently
- Native GCP integration with monitoring

### Cons

- Higher complexity than federated queries
- Additional infrastructure to manage
- Learning curve for Dataflow development
- Potential over-provisioning for small daily loads

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Pipeline failures could result in data loss without proper checkpointing |
| Scaling | Auto-scaling may not respond quickly enough for SLA requirements |
| Latency | Pipeline startup time could impact daily SLA |
| Cost | Dataflow workers running continuously even for small incremental loads |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 8 | 6 | 7 | 8 | **6.85** |

---

## Option 3 — Cloud SQL to GCS with BigQuery External Tables

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud SQL export to GCS using gcloud sql export |
| Processing | BigQuery external tables with scheduled queries for UPSERT operations |
| Storage | GCS for raw data, BigQuery for processed analytics tables |
| Consumption | BigQuery analytics tables with dbt transformations |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud SQL Export + GCS | — | Yes |
| Processing | BigQuery Scheduled Queries + dbt | 1.7 | Yes |
| Storage | GCS + BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.x | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.6 | No |

### Pros

- Lowest cost for storage with GCS
- Native Cloud SQL export functionality
- Clear separation of raw and processed data
- Can leverage BigQuery's columnar performance
- Good for audit trails with raw data retention

### Cons

- Additional storage layer increases complexity
- External table performance limitations
- Manual export process may not support incremental efficiently
- Data freshness depends on export frequency
- Limited real-time capabilities

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Export process failures could result in incomplete datasets |
| Scaling | Large exports may impact source database even on read replica |
| Latency | Multi-step process increases end-to-end processing time |
| Cost | Dual storage costs (GCS + BigQuery) for similar data |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 5 | 5 | 5 | 6 | **6.25** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud SQL Federated Queries with Composer | 7 | 6 | 8 | 6 | 7 | **6.65** |
| Dataflow with Cloud SQL Connector ✅ | 6 | 8 | 6 | 7 | 8 | **6.85** |
| Cloud SQL to GCS with BigQuery External Tables | 8 | 5 | 5 | 5 | 6 | **6.25** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Dataflow with Cloud SQL Connector**
**Weighted Score: 6.85**

**Justification:** Best balance of scalability and operability for handling both large historical loads and daily incremental syncs with robust error handling and monitoring

**Why highest score:** Highest weighted score (6.85) due to superior scalability (8) and operability (8) which are critical for production data pipeline reliability

**Trade-offs accepted:** Slightly higher complexity and cost in exchange for better reliability and scaling capabilities

---

## Rejected Options

### Cloud SQL Federated Queries with Composer

Lower scalability and latency scores due to federated query limitations for large datasets

### Cloud SQL to GCS with BigQuery External Tables

Lowest weighted score (6.25) due to poor scalability and complexity scores, making it unsuitable for production requirements

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Data Consistency | Read replica lag could cause data inconsistencies during incremental loads | Implement lag monitoring and adjust sync timing based on replica delay |
| Source Impact | Large queries on read replica might still impact source performance | Implement query throttling and monitor read replica performance metrics |
| SLA Compliance | 06:00 AM UTC deadline may be at risk during large data loads or pipeline failures | Implement alerting, automated retries, and backup processing windows |

---

## Assumptions

1. MySQL read replica has sufficient capacity for data extraction
2. Network connectivity between GCP and MySQL instance is stable
3. Employee data volume fits within daily processing windows
4. updated_at column exists and is properly maintained in source table

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Selected Dataflow over federated queries | functional_requirements | Daily batch processing with 06:00 AM SLA | Full historical load followed by daily incremental |
| BigQuery as target with partitioning | objective | Zero production database impact | Employee data with UPSERT operations |
| Cloud Composer for orchestration | technology.preferred_tools | — | — |

---

## Open Questions — Action Required

1. What is the estimated row count and data size for full historical employee data load?
2. Are there specific BigQuery dataset/table naming conventions to follow?
3. Should we implement data archival policies for historical data in BigQuery?
4. What is the acceptable read replica lag tolerance for data consistency?
