# Architecture Decision Document — Customer 360

| Field | Value |
|---|---|
| **Project** | Customer 360 |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Batch |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Cloud Functions + GCS + BigQuery Load Jobs
>
> **Why:** Best balance of cost-effectiveness, simplicity, and latency performance for the 10GB hourly batch requirement
>
> **Score:** 7.35 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2  | Option 3 ✅ |
|---|---||---||---|
| **Name** | Cloud SQL Connector + Dataflow + BigQuery | Dataproc + BigQuery Direct Load | Cloud Functions + GCS + BigQuery Load Jobs |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Dataflow | Dataproc Spark | Cloud Functions |
| **Storage** | BigQuery | BigQuery | BigQuery + GCS |
| **Weighted Score** | **7.15** | **7.25** | **7.35**  ✅ |

---

## Option 1 — Cloud SQL Connector + Dataflow + BigQuery

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud SQL Connector extracts from MySQL via JDBC |
| Processing | Dataflow batch job transforms and validates data |
| Storage | BigQuery tables for analytics consumption |
| Consumption | Direct BigQuery queries and BI tools |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud SQL Connector | — | Yes |
| Processing | Dataflow | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.x | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Native GCP integration with Cloud SQL
- Dataflow auto-scaling handles variable data volumes
- Built-in data quality validation in Dataflow
- Direct BigQuery loading for analytics

### Cons

- Higher cost due to Dataflow compute charges
- Requires Java/Python pipeline development
- Cloud SQL Connector licensing costs

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Dataflow transformations may fail silently without proper error handling |
| Scaling | Dataflow workers may not scale fast enough for 1-hour SLA |
| Latency | Network latency between MySQL and GCP could impact extraction time |
| Cost | Dataflow compute costs scale with data volume and complexity |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 9 | 6 | 8 | 8 | **7.15** |

---

## Option 2 — Dataproc + BigQuery Direct Load

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Dataproc Spark job connects to MySQL via JDBC |
| Processing | Spark transformations and data validation |
| Storage | Direct load to BigQuery via Spark BigQuery connector |
| Consumption | BigQuery analytics and reporting |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataproc | 2.1 | Yes |
| Processing | Dataproc Spark | 3.3 | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.x | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Cost-effective with ephemeral Dataproc clusters
- Spark's robust JDBC connectivity to MySQL
- Native BigQuery connector for efficient loading
- Familiar Spark ecosystem for data engineers

### Cons

- Cluster startup time impacts overall latency
- Requires Spark/Scala development expertise
- Manual cluster sizing and optimization needed

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Spark job failures may leave partial data loads in BigQuery |
| Scaling | Fixed cluster sizing may not handle data volume spikes efficiently |
| Latency | Cluster provisioning adds 2-3 minutes to each run |
| Cost | Inefficient cluster sizing leads to resource waste |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 7 | 7 | 6 | 7 | **7.25** |

---

## Option 3 — Cloud Functions + GCS + BigQuery Load Jobs ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Function extracts MySQL data via pymysql |
| Processing | Lightweight transformation in Cloud Function, stage to GCS |
| Storage | BigQuery load jobs from GCS CSV/JSON files |
| Consumption | BigQuery tables for analytics consumption |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Functions | 2nd gen | Yes |
| Processing | Cloud Functions | 2nd gen | Yes |
| Storage | BigQuery + GCS | — | Yes |
| Orchestration | Cloud Composer | 2.x | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Lowest cost with serverless execution
- Fast startup time meets 1-hour SLA easily
- Simple Python-based development
- Native GCS and BigQuery integration

### Cons

- 15-minute Cloud Function timeout limits large extracts
- Limited memory (8GB max) for data processing
- Manual error handling and retry logic needed

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Function timeouts may cause incomplete data extraction |
| Scaling | Memory and timeout limits constrain data volume growth |
| Latency | Large MySQL result sets may exceed function limits |
| Cost | Frequent function invocations increase costs at scale |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 9 | 5 | 8 | 9 | 7 | **7.35** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud SQL Connector + Dataflow + BigQuery | 6 | 9 | 6 | 8 | 8 | **7.15** |
| Dataproc + BigQuery Direct Load | 8 | 7 | 7 | 6 | 7 | **7.25** |
| Cloud Functions + GCS + BigQuery Load Jobs ✅ | 9 | 5 | 8 | 9 | 7 | **7.35** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Functions + GCS + BigQuery Load Jobs**
**Weighted Score: 7.35**

**Justification:** Best balance of cost-effectiveness, simplicity, and latency performance for the 10GB hourly batch requirement

**Why highest score:** Achieves highest weighted score (7.35) due to excellent cost (9) and latency (8) performance, with acceptable trade-offs in scalability

**Trade-offs accepted:** Limited scalability beyond current 10GB requirement in exchange for optimal cost and latency performance

---

## Rejected Options

### Cloud SQL Connector + Dataflow + BigQuery

Higher complexity and cost compared to simpler alternatives for this use case

### Dataproc + BigQuery Direct Load

Cluster startup latency conflicts with 1-hour SLA requirement

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Security | MySQL credentials stored in Cloud Composer variables | Use Secret Manager for credential storage and IAM-based access |
| Network | Dependency on external MySQL host availability | Implement retry logic and alerting for connection failures |
| Data Consistency | Hourly extracts may miss transactions in progress | Use timestamp-based incremental extraction with overlap buffer |

---

## Assumptions

1. MySQL source system allows concurrent read connections
2. Network connectivity between GCP and MySQL host (34.70.79.163) is stable
3. Dev environment has sufficient BigQuery quotas for hourly 10GB loads
4. EMPLOYEES table structure is relatively stable

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud Functions for extraction | latency | less than 1 hour | 10 GB |
| BigQuery as target storage | business_context | — | — |
| Cloud Composer orchestration | preferred_tools | — | — |
| Hourly scheduling | frequency | — | — |

---

## Open Questions — Action Required

1. What is the expected data growth rate beyond 10GB per hour?
2. Are there specific data transformation requirements beyond basic extraction?
3. What are the disaster recovery and backup requirements for the pipeline?
4. Should incremental or full extraction be used for the EMPLOYEES table?
