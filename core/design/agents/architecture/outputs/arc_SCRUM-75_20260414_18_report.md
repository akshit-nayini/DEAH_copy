# Architecture Decision Document — Network 5G Core

| Field | Value |
|---|---|
| **Project** | Network 5G Core |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Batch |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Dataflow ETL with Cloud Storage Staging
>
> **Why:** Best balance of scalability, control, and enterprise-grade orchestration for zero data loss requirement
>
> **Score:** 7.20 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2 ✅ | Option 3  |
|---|---||---||---|
| **Name** | Cloud SQL Federated Query + Scheduled Transfer | Dataflow ETL with Cloud Storage Staging | Database Migration Service + BigQuery Transfer |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | BigQuery Scheduled Queries | Dataflow | BigQuery Transfer Service |
| **Storage** | BigQuery | BigQuery + Cloud Storage | BigQuery + Cloud SQL |
| **Weighted Score** | **7.05** | **7.20**  ✅ | **6.45** |

---

## Option 1 — Cloud SQL Federated Query + Scheduled Transfer

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud SQL Federated Query directly accesses MySQL instance |
| Processing | BigQuery scheduled query performs SELECT with data validation |
| Storage | Direct load to BigQuery verizon_data_deah dataset |
| Consumption | Automated reconciliation via scheduled query logging to pipeline_audit |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | BigQuery Federated Query | — | Yes |
| Processing | BigQuery Scheduled Queries | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | BigQuery Scheduled Queries | — | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Minimal infrastructure - no intermediate storage
- Native BigQuery integration eliminates data movement
- Built-in scheduling and monitoring
- Automatic retry and error handling

### Cons

- Limited transformation capabilities during ingestion
- Federated queries can impact source MySQL performance
- Less control over data validation during transfer

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Limited validation during federated query execution |
| Scaling | Federated queries may timeout on large historical loads |
| Latency | Direct MySQL queries could impact transactional workload |
| Cost | Repeated federated queries against external MySQL instance |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 6 | 9 | 6 | 8 | **7.05** |

---

## Option 2 — Dataflow ETL with Cloud Storage Staging ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Dataflow reads from MySQL via JDBC connector |
| Processing | Dataflow pipeline performs data validation and transformation |
| Storage | Dataflow writes to BigQuery with staging via Cloud Storage |
| Consumption | Cloud Composer orchestrates pipeline and reconciliation queries |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataflow | — | Yes |
| Processing | Dataflow | — | Yes |
| Storage | BigQuery + Cloud Storage | — | Yes |
| Orchestration | Cloud Composer | 2.x | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Full control over data validation and transformation
- Handles large historical loads efficiently
- Built-in error handling and dead letter queues
- Comprehensive orchestration with Cloud Composer
- Auto-scaling based on data volume

### Cons

- Higher complexity with multiple components
- Additional cost for Cloud Composer and Dataflow compute
- Requires more operational expertise

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Complex pipeline increases risk of transformation errors |
| Scaling | Dataflow worker scaling latency during peak loads |
| Latency | Multi-hop architecture increases end-to-end processing time |
| Cost | Continuous Composer environment and Dataflow compute costs |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 9 | 6 | 7 | 7 | **7.20** |

---

## Option 3 — Database Migration Service + BigQuery Transfer

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Database Migration Service replicates MySQL to Cloud SQL |
| Processing | BigQuery Transfer Service scheduled jobs move data from Cloud SQL |
| Storage | Data lands in BigQuery verizon_data_deah dataset |
| Consumption | BigQuery scheduled queries for reconciliation and audit logging |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Database Migration Service | — | Yes |
| Processing | BigQuery Transfer Service | — | Yes |
| Storage | BigQuery + Cloud SQL | — | Yes |
| Orchestration | BigQuery Scheduled Queries | — | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Fully managed migration and transfer services
- Minimal custom code required
- Built-in CDC capability for ongoing sync
- Strong consistency guarantees

### Cons

- Additional Cloud SQL instance increases costs
- Two-hop architecture adds complexity
- Limited transformation capabilities
- Ongoing Cloud SQL maintenance overhead

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Two-stage transfer increases risk of data inconsistency |
| Scaling | Cloud SQL instance sizing requirements for historical load |
| Latency | Two-hop transfer increases total processing time |
| Cost | Ongoing Cloud SQL instance costs plus transfer service fees |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 7 | 7 | 6 | 8 | **6.45** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud SQL Federated Query + Scheduled Transfer | 7 | 6 | 9 | 6 | 8 | **7.05** |
| Dataflow ETL with Cloud Storage Staging ✅ | 6 | 9 | 6 | 7 | 7 | **7.20** |
| Database Migration Service + BigQuery Transfer | 5 | 7 | 7 | 6 | 8 | **6.45** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Dataflow ETL with Cloud Storage Staging**
**Weighted Score: 7.20**

**Justification:** Best balance of scalability, control, and enterprise-grade orchestration for zero data loss requirement

**Why highest score:** Highest weighted score due to superior scalability (9/10) for historical loads and comprehensive data validation capabilities ensuring zero data loss compliance

**Trade-offs accepted:** Higher operational complexity and cost in exchange for guaranteed zero data loss and scalable historical load processing

---

## Rejected Options

### Cloud SQL Federated Query + Scheduled Transfer

Lower scalability for historical loads and potential MySQL performance impact

### Database Migration Service + BigQuery Transfer

Lowest weighted score due to high cost overhead from additional Cloud SQL instance and two-stage architecture complexity

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Source System Impact | Data extraction operations may impact MySQL transactional performance | Schedule extractions during low-usage windows and implement connection pooling with read replicas if available |
| Network Connectivity | External MySQL instance dependency creates network reliability risk | Implement retry logic, circuit breakers, and monitoring for connection failures |
| Data Consistency | Zero tolerance for row count discrepancies requires robust validation | Implement comprehensive reconciliation queries, checksums, and automated alerting on discrepancies |

---

## Assumptions

1. MySQL source system can handle JDBC connections for data extraction
2. Historical load is one-time operation followed by incremental updates
3. Network connectivity exists between GCP and MySQL instance at 34.70.79.163
4. Zero data loss requirement necessitates comprehensive validation and reconciliation

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Selected Dataflow ETL pattern | Zero data loss requirement | batch | low |
| Cloud Composer orchestration | Automated reconciliation | — | — |
| BigQuery as target storage | Load data to BigQuery verizon_data_deah dataset | — | — |

---

## Open Questions — Action Required

1. What is the expected row count and size of the employees table for capacity planning?
2. Are there any network security restrictions between GCP and the MySQL instance?
3. What is the acceptable maintenance window for initial historical load?
4. Should the pipeline support schema evolution for future table structure changes?
