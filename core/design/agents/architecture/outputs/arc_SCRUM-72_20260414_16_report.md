# Architecture Decision Document — network 5g core requirement

| Field | Value |
|---|---|
| **Project** | network 5g core requirement |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Batch |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Dataflow ETL with Cloud Composer Orchestration
>
> **Why:** Provides comprehensive data validation and reconciliation capabilities essential for zero tolerance data discrepancy requirement while maintaining enterprise-grade orchestration and monitoring
>
> **Score:** 6.35 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2 ✅ | Option 3  |
|---|---||---||---|
| **Name** | Native BigQuery Data Transfer Service | Dataflow ETL with Cloud Composer Orchestration | Dataproc with Cloud Storage Staging |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | BigQuery SQL | Dataflow | Dataproc |
| **Storage** | BigQuery | BigQuery | BigQuery |
| **Weighted Score** | **7.65** | **6.35**  ✅ | **5.65** |

---

## Option 1 — Native BigQuery Data Transfer Service

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | BigQuery Data Transfer Service establishes scheduled connection to MySQL source using Cloud SQL Connector |
| Processing | Native BigQuery SQL transformations and data validation queries within BigQuery |
| Storage | Direct load to BigQuery tables with automated schema detection and data type mapping |
| Consumption | BigQuery native analytics interface with centralized data access patterns |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | BigQuery Data Transfer Service | — | Yes |
| Processing | BigQuery SQL | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | BigQuery Data Transfer Service | — | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Zero infrastructure management overhead
- Native BigQuery integration with automatic schema management
- Built-in retry mechanisms and error handling
- Minimal operational complexity

### Cons

- Limited custom transformation capabilities
- Less granular control over data validation logic
- Dependent on BigQuery Data Transfer Service feature set

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Limited custom validation logic beyond basic data type checks |
| Scaling | Service quotas may limit concurrent transfer operations |
| Latency | Fixed scheduling intervals may not meet immediate data freshness needs |
| Cost | BigQuery storage costs for full historical load without optimization |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 7 | 9 | 6 | 9 | **7.65** |

---

## Option 2 — Dataflow ETL with Cloud Composer Orchestration ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer DAG triggers Dataflow job to extract from MySQL using JDBC connector |
| Processing | Apache Beam pipeline in Dataflow performs row-level validation, transformation, and reconciliation checks |
| Storage | Validated data loaded to BigQuery with staging tables for quality checks |
| Consumption | BigQuery analytics with comprehensive data lineage and audit trails |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataflow | — | Yes |
| Processing | Dataflow | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.x | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Comprehensive data validation and reconciliation capabilities
- Pipeline halts on validation failures meeting zero tolerance requirement
- Full audit trail and data lineage tracking
- Flexible custom transformation logic
- Horizontal scaling for large historical loads

### Cons

- Higher operational complexity than native solutions
- Requires Apache Beam development expertise
- Additional infrastructure components to manage

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Custom validation logic requires thorough testing and maintenance |
| Scaling | Dataflow worker scaling may hit quotas during peak historical load |
| Latency | Multi-stage processing may extend overall pipeline runtime |
| Cost | Dataflow compute costs for processing full historical dataset |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 8 | 5 | 7 | 6 | **6.35** |

---

## Option 3 — Dataproc with Cloud Storage Staging

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer orchestrates Dataproc Spark job to extract MySQL data via JDBC |
| Processing | Spark SQL performs data transformations and validation checks with intermediate staging to Cloud Storage |
| Storage | Processed data loaded from Cloud Storage to BigQuery using native BigQuery load jobs |
| Consumption | BigQuery analytics with data available through standard SQL interface |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataproc | — | Yes |
| Processing | Dataproc | — | Yes |
| Storage | BigQuery | — | Yes |
| Orchestration | Cloud Composer | 2.x | Yes |
| Monitoring | Cloud Monitoring | — | Yes |
| Iac | Terraform | 1.5+ | No |

### Pros

- Familiar Spark ecosystem for data engineers
- Cost-effective for large batch processing workloads
- Good performance for historical data migration
- Flexible data transformation capabilities

### Cons

- Cluster management overhead even with managed service
- Additional complexity from multi-stage storage pattern
- Requires Spark expertise for optimal performance tuning

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Multi-stage process increases points of failure for validation |
| Scaling | Cluster auto-scaling may not respond quickly to variable workloads |
| Latency | Cloud Storage staging adds additional processing overhead |
| Cost | Persistent cluster costs if not properly managed |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 6 | 4 | 5 | 5 | **5.65** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Native BigQuery Data Transfer Service | 8 | 7 | 9 | 6 | 9 | **7.65** |
| Dataflow ETL with Cloud Composer Orchestration ✅ | 6 | 8 | 5 | 7 | 6 | **6.35** |
| Dataproc with Cloud Storage Staging | 7 | 6 | 4 | 5 | 5 | **5.65** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Dataflow ETL with Cloud Composer Orchestration**
**Weighted Score: 6.35**

**Justification:** Provides comprehensive data validation and reconciliation capabilities essential for zero tolerance data discrepancy requirement while maintaining enterprise-grade orchestration and monitoring

**Why highest score:** Only option that can implement custom validation logic to halt pipeline on any data discrepancy while providing full audit trails and data lineage required for production transactional data

**Trade-offs accepted:** Higher operational complexity accepted to achieve zero tolerance data quality requirements and comprehensive validation capabilities

---

## Rejected Options

### Native BigQuery Data Transfer Service

Limited data validation capabilities insufficient for zero tolerance requirement

### Dataproc with Cloud Storage Staging

Multi-stage architecture introduces unnecessary complexity and additional failure points compared to Dataflow solution

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Data Consistency | Source database continues to change during historical load process | Implement point-in-time snapshot strategy with transaction log tracking |
| Network Security | Database credentials and connection security over public internet | Use Cloud SQL Auth Proxy or VPN connection with encrypted credentials in Secret Manager |
| Performance Impact | Large historical data extraction may impact source MySQL performance | Schedule extraction during low-traffic periods and implement query rate limiting |

---

## Assumptions

1. MySQL source database allows read connections during operational hours
2. Network connectivity between GCP and MySQL host (34.70.79.163) is stable and secure
3. Source database schema is relatively stable during migration period
4. BigQuery dataset and project permissions are properly configured

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Selected Dataflow with comprehensive validation | zero tolerance for data discrepancies | batch processing acceptable | full historical load |
| Cloud Composer orchestration | pipeline must halt on any validation failure | — | — |
| BigQuery as target analytics store | eliminate analytical query load from transactional systems | — | — |

---

## Open Questions — Action Required

1. What is the estimated size of the employees table and total historical data volume?
2. Are there any specific data retention requirements for the source vs target systems?
3. What is the acceptable maintenance window for the initial historical load?
4. Are there any specific compliance requirements beyond data integrity validation?
