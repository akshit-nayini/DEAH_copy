# Architecture Decision Document — MySQL to BigQuery Data Ingestion Pipeline

| Field | Value |
|---|---|
| **Project** | MySQL to BigQuery Data Ingestion Pipeline |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Batch |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Cloud Composer + Cloud Run Jobs (Lightweight Python ETL)
>
> **Why:** Cloud Composer + Cloud Run Jobs achieves the highest weighted score (7.65) by optimally balancing cost efficiency, implementation simplicity, and complete functional requirement coverage. It is the lowest-cost runtime option per execution, requires no proprietary SDK expertise, and satisfies every stated functional requirement — schema validation, row-count parity checks, PK enforcement, gating, null violation logging, audit logging, stakeholder self-service dashboard, and failure alerting — as discrete, independently testable units. The pattern is operationally proven on GCP, transparent to debug, and extensible to additional tables without architectural changes.
>
> **Score:** 7.65 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2 ✅ | Option 3  |
|---|---||---||---|
| **Name** | Cloud Composer + Dataflow (Apache Beam ETL) | Cloud Composer + Cloud Run Jobs (Lightweight Python ETL) | GCP Datastream (CDC) + BigQuery Direct + Cloud Composer (Validation Gating) |
| **Pattern** | Batch | Batch | Hybrid |
| **Processing** | Cloud Dataflow (Apache Beam 2.x) | Cloud Run Jobs (Python 3.11, pandas, google-cloud-bigquery SDK) | BigQuery (native Datastream destination with auto-MERGE) |
| **Storage** | BigQuery + GCS | BigQuery + GCS | BigQuery + GCS |
| **Weighted Score** | **6.60** | **7.65**  ✅ | **6.55** |

---

## Option 1 — Cloud Composer + Dataflow (Apache Beam ETL)

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Dataflow pipeline reads MySQL employees table from Cloud SQL instance (verizon-data:us-central1:mysql-druid-metadatastore) via JDBC source I/O connector tunneled through Cloud SQL Auth Proxy on a VPC-peered connection; supports full snapshot reads and incremental PK/timestamp delta reads per schedule cadence. |
| Processing | Apache Beam pipeline performs explicit MySQL-to-BigQuery type mapping, null constraint validation, pre-load schema compatibility checks, and row-count checksums between source and sink; MERGE statements enforce PK uniqueness in the BigQuery target table after every load cycle. |
| Storage | BigQuery verizon_data_deah dataset (date-partitioned employees table, PK-clustered for dedup efficiency); GCS bucket for run audit log files, staging intermediates, and watermark state objects. |
| Consumption | BigQuery SQL for downstream analytics and reporting; Looker Studio dashboard connected to the BigQuery audit_log table and employees table for stakeholder self-service health visibility; Cloud Monitoring alerting policies on Dataflow job state transitions and failure metrics. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Dataflow (JDBC Source I/O + Cloud SQL Auth Proxy) | — | Yes |
| Processing | Cloud Dataflow (Apache Beam 2.x) | — | Yes |
| Storage | BigQuery + GCS | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging | — | Yes |
| Iac | Terraform (google provider) | — | No |

### Pros

- Fully managed, autoscaling pipeline handles unknown and growing data volumes without re-architecture
- Native BigQuery sink with built-in schema detection and optimized batch write throughput
- Beam-native DoFn transforms integrate row-count validation, null checks, and type-mapping cleanly into the pipeline graph
- Horizontal scalability supports adding additional MySQL tables with minimal configuration change to the existing Beam pipeline
- Rich Cloud Monitoring integration: Dataflow emits worker-level, job-level, and custom metrics natively

### Cons

- Dataflow worker cold-start latency (2-4 minutes) adds overhead to hourly load cycles and compresses the processing window
- Apache Beam SDK requires specialized engineering knowledge; steepest ramp-up cost of all three options
- Most expensive per-run option at low volume due to combined Dataflow worker + Cloud Composer environment cost
- JDBC connector for Cloud SQL requires custom container packaging and dependency management with no official Google-managed Dataflow template for Cloud SQL MySQL
- Architecturally over-specified for a single employees table at unquantified, likely small-to-medium volume

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | JDBC type coercion between MySQL and BigQuery requires an explicit type mapping layer; unmapped or exotic types silently truncate or cause runtime failures if not pre-validated in the schema compatibility check. |
| Scaling | Dataflow autoscaling responds to volume spikes but introduces variable, uncapped cost; without a volume baseline, the monthly cost ceiling is undefined and could spike significantly on backfill runs. |
| Latency | Worker cold-start adds 2-4 minutes to each scheduled run, potentially compressing the usable processing window for tight hourly cadences with large table volumes. |
| Cost | Dataflow plus Composer combined fixed and variable costs represent the highest baseline spend of all options; without volume data, the total monthly cost is unforecastable and may be difficult to justify for a single-table workload. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 9 | 5 | 7 | 8 | **6.60** |

---

## Option 2 — Cloud Composer + Cloud Run Jobs (Lightweight Python ETL) ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 DAG triggers a parameterized Cloud Run Job that connects to Cloud SQL (verizon-data:us-central1:mysql-druid-metadatastore) via the Cloud SQL Auth Proxy sidecar over a private VPC IP; the job reads the employees table using SQLAlchemy with a configurable timestamp or primary-key delta watermark persisted to a GCS state file between runs. |
| Processing | Within the Cloud Run Job container, a Python ETL module (1) validates schema compatibility by diffing MySQL INFORMATION_SCHEMA against BigQuery table schema — detecting type mismatches, new columns, and null constraint violations before load; (2) executes the BigQuery load job via the google-cloud-bigquery client; (3) runs post-load SQL assertions including row-count parity between MySQL source and BigQuery target and PK uniqueness enforcement via a MERGE or DISTINCT dedup query. |
| Storage | BigQuery verizon_data_deah dataset (date-partitioned employees table, clustered on primary key); GCS bucket for watermark state files (with Object Versioning enabled for rollback) and structured JSON audit log archives; Cloud Logging for structured per-run execution metadata and alert integration. |
| Consumption | Looker Studio dashboard connected to a BigQuery audit_log table (populated by each run with status, row counts, schema diff results, and timestamps) for stakeholder self-service health visibility with no developer involvement; Cloud Monitoring log-based alerting policies on Cloud Run Job failure exit codes and custom structured log metrics; BigQuery for downstream analytics and reporting queries. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Run Jobs + Cloud SQL Auth Proxy (SQLAlchemy) | — | Yes |
| Processing | Cloud Run Jobs (Python 3.11, pandas, google-cloud-bigquery SDK) | — | Yes |
| Storage | BigQuery + GCS | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio | — | Yes |
| Iac | Terraform (google provider) | — | No |

### Pros

- Lowest per-run cost: Cloud Run Jobs bill only for vCPU and memory consumed during execution with zero idle cost between scheduled runs
- Simplest implementation path: standard Python libraries (SQLAlchemy, google-cloud-bigquery) with no proprietary SDK or Beam programming model required
- All functional requirements — schema checks, row-count validation, PK enforcement, null violation logging, audit logging, new-column handling, gating, and stakeholder dashboard — are implementable as discrete, independently testable Python functions
- Cloud Composer DAG provides explicit, auditable gating: the incremental load DAG cannot be activated until a sign-off sensor task in the historical load DAG passes, satisfying the gate requirement exactly
- Looker Studio over the BigQuery audit_log table delivers stakeholder self-service visibility with no developer involvement after initial setup
- Container-based execution is portable, version-pinnable, and independently testable outside GCP using Docker and a local MySQL instance

### Cons

- Single-container execution model limits parallelism; very large table loads require chunked pagination logic within the job to avoid memory ceiling (32 GB max on Cloud Run Jobs)
- GCS watermark state file introduces a failure mode: corrupt or missing state file causes the next run to default to a full reload or skip records silently without integrity checks
- Ongoing Python code maintenance is required as MySQL schema evolves, whereas managed CDC approaches handle schema propagation automatically
- Cloud Composer is the dominant fixed cost driver at approximately $400-800 per month; cost-justified only if the environment is shared with other organizational pipelines
- Fan-out to many tables requires DAG-level parallelism design in Composer, adding orchestration complexity as table count grows beyond a handful

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Watermark drift due to clock skew between MySQL server time and the Cloud Run Job execution environment can cause records near the boundary timestamp to be missed in incremental loads; mitigated by a configurable overlap window that re-reads the last N minutes of the previous watermark interval. |
| Scaling | A single Cloud Run Job container handles one table per execution; scaling to many additional MySQL tables requires parallel job executions orchestrated via Composer DAG fan-out, which is achievable but requires explicit DAG design investment. |
| Latency | Cloud Run Job cold start is under 30 seconds; the total load cycle time is well within both hourly and daily batch SLAs. No latency risk for the stated requirements at unquantified small-to-medium volume. |
| Cost | Cloud Composer environment fixed cost (~$400-800/month) dominates the total pipeline cost regardless of run frequency. If this pipeline is the sole Composer consumer, the cost-per-load-cycle is disproportionate and Cloud Scheduler should be evaluated as a replacement orchestrator. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 7 | 8 | 8 | 7 | **7.65** |

---

## Option 3 — GCP Datastream (CDC) + BigQuery Direct + Cloud Composer (Validation Gating)

**Pattern:** Hybrid

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | GCP Datastream reads the MySQL binary log (binlog) from the Cloud SQL instance via private connectivity profile; the initial historical full load is executed via Datastream's built-in backfill/snapshot mode, which eliminates the need for a separate historical load pipeline. Subsequent incremental changes are streamed continuously from the binlog. |
| Processing | Datastream writes CDC events directly to BigQuery using the native BigQuery destination, where upserts are handled automatically via Datastream-managed MERGE operations — no intermediate processing code is required. Cloud Composer DAG executes validation tasks after the backfill completes: row-count parity assertion, PK uniqueness check, null violation log scan, and audit log write; the Composer gating task pauses Datastream stream activation until sign-off succeeds. |
| Storage | BigQuery verizon_data_deah dataset (Datastream-managed employees table with system _metadata columns for change tracking); GCS bucket for Datastream staging and audit log archives; Cloud Logging for structured per-event and per-validation run metadata. |
| Consumption | Cloud Monitoring for Datastream replication health, throughput, and latency metrics; Looker Studio connected to BigQuery (with _metadata columns filtered via a semantic view layer) for stakeholder self-service dashboard; BigQuery for downstream analytics and reporting. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | GCP Datastream (MySQL CDC via binlog, private connectivity) | — | Yes |
| Processing | BigQuery (native Datastream destination with auto-MERGE) | — | Yes |
| Storage | BigQuery + GCS | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging | — | Yes |
| Iac | Terraform (google provider) | — | No |

### Pros

- Near-real-time CDC replication (sub-minute latency) substantially exceeds the stated hourly and daily SLA, providing maximum latency headroom for future tightening
- Datastream built-in backfill/snapshot mode handles the historical full load natively without a separate pipeline, reducing implementation surface area
- Zero-ETL processing path: Datastream writes directly to BigQuery with auto-MERGE; no custom transformation code is required for the replication path
- Automatic schema evolution propagation via Datastream's schema change handling reduces maintenance burden as new columns are added to MySQL
- Datastream-to-BigQuery is a fully managed, Google-supported integration with SLA-backed availability

### Cons

- Requires MySQL binary logging (binlog) enabled on the Cloud SQL instance with ROW format and FULL row image — a DBA-level configuration change that increases Cloud SQL storage consumption and requires instance restart in some configurations
- Datastream pricing (per GB of data processed) is unpredictable without a volume and change-rate baseline; high-velocity UPDATE workloads can make Datastream significantly more expensive than batch ETL
- The historical load gating requirement (incremental must not activate until validation sign-off) directly conflicts with Datastream's continuous streaming model, requiring custom Composer-based stream pause and resume logic that negates the zero-ETL simplicity advantage
- Datastream _metadata system columns (_metadata_timestamp, _metadata_deleted, etc.) pollute the BigQuery table schema; all downstream consumers must filter them explicitly via views, adding a semantic layer dependency
- Row-count validation between MySQL and BigQuery is non-trivial with CDC: Datastream replication lag means counts transiently diverge, requiring retry and convergence logic in the Composer validation task

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | CDC event ordering depends on MySQL binlog sequence numbers; failover events, binlog rotation, or Cloud SQL maintenance windows can introduce replication gaps that require a manual Datastream stream reset and partial backfill to recover. |
| Scaling | Datastream scales with change event volume rather than table size; a large batch UPDATE or DELETE statement on MySQL generates a proportionally large CDC event burst that may cause Datastream backpressure and transient replication lag. |
| Latency | Datastream delivers sub-minute latency, which is strongly positive for the stated requirement. However, the gating requirement introduces deliberate controlled latency on first incremental activation pending historical validation sign-off. |
| Cost | Per-GB Datastream pricing without a change-rate baseline creates unforecastable monthly cost; combined with the Cloud Composer environment, this option may exceed Option 2 total cost by 2-3x for tables with high UPDATE/DELETE velocity. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 8 | 5 | 9 | 7 | **6.55** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Dataflow (Apache Beam ETL) | 5 | 9 | 5 | 7 | 8 | **6.60** |
| Cloud Composer + Cloud Run Jobs (Lightweight Python ETL) ✅ | 8 | 7 | 8 | 8 | 7 | **7.65** |
| GCP Datastream (CDC) + BigQuery Direct + Cloud Composer (Validation Gating) | 5 | 8 | 5 | 9 | 7 | **6.55** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Composer + Cloud Run Jobs (Lightweight Python ETL)**
**Weighted Score: 7.65**

**Justification:** Cloud Composer + Cloud Run Jobs achieves the highest weighted score (7.65) by optimally balancing cost efficiency, implementation simplicity, and complete functional requirement coverage. It is the lowest-cost runtime option per execution, requires no proprietary SDK expertise, and satisfies every stated functional requirement — schema validation, row-count parity checks, PK enforcement, gating, null violation logging, audit logging, stakeholder self-service dashboard, and failure alerting — as discrete, independently testable units. The pattern is operationally proven on GCP, transparent to debug, and extensible to additional tables without architectural changes.

**Why highest score:** Option 2 outscores Option 1 on cost (+3 points) and complexity (+3 points) while matching it on latency and nearly matching on operability — a decisive advantage given that cost (weight 0.30) and complexity (weight 0.20) together account for 50% of the total weighted score. Option 2 outscores Option 3 on cost (+3 points) and complexity (+3 points) while conceding only 1 point each on latency and scalability — dimensions weighted at 0.15 and 0.25 respectively, insufficient to overcome the 50% combined cost-complexity lead. The winner is determined by the alignment of Option 2's strongest dimensions with the highest-weight scoring categories.

**Trade-offs accepted:** Lower raw scalability score (7 vs. 9 for Dataflow) is accepted because: (a) data volume is unquantified and presumed small-to-medium for a single employees table — the regime where Cloud Run Jobs excel; (b) Cloud Run Jobs can be parallelized via Composer DAG fan-out if the table inventory grows significantly; and (c) migration to Dataflow is a well-defined upgrade path if sustained load volume crosses 50 GB per run. Watermark state management risk is accepted with a documented mitigation strategy (overlap window, GCS Object Versioning, integrity checksum at job start).

---

## Rejected Options

### Cloud Composer + Dataflow (Apache Beam ETL)

Despite best-in-class scalability (score 9), the Dataflow stack carries the highest engineering complexity and cost of all options. For a single-table batch pipeline at unquantified volume, the per-run Dataflow overhead and Beam SDK expertise requirement are disproportionate to the problem. Cloud Run Jobs (Option 2) satisfies every functional requirement with a simpler implementation, lower cost, and equivalent data correctness guarantees. Dataflow should be re-evaluated if table count exceeds 10 or sustained load volume exceeds 50 GB per run cycle.

### GCP Datastream (CDC) + BigQuery Direct + Cloud Composer (Validation Gating)

Datastream CDC is architecturally over-specified for a scheduled batch requirement (hourly or daily cadence). The binlog prerequisite introduces an operational dependency on DBA-level Cloud SQL configuration, which adds deployment risk and timeline uncertainty. The historical load gating requirement conflicts structurally with Datastream's continuous streaming model, necessitating custom Composer-based stream pause and resume orchestration that eliminates the zero-ETL simplicity advantage entirely. Row-count validation with transient CDC lag further complicates the post-load validation requirement. Option 2 satisfies all functional requirements with lower cost, lower implementation complexity, and lower operational risk. Datastream should be reconsidered if: (a) the latency SLA tightens to sub-minute, (b) the Cloud SQL instance already has binlog enabled, or (c) the use case expands to multiple high-frequency tables where continuous CDC becomes operationally superior to scheduled batch extraction.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Data Volume Uncertainty | No row count or byte volume was provided for the MySQL employees table. All compute tier selections, cost estimates, and chunking strategy recommendations are contingent on the actual volume being small-to-medium. If volume exceeds 50 GB per load cycle, the Cloud Run Job memory ceiling (32 GB) may be reached without chunked pagination. | Instrument the first historical full load with explicit row count and byte volume logging to Cloud Logging. If volume exceeds 50 GB, implement chunked pagination with configurable page size in the Cloud Run Job, or re-evaluate migration to Dataflow (Option 1) for autoscaling processing. |
| Watermark State Integrity | Incremental load correctness depends on a GCS-persisted watermark state file storing the last successfully processed timestamp or primary key. File corruption, accidental deletion, or write failure causes the next run to either miss records (if state reads as advanced) or trigger a full reload (if state reads as missing). | Enable GCS Object Versioning on the watermark state bucket for rollback capability. Implement a checksum integrity check at Cloud Run Job startup that validates the state file before reading its value. Define an explicit recovery runbook for state file corruption that triggers a bounded historical re-load from the last known good watermark. |
| Schema Evolution | New columns added to the MySQL employees table without advance notification will be encountered at load time. Without an explicit pre-load schema diff check, the load job may fail on NOT NULL columns without defaults or silently drop new nullable columns not yet present in the BigQuery target schema. | Implement a mandatory pre-load schema diff task in the Cloud Run Job that compares MySQL INFORMATION_SCHEMA.COLUMNS against the BigQuery table schema. Auto-add new nullable columns to BigQuery before load; for new NOT NULL columns, configure a default value strategy and alert to the stakeholder; halt and alert on data type conflicts. |
| SLA Definition Gap | The requirement specifies that monitoring alerts must trigger on pipeline failures within a defined SLA, but no specific SLA duration (e.g., 15 minutes, 30 minutes) is quantified. Cloud Monitoring alerting policies cannot be configured without a concrete threshold value. | Conduct a stakeholder alignment session with Yash and the analytics team to agree on and document the failure alerting SLA before production deployment. Configure Cloud Monitoring alerting policies with the agreed threshold and document the agreed SLA in the pipeline runbook. |
| Cloud Composer Cost Concentration | Cloud Composer 2 is the dominant fixed cost in the recommended architecture, estimated at $400-800 per month regardless of run frequency. If this pipeline is the sole consumer of the Composer environment, the per-run cost is disproportionate to the workload complexity. | Confirm whether the Composer environment will be shared with other organizational pipelines. If dedicated, evaluate replacing Cloud Composer with Cloud Scheduler (triggering Cloud Run Jobs directly) for orchestration; implement Composer-equivalent gating logic via Cloud Run Job exit code chaining and Cloud Scheduler one-time triggers for historical validation sign-off. |
| Cloud SQL Connectivity Failure Mode | Pipeline connectivity to Cloud SQL depends on Cloud SQL Auth Proxy configuration, service account IAM bindings, and VPC Serverless Access connector availability. Misconfiguration or transient Auth Proxy failures may produce empty loads rather than explicit errors if the connection failure is not caught early. | Add an explicit Cloud SQL connectivity health check as the first step of every Cloud Run Job execution. Configure the job to fail fast with a structured error log entry and non-zero exit code if the Cloud SQL connection cannot be established within a configurable timeout (default: 30 seconds). Map this exit code to a Cloud Monitoring alert. |
| Historical Load Gating Bypass | If the Composer DAG gating mechanism is misconfigured or the historical load DAG sign-off task is manually overridden, the incremental pipeline could activate before the historical load is fully validated, leading to duplicate or incomplete data in BigQuery. | Implement the gating as a dual control: (1) the incremental DAG is deployed in a paused state and activated only via an explicit Airflow DAG unpause step within the historical load DAG after sign-off task success; (2) the incremental job first-run checks for the existence of a GCS sign-off marker file before executing any load, halting and alerting if the marker is absent. |

---

## Assumptions

1. The MySQL employees table resides on a GCP Cloud SQL instance (verizon-data:us-central1:mysql-druid-metadatastore) accessible from the pipeline service account via Cloud SQL Auth Proxy using the Cloud SQL Client IAM role.
2. Data volume per load cycle is assumed small-to-medium (under 50 GB) based on a single employees table with no explicit row count or volume provided in requirements; this assumption governs compute tier selection.
3. The employees table contains at least one monotonically increasing timestamp column (e.g., updated_at or created_at) or a sequential integer primary key suitable for delta-based incremental load watermarking.
4. BigQuery dataset verizon_data_deah exists in the target GCP project or will be provisioned as part of IaC prior to first pipeline execution.
5. Cloud Composer 2 will be a shared environment serving other organizational DAGs to amortize its fixed monthly cost; if this pipeline is the sole consumer, Cloud Scheduler is the recommended cost-reduction alternative for orchestration.
6. Stakeholder Yash will have read-only IAM access to the Looker Studio dashboard and the BigQuery audit_log table; no BigQuery editor, developer console, or pipeline access is required for monitoring and reporting.
7. The historical full load gating requirement is enforced as an Airflow DAG dependency: the incremental load DAG remains in a paused state and is activated only after a dedicated sign-off sensor task in the historical load DAG returns success.
8. No PII, PHI, or regulated data classification has been applied to the employees table; standard GCP IAM, VPC Service Controls, and CMEK are sufficient without additional column-level masking unless classification is confirmed.
9. Terraform state will be stored in a GCS backend bucket within the same GCP project with state locking enabled via a Cloud Spanner or GCS lock.
10. The Cloud SQL instance's private IP (34.70.79.163) is reachable from the Cloud Run Job execution environment via VPC peering or Serverless VPC Access connector configured for the Cloud Run service.
11. MySQL schema for the employees table follows standard relational conventions; no JSON columns, spatial types, or non-standard MySQL storage engines (e.g., MyISAM) are present that would require special-case type mapping.

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud Run Jobs selected as the processing compute tier over Dataflow and Datastream | Design and implement a reliable and scalable pipeline to load MySQL tables into BigQuery on a scheduled basis, supporting both one-time full historical load and ongoing scheduled incremental loads | hourly or daily | — |
| Cloud Composer 2 selected for orchestration with explicit DAG dependency gating between historical and incremental DAGs | Gate incremental load activation: incremental pipeline must not begin until historical load validation is fully passed and signed off | — | — |
| Timestamp-based or primary-key delta watermark with configurable overlap window for incremental load strategy | Track incremental changes using timestamp-based or primary key delta strategies, consistently applied across all runs; prevent data duplication and gaps across all incremental load cycles | hourly or daily | — |
| Pre-load schema diff check implemented as first task in Cloud Run Job comparing MySQL INFORMATION_SCHEMA to BigQuery schema | Perform pre-load schema compatibility checks covering data types, null handling, field names, and new column handling strategy before each load execution | — | — |
| Post-load row count SQL assertion comparing MySQL source count to BigQuery target count executed as final Cloud Run Job task | Perform post-load row count validation between MySQL source and BigQuery target for every load cycle | — | — |
| PK uniqueness enforcement via BigQuery MERGE or SELECT DISTINCT dedup query executed after every load cycle | Enforce primary key uniqueness in BigQuery after every load execution | — | — |
| Auto-add new nullable BigQuery columns strategy; halt and alert on NOT NULL or type conflict columns before load execution | Define and implement a predefined handling strategy for new columns appearing in MySQL before they are loaded into BigQuery | — | — |
| Structured JSON audit log written to BigQuery audit_log table per run with status, row counts, schema diff results, and execution timestamp | Generate and store audit logs for every load execution, accessible after each run | — | — |
| Looker Studio dashboard over BigQuery audit_log table selected for stakeholder self-service monitoring | Implement a monitoring dashboard or log-based visibility layer enabling stakeholders to independently review load success without developer involvement | — | — |
| Cloud Monitoring log-based alerting policies on Cloud Run Job non-zero exit codes for failure notification | Trigger monitoring alerts on pipeline failures within a defined SLA | — | — |
| Null constraint violation scan executed as a named pre-completion task in the Cloud Run Job before writing the audit log success record | Log and report null constraint violations before marking any load as complete | — | — |
| Execute historical full load as a standalone Composer DAG with explicit 100% row count validation before activating incremental DAG | Execute a one-time full historical load of the MySQL employees table into BigQuery with 100% data completeness and no data loss | — | — |

---

## Open Questions — Action Required

1. What is the approximate row count and byte size of the MySQL employees table? This is the most critical missing input — it directly determines whether Cloud Run Jobs (under 50 GB) or Dataflow (over 50 GB) is the correct compute tier and whether cost estimates can be produced.
2. What is the quantified SLA for monitoring alert triggers on pipeline failure — for example, alert within 15 minutes, 30 minutes, or 1 hour of job failure? This is required to configure Cloud Monitoring alerting policies and cannot be inferred from requirements.
3. Does the MySQL employees table have an updated_at or equivalent server-side timestamp column that is reliably updated on every INSERT and UPDATE? If absent, the incremental strategy must rely solely on primary key delta, which cannot detect in-place updates to existing rows.
4. What GCP project ID hosts the BigQuery verizon_data_deah dataset and what project hosts the Cloud SQL instance? If these are different projects, cross-project IAM bindings and VPC peering or Shared VPC configurations must be provisioned.
5. Will the Cloud Composer 2 environment be shared with other organizational pipelines, or is it dedicated to this workload? The answer determines whether Composer cost is justified or whether Cloud Scheduler should replace it as the orchestrator.
6. What is the historical load sign-off process — automated (row count match equals auto-approve and incremental DAG auto-activates) or manual (Yash reviews audit log and triggers approval via a UI, email confirmation, or notification)? This defines the gating DAG task implementation.
7. What is the data sensitivity classification of the employees table? If the table contains PII fields (names, contact details, salary, national identifiers), column-level encryption, BigQuery Authorized Views, or VPC Service Controls will need to be added to the architecture.
8. Is binary logging (binlog) currently enabled on the Cloud SQL MySQL instance? This is not required for the recommended option but is a prerequisite if Datastream CDC is considered for future migration to a lower-latency replication model.
9. Are there additional MySQL tables beyond employees in scope for this pipeline, either now or in the near future? The answer affects DAG fan-out design, naming conventions, and whether the single-container Cloud Run Job model is sufficient or requires a factory pattern.
