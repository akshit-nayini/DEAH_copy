# Architecture Decision Document — mysql to bigquery data ingestion pipeline

| Field | Value |
|---|---|
| **Project** | mysql to bigquery data ingestion pipeline |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Batch |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Google Datastream + BigQuery Direct (Managed CDC Replication with Composer Gating)
>
> **Why:** Option 2 achieves the highest weighted score (8.55) by delivering the lowest operational complexity and maintenance burden among all options while fully satisfying every stated functional requirement: one-time full historical backfill, mandatory gated incremental activation, timestamp and PK-based change tracking, pre-load schema validation, new-column handling policy, post-load data quality checks, comprehensive audit logging, and a stakeholder-accessible Looker Studio dashboard. Datastream's native BigQuery destination eliminates all custom ingestion code; BigQuery SQL procedures handle all data quality and reconciliation logic within the managed BigQuery engine without additional compute infrastructure. Cloud Composer provides the required historical-load gate via Datastream stream PAUSE/RESUME API calls enforced as a hard Airflow task dependency.
>
> **Score:** 8.55 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2 ✅ | Option 3  |
|---|---||---||---|
| **Name** | Cloud Composer + Cloud Dataflow (Apache Beam) Batch Pipeline | Google Datastream + BigQuery Direct (Managed CDC Replication with Composer Gating) | Cloud Composer + Dataproc (PySpark) Batch Pipeline |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Cloud Dataflow / Apache Beam SDK 2.x | BigQuery SQL (MERGE / DML procedures + SQL-based data quality assertions) | Dataproc (PySpark) + BigQuery Load Jobs (Parquet from GCS) |
| **Storage** | Google Cloud Storage (staging) + BigQuery (analytical store) | Google Cloud Storage (Datastream staging buffer) + BigQuery (analytical store) | Google Cloud Storage (Parquet staging) + BigQuery (analytical store) |
| **Weighted Score** | **7.35** | **8.55**  ✅ | **5.55** |

---

## Option 1 — Cloud Composer + Cloud Dataflow (Apache Beam) Batch Pipeline

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer schedules and triggers parameterised Cloud Dataflow Flex Template jobs per table; Dataflow reads MySQL via JDBC connector using timestamp or primary key watermarks for incremental loads and a full unbounded range scan for the one-time historical load; source data is read in parallel partitions keyed on PK ranges to maximise MySQL throughput without full-table locks |
| Processing | Apache Beam pipelines enforce pre-load schema validation (type mismatch detection, null constraint checks, field mapping verification between MySQL and BigQuery schemas), data type coercion, PK-based deduplication, and post-load data quality assertions (row count reconciliation against a source-side COUNT query, PK uniqueness check, data type constraint verification); all execution outcomes are written atomically to Cloud Logging and a BigQuery audit log table |
| Storage | GCS bucket holds Dataflow temporary shuffle files and per-run audit artefacts; BigQuery target tables are date-partitioned on the load timestamp and clustered on primary key columns; a dedicated BigQuery audit dataset stores a per-execution record capturing start time, end time, source row count, target row count, validation status, and error payloads |
| Consumption | Analytics team queries BigQuery target tables directly via SQL clients, Looker, or connected BI tools; a Looker Studio dashboard linked to the BigQuery audit dataset provides self-serve stakeholder visibility into load health, row counts, and validation outcomes without engineering involvement |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Dataflow (JDBC connector for MySQL via Flex Templates) | — | Yes |
| Processing | Cloud Dataflow / Apache Beam SDK 2.x | — | Yes |
| Storage | Google Cloud Storage (staging) + BigQuery (analytical store) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio (audit dashboard) | — | Yes |
| Iac | Terraform (hashicorp/google provider) | — | No |

### Pros

- Fully serverless compute — Dataflow auto-scales horizontally with no cluster pre-provisioning or idle-cost risk
- Apache Beam SDK provides composable, testable transforms for schema validation, deduplication, and data quality checks within a single unified pipeline graph
- Native GCP service integration across Dataflow, GCS, BigQuery, Cloud Logging, and Cloud Monitoring sharing IAM, VPC, and billing contexts with zero cross-service friction
- Exactly-once semantics supported by the Dataflow runner, preventing duplicate records during retries or partial failures
- Cloud Composer hard-dependency gating: incremental DAG tasks are blocked until a dedicated historical-load validation task returns SUCCESS, satisfying the gate requirement natively
- Dataflow Flex Templates enable parameterised, reusable pipeline definitions deployable across all tables without code duplication
- Mature ecosystem with extensive GCP documentation, official JDBC connectors, and broad community support

### Cons

- Dataflow job startup latency of 1–3 minutes per job may consume a meaningful fraction of the hourly scheduling window when many tables are processed serially
- Apache Beam programming model has a moderate learning curve; teams without prior Beam experience face an initial ramp-up period before pipeline authorship is productive
- JDBC snapshot reads do not capture MySQL hard-deletes; deleted source rows persist in BigQuery as stale records unless a soft-delete column exists in the source schema
- Cost is fully consumption-based and unpredictable at unspecified data volumes; large historical loads may incur significant one-time Dataflow shuffle and worker costs without a cost ceiling
- JDBC partitioning must be tuned carefully per table to avoid long-running MySQL queries or connection exhaustion during the historical load phase

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | JDBC reads are snapshot-based; concurrent MySQL DML during extraction may produce slightly inconsistent cross-table snapshots; mitigated by scheduling loads in low-traffic windows and using REPEATABLE READ isolation where the MySQL driver supports it |
| Scaling | At high volumes (hundreds of GB per table), Dataflow shuffle service capacity and worker quota may require pre-approval; risk is unquantifiable until source volume is confirmed |
| Latency | Hourly incremental jobs spanning many tables in parallel may exhaust Cloud Composer slot capacity or Dataflow regional quota, causing queue-based scheduling delays; mitigated by staggered table-level scheduling and proactive quota increase requests |
| Cost | Cost is entirely variable and unknown until data volume is benchmarked; budget alerts via GCP Billing and Composer-level job cancellation thresholds are required to prevent runaway spend on the historical load |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 8 | 7 | 7 | 8 | **7.35** |

---

## Option 2 — Google Datastream + BigQuery Direct (Managed CDC Replication with Composer Gating) ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Google Datastream connects to the MySQL source via private connectivity (VPC peering or Cloud SQL Proxy); an initial full-backfill stream replicates all historical rows through GCS staging into BigQuery target tables; ongoing CDC events are captured from the MySQL binary log and written continuously to BigQuery; Cloud Composer enforces the mandatory gate by holding the Datastream stream in PAUSED state until a dedicated Airflow validation task confirms historical load completeness and correctness, at which point the stream is resumed and incremental replication begins |
| Processing | BigQuery natively receives and applies Datastream change events (INSERT, UPDATE, DELETE) to target tables using BigQuery's built-in change data handling; Cloud Composer triggers scheduled BigQuery SQL MERGE procedures to reconcile upserts and propagate hard-deletes within defined batch windows (hourly or daily per table); post-MERGE data quality routines — row count reconciliation against source, PK uniqueness assertion, and data type constraint checks — are implemented as BigQuery SQL procedures invoked by Airflow after each incremental window closes; schema validation is executed as a pre-load SQL assertion comparing INFORMATION_SCHEMA metadata between source (via Datastream schema registry) and target |
| Storage | GCS bucket serves as the Datastream backfill staging zone and durable replay buffer for CDC events; BigQuery stores all historical and incremental data in date-partitioned, PK-clustered tables per source table; a dedicated BigQuery audit dataset captures a per-execution audit record including run start, run end, source row count, target row count, validation pass or fail status, error detail, and the triggering Airflow run ID |
| Consumption | Analytics team queries BigQuery target tables directly via SQL clients, Looker, or connected BI tools; a Looker Studio dashboard connected to the BigQuery audit dataset provides stakeholder-facing load health visibility — showing per-table status, row counts, last successful run, and any validation failures — without requiring engineering involvement; BigQuery INFORMATION_SCHEMA and Data Catalog expose schema lineage and table metadata for governance |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Google Datastream (MySQL binary log CDC + full backfill to BigQuery via GCS) | — | Yes |
| Processing | BigQuery SQL (MERGE / DML procedures + SQL-based data quality assertions) | — | Yes |
| Storage | Google Cloud Storage (Datastream staging buffer) + BigQuery (analytical store) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio (stakeholder audit dashboard) | — | Yes |
| Iac | Terraform (hashicorp/google provider) | — | No |

### Pros

- Zero custom ingestion pipeline code required — Datastream handles MySQL connection management, full backfill, CDC event capture, schema mapping, and BigQuery delivery natively as a fully managed service
- Binary log CDC captures all DML events including hard-deletes, providing complete and accurate data replication that is architecturally superior to JDBC snapshot approaches used in Options 1 and 3
- Native BigQuery destination support eliminates a separate loading step, reducing the failure surface area and end-to-end latency between MySQL change and BigQuery availability
- Automatic schema evolution: Datastream detects new or modified MySQL columns and propagates schema changes to BigQuery, directly addressing the new-column handling requirement with a configurable alert-and-hold or auto-map policy
- Cloud Composer gating is implemented cleanly as a stream PAUSE/RESUME API call or a DAG sensor task — no workaround constructs needed to enforce the historical load prerequisite
- BigQuery SQL procedures for data quality checks require no additional compute infrastructure and run within the BigQuery engine at negligible incremental cost
- Looker Studio natively federates to BigQuery audit tables, requiring no additional tooling or infrastructure for the stakeholder dashboard requirement
- Lowest total operational overhead of all three options: no Beam SDK expertise, no cluster management, no dependency packaging, and no custom watermark state management

### Cons

- Requires MySQL binary logging (binlog) to be enabled with ROW format on the source instance; this is a DBA prerequisite action that may involve a MySQL service restart on self-managed instances
- Datastream CDC is inherently continuous rather than strictly windowed; for pure daily batch use cases the ongoing replication activity may be over-provisioned, though it can be paused between scheduled windows via Cloud Composer to control cost
- BigQuery MERGE operations for high-cardinality tables with high update rates incur query costs proportional to table size scanned; cost impact must be monitored and optimised via partitioning filters in MERGE predicates
- Datastream backfill offers less granular parallelism control than a custom Dataflow pipeline; for extremely large tables the backfill completion time cannot be tuned as precisely
- Datastream does not support all MySQL data types natively (e.g., spatial geometry types, ENUM in some configurations); per-table type compatibility must be validated during the design phase before stream creation

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | CDC event ordering and completeness depend on MySQL binlog retention integrity; if binlog_expire_logs_seconds is too low or binlog files are purged before Datastream consumes them, events may be missed; mitigated by setting a conservative binlog retention window (minimum 7 days), enabling Datastream lag monitoring via Cloud Monitoring alerts, and scheduling Composer-triggered gap-detection SQL assertions against source row counts |
| Scaling | Datastream scales automatically without operator intervention; however, very high MySQL write throughput may cause BigQuery Storage Write API quota pressure during peak ingestion; mitigated by pre-requesting Storage Write API quota increases and enabling BigQuery streaming buffer monitoring alerts |
| Latency | For strict hourly or daily batch windows Datastream delivers sub-minute CDC latency per event, making it technically over-provisioned; this is architecturally acceptable and does not introduce reliability risk, but the continuous replication model should be reviewed against budget once change volume is measured |
| Cost | Datastream charges per GB of data processed; cost is indeterminate until source change volume is benchmarked; BigQuery MERGE query costs add to storage costs; mitigated by GCP budget alerts, per-dataset BigQuery cost controls, and stream pause scheduling between batch windows to suppress unnecessary replication charges |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 9 | 9 | 8 | 9 | **8.55** |

---

## Option 3 — Cloud Composer + Dataproc (PySpark) Batch Pipeline

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer triggers ephemeral Dataproc cluster creation and submits PySpark jobs per table; PySpark reads MySQL via JDBC with partition predicates split by primary key range or timestamp bucket to parallelise extraction; the one-time historical load reads the full table range in a single large partitioned job; incremental loads read only rows where the watermark column (timestamp or PK) exceeds the last recorded high-watermark value stored in a BigQuery control table or GCS state file |
| Processing | PySpark DataFrames apply pre-load schema validation (column presence checks, data type casting, null enforcement), PK-based deduplication, row count reconciliation against a source-side JDBC COUNT query, and PK uniqueness assertion; validated output is written as partitioned Parquet files to GCS; a subsequent Airflow step triggers BigQuery load jobs to ingest Parquet from GCS into BigQuery target tables; the Airflow DAG writes a per-execution audit record to BigQuery after job completion confirmation |
| Storage | GCS stores intermediate Parquet files partitioned by extraction date and source table name; BigQuery holds final analytical tables with date partitioning and clustering; GCS also stores PySpark job logs, Dataproc cluster initialisation scripts, high-watermark state files for incremental tracking, and historical load completion flag files consumed by the Composer gate task |
| Consumption | Analytics team queries BigQuery directly via SQL clients or BI tools; Cloud Logging and Dataproc History Server provide engineering-level job diagnostics; a Looker Studio dashboard connected to the BigQuery audit table provides stakeholder-facing load health visibility |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataproc (PySpark JDBC connector for MySQL) triggered by Cloud Composer | — | Yes |
| Processing | Dataproc (PySpark) + BigQuery Load Jobs (Parquet from GCS) | — | Yes |
| Storage | Google Cloud Storage (Parquet staging) + BigQuery (analytical store) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Dataproc History Server | — | Yes |
| Iac | Terraform (hashicorp/google provider) | — | No |

### Pros

- PySpark's rich DataFrame API provides maximum transformation flexibility for complex data quality logic, custom schema validation, and multi-source joins that exceed what managed tools support natively
- Ephemeral Dataproc clusters eliminate idle compute cost — clusters are provisioned per job and torn down immediately after completion, paying only for active processing time
- PySpark JDBC with primary key range partitioning can achieve very high parallelised MySQL read throughput for extremely large individual tables when tuned correctly
- BigQuery load jobs from GCS Parquet are the most cost-efficient BigQuery ingestion method — no streaming insert charges or MERGE query costs for the bulk load path
- Broad team familiarity advantage for organisations with existing Spark expertise; PySpark is a widely adopted standard across enterprise data engineering teams

### Cons

- Highest operational complexity of all three options: requires Spark expertise, Dataproc cluster configuration, JDBC connection tuning, Python dependency packaging (wheel files and JAR management), and custom watermark state management
- Dataproc cluster startup time of 2–5 minutes per job adds significant fixed overhead to hourly incremental loads, consuming up to 8% of the hourly scheduling window before any data is processed
- No native hard-delete propagation: like all JDBC snapshot approaches, PySpark reads cannot detect MySQL row deletions without a soft-delete column in the source schema
- Watermark state management via GCS files or a BigQuery control table is a custom implementation with edge-case failure modes — a failed mid-run job can corrupt the high-watermark if the write sequencing is not carefully engineered
- Significantly more custom code to maintain compared to Options 1 and 2, increasing the long-term engineering ownership burden and regression risk for a primarily analytics-serving pipeline
- Higher cost uncertainty than serverless alternatives: per-minute Dataproc billing on ephemeral clusters is efficient at scale but more expensive than serverless Dataflow or Datastream for small to medium workloads

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Watermark drift is the primary data integrity risk: if a PySpark job fails mid-execution and the high-watermark is committed before all records are confirmed in BigQuery, the next incremental cycle will skip the failed window and produce a permanent data gap; mitigated by writing the high-watermark only after a confirmed BigQuery load job success status is returned to the Airflow task |
| Scaling | Dataproc autoscaling must be configured with distinct policies for the large historical load job and the smaller incremental jobs; a single misconfigured policy causes over-provisioning on small runs or under-provisioning on large ones, adding both cost and latency risk; tuning requires iterative benchmarking against real data volumes |
| Latency | Cluster startup adds 2–5 minutes of fixed overhead per job; for hourly incremental loads across many tables with serial scheduling, cumulative cluster startup time may approach or exceed the available scheduling window, causing cascading delays into the next cycle |
| Cost | At unspecified data volumes, Dataproc per-minute billing carries the highest cost uncertainty of all three options; large historical loads on ephemeral clusters with many workers can accumulate significant charges quickly; budget alerts and Composer-level job timeouts are required as cost guardrails |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 7 | 4 | 6 | 6 | **5.55** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Cloud Dataflow (Apache Beam) Batch Pipeline | 7 | 8 | 7 | 7 | 8 | **7.35** |
| Google Datastream + BigQuery Direct (Managed CDC Replication with Composer Gating) ✅ | 8 | 9 | 9 | 8 | 9 | **8.55** |
| Cloud Composer + Dataproc (PySpark) Batch Pipeline | 5 | 7 | 4 | 6 | 6 | **5.55** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Google Datastream + BigQuery Direct (Managed CDC Replication with Composer Gating)**
**Weighted Score: 8.55**

**Justification:** Option 2 achieves the highest weighted score (8.55) by delivering the lowest operational complexity and maintenance burden among all options while fully satisfying every stated functional requirement: one-time full historical backfill, mandatory gated incremental activation, timestamp and PK-based change tracking, pre-load schema validation, new-column handling policy, post-load data quality checks, comprehensive audit logging, and a stakeholder-accessible Looker Studio dashboard. Datastream's native BigQuery destination eliminates all custom ingestion code; BigQuery SQL procedures handle all data quality and reconciliation logic within the managed BigQuery engine without additional compute infrastructure. Cloud Composer provides the required historical-load gate via Datastream stream PAUSE/RESUME API calls enforced as a hard Airflow task dependency.

**Why highest score:** Option 2 leads all options on Complexity (9) and Operability (9) — the dimensions most critical for long-term analytical platform reliability and team ownership — while also scoring highest on Scalability (9), reflecting Datastream's fully managed horizontal scaling with no operator intervention. Its Cost score (8) reflects competitive per-GB pricing with no idle compute charges and no cluster provisioning overhead. Its Latency score (8) reflects that Datastream CDC delivers changes faster than the stated batch SLA, providing scheduling headroom. No other option matches this combination of zero custom ingestion code, native hard-delete propagation, automated schema evolution, and GCP-native observability integration.

**Trade-offs accepted:** MySQL binary logging must be enabled with ROW format prior to Datastream configuration — a prerequisite DBA action that must be planned into the project timeline. Datastream's continuous CDC model is over-provisioned relative to a pure daily batch SLA but does not introduce reliability or cost risk at moderate change volumes; stream pause scheduling between batch windows can be added to optimise cost. BigQuery MERGE query costs for large tables with high update rates must be monitored and may require partition-predicate optimisation after the first production load cycle.

---

## Rejected Options

### Cloud Composer + Cloud Dataflow (Apache Beam) Batch Pipeline

Rejected in favour of Option 2 (Datastream + BigQuery Direct), which delivers equivalent scalability and stronger data quality guarantees — including native hard-delete propagation via CDC — while requiring zero custom Beam pipeline code for ingestion. Option 1 demands Beam SDK expertise, custom JDBC partitioning logic, and manual soft-delete handling that add implementation and maintenance burden without differentiated capability for this use case.

### Cloud Composer + Dataproc (PySpark) Batch Pipeline

Rejected due to the lowest weighted score (5.55) and the highest operational complexity among all options. Custom PySpark code for JDBC ingestion, watermark state management, schema validation, and cluster lifecycle management substantially increases implementation effort, maintenance burden, and failure surface area relative to Options 1 and 2 — without delivering any differentiated capability for the stated requirements. Cluster startup latency is a structural disadvantage for hourly incremental scheduling. This option is appropriate only if confirmed data volumes exceed several TB per table or if complex multi-source transformation logic is introduced that exceeds the capabilities of managed tools.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Data Volume Uncertainty | Source data volume per table and in aggregate is unspecified. Datastream quota sizing, BigQuery slot reservation, MERGE query cost, GCS staging capacity, and overall cost estimates cannot be accurately planned without this information. Undersized quotas may cause pipeline failures at the historical load phase. | Conduct a table-level row count and size profiling exercise (SELECT COUNT(*), AVG(row_length) from INFORMATION_SCHEMA) against the MySQL source before pipeline design is finalised. Use results to validate tool selection, submit Datastream and BigQuery quota increase requests, and establish GCP Billing budget alerts with automated notification thresholds. |
| MySQL Source Connectivity | Network connectivity details between the MySQL host and GCP have not been provided. Pipeline deployment is blocked if private connectivity is not established. Firewall rules, VPN tunnel configuration, or Cloud SQL Proxy setup may require coordination across network, DBA, and cloud infrastructure teams. | Engage network and DBA teams to confirm and document the connectivity path (VPC peering, Cloud VPN, or Cloud SQL Proxy) before sprint planning begins. Validate the connection with a test Datastream stream or JDBC probe in a non-production GCP environment. Include network provisioning as a gating prerequisite in the project plan. |
| Schema Drift | MySQL source schemas may evolve over time through new column additions, data type changes, or column renames. Undetected schema drift can cause Datastream stream failures, silent data loss, or type coercion errors in BigQuery target tables. | Configure Datastream schema evolution policy to alert-and-hold on new column detection, preventing silent propagation of unanticipated changes. Store schema snapshots in a BigQuery metadata table after each load cycle and implement a Composer-triggered drift detection task that compares current INFORMATION_SCHEMA against the baseline snapshot. Define an explicit organisational policy for new-column handling (alert-and-hold vs. auto-map-with-review) and document it in the runbook. |
| Historical Load Gate Enforcement | Incremental loads must not begin until the historical load is fully validated and confirmed complete. A failure to enforce this gate — due to a misconfigured DAG dependency, a race condition, or a manual override — could result in data gaps, duplicate records, or conflicting writes in BigQuery. | Implement the gate as a hard Cloud Composer Airflow task dependency using a BigQuery sensor task that checks a control table row written only after all historical validation assertions pass. Store the gate state in a BigQuery control table with a Composer run ID, timestamp, and pass/fail status for full auditability. The Datastream stream remains in PAUSED state until the control table sensor returns success. |
| Hard-Delete Propagation | Options 1 and 3 (JDBC and PySpark snapshot-based approaches) do not capture MySQL hard-deletes; deleted source rows will persist as stale records in BigQuery indefinitely, degrading analytical accuracy. This risk does not apply to the recommended Option 2. | Option 2 (recommended) resolves this architecturally via CDC binary log capture, which includes DELETE events natively. If Options 1 or 3 are selected in future, source MySQL schemas must include a soft-delete column (e.g., is_deleted BOOLEAN, deleted_at TIMESTAMP) as a mandatory prerequisite for accurate incremental replication. |
| Security and Compliance | Data sensitivity classification, access control requirements, and compliance obligations (GDPR, SOC 2, internal data governance standards) have not been specified. PII or sensitive fields loaded into BigQuery without appropriate controls may create regulatory or contractual exposure. | Initiate a data classification workshop with the data owner (Shruthi B) and the security or compliance team before the pipeline goes to production. Apply BigQuery column-level security policies, Cloud Logging audit log sinks to a long-retention GCS archive, and VPC Service Controls around the BigQuery dataset once classification is confirmed. Revisit Datastream encryption-in-transit and CMEK configuration as part of the security review. |

---

## Assumptions

1. GCP is the target cloud platform, consistent with Google BigQuery as the specified analytical target and the absence of any alternative cloud provider requirement
2. The MySQL source instance is reachable from GCP via private connectivity — either VPC peering, Cloud VPN, or Cloud SQL Proxy — with no public internet exposure required for the data pipeline
3. Source MySQL tables contain at least one reliable timestamp column (e.g., updated_at, created_at) or a monotonically increasing primary key column that can serve as an incremental change-tracking watermark
4. MySQL binary logging (binlog) is enabled or can be enabled with ROW format by a DBA prior to Datastream stream configuration; this is a hard prerequisite for the recommended Option 2
5. Data volume per table and in aggregate is unknown; all cost estimates, processing tier selections, and scalability scores are based on medium-scale assumptions (GB to low-TB range) and must be re-evaluated once volume profiling is completed against the MySQL source
6. A GCP project with adequate quota for Google Datastream, Cloud Composer 2, BigQuery, and GCS is available or will be provisioned as part of this initiative
7. BigQuery target project, dataset structure, and table naming conventions will be defined and approved before pipeline deployment begins
8. The analytics team has BigQuery read access to target datasets and to the Looker Studio stakeholder dashboard without requiring bespoke access provisioning per user
9. Historical load validation is a defined, repeatable process — either fully automated SQL assertions against source row counts or a formal manual sign-off by the data owner — before incremental loads are unblocked via Cloud Composer
10. All pipelines are deployed within a single GCP project; multi-project Shared VPC or VPC Service Controls are out of scope unless explicitly required by a later security review
11. Security controls including column-level BigQuery security, VPC-SC perimeters, and CMEK encryption will be applied in alignment with organisational security policy once data sensitivity classification is confirmed
12. No real-time or sub-minute latency SLA is required; hourly or daily batch cadence is sufficient for all stated analytics and reporting use cases
13. Terraform state will be stored in a GCS backend bucket with versioning enabled; all GCP resource provisioning will be managed via Terraform in version-controlled source repositories

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Selected GCP as the cloud platform with BigQuery as the sole analytical target | technology.stack: [MySQL, Google BigQuery]; technology.cloud_or_onprem: cloud | — | — |
| Adopted a batch ingestion pattern with hourly and daily scheduling tiers rather than a streaming or micro-batch approach | data_requirements.frequency: daily schedule interval; hourly or daily per-table configuration for incremental loads | batch | — |
| Structured the pipeline in two mandatory phases: a one-time full historical load followed by ongoing scheduled incremental loads | functional_requirements[0]: Perform a one-time full historical load from MySQL to BigQuery for all identified tables without data loss; objective: including a one-time full historical load and ongoing scheduled incremental loads | — | — |
| Enforced the historical load gate as a hard Cloud Composer task dependency using a BigQuery control table sensor blocking Datastream stream resumption | functional_requirements[3]: Gate incremental loads so they cannot begin until the full historical load has been validated and confirmed complete; constraints.technical_limitations: Incremental loads must not begin until historical load validation has passed | — | — |
| Mandated timestamp-based or primary key-based watermarks for incremental change tracking; full table re-scans are architecturally prohibited | functional_requirements[2]: Use timestamp-based or primary key-based change tracking to identify and load only new or changed records; constraints.technical_limitations: full table re-scans are not permitted | — | — |
| Implemented pre-load schema validation as a blocking pipeline step covering type mismatches, null constraint inconsistencies, and field mapping errors | functional_requirements[4]: Implement pre-load schema validation that detects type mismatches, null handling inconsistencies, and field mapping issues between MySQL and BigQuery schemas | — | — |
| Adopted alert-and-hold as the default new-column handling policy with an optional auto-map-with-review configuration on the Datastream schema evolution setting | functional_requirements[5]: Define and implement a strategy for handling new columns that appear in the MySQL source (e.g., alert and hold, or auto-map with review) | — | — |
| Implemented post-load data quality checks as BigQuery SQL procedures covering row count reconciliation, PK uniqueness, and data type constraint verification, triggered by Cloud Composer after each incremental window | functional_requirements[6]: Implement per-load data quality checks covering row count reconciliation, primary key uniqueness, and data type constraint verification | — | — |
| Maintained a dedicated BigQuery audit dataset with a per-execution record capturing execution time, record counts, validation outcomes, and error payloads | functional_requirements[7]: Maintain audit logs for all load executions capturing execution time, record counts, validation results, and any errors | — | — |
| Provided a Looker Studio dashboard connected to the BigQuery audit dataset for zero-engineering stakeholder visibility into load health | functional_requirements[8]: Provide stakeholder visibility into load success through accessible logs or a dashboard without requiring engineering involvement | — | — |
| Selected Terraform as the IaC tool for all GCP resource provisioning across Datastream, Cloud Composer, BigQuery, and GCS | technology.cloud_or_onprem: cloud; existing_architecture: null — greenfield deployment requiring full infrastructure provisioning | — | — |
| Preferred fully managed GCP services (Datastream, Cloud Composer 2, BigQuery) over self-managed or cluster-based alternatives to minimise operational overhead | non_functional.scalability: Pipeline must be reliable and scalable to support analytics, reporting, and long-term data storage; non_functional.sla: scheduled hourly or daily incremental jobs must run without failures on the defined cadence | — | — |

---

## Open Questions — Action Required

1. What is the estimated total data volume for the historical load (GB or TB in aggregate), and what is the estimated daily incremental change volume (rows and GB) per table? This is required to validate Datastream quota sufficiency, set BigQuery slot reservation levels, size GCS staging buckets, and produce an accurate monthly cost estimate.
2. Is MySQL binary logging (binlog) currently enabled with ROW format on the source instance? If not, is a DBA-coordinated change request and potential MySQL service restart feasible before project kickoff? This is a hard prerequisite for the recommended Datastream-based architecture.
3. What are the network connectivity details for the MySQL source host — specifically, is private connectivity from the GCP project to the MySQL instance already established via VPC peering, Cloud VPN, or Cloud SQL Proxy, or must this be provisioned as part of the project scope?
4. Which specific tables are included in the pipeline scope, and which tables require hourly versus daily incremental load frequency? This determines Cloud Composer DAG scheduling topology, Datastream stream segmentation, and the number of concurrent BigQuery MERGE procedures to plan for.
5. What constitutes a passing historical load validation — is it a fully automated assertion (row count within a defined tolerance, PK uniqueness, zero null violations on mandatory columns), a manual data owner sign-off (Shruthi B), or a combination of both? The gate implementation depends on the answer.
6. Are there any PII, sensitive, or regulated data fields in the source tables that require masking, tokenisation, pseudonymisation, or column-level BigQuery security policies before the pipeline goes to production?
7. What are the target BigQuery project ID and dataset naming conventions, and are there pre-existing organisational standards for environment suffixing (e.g., _dev, _prod), source system prefixing, or data domain partitioning that must be respected?
8. Is an existing GCP project with pre-approved quotas for Datastream, Cloud Composer 2, BigQuery, and GCS available, or must project provisioning, IAM hierarchy configuration, and quota increase requests be included in the project delivery timeline?
9. What is the acceptable data freshness SLA for the Looker Studio stakeholder dashboard after an incremental load window closes — near-real-time, within 15 minutes of load completion, or within the full batch window (hourly or daily)?
