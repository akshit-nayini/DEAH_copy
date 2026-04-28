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

> **Build with:** Cloud Composer + Dataflow (Serverless Beam ETL)
>
> **Why:** Option 1 achieves the highest weighted score (7.75) by combining a fully serverless execution model with the native BigQuery IO connector and Cloud Composer orchestration as explicitly preferred by the client. It satisfies the less-than-1-hour latency SLA with substantial headroom, eliminates idle compute costs on an hourly schedule in Dev, and minimises operational overhead relative to cluster-based alternatives.
>
> **Score:** 7.75 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1 ✅ | Option 2  | Option 3  |
|---|---||---||---|
| **Name** | Cloud Composer + Dataflow (Serverless Beam ETL) | Cloud Composer + Dataproc (Ephemeral PySpark ETL) | Cloud Composer + Cloud Data Fusion (Low-Code Visual ETL) |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Dataflow (Apache Beam SDK 2.x) | Dataproc (Apache Spark 3.x) | Cloud Data Fusion (CDAP 6.x) |
| **Storage** | BigQuery + GCS | GCS (Parquet) + BigQuery | BigQuery + GCS |
| **Weighted Score** | **7.75**  ✅ | **6.45** | **6.80** |

---

## Option 1 — Cloud Composer + Dataflow (Serverless Beam ETL) ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer DAG triggers a Dataflow Flex Template job on an hourly cron schedule; Dataflow reads the MySQL EMPLOYEES table via JDBC over Cloud SQL Auth Proxy sidecar attached to Dataflow workers |
| Processing | Dataflow (Apache Beam) applies schema mapping, type casting, and null handling as in-pipeline transforms; writes directly to BigQuery via the native BigQuery IO connector using WRITE_TRUNCATE semantics |
| Storage | GCS bucket used exclusively for Dataflow temporary and staging artefacts; final data persists in BigQuery dataset customer360 with date-partitioned tables for query efficiency |
| Consumption | BigQuery tables exposed to analytics workloads via authorised views; downstream BI tools (Looker, Looker Studio) or dbt transformation models query directly against BigQuery |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud SQL Auth Proxy + Dataflow JDBC connector | — | Yes |
| Processing | Dataflow (Apache Beam SDK 2.x) | 2.x | Yes |
| Storage | BigQuery + GCS | — | Yes |
| Orchestration | Cloud Composer 2 (Airflow 2.x) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging | — | Yes |
| Iac | Terraform | ~> 1.5 | No |

### Pros

- Fully serverless — no cluster provisioning or infrastructure management required in Dev
- Native BigQuery IO connector enables direct writes, eliminating a GCS intermediate load step and reducing end-to-end latency
- Autoscaling with maxNumWorkers guardrail optimises worker count for variable 10 GB workloads without over-provisioning
- Dataflow Flex Templates provide job startup under 2 minutes, leaving ample headroom within the 1-hour SLA
- Pay-per-vCPU-hour billing avoids idle compute costs between hourly runs in Dev
- Deep native GCP integration: Cloud Monitoring dashboards, structured Cloud Logging, and IAM-native access control with no additional tooling

### Cons

- Apache Beam SDK requires specialised knowledge; steeper learning curve than PySpark for teams without prior Beam experience
- JDBC MySQL connectivity requires Cloud SQL Auth Proxy sidecar configuration or VPC peering, adding initial networking setup effort
- No built-in data quality framework; DQ assertions must be implemented as custom Beam DoFns or post-load Dataplex checks
- Dataflow Flex Template build pipeline introduces additional CI/CD artefact management compared to submitting a Spark job

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | No native DQ layer; schema drift or upstream MySQL DDL changes will silently corrupt BigQuery tables without explicit schema validation transforms in the Beam pipeline |
| Scaling | Without a maxNumWorkers cap, Dataflow may over-provision workers for 10 GB runs, inflating Dev costs; autoscaling parameters must be explicitly bounded per job template |
| Latency | Flex Template startup adds approximately 1-2 minutes of overhead; within the 1-hour window, but failure retries further reduce the available processing buffer |
| Cost | Per-vCPU-hour billing accumulates if jobs are long-running or workers are over-provisioned; recommend maxNumWorkers=4 and machine type n1-standard-2 for 10 GB in Dev |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 9 | 7 | 8 | 8 | **7.75** |

---

## Option 2 — Cloud Composer + Dataproc (Ephemeral PySpark ETL)

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer DAG provisions an ephemeral Dataproc cluster on an hourly schedule; PySpark job reads the MySQL EMPLOYEES table via JDBC driver using partitioned parallel reads to avoid a single-thread bottleneck |
| Processing | PySpark on Dataproc applies schema normalisation, deduplication, and type coercion; output written as Parquet files to a GCS landing zone before load into BigQuery |
| Storage | GCS acts as the primary raw landing zone (Parquet format); BigQuery native tables are loaded from GCS via the BigQuery Spark connector or a bq load command triggered by Composer |
| Consumption | BigQuery native tables serve the analytics and reporting layer; GCS Parquet archive remains available for reprocessing or ad-hoc Spark workloads without re-ingesting from MySQL |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | MySQL JDBC Driver + Dataproc PySpark | — | No |
| Processing | Dataproc (Apache Spark 3.x) | 3.x | Yes |
| Storage | GCS (Parquet) + BigQuery | — | Yes |
| Orchestration | Cloud Composer 2 (Airflow 2.x) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Dataproc History Server | — | Yes |
| Iac | Terraform | ~> 1.5 | No |

### Pros

- PySpark is a widely adopted data engineering skill, lowering the barrier to development and team onboarding compared to Apache Beam
- Ephemeral cluster pattern eliminates idle compute costs between hourly runs when clusters are deleted post-job
- GCS Parquet landing zone provides a raw data archive enabling full reprocessing without re-ingesting from the MySQL source
- Flexible for complex multi-stage transformations, window functions, and future ML feature engineering pipelines on the same platform
- Dataproc Serverless Spark available as a zero-infrastructure upgrade path if cluster management overhead becomes unacceptable

### Cons

- Cluster provisioning adds 3-5 minutes of startup overhead, reducing the available processing window within the 1-hour SLA
- Manual cluster sizing is required; under-provisioning risks job failure for volume spikes beyond 10 GB without explicit autoscaling configuration
- Higher operational overhead than serverless options: cluster YAML configs, init actions, and JDBC JAR distribution to workers must be maintained
- JDBC read parallelism requires explicit tuning of numPartitions and fetchsize parameters to prevent MySQL source bottlenecks
- Two-hop architecture (MySQL to GCS to BigQuery) adds latency and incremental GCS storage cost compared to a direct BigQuery write path

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | PySpark does not enforce schema on read by default; corrupt or schema-drifted MySQL records may silently land in Parquet without validation, propagating bad data to BigQuery |
| Scaling | Ephemeral cluster worker count is static per DAG parameter; volume spikes beyond 10 GB require manual adjustment of the workerCount variable in the Composer DAG, not automatic scaling |
| Latency | Cluster provisioning (3-5 min) plus a separate GCS-to-BigQuery load step reduces the effective processing window; the 1-hour SLA leaves limited retry budget on failure |
| Cost | Master node billing persists for the full cluster lifetime including setup and teardown phases; for 10 GB hourly runs, total per-run cost exceeds Dataflow per-use billing at equivalent throughput |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 8 | 5 | 7 | 6 | **6.45** |

---

## Option 3 — Cloud Composer + Cloud Data Fusion (Low-Code Visual ETL)

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer DAG triggers a Cloud Data Fusion pipeline run via the Data Fusion REST API on an hourly schedule; the pipeline uses the built-in MySQL JDBC source plugin with configurable batch size and optional delta extraction |
| Processing | CDAP pipeline in Data Fusion applies schema mapping, null handling, and data type coercion through visual transform nodes; Wrangler directives available for lightweight self-service data preparation without redeployment |
| Storage | Data Fusion BigQuery sink plugin writes directly to the BigQuery customer360 dataset; GCS used only for pipeline temporary storage during execution |
| Consumption | BigQuery tables immediately available for BI reporting and analytics; Data Fusion pipeline lineage metadata is automatically surfaced in Dataplex for governance and audit use cases |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Data Fusion MySQL JDBC Plugin | 6.x | Yes |
| Processing | Cloud Data Fusion (CDAP 6.x) | 6.x | Yes |
| Storage | BigQuery + GCS | — | Yes |
| Orchestration | Cloud Composer 2 (Airflow 2.x) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Data Fusion Pipeline Metrics | — | Yes |
| Iac | Terraform | ~> 1.5 | No |

### Pros

- Visual low-code pipeline builder significantly accelerates initial development and reduces coding errors for straightforward MySQL-to-BigQuery ingestion patterns
- Built-in MySQL JDBC source plugin with incremental load support eliminates custom connector development effort entirely
- Native Dataplex integration provides automated data lineage and governance metadata with zero additional instrumentation
- Wrangler UI enables iterative self-service schema mapping and data preparation without code changes or redeployment cycles
- Lowest time-to-first-pipeline for teams without deep Beam or Spark expertise, appropriate for accelerated Dev environment delivery

### Cons

- Highest cost tier among options: Basic instance (~$0.35/hr always-on) is resource-constrained for production patterns; Enterprise tier (~$1.20/hr) required for reliability, making it disproportionately expensive for a Dev environment
- Less flexible than code-based options for complex business logic, stateful operations, or custom transformation requirements beyond simple mappings
- Pipeline versioning, unit testing, and CI/CD integration are significantly less mature than Beam or Spark development workflows
- CDAP and Data Fusion REST API dependencies create stronger vendor lock-in than open-source Apache Beam or Spark frameworks
- Pipeline startup and CDAP orchestration overhead adds 5-10 minutes per run, reducing available processing time more than other options

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Data Fusion Wrangler provides limited programmatic DQ control; complex validation rules or conditional assertions require custom CDAP plugins or an external DQ framework |
| Scaling | Scaling is constrained by Data Fusion instance type rather than automatic worker addition; handling volume growth beyond 10 GB requires an instance upgrade, not a configuration change |
| Latency | Pipeline startup and CDAP scheduling overhead adds 5-10 minutes per run; acceptable within the 1-hour window but leaves less failure-recovery buffer than serverless options |
| Cost | Data Fusion instance billing is continuous (not per-use), making it the most expensive option in a Dev environment; even the Basic tier represents a disproportionate cost for a single 10 GB hourly table |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 7 | 8 | 7 | 9 | **6.80** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Dataflow (Serverless Beam ETL) ✅ | 7 | 9 | 7 | 8 | 8 | **7.75** |
| Cloud Composer + Dataproc (Ephemeral PySpark ETL) | 6 | 8 | 5 | 7 | 6 | **6.45** |
| Cloud Composer + Cloud Data Fusion (Low-Code Visual ETL) | 5 | 7 | 8 | 7 | 9 | **6.80** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Composer + Dataflow (Serverless Beam ETL)**
**Weighted Score: 7.75**

**Justification:** Option 1 achieves the highest weighted score (7.75) by combining a fully serverless execution model with the native BigQuery IO connector and Cloud Composer orchestration as explicitly preferred by the client. It satisfies the less-than-1-hour latency SLA with substantial headroom, eliminates idle compute costs on an hourly schedule in Dev, and minimises operational overhead relative to cluster-based alternatives.

**Why highest score:** Dataflow's native autoscaling delivers the highest scalability score (9) across all options, while its pay-per-use serverless billing earns a cost score (7) superior to both cluster-based alternatives. The direct BigQuery write path and managed service characteristics reduce operational complexity (7) and provide strong out-of-the-box observability (operability: 8), producing the best combined weighted profile of 7.75.

**Trade-offs accepted:** Teams must invest in Apache Beam SDK skills. Cloud SQL Auth Proxy configuration adds initial setup effort that is one-time and well-documented. The absence of a native DQ framework must be mitigated by adding lightweight schema validation Beam assertions before the pipeline is promoted beyond Dev.

---

## Rejected Options

### Cloud Composer + Dataproc (Ephemeral PySpark ETL)

Dataproc scores lower than Dataflow on cost (6 vs 7) due to master-node billing and the two-hop GCS-to-BigQuery architecture overhead. It scores significantly lower on complexity (5 vs 7) and operability (6 vs 8) because of the manual cluster configuration, JDBC tuning, and init-action management required. PySpark familiarity is a genuine advantage but does not compensate for the added latency risk from cluster startup within the less-than-1-hour SLA window, yielding an overall weighted score of 6.45 versus 7.75 for Option 1.

### Cloud Composer + Cloud Data Fusion (Low-Code Visual ETL)

Despite leading on operability (9) and complexity (8) due to its low-code visual development experience, Data Fusion scores the lowest on cost (5) because of continuous instance-based pricing that is disproportionate for a Dev workload with no budget specification. Instance-level scaling also caps its scalability score at 7, below both Dataflow and Dataproc. Its weighted score of 6.80 is 0.95 points below Option 1 and cannot be overcome by development-ease advantages alone given the cost and scaling constraints.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Connectivity | The MySQL host 34.70.79.163 corresponds to a Cloud SQL instance (verizon-data:us-central1:mysql-druid-metadatastore); connectivity from Dataflow workers requires Cloud SQL Auth Proxy configuration or Serverless VPC Access, which adds networking setup complexity before the first pipeline run can succeed | Configure Cloud SQL Auth Proxy as a Dataflow pipeline launch option using the --cloud-sql-instances flag; validate end-to-end TCP connectivity from a Dataflow Flex Template test job in Dev before committing to implementation; document VPC peering or Private Service Access requirements if Auth Proxy is not viable |
| Security | MySQL username 'sa' has no specified password policy, rotation cadence, or least-privilege scope; the EMPLOYEES table almost certainly contains PII (names, employment data, compensation records) with no data sensitivity classification or access control requirements provided in the requirements document | Immediately store credentials in Secret Manager with IAM-scoped service account access; conduct a data classification exercise for the EMPLOYEES table before any data lands in BigQuery; apply BigQuery column-level security or dynamic data masking to PII fields prior to any consumer access beyond the pipeline service account |
| Schema Drift | No schema change detection mechanism is defined in the requirements; upstream MySQL DDL changes such as column additions, type changes, or column renames will silently break Dataflow JDBC reads or corrupt BigQuery table schemas | Implement a pre-flight schema comparison step in the Composer DAG that compares live MySQL INFORMATION_SCHEMA against the last-known schema snapshot stored in GCS; alert and halt the pipeline on schema delta before processing; use BigQuery schema auto-detection with NULLABLE mode as a defensive fallback |
| Scalability | Scalability NFRs are entirely unspecified in the requirements; the current design is sized for 10 GB per hour on a single table and has not been validated for multi-table ingestion, parallel pipeline concurrency, or data volume growth scenarios | Define volume growth projections and target table counts with stakeholders before promoting beyond Dev; re-evaluate Dataflow worker sizing, Composer DAG concurrency limits, and BigQuery slot reservations based on confirmed scale targets at the design review stage |
| Confidence | Overall requirements confidence is 42%, which is below the 60% threshold; business acceptance criteria, performance NFRs, SLA definitions, security classification, budget constraints, and incremental versus full-load strategy were all absent or unspecified and have been derived from minimal explicit source fields | Conduct a structured requirements clarification session with product and platform stakeholders before implementation begins; validate every item in global_assumptions and resolve all open_questions; do not promote this design to non-Dev environments until confidence reaches at least 70% |

---

## Assumptions

1. MySQL instance at 34.70.79.163:3306 is network-reachable from GCP Dataflow workers via Cloud SQL Auth Proxy; firewall rules permit outbound connections from the Dataflow worker IP range to Cloud SQL
2. Ingestion strategy is full-load (WRITE_TRUNCATE) for the EMPLOYEES table unless an incremental or CDC requirement is subsequently specified by stakeholders
3. The 10 GB volume figure represents the uncompressed row data for the EMPLOYEES table in a single hourly run; multi-table expansion has not been accounted for in current sizing
4. BigQuery dataset customer360 will be created in the same GCP project as the Dataflow and Composer resources; no cross-project data sharing is required
5. Dev environment does not carry a production-grade SLA; a single automatic retry on Dataflow job failure is sufficient before alerting on-call
6. MySQL credentials for user 'sa' will be stored in GCP Secret Manager and accessed via the Airflow Secret Backend; credentials will not be hardcoded in DAG definitions or pipeline configurations
7. Cloud Composer is treated as a hard constraint based on technology.preferred_tools; all architecture options use Composer as the orchestration layer
8. Confidence score of 42% reflects the absence of NFRs for performance, scalability, security, and budget; this architecture document may require revision once those requirements are confirmed with stakeholders

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud Composer selected as the orchestration layer across all architecture options | technology.preferred_tools[Airflow Composer] | < 1 hr | 10 GB |
| Hourly pipeline trigger schedule applied to all options | data_requirements.frequency[hourly] | < 1 hr | 10 GB |
| BigQuery selected as the target analytical storage layer across all options | technology.stack[GCP] aligned with GCP defaults (BigQuery/GCS for storage) | — | — |
| GCP-only stack enforced; no cross-cloud or multi-cloud services evaluated | technology.cloud_or_onprem[Cloud] + technology.stack[GCP] | — | — |
| Dataflow recommended over Dataproc for serverless cost-efficiency and reduced operational overhead in Dev | technology.environment[Dev] + constraints.budget[null — no budget ceiling specified] | < 1 hr | 10 GB |
| Full-load (WRITE_TRUNCATE) assumed as the default ingestion strategy for the EMPLOYEES table | data_requirements.data_types[batch] — incremental or CDC strategy not specified in requirements | < 1 hr | 10 GB |

---

## Open Questions — Action Required

1. Is the MySQL instance at 34.70.79.163 hosted on Cloud SQL (the instance_connection_name verizon-data:us-central1:mysql-druid-metadatastore implies yes) or on-premises? This determines whether Cloud SQL Auth Proxy or VPC peering is the correct and sufficient connectivity approach for Dataflow workers.
2. Is ingestion expected to be full-load (replacing all rows each run) or incremental (watermark-based delta or CDC)? The current design assumes full WRITE_TRUNCATE; an incremental design requires identifying a reliable high-watermark column on the EMPLOYEES table or introducing a CDC tool such as Debezium.
3. What is the target BigQuery project ID, dataset name, and table naming convention that the Customer360 data platform team has standardised on?
4. Does the EMPLOYEES table contain PII or sensitive HR data requiring column-level encryption, BigQuery dynamic data masking, or restricted IAM access policies before any downstream consumer can query the data?
5. Will the pipeline need to expand beyond the EMPLOYEES table to additional MySQL tables in the agentichub database? If so, how many tables and what is the aggregate volume per run, to confirm that the Dataflow sizing recommendation holds?
6. What is the failure and backfill strategy if an hourly Dataflow run fails? Is a manual re-trigger via Composer acceptable in Dev, or is automated gap-fill backfill logic required from day one?
7. Scalability requirements are unspecified — what is the expected data volume growth rate over 6 to 12 months, and is the 10 GB per run figure stable or an initial estimate that may grow significantly?
