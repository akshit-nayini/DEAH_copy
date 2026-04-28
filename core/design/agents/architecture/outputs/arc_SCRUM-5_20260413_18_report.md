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

> **Build with:** Direct MySQL to BigQuery Transfer
>
> **Why:** Optimal balance of cost, simplicity, and performance for medium volume batch MySQL ingestion with hourly frequency
>
> **Score:** 8.35 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2 ✅ | Option 3  |
|---|---||---||---|
| **Name** | Cloud SQL Connector with Dataflow | Direct MySQL to BigQuery Transfer | Dataproc Spark with JDBC |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Dataflow | BigQuery SQL | Dataproc Spark |
| **Storage** | BigQuery | BigQuery | Cloud Storage + BigQuery |
| **Weighted Score** | **7.00** | **8.35**  ✅ | **6.70** |

---

## Option 1 — Cloud SQL Connector with Dataflow

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud SQL Connector extracts MySQL data via JDBC |
| Processing | Dataflow batch job transforms and validates data |
| Storage | BigQuery tables for structured analytics data |
| Consumption | Direct BigQuery queries and BI tools |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud SQL Connector | — | Yes |
| Processing | Dataflow | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.0 | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Native GCP integration with optimal performance
- Serverless auto-scaling for variable workloads
- Built-in error handling and retry mechanisms
- Direct BigQuery integration for analytics

### Cons

- Higher cost for small datasets due to Dataflow overhead
- Requires Java/Python development skills
- Cold start latency for Dataflow jobs

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | No built-in schema validation - requires custom implementation |
| Scaling | Dataflow auto-scaling may over-provision for consistent 10GB loads |
| Latency | Dataflow startup time (2-5 mins) may impact tight SLA |
| Cost | Dataflow pricing model expensive for predictable medium volumes |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 9 | 6 | 7 | 8 | **7.00** |

---

## Option 2 — Direct MySQL to BigQuery Transfer ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | BigQuery Data Transfer Service connects directly to Cloud SQL MySQL |
| Processing | Minimal transformation during transfer with SQL views |
| Storage | BigQuery native tables with automatic optimization |
| Consumption | Direct BigQuery analytics and reporting |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | BigQuery Data Transfer Service | — | Yes |
| Processing | BigQuery SQL | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.0 | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Lowest cost solution with no compute overhead
- Zero cold start latency
- Minimal operational complexity
- Built-in incremental sync capabilities

### Cons

- Limited transformation capabilities
- Requires data transformations in BigQuery post-load
- Less flexible for complex business logic

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Limited validation during transfer - relies on BigQuery constraints |
| Scaling | Transfer service has undocumented rate limits for large tables |
| Latency | Transfer timing depends on BigQuery slot availability |
| Cost | BigQuery storage costs grow linearly but remain predictable |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 9 | 7 | 9 | 8 | 9 | **8.35** |

---

## Option 3 — Dataproc Spark with JDBC

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Dataproc Spark cluster reads MySQL via JDBC connector |
| Processing | Spark transformations for data cleansing and aggregation |
| Storage | Parquet files in Cloud Storage with BigQuery external tables |
| Consumption | BigQuery federated queries over Cloud Storage |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataproc Spark | 3.3 | Yes |
| Processing | Dataproc Spark | 3.3 | Yes |
| Storage | Cloud Storage + BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.0 | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Powerful transformation capabilities with Spark
- Cost-effective for compute-intensive workloads
- Familiar tooling for existing Spark teams
- Efficient for large-scale data processing

### Cons

- Cluster management overhead even when managed
- Over-engineered for simple MySQL extraction
- Higher operational complexity
- Longer startup times compared to serverless options

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Requires custom Spark code for comprehensive validation |
| Scaling | Manual cluster sizing may be suboptimal for varying loads |
| Latency | Cluster provisioning adds 3-5 minutes to each job |
| Cost | Always-on clusters or frequent provisioning increases costs |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 8 | 5 | 6 | 6 | **6.70** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud SQL Connector with Dataflow | 6 | 9 | 6 | 7 | 8 | **7.00** |
| Direct MySQL to BigQuery Transfer ✅ | 9 | 7 | 9 | 8 | 9 | **8.35** |
| Dataproc Spark with JDBC | 7 | 8 | 5 | 6 | 6 | **6.70** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Direct MySQL to BigQuery Transfer**
**Weighted Score: 8.35**

**Justification:** Optimal balance of cost, simplicity, and performance for medium volume batch MySQL ingestion with hourly frequency

**Why highest score:** Achieves highest weighted score (8.35) by excelling in cost (9), complexity (9), and operability (9) while meeting latency requirements

**Trade-offs accepted:** Limited in-flight transformation capabilities traded for significant cost savings and operational simplicity

---

## Rejected Options

### Cloud SQL Connector with Dataflow

Higher cost and complexity than required for medium volume predictable batch loads

### Dataproc Spark with JDBC

Unnecessarily complex and costly for straightforward MySQL batch ingestion requirements

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Network Connectivity | MySQL source system connectivity from GCP may be unreliable | Implement connection pooling, retry logic, and network monitoring |
| Data Consistency | Hourly batch may miss rapid changes in source system | Use incremental sync with timestamp-based checkpointing |
| Source System Impact | Batch extraction may impact MySQL operational performance | Schedule during low-usage periods and use read replicas if available |

---

## Assumptions

1. MySQL instance is accessible from GCP via private connectivity or public IP
2. 10GB represents peak volume, actual volumes may be smaller
3. Dev environment has relaxed security requirements compared to production
4. Hourly schedule allows for some variability in execution time

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Selected BigQuery Data Transfer Service for ingestion | functional_requirements[0] | less than 1 hour | 10 GB |
| Cloud Composer for orchestration | technology.preferred_tools[0] | — | — |
| BigQuery for storage and analytics | business_context | — | — |

---

## Open Questions — Action Required

1. What is the expected data growth rate beyond the initial 10GB volume?
2. Are there specific data transformation requirements beyond basic ingestion?
3. Should the solution support incremental vs full refresh patterns?
4. What are the disaster recovery and backup requirements for the ingested data?
