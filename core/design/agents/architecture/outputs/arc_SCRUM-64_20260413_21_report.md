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

> **Build with:** Cloud Composer + Cloud Functions + BigQuery
>
> **Why:** Optimal balance of cost-effectiveness, simplicity, and operational efficiency for low-volume daily batch processing with strong BigQuery integration
>
> **Score:** 7.90 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2  | Option 3 ✅ |
|---|---||---||---|
| **Name** | Cloud Composer + Dataflow Batch Pipeline | Cloud Composer + BigQuery Data Transfer Service | Cloud Composer + Cloud Functions + BigQuery |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Dataflow | BigQuery | BigQuery |
| **Storage** | BigQuery | BigQuery | BigQuery |
| **Weighted Score** | **7.55** | **7.15** | **7.90**  ✅ |

---

## Option 1 — Cloud Composer + Dataflow Batch Pipeline

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer orchestrates daily batch jobs that extract from MySQL read-replica using JDBC connector |
| Processing | Dataflow jobs perform UPSERT logic, deduplication, and data quality checks with custom transformations |
| Storage | BigQuery as target data warehouse with partitioned tables and clustering for optimal query performance |
| Consumption | Direct BigQuery access for analytics with dbt for transformation layers |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Composer | 2.x | Yes |
| Processing | Dataflow | 2.x | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.x | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Fully managed services reduce operational overhead
- Native GCP integration with optimal performance
- Auto-scaling Dataflow handles variable data volumes
- Built-in monitoring and alerting capabilities
- Strong data quality validation framework

### Cons

- Higher cost due to premium managed services
- Dataflow startup latency for small datasets
- Limited flexibility in custom processing logic
- Composer minimum instance costs regardless of usage

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Dataflow transformations may introduce complexity in UPSERT logic validation |
| Scaling | Minimal risk with auto-scaling Dataflow, but startup overhead for small incremental loads |
| Latency | Dataflow job startup time may impact 06:00 AM SLA for small datasets |
| Cost | Premium pricing for fully managed stack may exceed budget expectations |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 9 | 8 | 7 | 9 | **7.55** |

---

## Option 2 — Cloud Composer + BigQuery Data Transfer Service

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | BigQuery Data Transfer Service scheduled transfers from MySQL using federated queries |
| Processing | BigQuery SQL-based UPSERT operations with stored procedures for data quality validation |
| Storage | BigQuery native storage with time-partitioned tables based on ingestion timestamp |
| Consumption | Direct BigQuery analytics with dbt transformations for business logic |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | BigQuery Data Transfer Service | — | Yes |
| Processing | BigQuery | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.x | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Simplified architecture with minimal components
- Lower operational complexity
- Native BigQuery optimizations for analytical workloads
- Cost-effective for moderate data volumes
- Excellent SQL-based data quality validation

### Cons

- Limited MySQL connector support in Data Transfer Service
- Less flexible transformation capabilities
- Potential network latency for federated queries
- Limited incremental sync pattern support

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Federated query limitations may restrict complex data validation logic |
| Scaling | Network bandwidth constraints for large historical loads |
| Latency | Cross-network federated queries may introduce unpredictable latency |
| Cost | Data transfer costs and federated query pricing may accumulate |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 6 | 9 | 6 | 8 | **7.15** |

---

## Option 3 — Cloud Composer + Cloud Functions + BigQuery ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Functions triggered by Composer extract data from MySQL read-replica using Python connectors |
| Processing | Lightweight Python transformations in Cloud Functions with BigQuery SQL for UPSERT operations |
| Storage | BigQuery with date-partitioned employee tables and clustering on primary keys |
| Consumption | BigQuery analytics interface with dbt for advanced transformations and data modeling |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Functions | 2nd gen | Yes |
| Processing | BigQuery | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.x | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Cost-effective serverless execution model
- Fast startup times for daily batch processing
- Simple and maintainable codebase
- Excellent fit for low-volume incremental syncs
- Easy debugging and monitoring capabilities

### Cons

- Cloud Functions timeout limitations for large datasets
- Memory constraints for processing large result sets
- Manual connection management for MySQL
- Limited parallel processing capabilities

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Custom Python code requires thorough testing for UPSERT logic correctness |
| Scaling | Function timeout limits may constrain large historical loads |
| Latency | Sequential processing may impact SLA for larger datasets |
| Cost | Function invocation costs scale with data volume and frequency |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 7 | 9 | 8 | 8 | **7.90** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Dataflow Batch Pipeline | 6 | 9 | 8 | 7 | 9 | **7.55** |
| Cloud Composer + BigQuery Data Transfer Service | 7 | 6 | 9 | 6 | 8 | **7.15** |
| Cloud Composer + Cloud Functions + BigQuery ✅ | 8 | 7 | 9 | 8 | 8 | **7.90** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Composer + Cloud Functions + BigQuery**
**Weighted Score: 7.90**

**Justification:** Optimal balance of cost-effectiveness, simplicity, and operational efficiency for low-volume daily batch processing with strong BigQuery integration

**Why highest score:** Highest weighted score (7.9) due to excellent cost efficiency and low complexity while meeting all functional requirements for daily incremental syncs

**Trade-offs accepted:** Function timeout constraints accepted as historical load can be chunked, and daily incremental volumes are expected to be manageable within limits

---

## Rejected Options

### Cloud Composer + Dataflow Batch Pipeline

Higher cost and complexity compared to simpler alternatives for low-volume daily batch processing

### Cloud Composer + BigQuery Data Transfer Service

Limited MySQL support and federated query reliability concerns for production workloads

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Data Consistency | Potential data inconsistency between production MySQL and BigQuery during high-frequency updates | Implement row count reconciliation and primary key validation checks with automated alerting |
| Network Dependency | Cross-network connectivity failures could impact daily sync SLA | Configure retry logic, connection pooling, and network monitoring with failover procedures |
| Performance Impact | Read-replica lag or high query load could affect sync reliability | Monitor read-replica lag metrics and implement query optimization for extraction operations |

---

## Assumptions

1. Daily incremental data volume remains within Cloud Functions processing limits
2. MySQL read-replica has sufficient capacity for daily extraction workloads
3. Network connectivity between GCP and MySQL instance is reliable
4. Employee table schema includes updated_at timestamp for watermark-based incremental sync

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud Functions for ingestion | functional_requirements | Daily refresh cycle | Low volume incremental updates |
| BigQuery as target storage | technology.stack | Data available by 06:00 AM UTC | Employee data with historical load |
| Cloud Composer orchestration | technology.preferred_tools | Daily scheduling requirement | — |
| Read-replica usage | constraints.technical_limitations | — | — |

---

## Open Questions — Action Required

1. What is the expected data volume for historical load and daily incremental syncs?
2. Are there specific data retention requirements for the BigQuery analytics store?
3. What is the acceptable data freshness tolerance beyond the 06:00 AM SLA?
4. Are there any specific compliance or audit requirements for the employee data?
