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

> **Build with:** Cloud Composer + Dataflow Batch Pipeline
>
> **Why:** Best alignment with GCP-native architecture and explicit Airflow Composer preference. Handles 1-hour SLA with robust orchestration.
>
> **Score:** 7.35 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1 ✅ | Option 2  | Option 3  |
|---|---||---||---|
| **Name** | Cloud Composer + Dataflow Batch Pipeline | Cloud Scheduler + Cloud Functions + BigQuery | Cloud Composer + Dataproc + GCS Staging |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Dataflow | BigQuery | Dataproc |
| **Storage** | BigQuery | BigQuery | BigQuery |
| **Weighted Score** | **7.35**  ✅ | **7.05** | **6.05** |

---

## Option 1 — Cloud Composer + Dataflow Batch Pipeline ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer orchestrates Dataflow job to extract from MySQL via Cloud SQL Proxy |
| Processing | Dataflow Apache Beam pipeline transforms and validates data with auto-scaling |
| Storage | Processed data lands in BigQuery with Cloud Storage as staging area |
| Consumption | BigQuery tables available for analytics and reporting queries |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataflow | — | Yes |
| Processing | Dataflow | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | — | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | — | No |

### Pros

- Native GCP integration with optimal performance
- Auto-scaling Dataflow handles 10GB volume efficiently
- Built-in error handling and retry mechanisms
- Airflow Composer provides robust scheduling and monitoring

### Cons

- Higher cost due to fully managed services
- Composer overhead for simple hourly scheduling
- Learning curve for Apache Beam development

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Beam transformations require careful schema validation |
| Scaling | Dataflow auto-scaling may over-provision for consistent 10GB loads |
| Latency | Cold start delays in Dataflow job initialization |
| Cost | Composer runs continuously even when idle between hourly runs |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 9 | 6 | 8 | 9 | **7.35** |

---

## Option 2 — Cloud Scheduler + Cloud Functions + BigQuery

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Scheduler triggers Cloud Function hourly to execute BigQuery Data Transfer or federated queries |
| Processing | BigQuery SQL transformations handle data processing with external table queries to MySQL |
| Storage | Data materialized directly into BigQuery tables |
| Consumption | BigQuery tables immediately available for analytics |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Functions | — | Yes |
| Processing | BigQuery | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Scheduler | — | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | — | No |

### Pros

- Lowest cost with serverless architecture
- Minimal operational overhead
- Direct MySQL to BigQuery integration
- Simple deployment and maintenance

### Cons

- Does not use preferred Airflow Composer
- Limited transformation capabilities in pure SQL
- Cloud Functions timeout limitations for large datasets
- Less sophisticated error handling and retry logic

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Limited data validation options in federated queries |
| Scaling | Cloud Functions may timeout on 10GB transfers |
| Latency | Network latency for federated queries to on-premise MySQL |
| Cost | BigQuery slot usage for large federated queries |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 9 | 6 | 8 | 6 | 6 | **7.05** |

---

## Option 3 — Cloud Composer + Dataproc + GCS Staging

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer orchestrates Dataproc Spark jobs to extract from MySQL with JDBC |
| Processing | Spark jobs on Dataproc clusters perform ETL transformations |
| Storage | Data staged in Cloud Storage then loaded to BigQuery via batch jobs |
| Consumption | BigQuery tables available for analytics after batch loading |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataproc | — | Yes |
| Processing | Dataproc | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | — | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | — | No |

### Pros

- Uses preferred Airflow Composer orchestration
- Spark provides powerful transformation capabilities
- Good for complex ETL logic requirements
- Dataproc ephemeral clusters optimize costs

### Cons

- Higher complexity with cluster management
- Spark overhead unnecessary for 10GB volume
- Longer startup times for ephemeral clusters
- Additional GCS staging step increases latency

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Spark job failures require sophisticated error handling |
| Scaling | Cluster provisioning delays impact SLA adherence |
| Latency | Multi-stage process with staging increases end-to-end time |
| Cost | Dataproc cluster costs even with ephemeral mode |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 7 | 4 | 5 | 6 | **6.05** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Dataflow Batch Pipeline ✅ | 6 | 9 | 6 | 8 | 9 | **7.35** |
| Cloud Scheduler + Cloud Functions + BigQuery | 9 | 6 | 8 | 6 | 6 | **7.05** |
| Cloud Composer + Dataproc + GCS Staging | 7 | 7 | 4 | 5 | 6 | **6.05** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Composer + Dataflow Batch Pipeline**
**Weighted Score: 7.35**

**Justification:** Best alignment with GCP-native architecture and explicit Airflow Composer preference. Handles 1-hour SLA with robust orchestration.

**Why highest score:** Superior operability and scalability scores outweigh cost concerns, matching enterprise requirements for reliability.

**Trade-offs accepted:** Higher cost accepted for managed service benefits and alignment with preferred Airflow Composer tool.

---

## Rejected Options

### Cloud Scheduler + Cloud Functions + BigQuery

Does not align with explicit preference for Airflow Composer orchestration

### Cloud Composer + Dataproc + GCS Staging

Unnecessary complexity for 10GB volume with longer latency due to multi-stage processing

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Connectivity | Network connectivity to MySQL source may introduce latency or failures | Implement Cloud SQL Proxy or VPN with connection pooling and retry logic |
| Schema Evolution | MySQL schema changes could break ingestion pipelines | Implement schema validation and alerting in pipeline code |
| Data Quality | Source data quality issues could propagate to BigQuery | Add data quality checks and anomaly detection in processing stage |

---

## Assumptions

1. MySQL source system accessible from GCP with appropriate network connectivity
2. 10GB represents consistent hourly volume, not peak load
3. Dev environment has sufficient BigQuery and Dataflow quotas
4. MySQL schema is relatively stable for pipeline development

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Selected Cloud Composer orchestration | technology.preferred_tools | — | — |
| Dataflow for processing | functional_requirements | less than 1 hour | 10 GB |
| BigQuery as target storage | business_context | — | — |
| Hourly scheduling requirement | data_requirements.frequency | — | — |

---

## Open Questions — Action Required

1. What are the specific MySQL table schemas and expected growth patterns?
2. Are there any data retention policies for the ingested data in BigQuery?
3. What level of data transformation is needed beyond basic ingestion?
4. Are there specific security requirements for data in transit and at rest?
