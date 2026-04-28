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

> **Build with:** Cloud Composer + Cloud Run Jobs + GCS + BigQuery Native (Recommended)
>
> **Why:** Option 2 delivers the highest weighted score (8.10) by optimising across all five dimensions simultaneously. Cloud Run Jobs provide serverless cost-proportional ingestion with zero idle cost aligned to the medium-volume workload. BigQuery native Load Jobs and stored procedures encapsulate all merge and validation logic without additional compute infrastructure or framework expertise. Cloud Composer enforces the required historical-load validation gate and supports per-table hourly or daily scheduling. The bq_load_audit table with a Looker Studio dashboard directly satisfies the stakeholder independent-visibility requirement. The architecture is the simplest of the three options to implement, operate, extend to additional tables, and hand over to a wider team.
>
> **Score:** 8.10 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2 ✅ | Option 3  |
|---|---||---||---|
| **Name** | Cloud Composer + Dataflow JDBC (Enterprise Beam Pipeline) | Cloud Composer + Cloud Run Jobs + GCS + BigQuery Native (Recommended) | Datastream CDC + BigQuery Native + Cloud Composer (Event-Driven Replication) |
| **Pattern** | Batch | Batch | Hybrid |
| **Processing** | Dataflow (Apache Beam) + BigQuery Stored Procedures | BigQuery Load Jobs + BigQuery Stored Procedures (sp_mysqltobq_load) | BigQuery Stored Procedures (sp_mysqltobq_load) + Cloud Run Jobs (reconciliation queries) |
| **Storage** | BigQuery (verizon_data_dea) + GCS (staging) | BigQuery (verizon_data_dea) + GCS (staging) | BigQuery (verizon_data_dea) |
| **Weighted Score** | **6.20** | **8.10**  ✅ | **6.75** |

---

## Option 1 — Cloud Composer + Dataflow JDBC (Enterprise Beam Pipeline)

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 schedules Dataflow jobs that connect to Cloud SQL MySQL (verizon-data:us-central1:mysql-druid-metadatastore) via JDBC over Cloud SQL Proxy. For the historical load, a full table scan is executed with no filter. For incremental loads, a parameterised query filters rows WHERE updated_date > last_watermark read from the bq_load_audit control table in BigQuery. |
| Processing | Dataflow (Apache Beam) applies in-flight schema validation, datatype casting, and null-constraint checks within the pipeline graph. Validated records are written to GCS as staged Parquet files. A subsequent BigQuery Load Job ingests the staged files into a staging table, after which sp_mysqltobq_load executes a MERGE into the target table using (employee_id, updated_date) as the composite merge key. Post-merge validation SQL asserts row-count reconciliation, PK uniqueness, and null constraints, writing results to bq_load_audit. |
| Storage | GCS bucket (verizon-data-5gcore-staging) holds ephemeral Parquet stage files under a 7-day lifecycle deletion rule. BigQuery dataset verizon_data_dea holds the target table with a 60-day partition expiry on _PARTITIONTIME and a permanent bq_load_audit table capturing every run status, record counts, and timestamps. |
| Consumption | Looker Studio dashboard connects directly to verizon_data_dea.bq_load_audit and BigQuery INFORMATION_SCHEMA.JOBS for stakeholder-facing load-success summaries, row-count trends, and schema-validation history. Cloud Monitoring alerting policies fire on Dataflow job failures and BigQuery DML error log entries via email or Pub/Sub notification channels. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataflow (Apache Beam JDBC IO + Cloud SQL Proxy sidecar) | 2.x | Yes |
| Processing | Dataflow (Apache Beam) + BigQuery Stored Procedures | 2.x | Yes |
| Storage | BigQuery (verizon_data_dea) + GCS (staging) | — | Yes |
| Orchestration | Cloud Composer 2 (Airflow 2.9) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio | — | Yes |
| Iac | Terraform | 1.8 | No |

### Pros

- Dataflow provides fine-grained, in-flight schema validation and datatype enforcement within the pipeline graph before data lands in BigQuery, catching quality issues upstream.
- Apache Beam autoscaling accommodates burst ingestion volumes across many concurrent tables without manual tuning of worker counts.
- Mature JDBC IO connector delivers reliable MySQL read semantics with configurable fetch sizes and connection pooling, well-suited to structured relational data.
- Full observability stack via Dataflow job metrics, Cloud Monitoring, and structured Cloud Logging provides deep operational insight.
- Cloud Composer dependency operator natively enforces the historical-load validation gate before enabling incremental DAG tasks.

### Cons

- Dataflow per-vCPU per-hour pricing is disproportionate to the medium-volume workload of 5 GB initial load and 1 GB/month growth, inflating operating cost.
- Apache Beam pipeline development requires specialised Beam SDK expertise (Python or Java), raising onboarding time and narrowing the pool of maintainers.
- Dataflow job spin-up latency of 2-5 minutes per execution adds unnecessary overhead against hourly/daily SLA windows.
- Cloud Composer environment incurs a fixed monthly baseline cost of approximately $300-400 regardless of pipeline execution frequency.
- JDBC driver lifecycle management, Cloud SQL Proxy sidecar configuration, and Beam pipeline packaging increase the operational surface area significantly versus native BigQuery alternatives.

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | In-flight schema mismatch between MySQL DDL and Beam pipeline schema definitions causes job failures if source columns are added without propagating changes to the Beam schema registry; requires a documented schema-change runbook and pre-deployment schema freeze. |
| Scaling | High concurrency across many tables simultaneously may saturate Cloud SQL vCPUs via JDBC read parallelism if connection pool bounds are not explicitly tuned in Dataflow pipeline options. |
| Latency | Dataflow worker spin-up adds 2-5 minutes to every execution cycle, which is acceptable for daily cadence but marginal for tight hourly SLA windows where alerting thresholds are strict. |
| Cost | Dataflow autoscaling can over-provision workers for small datasets; without explicit min/max worker bounds set in pipeline options, compute costs can exceed projections on every scheduled run. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 9 | 4 | 7 | 6 | **6.20** |

---

## Option 2 — Cloud Composer + Cloud Run Jobs + GCS + BigQuery Native (Recommended) ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 schedules Cloud Run Jobs on per-table hourly or daily cadences defined in Airflow Variables. Each Cloud Run Job connects to Cloud SQL MySQL (verizon-data:us-central1:mysql-druid-metadatastore) via the Cloud SQL Python Connector using IAM service-account authentication. A pre-flight step compares MySQL INFORMATION_SCHEMA column definitions against the BigQuery table schema; additive new columns are auto-provisioned in BigQuery via ALTER TABLE, breaking changes (type mutations, column drops) halt execution and write an ERROR record to bq_load_audit. For the historical load the job executes a full SELECT with no filter; for incremental loads it filters WHERE updated_date > last_watermark read from verizon_data_dea.bq_load_audit for that table. Results are written as Parquet files partitioned by run_id to GCS (gs://verizon-data-5gcore-staging/{table}/{run_id}/). |
| Processing | A BigQuery Load Job ingests Parquet files from GCS into a staging table (verizon_data_dea.{table}_stage). BigQuery stored procedure sp_mysqltobq_load is called via CALL statement and executes a MERGE from the staging table into the target table using (employee_id, updated_date) as the composite merge key, performing INSERT for new records and UPDATE for changed records. A post-merge BigQuery SQL validation script asserts: (1) MySQL source row count (captured in Cloud Run Job and stored in bq_load_audit) matches the staging row count; (2) no duplicate (employee_id, updated_date) pairs exist in the target table; (3) NOT NULL constraints are satisfied for all defined key columns. All assertion outcomes write PASS or FAIL records with counts and timestamps to bq_load_audit. |
| Storage | GCS bucket verizon-data-5gcore-staging with a 7-day lifecycle deletion rule on staged Parquet files. BigQuery dataset verizon_data_dea holds: the target table partitioned by _PARTITIONTIME with a 60-day partition expiry policy, a {table}_stage temporary staging table truncated before each load, and the permanent bq_load_audit table (no expiry) recording table_name, run_id, load_type, status, source_row_count, target_row_count, schema_validation_status, started_at, and completed_at for every execution. |
| Consumption | Looker Studio dashboard connected to verizon_data_dea.bq_load_audit provides stakeholder-facing load-success history, row-count reconciliation trend charts, schema-validation event log, and SLA compliance summary accessible without engineering involvement. Cloud Monitoring alerting policies send email and optional Pub/Sub notifications on Cloud Run Job non-zero exit codes, BigQuery stored procedure ERROR-severity log entries, and row-count reconciliation mismatches exceeding a configurable tolerance threshold. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Run Jobs (Python 3.12, Cloud SQL Python Connector, pandas-gbq) | Cloud Run Jobs GA | Yes |
| Processing | BigQuery Load Jobs + BigQuery Stored Procedures (sp_mysqltobq_load) | — | Yes |
| Storage | BigQuery (verizon_data_dea) + GCS (staging) | — | Yes |
| Orchestration | Cloud Composer 2 (Airflow 2.9) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio (on bq_load_audit) | — | Yes |
| Iac | Terraform | 1.8 | No |

### Pros

- Cloud Run Jobs are billed only for vCPU and memory consumed per invocation, making cost directly proportional to the 5 GB and 1 GB/month workload with zero idle infrastructure spend.
- BigQuery batch Load Jobs are free per Google pricing and do not consume slot reservation credits, minimising the processing cost component of the pipeline.
- The sp_mysqltobq_load stored-procedure pattern encapsulates all merge, validation, and audit-log writes in a single BigQuery-native SQL artifact that is easy to review, version-control in Git, and invoke idempotently.
- Cloud Run Job container isolation ensures stateless, idempotent execution; retries are safe and do not risk double-ingestion when combined with the staging table plus MERGE pattern.
- The bq_load_audit table with a Looker Studio dashboard directly satisfies the stakeholder independent-visibility requirement without any custom application, API, or engineering involvement.
- Cloud Composer dependency and sensor operators natively enforce the historical-load validation gate by checking the historical_load_validated flag in bq_load_audit before enabling incremental DAG tasks.
- New MySQL tables are onboarded by adding a parameterised Airflow task and a matching sp_mysqltobq_load variant; no new infrastructure components or container images are required.
- Cloud SQL Python Connector supports IAM database authentication, eliminating the need to store MySQL passwords outside of Secret Manager.

### Cons

- Cloud Run Job container images must be maintained and rebuilt whenever Python dependencies, schema-validation logic, or the Parquet serialisation layer changes.
- Cloud Composer small environment incurs a fixed monthly baseline cost of approximately $300-400 even for low-frequency pipelines where simpler scheduling alternatives could suffice.
- The GCS Parquet staging hop introduces a minor intermediate step; direct BigQuery streaming inserts would eliminate it but are not free and conflict with the batch pattern and free Load Job pricing.
- Cloud Run Jobs have a maximum execution timeout of 24 hours; extremely large single-table exports approaching this limit require chunking logic, though this is unlikely at the stated 5 GB initial volume.
- Schema validation logic in the Cloud Run Job and the BigQuery stored procedure column list must be kept in sync; a drift between the two can produce silent data mismatches.

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Incremental load relies on the updated_date watermark column being consistently maintained by the MySQL application layer. Records modified via direct SQL writes that bypass application-level timestamp updates will not appear in the incremental filter and will be silently excluded from BigQuery. Mitigation: schedule a weekly full-reconciliation run comparing total MySQL source row counts against BigQuery target row counts per table and alert on discrepancies exceeding a configurable tolerance of 0.1%. |
| Scaling | At current medium volume Cloud Run Jobs are well within execution limits. If additional high-write-volume tables are onboarded, concurrent job executions may create Cloud SQL connection saturation; connection pool sizing in the Cloud SQL Python Connector must be tuned proportionally to the number of concurrent jobs. |
| Latency | Cloud Run Job cold-start adds 5-30 seconds per execution. This is negligible against hourly or daily SLA windows but must be factored into SLA window boundary calculations when setting Airflow schedule intervals and monitoring alert thresholds. |
| Cost | Cloud Composer is the dominant fixed cost driver at approximately $300-400 per month. If the finalised schedule for all tables is exclusively daily rather than hourly, replacing Composer with Cloud Scheduler invoking Cloud Run Jobs directly should be evaluated to eliminate this cost. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 8 | 8 | 8 | 9 | **8.10** |

---

## Option 3 — Datastream CDC + BigQuery Native + Cloud Composer (Event-Driven Replication)

**Pattern:** Hybrid

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Datastream is configured with a MySQL source profile pointing to Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore and a BigQuery destination profile targeting verizon_data_dea. MySQL binary logging must be enabled on the Cloud SQL instance (binlog_format=ROW) with a minimum 48-hour binlog_expire_logs_seconds retention before the stream is activated. A Datastream backfill operation performs the initial full historical load directly into a BigQuery replica staging table. Ongoing CDC reads binary log row-level INSERT, UPDATE, and DELETE events and writes them to the staging replica table in near-real-time via the Datastream native BigQuery destination integration. |
| Processing | Cloud Composer triggers a scheduled validation DAG (hourly or daily per table) that: (1) executes sp_mysqltobq_load MERGE from the Datastream staging replica into the validated target table using (employee_id, updated_date) as the merge key; (2) executes a Cloud Run Job query against Cloud SQL to capture current source row counts for reconciliation; (3) asserts staging-to-target row count parity, PK uniqueness, and null constraints via BigQuery SQL; and (4) writes all assertion outcomes to bq_load_audit. A Composer sensor task checks the historical_load_validated flag in bq_load_audit before enabling incremental validation DAG runs. |
| Storage | BigQuery dataset verizon_data_dea holds: the Datastream-managed staging replica table, the validated target table with 60-day partition expiry, and the permanent bq_load_audit table. Datastream uses GCS internally for its change-event staging buffer; this bucket is managed by Datastream and is not user-visible or user-maintained. |
| Consumption | Looker Studio dashboard connected to verizon_data_dea.bq_load_audit provides stakeholder-facing load history and validation outcomes. Cloud Monitoring covers Datastream stream health, replication lag metrics, and BigQuery validation job failures via alerting policies. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Datastream (MySQL CDC with BigQuery native destination) | — | Yes |
| Processing | BigQuery Stored Procedures (sp_mysqltobq_load) + Cloud Run Jobs (reconciliation queries) | — | Yes |
| Storage | BigQuery (verizon_data_dea) | — | Yes |
| Orchestration | Cloud Composer 2 (Airflow 2.9) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Datastream Stream Monitoring + Looker Studio | — | Yes |
| Iac | Terraform | 1.8 | No |

### Pros

- Datastream native BigQuery destination eliminates manual ETL ingestion code; CDC captures all row-level changes without relying on an updated_date watermark column being correctly maintained.
- Near-real-time CDC provides sub-minute replication lag, offering architectural headroom if business requirements shift from daily or hourly to more frequent data freshness.
- Datastream handles historical backfill and ongoing incremental replication in a single managed stream, reducing the operational distinction between full load and incremental load phases.
- No user-managed GCS staging bucket is required for the primary data flow; the ingestion-to-BigQuery path is fully managed by Datastream.
- Binary-log-based CDC is more reliable than timestamp-watermark tracking for tables where the application layer does not consistently maintain updated_date on every write.

### Cons

- Datastream requires MySQL binary logging (binlog_format=ROW) to be enabled on the Cloud SQL instance; if not already configured, enabling this may require a Cloud SQL instance restart and DBA-team coordination, introducing deployment risk.
- Datastream pricing is based on GB of data processed through the stream; for tables with high update rates the ongoing streaming cost may exceed equivalent periodic batch-export costs and is harder to forecast.
- The historical-load validation gate is less naturally enforced in a continuously streaming architecture; Datastream backfill runs independently of validation, requiring additional Composer sensor logic and manual coordination to confirm completeness before incremental CDC is treated as authoritative.
- The near-real-time CDC capability is architectural over-engineering relative to the stated batch (hourly or daily) latency requirement, introducing operational complexity and cost without delivering a latency benefit the business has requested.
- Datastream CDC does not natively produce the schema-drift audit log in the bq_load_audit format required by the functional requirements; supplementary schema-check Cloud Run Jobs are still needed alongside the CDC stream.
- Binary log retention on the Cloud SQL source must be actively managed to ensure Datastream can resume after planned maintenance or temporary stream pauses without losing change events.

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | If binary logging is temporarily interrupted by Cloud SQL maintenance or binlog rotation occurring before Datastream reads the events, change records can be silently lost and the BigQuery target will diverge from the MySQL source without immediate detection. Mitigation: configure binlog_expire_logs_seconds to retain at minimum 48 hours of binary logs and enable Datastream replication lag and stream-health alerting in Cloud Monitoring. |
| Scaling | Datastream throughput is bounded by the Cloud SQL source instance binlog generation rate; onboarding additional high-write-volume tables may increase replication lag under a single stream. Mitigation: monitor the datastream.googleapis.com/stream/unsupported_events and throughput metrics and scale via multiple streams if lag exceeds the SLA window. |
| Latency | While Datastream delivers near-real-time ingestion, the downstream Composer validation DAG runs on a scheduled hourly or daily cadence; the effective data freshness in the validated target table therefore remains batch, adding architectural complexity without a latency benefit relative to the stated requirement. |
| Cost | Datastream charges per GB of change data processed through the stream; for tables with high-frequency update patterns the ongoing streaming cost can exceed equivalent Cloud Run Job periodic batch-export costs. A unit-cost comparison between Datastream GB fees and Cloud Run invocation costs should be validated for each table before adoption. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 8 | 6 | 7 | 7 | **6.75** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Dataflow JDBC (Enterprise Beam Pipeline) | 5 | 9 | 4 | 7 | 6 | **6.20** |
| Cloud Composer + Cloud Run Jobs + GCS + BigQuery Native (Recommended) ✅ | 8 | 8 | 8 | 8 | 9 | **8.10** |
| Datastream CDC + BigQuery Native + Cloud Composer (Event-Driven Replication) | 6 | 8 | 6 | 7 | 7 | **6.75** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Composer + Cloud Run Jobs + GCS + BigQuery Native (Recommended)**
**Weighted Score: 8.10**

**Justification:** Option 2 delivers the highest weighted score (8.10) by optimising across all five dimensions simultaneously. Cloud Run Jobs provide serverless cost-proportional ingestion with zero idle cost aligned to the medium-volume workload. BigQuery native Load Jobs and stored procedures encapsulate all merge and validation logic without additional compute infrastructure or framework expertise. Cloud Composer enforces the required historical-load validation gate and supports per-table hourly or daily scheduling. The bq_load_audit table with a Looker Studio dashboard directly satisfies the stakeholder independent-visibility requirement. The architecture is the simplest of the three options to implement, operate, extend to additional tables, and hand over to a wider team.

**Why highest score:** Option 2 scores highest because it precisely aligns tool cost to the medium-volume workload through serverless Cloud Run billing versus Dataflow per-vCPU charges in Option 1 and Datastream per-GB streaming fees in Option 3. It avoids the operational complexity of CDC binary-log management and MySQL restart risk required by Datastream in Option 3. All merge and audit logic lives in BigQuery-native SQL, maximising team familiarity and stakeholder transparency. The architecture natively supports all three required workstreams (historical load gate, scheduled incremental load, audit and monitoring) using managed GCP services with no specialised framework expertise, producing the highest operability score (9) of any option.

**Trade-offs accepted:** The fixed Cloud Composer environment cost of approximately $300-400 per month is accepted as necessary to provide DAG-level dependency management, the historical-load gate sensor, per-table schedule flexibility, and retry semantics. The GCS Parquet staging hop adds minor processing latency measured in seconds that is inconsequential against hourly or daily SLAs. If future requirements shift to sub-hourly latency or high-frequency change capture, the architecture can be augmented with Datastream for CDC ingestion into the same bq_load_audit and BigQuery storage layer without replacing the core pipeline pattern.

---

## Rejected Options

### Cloud Composer + Dataflow JDBC (Enterprise Beam Pipeline)

Despite excellent scalability headroom, Dataflow's per-vCPU pricing is disproportionate to the medium-volume workload (5 GB initial, 1 GB/month), Beam expertise requirements raise implementation and operational complexity beyond the team's likely baseline, and the 2-5 minute job spin-up is unnecessary overhead for a pipeline with hourly/daily SLAs. The weighted score of 6.20 is the lowest of the three options, driven by the cost (5) and complexity (4) dimension scores.

### Datastream CDC + BigQuery Native + Cloud Composer (Event-Driven Replication)

Datastream introduces CDC binary-log infrastructure prerequisites (binlog_format=ROW, binlog retention configuration, potential Cloud SQL instance restart) that add deployment risk and require DBA-team coordination for a pipeline explicitly classified as batch with hourly or daily SLAs. The near-real-time CDC capability is architectural over-engineering relative to the stated latency requirement and introduces per-GB streaming cost uncertainty without delivering a latency benefit the business has requested. The historical-load validation gate is harder to enforce in a continuously streaming architecture, requiring supplementary sensor and coordination logic. The weighted score of 6.75 is below Option 2 (8.10), driven by lower cost (6) and complexity (6) scores reflecting the operational overhead and cost unpredictability of the CDC approach at this data volume.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Connectivity and Credential Management | The MySQL source is accessed via a public IP (34.70.79.163:3306) using the username 'sa'. If the public IP is rotated, firewall rules change, or the credential is compromised, all Cloud Run Job executions will fail. Storing credentials as environment variables or in source code creates a credentials-exposure risk. | Migrate to Private IP connectivity via VPC peering between the Cloud Run Jobs VPC connector and the Cloud SQL instance. Create a dedicated read-only database user for the pipeline service account. Store all MySQL credentials in Secret Manager with automatic 90-day rotation and mount them as volume secrets in Cloud Run Jobs. Enable Cloud SQL IAM database authentication as the long-term replacement for password-based access. |
| Schema Drift at Source | New columns added to MySQL source tables without advance notice will cause schema mismatches between the MySQL INFORMATION_SCHEMA, the Cloud Run Job Parquet schema, and the BigQuery target table schema. Additive columns silently ignored will result in incomplete BigQuery data; breaking changes (type mutations or column drops) can silently corrupt the merge. | Implement a pre-load schema comparison step in the Cloud Run Job that classifies changes as additive (new nullable column added to MySQL: auto-provision in BigQuery via ALTER TABLE and log as WARNING to bq_load_audit) or breaking (type change, column drop, NOT NULL added: halt execution, log ERROR to bq_load_audit, and fire an immediate alert). Document this strategy in the operational runbook and obtain DBA confirmation that no breaking DDL changes will be applied to production without a pipeline-team change request. |
| Watermark Data Completeness | Incremental loads rely on the updated_date column being consistently maintained by the MySQL application layer on every record write. Direct SQL modifications that bypass the application layer will not update this column and will be silently excluded from incremental loads, causing the BigQuery target to diverge from the MySQL source without immediate detection. | Schedule a weekly full-reconciliation Cloud Run Job that compares total source row counts per table against total BigQuery target row counts and alerts on discrepancies exceeding 0.1%. Document the watermark dependency assumption with the data owner and confirm that updated_date is a system-managed column with a database-level DEFAULT CURRENT_TIMESTAMP ON UPDATE trigger. |
| Historical Load Gate Enforcement | If the historical load validation gate is misconfigured, bypassed, or the bq_load_audit flag is set incorrectly, incremental loads may begin before 100% data completeness is confirmed. A permanently incomplete BigQuery dataset with no audit record of the gap is the worst-case outcome. | Implement the gate as an Airflow ExternalTaskSensor or BranchPythonOperator that reads the historical_load_validated boolean from verizon_data_dea.bq_load_audit and pauses (not skips) the incremental DAG until it is TRUE. Require a manual two-step approval: an engineering team member sets the flag in BigQuery after row-count validation passes, and stakeholder Yash confirms acceptance via the agreed approval workflow before the incremental DAG is unpaused. |
| Operational Continuity | Cloud Composer environment failures or upgrades can block all scheduled pipeline executions during the outage window, causing SLA breaches that accumulate until the environment recovers. There is currently no documented fallback execution path. | Enable Cloud Composer high-availability mode (multi-zone scheduler and web server). Configure a dead-man Cloud Monitoring alerting policy that fires when no successful DAG run for a given table has completed within 2 times the expected schedule interval. Document an emergency manual execution procedure: a Cloud Run Job invocation via gcloud run jobs execute that can be triggered by an engineer without Composer access. |
| Security and Access Governance | The BigQuery verizon_data_dea dataset and bq_load_audit table will be accessible to stakeholders via Looker Studio. Misconfigured IAM roles could expose the target employees table (potentially containing PII) to unauthorised viewers beyond the intended stakeholder audience. | Apply column-level security policies in BigQuery on any PII columns in the employees target table. Scope Looker Studio data source credentials to a dedicated BigQuery service account with Data Viewer role restricted to bq_load_audit only. Conduct an IAM audit before go-live. If PII is confirmed present, evaluate BigQuery column masking policies in alignment with the data sensitivity classification pending clarification. |

---

## Assumptions

1. The BigQuery target project is verizon-data and the target dataset is verizon_data_dea as stated explicitly in the requirements.
2. The Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore is reachable from GCP compute resources in us-central1 via Private IP or Cloud SQL Proxy without cross-region network routing.
3. sp_mysqltobq_load is implemented as a BigQuery scripting stored procedure (invoked via CALL statement) deployed to the verizon_data_dea dataset and managed as a versioned SQL artifact in the IaC repository.
4. The composite merge key (employee_id, updated_date) uniquely identifies a record version in the source; no two source rows share the same (employee_id, updated_date) pair.
5. The 60-day retention policy is implemented via BigQuery partition expiry on the target table _PARTITIONTIME column, preserving the bq_load_audit table indefinitely with no expiry.
6. All GCP service accounts follow least-privilege IAM: the Cloud Run Job service account holds Cloud SQL Client, BigQuery Data Editor, and Storage Object Admin; the Cloud Composer service account holds Cloud Run Admin and BigQuery Job User.
7. Stakeholder Yash is granted Looker Studio Viewer access and BigQuery Data Viewer role scoped to verizon_data_dea.bq_load_audit; no direct MySQL credentials or Cloud SQL access are granted to stakeholders.
8. Terraform remote state is stored in a GCS backend bucket in the verizon-data project with versioning enabled and a dedicated state-locking service account.
9. The employees table is the only confirmed source table at the time of authoring; additional tables will follow the same parameterised Cloud Run Job and Composer DAG task pattern without architectural changes.
10. The pipeline will not be activated for incremental loads until the historical load validation gate passes and stakeholder sign-off from Yash is formally recorded.
11. MySQL credentials for user 'sa' are stored in GCP Secret Manager and injected into Cloud Run Jobs as mounted secrets; they are not stored in environment variables or source code.
12. All three SCRUM tickets (SCRUM-160, SCRUM-161, SCRUM-162) are treated as a single cohesive pipeline initiative and are addressed by this architecture decision.

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud Run Jobs selected for MySQL ingestion over Dataflow and Datastream | Support an initial data volume of 5 GB with ongoing growth of 1 GB/month | batch (hourly or daily) | 5 GB initial, 1 GB/month ongoing |
| BigQuery stored procedure sp_mysqltobq_load with MERGE on composite key (employee_id, updated_date) | Execute all load logic via stored procedure sp_mysqltobq_load.sql with merge key on employee_id and updated_date | — | — |
| Cloud Composer 2 selected for orchestration to enforce the historical-load validation gate via sensor operator | Block the incremental load pipeline from starting until full historical load validation is confirmed and passes | batch | — |
| 60-day partition expiry on BigQuery target table _PARTITIONTIME column | Enforce a 60-day data retention policy on the target BigQuery table | — | — |
| bq_load_audit permanent table with Looker Studio dashboard for stakeholder-independent visibility | Provide stakeholder-accessible dashboards or log views enabling independent review of load success and execution history without engineering involvement | — | — |
| Pre-load MySQL INFORMATION_SCHEMA vs BigQuery schema comparison in Cloud Run Job with additive/breaking classification | Perform schema validation before each load with mismatch logging and a documented strategy for handling new MySQL columns | — | — |
| Post-MERGE SQL assertion scripts writing source and target row counts to bq_load_audit after every execution | Perform row count reconciliation between MySQL and BigQuery after every load | — | — |
| Post-MERGE BigQuery SQL validation asserting no duplicate (employee_id, updated_date) pairs in target table | Confirm primary key uniqueness post-load and verify null and datatype constraints against schema definitions | — | — |
| Cloud Monitoring alerting policies on Cloud Run Job failures and BigQuery stored procedure ERROR log entries | Send alerts promptly on any pipeline failure or data quality violation | — | — |
| Parameterised Cloud Run Job and Airflow DAG task pattern to support table list expansion beyond employees | Scalability: pipeline must accommodate ongoing data growth of 1 GB/month and support all agreed-upon MySQL tables beyond the initial employees table | batch | 1 GB/month ongoing growth per additional table |

---

## Open Questions — Action Required

1. Hourly vs daily cadence per table has not been determined: the requirements state 'hourly or daily per table depending on business requirements' but do not define which tables require which cadence. This must be confirmed with Yash before Airflow schedule intervals and SLA alerting thresholds are configured.
2. The full list of MySQL source tables to be ingested has not been identified: only the employees table is confirmed. The complete table list must be agreed with the data owner before the historical load begins to ensure the 100% completeness gate is achievable and measurable.
3. Deployment environment strategy is unspecified: dev, staging, and production environments are assumed but not confirmed. A three-workspace Terraform strategy is recommended but requires confirmation to avoid deploying directly to production without a tested promotion path.
4. Data sensitivity classification is not provided: if the agentichub employees table contains PII such as names, contact details, national identifiers, or salary data, BigQuery column-level security policies and data masking rules may be required before the pipeline is activated in production.
5. MySQL credential rotation and access governance is unresolved: it is unknown whether a dedicated read-only database user exists for the pipeline or whether the 'sa' superuser credential will be used permanently. A least-privilege read-only database account should be created before production go-live.
6. The stakeholder approval workflow for the historical-load gate has no defined process: the mechanism by which Yash formally approves the transition from historical load to incremental load (Jira state change, email confirmation, manual BigQuery flag update) must be agreed to avoid the gate being bypassed informally.
7. Weekly full-reconciliation run acceptability on the Cloud SQL source has not been confirmed: the additional SELECT load on the production Cloud SQL instance during business hours may require DBA approval or scheduling during a low-activity window.
8. Latency SLA not specified: no maximum acceptable data lag from MySQL write to BigQuery availability has been defined. Without this, it is not possible to validate whether the hourly or daily cadence is sufficient, or to set meaningful Cloud Monitoring SLA-breach alerting thresholds.
