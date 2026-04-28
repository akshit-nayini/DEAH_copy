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

> **Build with:** Cloud Composer + Dataflow Batch Pipeline
>
> **Why:** Best alignment with requirements: uses preferred Airflow Composer, handles 10GB volume efficiently, provides enterprise-grade orchestration and monitoring. Higher cost offset by reduced operational complexity.
>
> **Score:** 7.35 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1 ✅ | Option 2  | Option 3  |
|---|---||---||---|
| **Name** | Cloud Composer + Dataflow Batch Pipeline | Cloud Functions + Dataproc Batch Processing | Minimal Cloud Run + BigQuery Data Transfer |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Dataflow | Dataproc | BigQuery |
| **Storage** | BigQuery + GCS | BigQuery + GCS | BigQuery + GCS |
| **Weighted Score** | **7.35**  ✅ | **7.25** | **7.00** |

---

## Option 1 — Cloud Composer + Dataflow Batch Pipeline ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer orchestrates Dataflow job to extract from MySQL via Cloud SQL Proxy |
| Processing | Dataflow processes and transforms data with auto-scaling |
| Storage | Land raw data in GCS, store processed data in BigQuery |
| Consumption | BigQuery tables available for analytics and reporting |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataflow | — | Yes |
| Processing | Dataflow | — | Yes |
| Storage | BigQuery + GCS | — | Yes |
| Orchestration | Cloud Composer | — | Yes |
| Monitoring | Cloud Monitoring + Logging | — | Yes |
| Iac | Terraform | — | No |

### Pros

- Fully managed services reduce operational overhead
- Auto-scaling handles variable workloads efficiently
- Native GCP integration and monitoring
- Airflow-based orchestration as requested
- Built-in error handling and retry mechanisms

### Cons

- Higher cost for smaller workloads due to Cloud Composer overhead
- Learning curve for Dataflow if team lacks experience
- Cloud Composer startup time can add latency

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | No built-in data validation - requires custom implementation |
| Scaling | Cloud Composer has minimum resource requirements even for small workloads |
| Latency | Composer startup and Dataflow job initialization could approach 1-hour SLA |
| Cost | Cloud Composer costs ~$300/month minimum regardless of usage |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 9 | 7 | 7 | 9 | **7.35** |

---

## Option 2 — Cloud Functions + Dataproc Batch Processing

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Scheduler triggers Cloud Function to submit Dataproc job |
| Processing | Dataproc cluster processes MySQL data with Spark |
| Storage | Raw data in GCS, processed data in BigQuery |
| Consumption | BigQuery tables for analytics consumption |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Functions + Dataproc | — | Yes |
| Processing | Dataproc | — | Yes |
| Storage | BigQuery + GCS | — | Yes |
| Orchestration | Cloud Scheduler + Cloud Functions | — | Yes |
| Monitoring | Cloud Monitoring + Logging | — | Yes |
| Iac | Terraform | — | No |

### Pros

- Lower baseline cost - pay only when jobs run
- Familiar Spark ecosystem for data processing
- Good performance for medium-volume batch processing
- Simpler orchestration model

### Cons

- Does not use preferred Airflow Composer
- Manual error handling and retry logic required
- Less sophisticated workflow management
- Cluster startup time adds latency

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Limited built-in data quality checks compared to Dataflow |
| Scaling | Manual cluster sizing decisions required |
| Latency | Dataproc cluster cold start can take 2-5 minutes |
| Cost | Potential cost spikes if cluster sizing is misconfigured |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 7 | 8 | 8 | 6 | **7.25** |

---

## Option 3 — Minimal Cloud Run + BigQuery Data Transfer

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Scheduler triggers Cloud Run service for custom extraction |
| Processing | BigQuery handles transformation via scheduled queries |
| Storage | Direct load to BigQuery, GCS for staging if needed |
| Consumption | BigQuery tables ready for consumption |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Run | — | Yes |
| Processing | BigQuery | — | Yes |
| Storage | BigQuery + GCS | — | Yes |
| Orchestration | Cloud Scheduler | — | Yes |
| Monitoring | Cloud Monitoring + Logging | — | Yes |
| Iac | Terraform | — | No |

### Pros

- Lowest cost option with serverless components
- Minimal infrastructure to manage
- Fast cold start times
- Simple architecture

### Cons

- Does not use preferred Airflow Composer
- Limited workflow orchestration capabilities
- Custom code required for MySQL extraction
- No built-in retry/error handling mechanisms

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Minimal built-in data validation and quality checks |
| Scaling | Cloud Run has execution time limits for long-running extractions |
| Latency | Sequential processing may not meet 1-hour SLA for large datasets |
| Cost | BigQuery storage costs can accumulate over time |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 9 | 6 | 9 | 6 | 5 | **7.00** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Dataflow Batch Pipeline ✅ | 6 | 9 | 7 | 7 | 9 | **7.35** |
| Cloud Functions + Dataproc Batch Processing | 8 | 7 | 8 | 8 | 6 | **7.25** |
| Minimal Cloud Run + BigQuery Data Transfer | 9 | 6 | 9 | 6 | 5 | **7.00** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Composer + Dataflow Batch Pipeline**
**Weighted Score: 7.35**

**Justification:** Best alignment with requirements: uses preferred Airflow Composer, handles 10GB volume efficiently, provides enterprise-grade orchestration and monitoring. Higher cost offset by reduced operational complexity.

**Why highest score:** Scores highest on scalability and operability while meeting latency requirements. Cloud Composer preference in requirements justifies cost trade-off.

**Trade-offs accepted:** Higher baseline cost for Cloud Composer in exchange for preferred orchestration tool and reduced operational overhead.

---

## Rejected Options

### Cloud Functions + Dataproc Batch Processing

Does not align with preferred Airflow Composer requirement and scores lower on operability due to manual orchestration complexity.

### Minimal Cloud Run + BigQuery Data Transfer

Does not meet preferred Airflow Composer requirement and has limited workflow orchestration capabilities for enterprise use case.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Network Connectivity | MySQL source system accessibility from GCP not confirmed | Verify network connectivity and implement Cloud SQL Proxy or VPN if needed |
| Data Schema Evolution | MySQL schema changes could break ingestion pipelines | Implement schema monitoring and flexible schema handling in pipelines |
| Resource Sizing | Uncertainty around actual data volumes and processing requirements | Start with auto-scaling solutions and monitor performance metrics to optimize |

---

## Assumptions

1. MySQL source system is accessible from GCP via network connectivity
2. 10GB volume represents peak load, actual loads may vary
3. Dev environment has relaxed security requirements compared to production
4. Team has or can acquire GCP and data engineering skills

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Selected Cloud Composer orchestration | preferred_tools | less than 1 hour | 10 GB |
| Dataflow for batch processing | functional_requirements | less than 1 hour | 10 GB |
| BigQuery for analytics storage | business_context | — | 10 GB |

---

## Open Questions — Action Required

1. What are the specific scalability requirements beyond the current 10GB volume?
2. Are there data governance or security requirements for the production environment?
3. What is the expected growth rate of data volume over time?
4. Are there specific data quality validation requirements?
5. What is the network connectivity setup between on-premises MySQL and GCP?
