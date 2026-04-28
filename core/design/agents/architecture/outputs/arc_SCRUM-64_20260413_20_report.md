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

> **Build with:** Cloud Composer + Cloud Run Jobs + BigQuery ETL
>
> **Why:** Best balance of cost, control, and operability for the specific requirements. Cloud Run's serverless model is cost-effective for daily batch jobs, while providing the granular control needed for UPSERT logic and data validation.
>
> **Score:** 7.60 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2  | Option 3 ✅ |
|---|---||---||---|
| **Name** | Cloud Composer + Dataflow + BigQuery Native Pipeline | Cloud Composer + Cloud SQL Federated Queries + dbt | Cloud Composer + Cloud Run Jobs + BigQuery ETL |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Dataflow | dbt Core | Cloud Run Jobs + BigQuery |
| **Storage** | BigQuery | BigQuery | BigQuery + Cloud Storage |
| **Weighted Score** | **7.35** | **6.55** | **7.60**  ✅ |

---

## Option 1 — Cloud Composer + Dataflow + BigQuery Native Pipeline

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud SQL Proxy connects to MySQL read-replica via secure tunnel |
| Processing | Dataflow batch job performs UPSERT with data validation and reconciliation |
| Storage | BigQuery tables with partitioning and clustering for optimal performance |
| Consumption | Direct BigQuery access with view layer for business logic |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud SQL Proxy + Dataflow connectors | — | Yes |
| Processing | Dataflow | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer (Airflow) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Fully managed services reduce operational overhead
- Native BigQuery integration with optimal performance
- Auto-scaling Dataflow handles variable data volumes
- Built-in monitoring and alerting capabilities
- Secure connectivity through Cloud SQL Proxy

### Cons

- Higher cost for fully managed services
- Dataflow startup latency for small data volumes
- Cloud Composer overhead for simple scheduling

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Dataflow job failures could skip validation steps |
| Scaling | Dataflow auto-scaling may over-provision for small datasets |
| Latency | Dataflow cold start could delay 06:00 AM SLA |
| Cost | Fully managed services premium pricing |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 9 | 7 | 7 | 9 | **7.35** |

---

## Option 2 — Cloud Composer + Cloud SQL Federated Queries + dbt

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | BigQuery federated queries directly access MySQL read-replica |
| Processing | dbt models handle UPSERT logic, data validation, and transformations in BigQuery |
| Storage | BigQuery staging and production tables with incremental materialization |
| Consumption | dbt-generated views and tables for analytics consumption |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | BigQuery Federated Queries | — | Yes |
| Processing | dbt Core | 1.6+ | No |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer (Airflow) | 2.x | Yes |
| Monitoring | Cloud Monitoring + dbt docs | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- No separate ingestion infrastructure needed
- dbt provides excellent data transformation capabilities
- Direct SQL-based approach aligns with team expertise
- Built-in data lineage and documentation
- Incremental models optimize for daily updates

### Cons

- Federated queries may have performance limitations
- Network latency between BigQuery and MySQL
- Limited control over data extraction timing

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Federated query failures could impact data consistency |
| Scaling | Cross-network queries may not scale well with data growth |
| Latency | Network dependency could cause SLA misses |
| Cost | Repeated federated queries increase BigQuery slot usage |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 6 | 6 | 6 | 7 | **6.55** |

---

## Option 3 — Cloud Composer + Cloud Run Jobs + BigQuery ETL ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Run job connects to MySQL read-replica and extracts data to GCS staging |
| Processing | Subsequent Cloud Run job loads from GCS to BigQuery with UPSERT and validation logic |
| Storage | BigQuery tables with date partitioning and employee_id clustering |
| Consumption | BigQuery views for business analytics with proper access controls |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Run Jobs (Python/SQL) | — | Yes |
| Processing | Cloud Run Jobs + BigQuery | — | Yes |
| Storage | BigQuery + Cloud Storage | — | Yes |
| Orchestration | Cloud Composer (Airflow) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Cost-effective serverless execution model
- Fine-grained control over extraction and loading logic
- GCS staging provides data durability and audit trail
- Predictable performance for scheduled workloads
- Easy to implement row count reconciliation and validation

### Cons

- Custom code maintenance overhead
- Multi-step process increases complexity
- Manual error handling and retry logic required

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Custom code bugs could compromise data integrity |
| Scaling | Single-threaded Cloud Run jobs may not handle large data growth |
| Latency | Multi-step process could delay completion |
| Cost | Storage costs for GCS staging area |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 7 | 8 | 8 | 7 | **7.60** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Dataflow + BigQuery Native Pipeline | 6 | 9 | 7 | 7 | 9 | **7.35** |
| Cloud Composer + Cloud SQL Federated Queries + dbt | 7 | 6 | 6 | 6 | 7 | **6.55** |
| Cloud Composer + Cloud Run Jobs + BigQuery ETL ✅ | 8 | 7 | 8 | 8 | 7 | **7.60** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Composer + Cloud Run Jobs + BigQuery ETL**
**Weighted Score: 7.60**

**Justification:** Best balance of cost, control, and operability for the specific requirements. Cloud Run's serverless model is cost-effective for daily batch jobs, while providing the granular control needed for UPSERT logic and data validation.

**Why highest score:** Achieved highest weighted score (7.6) due to excellent cost efficiency (8/10), good scalability (7/10), and strong complexity management (8/10). The serverless model aligns perfectly with daily batch requirements.

**Trade-offs accepted:** Accepting custom code maintenance overhead in exchange for precise control over data validation, reconciliation logic, and cost optimization through serverless execution.

---

## Rejected Options

### Cloud Composer + Dataflow + BigQuery Native Pipeline

Higher complexity and cost compared to simpler alternatives for this use case

### Cloud Composer + Cloud SQL Federated Queries + dbt

Federated queries introduce network dependencies and scaling limitations

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Data Consistency | Read-replica lag could cause data inconsistencies if writes occur during extraction window | Implement checksum validation and reconciliation processes with source system |
| SLA Compliance | 06:00 AM UTC deadline may be missed due to data volume growth or system failures | Set up proactive monitoring, alerts, and automatic retry mechanisms with sufficient buffer time |
| Security | Database credentials and network access require secure management | Use Secret Manager for credentials, VPC peering or Cloud SQL Auth Proxy for secure connectivity |

---

## Assumptions

1. MySQL read-replica has sufficient capacity for daily full table scans
2. Network connectivity between GCP and MySQL instance is stable
3. Employee data volume fits within Cloud Run job execution limits
4. updated_at column is reliably maintained in source system

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Selected Cloud Run Jobs for processing | functional_requirements | Daily refresh cycle with 06:00 AM UTC SLA | Low volume daily incremental with historical full load |
| BigQuery as target storage with partitioning | objective | — | Employee data with primary key relationships |
| Cloud Composer for orchestration | technology.preferred_tools | — | — |

---

## Open Questions — Action Required

1. What is the approximate row count and data size of the employees table?
2. Are there specific data retention requirements for the staging area in GCS?
3. Should the pipeline support schema evolution or is the employee table structure stable?
4. Are there specific business hours when the read-replica should not be accessed?
