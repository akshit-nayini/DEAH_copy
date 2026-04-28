# Architecture Decision Document — 5gcore

| Field | Value |
|---|---|
| **Project** | 5gcore |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Batch |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Dataflow Apache Beam JDBC Batch Pipeline with BigQuery Direct Write and Cloud Composer Orchestration
>
> **Why:** Option 3 is recommended as the architecturally correct and economically optimal solution for the 5gcore pipeline. It aligns precisely with the stated batch pattern (hourly and daily scheduled loads), satisfies every functional requirement — historical load completeness gate, incremental watermarking, stored procedure MERGE on employee_id and updated_date, row count reconciliation, schema validation, PK uniqueness checks, audit logging, stakeholder Looker Studio dashboards, and prompt failure alerting — using fully managed GCP services with no cross-cloud dependencies. Job-based Dataflow billing is optimal for the 5 GB initial and 1 GB per month volume profile. Cloud Composer's task dependency model directly implements the hard requirement to block incremental loads until historical load validation passes, a control that cannot be expressed as simply in the other options. The architecture is extensible to additional agentichub tables without redesign by adding parameterised DAG tasks pointing to the same Flex Template.
>
> **Score:** 7.35 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2  | Option 3 ✅ |
|---|---||---||---|
| **Name** | Datastream CDC Replication with BigQuery Stored Procedure Merge | Cloud Data Fusion JDBC Batch ETL with GCS Staging and BigQuery | Dataflow Apache Beam JDBC Batch Pipeline with BigQuery Direct Write and Cloud Composer Orchestration |
| **Pattern** | Hybrid | Batch | Batch |
| **Processing** | BigQuery Stored Procedures (MERGE / sp_mysqltobq_load.sql) | BigQuery Stored Procedures (MERGE / sp_mysqltobq_load.sql) + BigQuery Batch Load Jobs | BigQuery Stored Procedures (MERGE / sp_mysqltobq_load.sql) |
| **Storage** | Google BigQuery | Google BigQuery + Google Cloud Storage | Google BigQuery |
| **Weighted Score** | **6.80** | **6.10** | **7.35**  ✅ |

---

## Option 1 — Datastream CDC Replication with BigQuery Stored Procedure Merge

**Pattern:** Hybrid

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Datastream establishes a CDC stream from Cloud SQL MySQL (agentichub, instance: verizon-data:us-central1:mysql-druid-metadatastore) using binary log replication. An initial backfill snapshot performs the one-time full historical load directly into BigQuery staging tables under verizon_data_dea with no separate ingestion mechanism required. |
| Processing | Cloud Composer triggers execution of the BigQuery stored procedure sp_mysqltobq_load.sql on the defined hourly or daily schedule. The stored procedure executes a MERGE into the production table using employee_id and updated_date as composite merge keys, enforces 60-day partition expiry, performs row count reconciliation, schema validation, PK uniqueness checks, and writes a complete audit record to a dedicated audit_log table. |
| Storage | BigQuery (project: verizon-data, dataset: verizon_data_dea) serves as both the Datastream CDC landing zone and the curated analytical store. Table-level 60-day partition expiry on updated_date enforces the retention policy. A separate audit_log table and watermark_control table reside in the same dataset. |
| Consumption | Looker Studio dashboards connect directly to BigQuery audit and reconciliation tables, providing stakeholder-facing visibility into load history, record counts, and quality check results without engineering involvement. Cloud Monitoring alerting policies fire on Datastream replication lag breaches, Composer task failures, and data quality violations written to the audit table. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Datastream | — | Yes |
| Processing | BigQuery Stored Procedures (MERGE / sp_mysqltobq_load.sql) | — | Yes |
| Storage | Google BigQuery | — | Yes |
| Orchestration | Cloud Composer 2 | 2.x | Yes |
| Monitoring | Cloud Monitoring + Looker Studio | — | Yes |
| Iac | Terraform | 1.x | No |

### Pros

- Native Datastream-to-BigQuery integration eliminates custom ingestion code entirely, reducing engineering overhead for ongoing replication configuration and maintenance.
- CDC binary log replication guarantees zero data loss and captures every row-level insert and update including corrections that timestamp-based polling would miss.
- Built-in Datastream backfill capability satisfies the one-time historical load requirement without a separate ingestion mechanism or pipeline.
- BigQuery MERGE via stored procedure executes entirely within the storage layer, eliminating data movement costs between ingestion and processing stages.
- Continuous replication means incremental data is always available in BigQuery, giving stakeholders near-real-time freshness even when Composer triggers stored procedure execution on a batch schedule.

### Cons

- Datastream incurs continuous processing costs billed per GB regardless of load frequency; for a scheduled batch pattern requiring only hourly or daily cadence, continuous CDC billing is economically inefficient at the stated 1 GB/month growth rate.
- Enabling binary log replication on Cloud SQL MySQL requires specific instance flags (binlog_format=ROW) which may require a Cloud SQL instance restart, introducing a one-time operational disruption risk to the source system.
- CDC schema evolution is more complex: column additions or type changes in MySQL propagate immediately to BigQuery without a gating validation step, risking downstream stored procedure breakage on schema mismatch.
- Pattern mismatch: the business requirement is scheduled batch ingestion at hourly or daily cadence; CDC introduces a continuous streaming architectural layer that adds operational complexity without commensurate business value at this volume.
- Datastream replication lag monitoring introduces an additional operational concern and alert channel absent in a pure-batch design.

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | CDC event ordering guarantees depend on MySQL binlog consistency. Any binlog gap or purge event during a network interruption could introduce silent data loss requiring manual gap detection and reconciliation against the MySQL source. |
| Scaling | Datastream throughput is adequate for 1 GB/month growth, but schema changes on high-cardinality tables may cause transient replication pauses during backfill operations when additional tables are onboarded. |
| Latency | Not a risk — CDC provides sub-minute latency, which far exceeds the batch SLA. However, Composer-triggered stored procedure execution introduces scheduling latency on top of CDC landing time, meaning the batch trigger cadence remains the effective delivery window. |
| Cost | Continuous Datastream billing (charged per GB processed) combined with Cloud Composer fixed costs (approximately $300-500 per month for a minimal environment) makes this the most expensive option relative to the 1 GB per month data volume and batch cadence requirements. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 9 | 5 | 9 | 7 | **6.80** |

---

## Option 2 — Cloud Data Fusion JDBC Batch ETL with GCS Staging and BigQuery

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Data Fusion pipelines use the native MySQL JDBC plugin to read from Cloud SQL (agentichub) in batch mode. For the historical load, a full-table read pipeline is executed once and writes data as Parquet files to a GCS staging bucket. For incremental loads, a delta pipeline applies a WHERE updated_date > last_watermark filter to extract only changed records, writing Parquet increments to GCS. |
| Processing | BigQuery batch load jobs ingest Parquet files from GCS into staging tables in verizon_data_dea. Cloud Composer then invokes the BigQuery stored procedure sp_mysqltobq_load.sql via BigQueryInsertJobOperator to execute MERGE operations using employee_id and updated_date as composite merge keys, enforce 60-day partition expiry, run row count reconciliation, validate schema consistency, confirm PK uniqueness, and write a complete audit log record to the audit_log table. |
| Storage | GCS serves as a transient landing zone for Parquet staging files, with a lifecycle rule to auto-delete after 7 days post-successful load. BigQuery (project: verizon-data, dataset: verizon_data_dea) is the analytical target and long-term store. Data Catalog is enabled for automatic metadata lineage tracking from MySQL source through GCS to BigQuery. |
| Consumption | Looker Studio dashboards query the BigQuery audit_log and reconciliation tables for stakeholder-accessible load history and quality status views. Cloud Monitoring alerting policies fire on Data Fusion pipeline failures, BigQuery load job failures, and data quality violations flagged by the stored procedure. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Data Fusion | 6.x | Yes |
| Processing | BigQuery Stored Procedures (MERGE / sp_mysqltobq_load.sql) + BigQuery Batch Load Jobs | — | Yes |
| Storage | Google BigQuery + Google Cloud Storage | — | Yes |
| Orchestration | Cloud Composer 2 | 2.x | Yes |
| Monitoring | Cloud Monitoring + Looker Studio + Data Catalog | — | Yes |
| Iac | Terraform | 1.x | No |

### Pros

- Cloud Data Fusion provides a visual no-code pipeline studio that reduces custom code maintenance and makes pipeline logic inspectable by less technical team members without requiring Beam or Spark expertise.
- The native MySQL JDBC plugin with configurable incremental watermark on updated_date eliminates custom change detection logic and is configurable through the UI without code changes.
- GCS staging layer provides an intermediate audit point: raw MySQL extracts are preserved in Parquet before transformation, enabling independent reconciliation and full replay without re-querying the source.
- Data Catalog integration provides automatic metadata lineage from MySQL source through GCS to BigQuery, supporting governance, data discovery, and future compliance requirements.
- Separation of ingestion (Data Fusion), staging (GCS), and processing (stored procedure) creates distinct failure domains that simplify debugging by isolating failures to a specific pipeline stage.

### Cons

- Cloud Data Fusion Developer edition is billed hourly while the instance is provisioned (approximately $0.35 per CU-hour), making it economically unfavorable relative to data volume even when pipelines are not actively executing.
- GCS staging introduces an additional storage hop and data movement cost that is unnecessary when direct MySQL-to-BigQuery ingestion is achievable without intermediate landing.
- Data Fusion instance cold start time (3-5 minutes) reduces the effective processing window within each hourly schedule slot, creating risk of SLA breach under failure-and-retry scenarios.
- Managing two primary managed services (Data Fusion and Composer) in addition to BigQuery and GCS increases IAM surface area, service account scope, and operational monitoring points.
- The visual pipeline abstraction can obscure underlying execution details, making JDBC connection tuning and Spark executor configuration more difficult than in code-first approaches.

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | JDBC timestamp-based watermarking on updated_date can miss records where the source system back-populates or retroactively corrects historical timestamps below the current watermark. A documented late-arriving data strategy with a configurable lookback window must be defined before go-live. |
| Scaling | Data Fusion JDBC read throughput is constrained by MySQL max_connections and Cloud SQL instance vCPU count. As additional tables are onboarded, concurrent Data Fusion pipeline runs may saturate Cloud SQL connections unless per-pipeline connection limits are explicitly configured. |
| Latency | GCS Parquet staging adds one full write-then-read hop before BigQuery ingestion, and Data Fusion instance startup adds 3-5 minutes per run. For strict hourly windows with retry logic, available processing time may be insufficient to guarantee on-time completion. |
| Cost | Data Fusion hourly instance billing is the dominant cost driver. At the current 1 GB per month data volume, the cost-per-byte ratio is materially unfavorable compared to job-based Dataflow billing, which charges only for active execution duration. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 4 | 7 | 8 | 5 | 8 | **6.10** |

---

## Option 3 — Dataflow Apache Beam JDBC Batch Pipeline with BigQuery Direct Write and Cloud Composer Orchestration ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Apache Beam pipelines running on Dataflow use the JdbcIO connector with the MySQL JDBC driver to read directly from Cloud SQL (agentichub, host: 34.70.79.163, port: 3306) via Cloud SQL Auth Proxy sidecar or VPC Private IP peering within us-central1. For the historical load, a single Dataflow batch job performs a full table scan with no filter predicate, writing all rows in parallel into a BigQuery staging table (employees_staging) in verizon_data_dea. JdbcIO partitioning parameters (partitionColumn, numPartitions, lowerBound, upperBound on employee_id) enable parallel reads. For incremental loads, the same Flex Template is invoked with a WHERE updated_date > last_watermark parameter, reading only changed and new records since the last successful run. |
| Processing | Upon Dataflow job completion and success status confirmation, Cloud Composer triggers the BigQuery stored procedure sp_mysqltobq_load.sql via BigQueryInsertJobOperator. The stored procedure executes a MERGE into the production table (employees) using employee_id and updated_date as composite merge keys, enforces 60-day partition expiry on the updated_date partition column, queries MySQL row counts via a Cloud SQL federated query or proxy connection for reconciliation, validates schema consistency against a registered schema definition, confirms primary key uniqueness, verifies null and datatype constraints, and writes a complete audit log record (status, record counts, load start and end timestamps, watermark values) to the audit_log table. The Composer DAG enforces a hard task dependency: the incremental load branch is gated by a BigQueryCheckOperator that asserts a PASS status exists in the audit_log for the completed historical load before any incremental Dataflow job is submitted. |
| Storage | BigQuery (project: verizon-data, dataset: verizon_data_dea) stores staging tables (raw Dataflow output, e.g., employees_staging), production tables (post-MERGE output, e.g., employees), the audit_log table, and a watermark_control table tracking the last_loaded_watermark per table name. Production tables are partitioned by updated_date with a 60-day partition expiry policy enforcing the retention requirement. No intermediate GCS landing is required. |
| Consumption | A Looker Studio report connects directly to the BigQuery audit_log and reconciliation result tables in verizon_data_dea, presenting load execution history, record counts, data quality check outcomes, and pipeline status to stakeholders led by Yash without engineering involvement. Cloud Monitoring alerting policies are configured on Dataflow job state transitions (JOB_STATE_FAILED), Cloud Composer task failure events, and custom log-based metrics derived from ERROR-severity entries written by the stored procedure to Cloud Logging, with notifications delivered via email or configured PagerDuty channel. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Dataflow (Apache Beam JdbcIO + Flex Templates) | 2.x | Yes |
| Processing | BigQuery Stored Procedures (MERGE / sp_mysqltobq_load.sql) | — | Yes |
| Storage | Google BigQuery | — | Yes |
| Orchestration | Cloud Composer 2 | 2.x | Yes |
| Monitoring | Cloud Monitoring + Looker Studio | — | Yes |
| Iac | Terraform | 1.x | No |

### Pros

- Job-based Dataflow billing charged only per vCPU-hour and GB processed during active job execution is highly cost-efficient for batch workloads at 5 GB initial and 1 GB per month growth, with expected per-run costs in the sub-dollar range for incremental jobs.
- JdbcIO parallel read support via partitionColumn, numPartitions, lowerBound, and upperBound parameters enables horizontal MySQL read scaling without application changes, accommodating additional tables and growing volumes as the programme expands.
- Direct MySQL-to-BigQuery write with no GCS intermediate hop minimises pipeline steps, reduces failure surface area, and eliminates staging storage costs entirely.
- Cloud Composer task dependency chaining directly satisfies the hard requirement to block incremental loads until historical load validation passes: a BigQueryCheckOperator asserts a confirmed PASS in the audit_log before any incremental Dataflow job is submitted, enforced at the DAG level.
- BigQuery-native stored procedure handles all post-load processing (MERGE, reconciliation, schema validation, audit log write, watermark update) within the analytical platform, keeping transformation logic close to data and eliminating network round-trips between processing and storage layers.
- Cloud Composer provides built-in retry logic, SLA miss alerting, and execution history visibility via the Airflow UI, enabling the engineering team to diagnose failures without requiring ad-hoc BigQuery queries.
- Dataflow Flex Templates allow the same parameterised pipeline artefact to serve both the historical full load and all incremental loads across all tables by varying input parameters, reducing code duplication as the table inventory grows.

### Cons

- Dataflow Flex Templates require an Apache Beam pipeline code artefact (Java or Python) including JDBC driver packaging and a container image published to Artifact Registry; this is a code asset that must be versioned, tested, and maintained alongside the pipeline configuration.
- Cloud Composer carries a fixed baseline cost of approximately $300 per month for a minimal single-node environment, which may be disproportionate if the 5gcore pipeline is the sole Composer workload in the project.
- JdbcIO parallel reads place concurrent connection load on the Cloud SQL MySQL instance; max_connections must be reviewed and connection pool limits tuned to avoid source system saturation, particularly during the initial 5 GB historical load.
- Watermark management for incremental loads (tracking last_loaded_watermark per table in the watermark_control table) must be implemented explicitly within the stored procedure and validated by the Composer DAG, adding design and testing complexity not present in CDC-based approaches.

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Timestamp-based incremental watermarking on updated_date may miss records where source-side corrections retroactively lower the updated_date below the current watermark. Mitigation: implement a configurable lookback window (e.g., minus 15 minutes) in the JdbcIO WHERE predicate and enforce post-load PK uniqueness validation and null constraint checks within the stored procedure on every incremental run. |
| Scaling | MySQL Cloud SQL instance connection limits constrain Dataflow JDBC parallelism. As additional agentichub tables are onboarded and concurrent Dataflow jobs run simultaneously, Cloud SQL max_connections may be exhausted. Mitigation: configure Cloud SQL Auth Proxy with a per-job max-connections cap and implement a Composer sensor that checks active Dataflow job count before launching new jobs. |
| Latency | Dataflow worker provisioning takes approximately 2-3 minutes per job submission, reducing the effective processing window within each hourly schedule slot. Mitigation: use Dataflow Flex Templates with pre-built container images to minimise startup time, and configure Composer retry delays to avoid cascading schedule slot collisions on transient failures. |
| Cost | Cloud Composer fixed baseline cost (approximately $300 per month) dominates total pipeline cost at current data volumes and will exceed Dataflow execution costs by an order of magnitude. This is accepted given Composer's orchestration value (dependency gating, retry management, audit task chaining, SLA alerting) but should be reviewed if Composer is not reused for other programme workloads, in which case Cloud Scheduler plus Cloud Functions may be evaluated as a lower-cost alternative. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 8 | 6 | 7 | 7 | **7.35** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Datastream CDC Replication with BigQuery Stored Procedure Merge | 5 | 9 | 5 | 9 | 7 | **6.80** |
| Cloud Data Fusion JDBC Batch ETL with GCS Staging and BigQuery | 4 | 7 | 8 | 5 | 8 | **6.10** |
| Dataflow Apache Beam JDBC Batch Pipeline with BigQuery Direct Write and Cloud Composer Orchestration ✅ | 8 | 8 | 6 | 7 | 7 | **7.35** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Dataflow Apache Beam JDBC Batch Pipeline with BigQuery Direct Write and Cloud Composer Orchestration**
**Weighted Score: 7.35**

**Justification:** Option 3 is recommended as the architecturally correct and economically optimal solution for the 5gcore pipeline. It aligns precisely with the stated batch pattern (hourly and daily scheduled loads), satisfies every functional requirement — historical load completeness gate, incremental watermarking, stored procedure MERGE on employee_id and updated_date, row count reconciliation, schema validation, PK uniqueness checks, audit logging, stakeholder Looker Studio dashboards, and prompt failure alerting — using fully managed GCP services with no cross-cloud dependencies. Job-based Dataflow billing is optimal for the 5 GB initial and 1 GB per month volume profile. Cloud Composer's task dependency model directly implements the hard requirement to block incremental loads until historical load validation passes, a control that cannot be expressed as simply in the other options. The architecture is extensible to additional agentichub tables without redesign by adding parameterised DAG tasks pointing to the same Flex Template.

**Why highest score:** Option 3 achieves the highest weighted score (7.35) by leading on Cost (8/10) due to job-based billing versus continuous billing in Option 1 (5/10) and hourly instance billing in Option 2 (4/10). Under the 0.30 cost weight, this advantage contributes 2.40 weighted points versus 1.50 and 1.20 for the alternatives. Option 3 matches Option 1 on Scalability (8 vs 9) for a batch workload where CDC replication headroom provides no practical benefit, and scores competitively on Latency (7/10) relative to the batch SLA. Option 1 leads on Latency (9) and Scalability (9) but its cost penalty outweighs those gains under the weighting model. Option 2 leads on Complexity (8) and Operability (8) but its Cost score of 4 and Latency score of 5 from the GCS staging hop produce the lowest overall weighted score at 6.10.

**Trade-offs accepted:** The team accepts the following trade-offs inherent in this recommendation: (1) a Dataflow Flex Template code artefact (Apache Beam pipeline with JDBC) that must be developed, containerised, version-controlled, and maintained; this is offset by the artefact's reuse across all tables and both load modes via parameterisation. (2) A fixed Cloud Composer baseline cost of approximately $300 per month justified by its orchestration, dependency gating, retry management, and SLA alerting capabilities that directly satisfy the stakeholder control requirements. (3) Explicit watermark management logic for incremental loads implemented in the stored procedure and validated by the Composer DAG, in lieu of CDC-based automatic change capture; this is a deliberate design choice appropriate to the batch pattern and provides a deterministic, auditable state model.

---

## Rejected Options

### Datastream CDC Replication with BigQuery Stored Procedure Merge

Datastream CDC introduces continuous streaming replication for a workload that requires only scheduled batch ingestion at hourly or daily cadence. The architectural pattern mismatch results in inflated cost (continuous billing vs. job-based billing, scoring 5/10 on cost) and elevated operational complexity including binlog management, schema evolution propagation risk, and replication lag monitoring — none of which deliver business value for a 5 GB initial, 1 GB per month growth scenario. Its high Latency (9) and Scalability (9) scores are technically impressive but irrelevant to a batch SLA and carry a 0.30-weighted cost penalty that depresses the overall weighted score to 6.80. The recommended Dataflow option achieves all functional requirements at lower cost and complexity.

### Cloud Data Fusion JDBC Batch ETL with GCS Staging and BigQuery

Cloud Data Fusion provides an excellent visual authoring experience and scores highest on Complexity (8) and Operability (8), but is economically unfavorable for this workload. Its hourly instance billing model produces the lowest Cost score (4/10) across all options at the current 5 GB initial and 1 GB per month volume. The GCS staging hop adds pipeline latency risk for hourly cadence windows (Latency score 5/10) and introduces an unnecessary intermediate store. The recommended Dataflow option delivers equivalent batch ingestion capability with job-based billing, direct MySQL-to-BigQuery writes, no GCS staging dependency, and comparable operability at materially lower total cost, producing a weighted score 1.25 points higher.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Data Completeness — Historical Load Gate | The historical load must achieve 100% row completeness before incremental loads activate. A network interruption or Cloud SQL connection drop mid-scan may produce a partial Dataflow output that writes fewer rows than the MySQL source count, but the Dataflow job itself may still report success if partial output was committed to BigQuery before the failure. | The Composer DAG must gate the incremental load activation task on a confirmed PASS status written to the audit_log table by the stored procedure, which compares a pre-load MySQL source row count (queried before the Dataflow job starts and stored in a Composer XCom variable) against the BigQuery post-load count. Dataflow job success status alone is insufficient as the gate condition. |
| Schema Evolution — New MySQL Columns | New columns added to MySQL source tables will not automatically appear in BigQuery target tables. The MERGE stored procedure will fail or silently discard new column data until the BigQuery schema is updated. This is a go-live blocker: the new column handling strategy must be documented and implemented before production activation. | Implement a schema comparison pre-flight task in the Composer DAG that runs INFORMATION_SCHEMA queries against MySQL (via Cloud SQL Auth Proxy) and BigQuery before each Dataflow job submission. Column-count or name mismatches must write an ERROR record to the audit_log table, halt the pipeline, and trigger a Cloud Monitoring alert. The approved runbook must specify whether schema additions trigger an automatic BigQuery ALTER TABLE (low risk for nullable columns) or a manual engineering review gate (required for type changes or NOT NULL additions). |
| Source System Load — Cloud SQL Saturation | Parallel JDBC reads from Dataflow place concurrent query and connection load on the Cloud SQL MySQL instance. During the 5 GB historical full scan, this could degrade MySQL performance for other consumers of the agentichub database on the same instance. | Schedule the historical full load during off-peak hours. Configure JdbcIO numPartitions conservatively (2-4 partitions) for the initial historical run and tune based on observed Cloud SQL CPU utilisation and connection count metrics in Cloud Monitoring. Evaluate promoting to a Cloud SQL read replica if source load becomes a recurring concern as additional tables are onboarded. |
| Watermark Integrity — Incremental State Corruption | If the watermark_control table entry is corrupted, reset to an incorrect value, or not updated atomically with the MERGE operation, subsequent incremental loads may reprocess historical data (producing duplicates) or skip a time window of records (producing gaps), both of which are silent data quality violations. | The stored procedure must update the watermark_control table atomically as part of the same logical transaction as the MERGE, using BigQuery scripting BEGIN...EXCEPTION...END blocks to ensure partial failures roll back the watermark update. The Composer DAG must include a pre-run sensor that validates the stored watermark value is within an expected range (not in the future, not older than the configured maximum lookback period) before submitting the Dataflow job. |
| Audit Log Completeness — Partial Stored Procedure Failures | If the stored procedure fails mid-execution after the MERGE but before writing the SUCCESS audit record, stakeholders will see a missing or stale status entry in the Looker Studio dashboard and may incorrectly interpret the load as pending rather than failed. | Structure the stored procedure to write a STARTED audit record at invocation and update it to SUCCESS or FAILED in a separate DML statement within an EXCEPTION handler, ensuring every execution path produces a terminal audit record. Cloud Monitoring alerting policies must independently notify on Composer task failure events regardless of audit_log table state, so operational response is not contingent on audit record correctness. |
| IAM and Network Security — Runtime Connectivity Failures | Dataflow workers require specific IAM roles (roles/cloudsql.client on the Dataflow service account, roles/bigquery.dataEditor on the target dataset) and network access to Cloud SQL. Misconfigured firewall rules or missing IAM bindings will produce runtime pipeline failures that are not detectable at Terraform plan time. | All IAM bindings, VPC firewall rules, and Cloud SQL Auth Proxy configurations must be declared and provisioned by Terraform, validated in a dev environment before production deployment. A pre-flight connectivity check task in the Composer DAG must verify Cloud SQL reachability and BigQuery dataset write access before submitting the Dataflow job, surfacing misconfiguration as a pipeline failure rather than a silent data gap. |

---

## Assumptions

1. The BigQuery stored procedure sp_mysqltobq_load.sql either already exists or will be developed as part of this programme; this document treats it as an encapsulated processing unit responsible for MERGE, reconciliation, schema validation, constraint checking, watermark update, and audit log write.
2. The Cloud SQL instance (verizon-data:us-central1:mysql-druid-metadatastore) is accessible from Dataflow workers in us-central1 via Cloud SQL Auth Proxy sidecar or VPC Private IP peering; firewall rules and IAM bindings permitting this access will be provisioned by Terraform.
3. The target BigQuery project is verizon-data, dataset is verizon_data_dea; the initial production table is employees; all additional agentichub tables will be confirmed with stakeholder Yash and documented in a load inventory before the historical load begins.
4. The 60-day retention policy is implemented as a BigQuery table partition expiry on the updated_date partition column applied to production tables in verizon_data_dea.
5. A Looker Studio report connected to BigQuery audit_log and reconciliation tables in verizon_data_dea is sufficient to meet the stakeholder-accessible dashboard requirement without a separate BI platform or additional licensing.
6. Stakeholder approval from Yash is the formal gate condition before any pipeline component progresses from draft to production deployment.
7. All pipeline artefacts (Dataflow Flex Template container image, Composer DAG files, Terraform modules, stored procedure SQL) will be managed in version-controlled source repositories with peer-reviewed change management.
8. The deployment target is production; dev and staging environment parity with production is assumed and must be validated before pipeline promotion.
9. No hard delivery deadline has been set; the timeline is governed by stakeholder review, sign-off, and the new column handling strategy sign-off gate.
10. The MySQL source user sa has SELECT privileges on all agentichub tables to be ingested; no DDL or DML access to the source is required by the pipeline.

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud Dataflow (Apache Beam JdbcIO with Flex Templates) selected as the ingestion engine for both historical and incremental loads | Perform a one-time full historical load with 100% data completeness; implement scheduled incremental loads hourly or daily per table; support ongoing data growth beyond the initial employees table | batch | 5 GB initial load; 1 GB per month ongoing growth |
| BigQuery Stored Procedure sp_mysqltobq_load.sql retained as the authoritative processing and MERGE layer with composite merge key on employee_id and updated_date | Execute all load logic via stored procedure sp_mysqltobq_load.sql with merge key on employee_id and updated_date | — | — |
| Cloud Composer 2 selected as orchestration layer with BigQueryCheckOperator task dependency gating the incremental load branch on confirmed historical load PASS status in audit_log | Block the incremental load pipeline from starting until full historical load validation is confirmed and passes; scheduled incremental loads must run without failures on defined hourly or daily cadence | batch | — |
| BigQuery production tables partitioned on updated_date with 60-day partition expiry policy | Enforce a 60-day data retention policy on the target BigQuery table | — | — |
| Schema comparison pre-flight task added to Composer DAG querying INFORMATION_SCHEMA on both MySQL and BigQuery before each Dataflow job submission, with mismatch logging to audit_log and pipeline halt on detected divergence | Perform schema validation before each load with mismatch logging and a documented strategy for handling new MySQL columns | — | — |
| Row count reconciliation, PK uniqueness check, and null and datatype constraint validation implemented within sp_mysqltobq_load.sql post-MERGE, with results written to audit_log | Perform row count reconciliation between MySQL and BigQuery after every load; confirm primary key uniqueness post-load and verify null and datatype constraints against schema definitions | — | — |
| Dedicated audit_log table in verizon_data_dea capturing status, record counts, load start and end timestamps, and watermark values for every load execution | Maintain a complete audit log for every load execution capturing status, record counts, and timestamps | — | — |
| Looker Studio report connected to BigQuery audit_log and reconciliation tables in verizon_data_dea providing stakeholder-accessible load history and data quality visibility | Provide stakeholder-accessible dashboards or log views enabling independent review of load success and execution history without engineering involvement | — | — |
| Cloud Monitoring alerting policies configured on Dataflow JOB_STATE_FAILED transitions, Composer task failure events, and custom log-based metrics from stored procedure ERROR log entries | Send alerts promptly on any pipeline failure or data quality violation | — | — |
| Terraform selected as IaC tool for all GCP resource provisioning including Dataflow Flex Template registration, Composer environment, BigQuery dataset and table definitions, IAM bindings, and VPC firewall rules | Cloud-native GCP deployment; production-bound pipeline requiring reproducible, version-controlled, and peer-reviewed infrastructure | — | — |

---

## Open Questions — Action Required

1. Latency SLA not specified: the requirements state hourly or daily cadence per table but do not define a maximum acceptable delay from MySQL commit to BigQuery availability. If a sub-hour data freshness SLA is introduced in future, the batch Dataflow option should be re-evaluated against Datastream CDC replication.
2. Table inventory incomplete: only the employees table is confirmed as the initial target. The full list of agentichub tables to be ingested must be agreed with stakeholder Yash and documented in a load inventory matrix before the historical load begins, as each additional table requires a corresponding Composer DAG branch, stored procedure extension, watermark_control entry, and schema definition registration.
3. Per-table load cadence not finalised: the requirements permit hourly or daily cadence per table but do not specify which tables require which frequency. A load frequency matrix mapping each table to its required cadence must be signed off before Composer DAG configuration is finalised.
4. New column handling strategy not yet documented or approved: the strategy for handling new MySQL columns (automatic BigQuery ALTER TABLE for nullable additions versus manual engineering review gate for type changes or NOT NULL additions) must be agreed, documented, and validated in a non-production environment before pipeline go-live, as it is a blocking constraint in the requirements.
5. Cloud SQL connectivity method not confirmed: the preferred method for Dataflow worker connectivity to Cloud SQL (Cloud SQL Auth Proxy sidecar versus Private IP VPC peering) has not been specified. Private IP is preferred for production security posture and eliminates the Auth Proxy operational dependency; VPC network topology and available CIDR ranges in us-central1 must be confirmed with the infrastructure team.
6. Alert notification channels not defined: the stakeholder requirement for prompt failure alerts does not specify delivery channels (email distribution list, PagerDuty service, Slack webhook, or SMS). Notification channel configuration must be confirmed with Yash and the engineering team before Cloud Monitoring alerting policies are activated in production.
7. Artifact Registry project and location for Dataflow Flex Template container images not specified: the GCP project and Artifact Registry repository path for storing and versioning the Dataflow Flex Template container image must be confirmed before the CI/CD pipeline for the Flex Template can be configured.
8. Data sensitivity classification absent: no PII, PHI, or PCI classification has been specified for the agentichub employees data. If the employees table contains personally identifiable information, column-level encryption via BigQuery AEAD functions, VPC Service Controls around the verizon_data_dea dataset, and BigQuery Authorized Views restricting stakeholder dashboard access to non-sensitive columns may be required before production go-live.
