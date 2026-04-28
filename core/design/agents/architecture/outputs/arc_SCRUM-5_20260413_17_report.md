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

> **Build with:** Cloud Functions + Cloud SQL Proxy + BigQuery
>
> **Why:** Best balance of simplicity, cost-effectiveness, and latency for the 10GB hourly MySQL ingestion requirement
>
> **Score:** 7.95 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2  | Option 3 ✅ |
|---|---||---||---|
| **Name** | Cloud SQL Connector + Dataflow + BigQuery | Dataproc + JDBC + BigQuery | Cloud Functions + Cloud SQL Proxy + BigQuery |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Dataflow | Dataproc | Cloud Functions |
| **Storage** | BigQuery | BigQuery | BigQuery |
| **Weighted Score** | **7.15** | **6.85** | **7.95**  ✅ |

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

## Option 2 — Dataproc + JDBC + BigQuery

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Dataproc Spark job connects to MySQL via JDBC |
| Processing | Spark transformations and data validation |
| Storage | BigQuery via Spark BigQuery connector |
| Consumption | BigQuery analytics and reporting |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataproc | 2.1 | Yes |
| Processing | Dataproc | 2.1 | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.x | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Cost-effective with ephemeral clusters
- Familiar Spark ecosystem for data engineers
- Good performance for medium data volumes
- Flexible transformation capabilities

### Cons

- Cluster startup time impacts latency
- Requires Spark/Scala expertise
- Manual cluster sizing and optimization

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Spark job failures may not be immediately visible |
| Scaling | Fixed cluster sizing may not handle volume spikes |
| Latency | Cluster provisioning adds 2-5 minutes to pipeline runtime |
| Cost | Underutilized clusters waste compute resources |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 7 | 5 | 6 | 7 | **6.85** |

---

## Option 3 — Cloud Functions + Cloud SQL Proxy + BigQuery ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Functions triggered by Composer connects via Cloud SQL Proxy |
| Processing | Lightweight Python transformations in Cloud Functions |
| Storage | Direct BigQuery streaming inserts or batch loads |
| Consumption | BigQuery for analytics and reporting |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Functions | 2nd gen | Yes |
| Processing | Cloud Functions | 2nd gen | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.x | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Lowest cost with pay-per-execution model
- Fast startup time meets 1-hour SLA easily
- Simple Python code for basic transformations
- Native GCP integration and monitoring

### Cons

- 15-minute execution timeout limits complex processing
- Memory constraints for large datasets
- Limited transformation capabilities

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Limited error handling and retry mechanisms |
| Scaling | Function timeout may not handle 10GB in single execution |
| Latency | Memory constraints could cause function restarts |
| Cost | BigQuery streaming inserts more expensive than batch loads |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 9 | 6 | 9 | 9 | 8 | **7.95** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud SQL Connector + Dataflow + BigQuery | 6 | 9 | 6 | 8 | 8 | **7.15** |
| Dataproc + JDBC + BigQuery | 8 | 7 | 5 | 6 | 7 | **6.85** |
| Cloud Functions + Cloud SQL Proxy + BigQuery ✅ | 9 | 6 | 9 | 9 | 8 | **7.95** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Functions + Cloud SQL Proxy + BigQuery**
**Weighted Score: 7.95**

**Justification:** Best balance of simplicity, cost-effectiveness, and latency for the 10GB hourly MySQL ingestion requirement

**Why highest score:** Highest weighted score due to excellent cost efficiency (9/10), low complexity (9/10), and fast execution (9/10) that easily meets the 1-hour SLA

**Trade-offs accepted:** Limited transformation capabilities and potential scaling constraints for future growth beyond 10GB

---

## Rejected Options

### Cloud SQL Connector + Dataflow + BigQuery

Higher complexity and cost compared to simpler alternatives for this use case

### Dataproc + JDBC + BigQuery

Cluster startup latency and complexity outweigh cost benefits for hourly 10GB loads

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Network | MySQL connectivity issues could cause pipeline failures | Implement connection pooling and retry logic with exponential backoff |
| Data Volume | Data growth beyond 10GB could break function execution limits | Monitor data volumes and implement chunking strategy or migrate to Dataflow |
| Security | Database credentials management in cloud functions | Use Secret Manager for credential storage and IAM for access control |

---

## Assumptions

1. MySQL source system is accessible from GCP via private connectivity or public internet
2. 10GB data volume is consistent and won't significantly exceed this limit
3. Basic data transformations are sufficient (no complex joins or aggregations)
4. Dev environment has relaxed security requirements compared to production

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud Functions for ingestion | latency | less than 1 hour | 10 GB |
| BigQuery for storage | business_context | — | — |
| Cloud Composer for orchestration | preferred_tools | — | — |
| Hourly scheduling | frequency | — | — |

---

## Open Questions — Action Required

1. What specific data transformations are required beyond basic extraction?
2. Are there data retention requirements for the ingested data?
3. What is the expected data growth rate for future capacity planning?
4. Are there specific data quality validation rules that need to be implemented?
