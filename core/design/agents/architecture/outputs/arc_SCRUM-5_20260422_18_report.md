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

> **Build with:** Cloud Composer + Dataflow (Apache Beam) + BigQuery
>
> **Why:** Cloud Composer + Dataflow + BigQuery is the canonical GCP-native batch ingestion pattern for JDBC sources. It directly satisfies all stated functional requirements: hourly schedule via Composer DAG, 10 GB volume via Dataflow auto-scaling, < 1 hour SLA via serverless execution with no cluster cold-start, and GCP-only platform constraint. It also honours the requester's explicit preference for Airflow Composer as the orchestration layer.
>
> **Score:** 7.55 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1 ✅ | Option 2  | Option 3  |
|---|---||---||---|
| **Name** | Cloud Composer + Dataflow (Apache Beam) + BigQuery | Cloud Composer + Dataproc (PySpark) + BigQuery | Cloud Composer + Cloud Data Fusion + BigQuery |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Google Cloud Dataflow (Apache Beam SDK) | Google Cloud Dataproc (PySpark) | Cloud Data Fusion (managed Dataflow backend) |
| **Storage** | Google Cloud Storage + BigQuery | Google Cloud Storage + BigQuery | Google Cloud Storage + BigQuery |
| **Weighted Score** | **7.55**  ✅ | **5.55** | **6.50** |

---

## Option 1 — Cloud Composer + Dataflow (Apache Beam) + BigQuery ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer (Airflow) triggers an hourly DAG (cron: 0 * * * *); a Dataflow job reads the EMPLOYEES table from MySQL (host: 34.70.79.163:3306, instance: verizon-data:us-central1:mysql-druid-metadatastore) via the JDBC connector, writing raw records to a GCS staging bucket. |
| Processing | Dataflow Apache Beam pipeline applies schema validation, type casting, null handling, and watermark-based incremental load logic before writing structured records to BigQuery via the native BigQuery I/O connector. |
| Storage | GCS bucket serves as the raw landing zone (Avro/Parquet); BigQuery dataset (customer360_dev) hosts the cleansed and conformed EMPLOYEES table as the analytical serving layer. |
| Consumption | BigQuery serves ad-hoc analytics queries, Looker Studio dashboards, and downstream Customer360 data products. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Google Cloud Dataflow (JDBC MySQL Source Connector) | — | Yes |
| Processing | Google Cloud Dataflow (Apache Beam SDK) | — | Yes |
| Storage | Google Cloud Storage + BigQuery | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Dataflow Job Metrics | — | Yes |
| Iac | Terraform (hashicorp/google provider) | — | No |

### Pros

- Fully serverless and auto-scaling — no cluster provisioning required for 10 GB hourly runs; workers spin up and down per job.
- Native BigQuery I/O connector in Dataflow eliminates an explicit GCS-to-BigQuery load step, reducing end-to-end elapsed time.
- Cloud Composer is explicitly preferred by the requester, ensuring alignment with existing team tooling and operational knowledge.
- Dataflow handles JDBC MySQL reads natively via the Google-provided connector, reducing custom code surface area.
- Pay-per-vCPU-second billing is cost-efficient for discrete hourly batch jobs at 10 GB — no idle compute charges between runs.
- First-class observability: Dataflow job DAG, step-level throughput metrics, and Cloud Monitoring integration available without additional instrumentation.

### Cons

- Dataflow job startup and worker allocation overhead (~2-3 minutes) must be factored into the < 1 hour SLA budget for each run.
- Apache Beam pipeline development requires engineers familiar with the Beam programming model — steeper initial learning curve than PySpark.
- Network connectivity from Dataflow workers to MySQL host (34.70.79.163) must be established via Cloud SQL Auth Proxy or VPC peering before Dev deployment.
- Dataflow worker autoscaling heuristics may not always be optimal for short, predictable 10 GB batch jobs; manual maxWorkers tuning may be required.

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | MySQL source schema drift on the EMPLOYEES table (column additions, type changes) may silently corrupt downstream BigQuery records without explicit schema validation guards in the Beam pipeline. |
| Scaling | If data volume grows beyond 10 GB per run without pipeline re-tuning, Dataflow worker allocation and shuffle memory settings may need adjustment to sustain the < 1 hour SLA. |
| Latency | Network round-trip latency between Dataflow workers and the MySQL host over Cloud SQL Auth Proxy or VPC peering adds variable overhead that must be benchmarked in the Dev environment before SLA sign-off. |
| Cost | Untuned Dataflow jobs with over-allocated workers or non-optimised shuffle mode may inflate per-run costs; enabling Dataflow Shuffle service and right-sizing machine types is required for cost control. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 9 | 6 | 8 | 8 | **7.55** |

---

## Option 2 — Cloud Composer + Dataproc (PySpark) + BigQuery

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer triggers an hourly DAG that submits a PySpark job to an ephemeral Dataproc cluster; the Spark JDBC connector reads the EMPLOYEES table from MySQL (34.70.79.163:3306) into a Spark DataFrame. |
| Processing | PySpark transformations on the ephemeral Dataproc cluster enforce schema, apply type coercion, perform deduplication, and detect incremental deltas before writing output to GCS as Parquet. |
| Storage | GCS (Parquet staging) serves as the intermediate layer; data is loaded into BigQuery via the Spark BigQuery connector or a BigQuery batch load job triggered by Composer after PySpark completion. |
| Consumption | BigQuery as the analytical serving layer for Customer360 reporting and downstream data products. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataproc Ephemeral Cluster (Spark JDBC MySQL Connector) | — | Yes |
| Processing | Google Cloud Dataproc (PySpark) | — | Yes |
| Storage | Google Cloud Storage + BigQuery | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow) | — | Yes |
| Monitoring | Cloud Monitoring + Dataproc Job History Server + Cloud Logging | — | Yes |
| Iac | Terraform (hashicorp/google provider) | — | No |

### Pros

- PySpark is widely known among data engineers, reducing the learning curve compared to the Apache Beam programming model.
- Ephemeral Dataproc clusters terminate after job completion, avoiding idle compute charges between hourly runs.
- Full Spark ecosystem available for complex multi-table joins or window functions if pipeline requirements expand.
- Flexible cluster configuration allows fine-grained resource tuning per job type or data volume tier.

### Cons

- Ephemeral Dataproc cluster startup time (3-5 minutes) consumes a larger share of the < 1 hour SLA budget compared to Dataflow's serverless model.
- Cluster node type and count must be manually sized for 10 GB; over-provisioning increases cost and under-provisioning risks SLA breach.
- Additional operational surface: Spark job packaging (JARs/wheels), GCS staging lifecycle management, and cluster configuration versioning.
- Dataproc is architecturally disproportionate for a single-table 10 GB hourly batch — the overhead-to-value ratio is unfavourable at this scale.

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | PySpark does not enforce schema on read by default; without explicit StructType schema definitions, MySQL source schema drift may propagate silently into BigQuery without validation failures. |
| Scaling | Ephemeral cluster spin-up and YARN resource negotiation for hourly 10 GB runs introduces variable elapsed time; sustained SLA compliance requires cluster pre-warming strategies or autoscaling policy tuning. |
| Latency | The combined latency of Composer DAG trigger, Dataproc cluster boot, JDBC extraction, Spark processing, GCS write, and BigQuery load job may stress the < 1 hour SLA without careful stage-level benchmarking. |
| Cost | Hourly ephemeral cluster charges (even minimal n1-standard-4 configurations) accumulate at 24 runs per day; the aggregate daily cost may exceed Dataflow's pay-per-vCPU-second model for equivalent 10 GB workloads. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 7 | 4 | 6 | 6 | **5.55** |

---

## Option 3 — Cloud Composer + Cloud Data Fusion + BigQuery

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer triggers a Cloud Data Fusion pipeline via the Data Fusion REST API on an hourly schedule; the Data Fusion MySQL JDBC source plugin reads the EMPLOYEES table from the configured MySQL instance. |
| Processing | Cloud Data Fusion visual ETL pipeline applies transformations (type casting, field renaming, null filtering) on a managed Dataflow backend without requiring custom pipeline code. |
| Storage | BigQuery as the direct target sink via the Data Fusion BigQuery sink plugin; GCS may serve as a transient intermediate layer managed automatically by Data Fusion's Dataflow backend. |
| Consumption | BigQuery for Customer360 analytics, self-service reporting, and downstream data product consumption. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Data Fusion (MySQL JDBC Source Plugin) | — | Yes |
| Processing | Cloud Data Fusion (managed Dataflow backend) | — | Yes |
| Storage | Google Cloud Storage + BigQuery | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Data Fusion Pipeline Metrics + Cloud Logging | — | Yes |
| Iac | Terraform (hashicorp/google provider) | — | No |

### Pros

- Low-code visual ETL reduces development time and enables non-engineer stakeholders to review and modify pipelines without code changes.
- Built-in MySQL connector with schema auto-detection eliminates custom JDBC boilerplate and connector maintenance.
- Managed Dataflow backend inherits Dataflow scalability without requiring engineers to learn the Apache Beam programming model.
- Highest operability score (9/10): GUI-based pipeline management, built-in data lineage tracking, and integrated monitoring dashboards.

### Cons

- Cloud Data Fusion Developer edition carries a minimum baseline cost of approximately $250/month regardless of usage — the highest fixed cost of all three options and misaligned with a Dev environment cost profile.
- Enterprise-grade features (data lineage, policy tagging integration, governance) are locked to the Enterprise edition at significantly higher cost.
- Pipeline logic is encapsulated in the Data Fusion UI; version-controlled, code-first IaC representation of pipeline configuration is limited compared to Dataflow or Dataproc.
- Composer-to-Data-Fusion orchestration via REST API introduces an additional integration layer not required in the native Composer-to-Dataflow operator pattern.

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Schema auto-detection from MySQL may introduce type inference errors for ambiguous column types (e.g. TINYINT interpreted as boolean, DECIMAL precision loss); explicit schema override configuration in the Data Fusion pipeline is required. |
| Scaling | Data Fusion pipeline execution scales via the underlying Dataflow backend, but pipeline configuration changes require UI interaction rather than code-level tuning, slowing incident response and iteration cycles. |
| Latency | Data Fusion pipeline startup combined with Dataflow job compilation overhead adds 3-5 minutes per run; must be validated against the < 1 hour SLA at 10 GB before Dev sign-off. |
| Cost | The Developer edition flat-rate billing model makes Data Fusion the most expensive option at low-to-medium volumes; cost-effectiveness only emerges at higher data complexity or multi-pipeline scenarios that are not in scope for this requirement. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 4 | 7 | 8 | 7 | 9 | **6.50** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Dataflow (Apache Beam) + BigQuery ✅ | 7 | 9 | 6 | 8 | 8 | **7.55** |
| Cloud Composer + Dataproc (PySpark) + BigQuery | 5 | 7 | 4 | 6 | 6 | **5.55** |
| Cloud Composer + Cloud Data Fusion + BigQuery | 4 | 7 | 8 | 7 | 9 | **6.50** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Composer + Dataflow (Apache Beam) + BigQuery**
**Weighted Score: 7.55**

**Justification:** Cloud Composer + Dataflow + BigQuery is the canonical GCP-native batch ingestion pattern for JDBC sources. It directly satisfies all stated functional requirements: hourly schedule via Composer DAG, 10 GB volume via Dataflow auto-scaling, < 1 hour SLA via serverless execution with no cluster cold-start, and GCP-only platform constraint. It also honours the requester's explicit preference for Airflow Composer as the orchestration layer.

**Why highest score:** Achieves the highest weighted score (7.55) driven by a near-perfect scalability rating (9/10) from serverless Dataflow auto-scaling and strong latency (8/10) and operability (8/10) scores from native BigQuery I/O and integrated Cloud Monitoring. The cost score (7/10) reflects pay-per-use billing efficiency for discrete hourly jobs, outperforming Data Fusion's flat-rate model and Dataproc's cluster-hour model at this volume.

**Trade-offs accepted:** Moderate complexity (6/10) is accepted — Beam pipeline development requires specific skills, but this is a well-documented GCP reference pattern with extensive community support and Google-provided JDBC connector examples. The 2-3 minute Dataflow startup overhead is accepted given the < 1 hour SLA provides ample headroom for processing 10 GB at auto-scaled throughput.

---

## Rejected Options

### Cloud Composer + Dataproc (PySpark) + BigQuery

Rejected in favour of Option 1. Dataproc introduces higher operational complexity (cluster sizing, Spark job packaging, staged GCS loads) and longer startup latency that is disproportionate to a single-table 10 GB workload. The ephemeral cluster billing model also carries higher per-run cost than Dataflow's pay-per-vCPU-second pricing at this volume. Achieves the lowest weighted score (5.55) across all evaluated options, penalised most heavily on cost (5/10), complexity (4/10), and latency (6/10).

### Cloud Composer + Cloud Data Fusion + BigQuery

Rejected in favour of Option 1. Cloud Data Fusion carries the highest baseline cost (~$250/month Developer edition flat-rate) and limited code-first IaC pipeline management — both misaligned with a Dev environment prioritising cost efficiency and version-controlled governance. Despite excellent operability (9/10) and low complexity (8/10), the cost score (4/10) materially depresses the weighted score to 6.50, placing it second overall. Recommended for re-evaluation if the project expands to require multi-source low-code ETL authoring at scale across numerous tables or source systems.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Security — Credential Exposure | MySQL connection credentials (username: sa, host: 34.70.79.163, port: 3306) are present in the requirements document in plaintext. If this document is committed to source control or shared via unprotected channels, it constitutes a credential leak risk. | Store all MySQL credentials exclusively in Google Secret Manager. Reference secrets at runtime via Airflow Connections backed by Secret Manager or direct Secret Manager SDK calls in Dataflow pipeline code. Rotate the 'sa' password before Dev pipeline deployment and enforce the principle of least privilege on the MySQL user account. |
| Network Connectivity | Dataflow workers must establish a stable connection to the MySQL instance at 34.70.79.163:3306. If the host is a Cloud SQL instance (indicated by instance_connection_name), direct IP connectivity without the Auth Proxy is a security anti-pattern. If it is an external host, firewall ingress rules and IP allowlisting are required. | Confirm whether 34.70.79.163 is a Cloud SQL instance or an external host. For Cloud SQL: use the Cloud SQL Connector library (recommended) or Cloud SQL Auth Proxy sidecar pattern with Dataflow. For external hosts: establish VPC peering or Cloud Interconnect with least-privilege firewall rules scoped to Dataflow worker subnet CIDR ranges. |
| Data Quality | No data quality requirements, validation rules, or acceptance criteria were specified in the requirements. Pipeline runs may report success while silently delivering incomplete, malformed, or duplicate records to BigQuery without detection. | Implement row-count reconciliation (source COUNT(*) vs. BigQuery row count post-load), null checks on primary key and critical columns of the EMPLOYEES table, and schema drift detection in the Dataflow pipeline. Publish pipeline quality metrics to Cloud Monitoring and configure alerting on anomaly thresholds before Dev sign-off. |
| SLA Compliance | The < 1 hour end-to-end SLA for 10 GB has not been validated by benchmarking in the target environment. Dataflow startup (~2-3 min), JDBC MySQL extraction time, Beam processing throughput, BigQuery load, and Composer DAG scheduling lag all contribute to total elapsed time. | Conduct end-to-end SLA benchmarking in the Dev environment before any environment promotion. Instrument each pipeline stage with elapsed-time metrics surfaced to Cloud Monitoring. Configure a Cloud Monitoring SLO alert at 45 minutes elapsed to provide a 15-minute early-warning buffer for remediation. |
| Low Requirements Confidence | Requirements confidence is 42% — materially below the 60% threshold. Business context, functional requirements, and acceptance criteria were derived from source fields rather than explicitly stated, introducing residual uncertainty into architectural decisions made in this document. | Validate all inferred requirements, functional requirements, and global assumptions with the Product Owner and data engineering lead before proceeding to IaC or pipeline implementation. Resolve all open questions listed below, particularly around incremental load strategy, IAM identity, and target schema conventions. |

---

## Assumptions

1. Network connectivity between Dataflow workers and the MySQL host (34.70.79.163:3306) will be established via Cloud SQL Auth Proxy or VPC peering prior to pipeline deployment in Dev. The instance_connection_name (verizon-data:us-central1:mysql-druid-metadatastore) suggests this is a Cloud SQL instance, making Cloud SQL Auth Proxy the default connectivity path.
2. MySQL credentials (username: sa) will be stored in Google Secret Manager and injected at runtime via the Airflow Connections framework or Secret Manager SDK; plaintext credentials will not persist in DAG code, environment variables, or Terraform state.
3. The EMPLOYEES table contains a monotonically increasing or timestamp-based column (e.g. updated_at, created_at, or auto-increment ID) suitable for incremental/delta load; if no such column exists, full-table extraction will be the default strategy for the Dev phase.
4. The GCP project (inferred: verizon-data) has the following APIs enabled: Dataflow, BigQuery, Cloud Storage, Cloud Composer, Cloud Monitoring, Secret Manager, and Cloud SQL Admin.
5. A dedicated GCS bucket (e.g. customer360-dev-raw) and BigQuery dataset (customer360_dev) will be provisioned via Terraform as part of the Dev environment baseline infrastructure.
6. 10 GB refers to uncompressed MySQL data volume per hourly run; compressed transfer size over JDBC will be materially smaller, reducing network and processing elapsed time.
7. Hourly schedule is implemented as cron: 0 * * * * in Cloud Composer; max_active_runs=1 will be enforced on the DAG to prevent pipeline overlap if a run exceeds 60 minutes.
8. Scalability requirements beyond 10 GB per run are not specified; this architecture is designed for the current stated volume, with Dataflow auto-scaling providing natural headroom for moderate growth without re-architecture.
9. The scope of this design is limited to the Dev environment and the EMPLOYEES table only; promotion to higher environments and onboarding of additional tables are out of scope for this decision document.

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud Composer (Airflow) selected as the orchestration layer | technology.preferred_tools | — | — |
| Dataflow selected as the batch processing and ingestion engine | classification.ingestion_type + non_functional.latency + data_requirements.volume | < 1 hour | 10 GB |
| BigQuery selected as the target analytical storage layer | technology.stack + objective | — | 10 GB |
| Hourly cron schedule (0 * * * *) with max_active_runs=1 enforced on the DAG | data_requirements.frequency + non_functional.latency | < 1 hour | — |
| Architecture scoped to Dev environment only; no multi-environment promotion path designed in this document | technology.environment | — | — |
| Terraform selected for infrastructure-as-code provisioning of GCS, BigQuery, Composer, and IAM resources | technology.cloud_or_onprem | — | — |
| Ingestion scope limited to EMPLOYEES table from agentichub database in this design phase | source_connections[0].source_tables + source_connections[0].database | — | 10 GB |
| GCP selected as the sole cloud platform; no cross-cloud services introduced | technology.stack + constraints (no cross-cloud requirement stated) | — | — |

---

## Open Questions — Action Required

1. Is the MySQL host (34.70.79.163) a Cloud SQL instance — as suggested by the instance_connection_name (verizon-data:us-central1:mysql-druid-metadatastore) — or an external on-premise or self-hosted instance? This is a critical blocker: the answer determines the network connectivity pattern (Cloud SQL Connector library vs. VPC peering / firewall allowlisting).
2. Does the EMPLOYEES table contain a reliable incremental load column (e.g. updated_at TIMESTAMP, created_at DATETIME, or an auto-increment ID) to support delta/CDC-style extraction, or is full-table extraction required on each hourly run? This directly impacts pipeline design, BigQuery write mode (WRITE_APPEND vs. WRITE_TRUNCATE), and storage cost.
3. What are the data sensitivity and access control requirements for the EMPLOYEES table? PII handling obligations, column-level BigQuery encryption, row-level security policies, and VPC Service Controls perimeter requirements are unspecified and must be addressed before the Dev pipeline handles real employee data.
4. Scalability requirements are not specified. What is the anticipated data volume growth trajectory beyond 10 GB per run? Are additional source tables beyond EMPLOYEES planned for ingestion in subsequent phases of the Customer360 programme?
5. What is the target BigQuery dataset and table naming convention? Confirm: dataset ID, table ID, partitioning strategy (DATE partition on ingestion timestamp or source date column), clustering columns, and whether a MERGE/UPSERT pattern is required for idempotent reprocessing.
6. What service account identity will the Dataflow job and Cloud Composer DAG execute under? Confirm required IAM roles: roles/dataflow.worker, roles/bigquery.dataEditor, roles/storage.objectAdmin, roles/cloudsql.client (if Cloud SQL), and roles/secretmanager.secretAccessor.
7. Are there downstream consumers of the BigQuery EMPLOYEES data with independent latency or data freshness SLAs beyond the pipeline < 1 hour completion requirement? If so, BigQuery slot reservation or BI Engine configuration may be needed.
8. Is there a preference for Dataflow Flex Templates vs. Classic Templates for pipeline packaging, versioning, and CI/CD integration within the Customer360 Dev environment?
