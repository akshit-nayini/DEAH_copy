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

> **Build with:** Cloud Composer + Native Airflow Operators + GCS Staging + BigQuery MERGE
>
> **Why:** Option 1 achieves the highest weighted score of 7.70 by delivering the optimal balance of cost efficiency, operational simplicity, and alignment with the stakeholder-mandated toolchain. It uses Cloud Composer and native Airflow providers as explicitly preferred, requires no additional managed services, and satisfies every functional requirement — chunked historical load with retry logic, incremental MERGE via stored procedure, historical sign-off gate, pre- and post-load data quality assertions, audit logging, and 60-day BigQuery retention — entirely within the declared technology stack and within the sprint 14 timeline constraint.
>
> **Score:** 7.70 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1 ✅ | Option 2  | Option 3  |
|---|---||---||---|
| **Name** | Cloud Composer + Native Airflow Operators + GCS Staging + BigQuery MERGE | Cloud Composer + Dataflow JDBC Flex Template + BigQuery MERGE | Cloud Composer + Custom PythonOperator + BigQuery Storage Write API Direct Ingest |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | BigQuery — MERGE stored procedure sp_mysqltobq_load.sql + BigQuery SQL assertion tasks via BigQueryInsertJobOperator | Dataflow (Apache Beam parallel workers) + BigQuery MERGE stored procedure sp_mysqltobq_load.sql | BigQuery Storage Write API (COMMITTED mode) + BigQuery MERGE stored procedure sp_mysqltobq_load.sql |
| **Storage** | Google Cloud Storage (staging, 1-day lifecycle) + BigQuery native table verizon_data_dea.employees (60-day partition expiry) | Google Cloud Storage (Dataflow managed temp) + BigQuery native table verizon_data_dea.employees (60-day partition expiry) | BigQuery native table verizon_data_dea.employees (60-day partition expiry) — no GCS staging |
| **Weighted Score** | **7.70**  ✅ | **6.65** | **6.60** |

---

## Option 1 — Cloud Composer + Native Airflow Operators + GCS Staging + BigQuery MERGE ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 DAG triggers MySQLToGCSOperator (apache-airflow-providers-google) to perform chunked reads from Cloud SQL MySQL instance verizon-data:us-central1:mysql-druid-metadatastore, database agentichub, table employees; historical load uses configurable page_size (100,000 rows per chunk) to produce partitioned CSV/Avro files written to GCS staging bucket gs://verizon-data-etl-staging/employees/; incremental loads apply WHERE updated_date > last_successful_run watermark with identical chunking strategy; Airflow retry policies with exponential backoff are applied at the operator level |
| Processing | GCSToBigQueryOperator loads GCS staged files into transient BigQuery staging table verizon_data_dea.employees_staging; BigQuery stored procedure sp_mysqltobq_load.sql executes MERGE on composite key (employee_id, updated_date) from staging into target verizon_data_dea.employees; sequential post-load Airflow tasks execute BigQuery SQL assertions for zero-tolerance row count reconciliation against MySQL source count, primary key uniqueness enforcement, null and datatype constraint validation, and schema drift detection; an audit log record is written to verizon_data_dea.pipeline_audit_log on every execution regardless of outcome |
| Storage | GCS staging bucket with 1-day lifecycle auto-deletion policy; BigQuery target table verizon_data_dea.employees with 60-day partition expiry enforced via partitionExpirationMs; BigQuery audit table verizon_data_dea.pipeline_audit_log for full execution history; Airflow Variable historical_load_signoff_status used as programmatic sign-off gate blocking incremental DAG activation |
| Consumption | BigQuery for direct SQL analytics and ad-hoc reporting by the 5gcore programme; Looker Studio dashboards surfacing pipeline_audit_log for stakeholder self-service visibility without engineering assistance; Cloud Logging for immutable audit trail; Cloud Monitoring dashboards for operational pipeline health |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Composer 2 — MySQLToGCSOperator (apache-airflow-providers-google) | 2.x | Yes |
| Processing | BigQuery — MERGE stored procedure sp_mysqltobq_load.sql + BigQuery SQL assertion tasks via BigQueryInsertJobOperator | — | Yes |
| Storage | Google Cloud Storage (staging, 1-day lifecycle) + BigQuery native table verizon_data_dea.employees (60-day partition expiry) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + BigQuery audit table verizon_data_dea.pipeline_audit_log | — | Yes |
| Iac | Terraform (hashicorp/google provider) | >=1.5 | No |

### Pros

- Directly aligns with the stakeholder-mandated toolchain: Cloud Composer and native Apache Airflow providers with zero additional managed services required
- MySQLToGCSOperator natively supports page_size-based chunked reads, satisfying the 5 GB historical load batching and timeout-prevention requirement without custom code
- Native Airflow operator retry configuration (retries, retry_delay, retry_exponential_backoff) satisfies the retry logic requirement declaratively at the operator level
- GCS staging physically decouples extraction from loading: each stage can be independently retried without re-reading MySQL, improving fault tolerance
- Historical sign-off gate is cleanly implemented as a ShortCircuitOperator checking the Airflow Variable historical_load_signoff_status at the start of the incremental DAG
- Lowest total cost of ownership: no additional serverless compute services beyond the existing Cloud Composer environment and BigQuery
- Highest operability score: native Airflow task logs, Airflow UI task-level audit trail, and Cloud Monitoring deliver complete observability with minimal configuration overhead
- All data quality requirements — schema validation, row count reconciliation, PK uniqueness, null/type checks, audit logging — are implementable as lightweight BigQuery SQL tasks within the DAG without any custom libraries
- Well-understood, battle-tested ingestion pattern with extensive GCP documentation, provider support, and community knowledge base

### Cons

- GCS intermediate staging introduces an additional storage hop and 2 to 5 minutes of latency per execution compared to direct-write alternatives
- Page-based LIMIT/OFFSET chunking on MySQL degrades at very high row counts due to MySQL full offset scan cost; acceptable at current volume but requires monitoring as data grows
- GCS staging files require explicit lifecycle management policy to prevent unbounded storage accumulation if lifecycle rule misconfiguration occurs
- Schema drift detection must be explicitly coded as a pre-load Airflow task; there is no automatic schema mismatch prevention built into MySQLToGCSOperator
- Airflow worker container memory constrains maximum viable chunk size; very wide employee table schemas may require careful page_size tuning to avoid worker OOMKill

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | LIMIT/OFFSET chunking on MySQL can produce row gaps or duplicates if records are inserted or updated mid-extraction run; mitigated by anchoring incremental extractions to a consistent updated_date watermark snapshot and enforcing zero-tolerance post-load row count reconciliation between MySQL COUNT(*) and BigQuery COUNT(*) as a hard DAG failure gate |
| Scaling | At 1 GB/month growth, total volume reaches approximately 17 GB at end of year one, which remains well within Cloud Composer and BigQuery operational limits with no architectural changes required; page_size tuning may be needed beyond 100 GB total volume but is a configuration change, not an architectural one |
| Latency | Daily 2 AM batch scheduling is well-suited to this pattern; GCS staging adds 2 to 5 minutes per execution but remains within the available overnight batch window; Cloud Monitoring alerting is configured to fire within the defined SLA on any DAG task failure or missed schedule |
| Cost | Cloud Composer environment is a fixed background cost; incremental per-execution cost is dominated by BigQuery query bytes processed and GCS class-A operation charges; 60-day retention policy enforced via partition expiry bounds BigQuery storage cost; estimated monthly incremental cost remains low given 1 GB/month volume growth |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 7 | 8 | 7 | 9 | **7.70** |

---

## Option 2 — Cloud Composer + Dataflow JDBC Flex Template + BigQuery MERGE

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 DAG triggers Dataflow Flex Template job (JdbcToBigQuery) via DataflowStartFlexTemplateOperator; Dataflow uses Cloud SQL Auth Proxy sidecar and JDBC driver to connect to agentichub.employees; for the historical load, Dataflow auto-partitions reads using employee_id range splits across configurable parallel workers to handle 5 GB without timeout risk; incremental loads pass a time-bound WHERE updated_date > watermark parameter to the Flex Template at runtime |
| Processing | Dataflow workers write extracted rows to BigQuery staging table verizon_data_dea.employees_staging via BigQuery Storage Write API; Cloud Composer subsequent tasks execute BigQuery stored procedure sp_mysqltobq_load.sql for MERGE on composite key (employee_id, updated_date); BigQuery SQL assertion tasks in the DAG perform zero-tolerance row count reconciliation, PK uniqueness validation, null and type constraint checks, and audit log record insertion into verizon_data_dea.pipeline_audit_log |
| Storage | Dataflow-managed GCS temp bucket auto-cleaned post-job completion; BigQuery target table verizon_data_dea.employees with 60-day partition expiry; BigQuery staging table truncated after successful MERGE; BigQuery audit table for execution records |
| Consumption | BigQuery for analytics queries; Looker Studio for stakeholder reporting dashboards; Cloud Monitoring plus Dataflow UI for detailed operational observability; Cloud Logging for immutable audit trail |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataflow Flex Template (JdbcToBigQuery) via Cloud Composer DataflowStartFlexTemplateOperator | Beam 2.50+ | Yes |
| Processing | Dataflow (Apache Beam parallel workers) + BigQuery MERGE stored procedure sp_mysqltobq_load.sql | Beam 2.50+ | Yes |
| Storage | Google Cloud Storage (Dataflow managed temp) + BigQuery native table verizon_data_dea.employees (60-day partition expiry) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Dataflow Monitoring UI + Cloud Logging + BigQuery audit table | — | Yes |
| Iac | Terraform (hashicorp/google provider) | >=1.5 | No |

### Pros

- Dataflow auto-scales parallel workers for the 5 GB historical load, providing higher extraction throughput and faster job completion than sequential chunked operators
- Built-in Dataflow shuffle service, auto-retry, and fault-tolerant execution eliminate the need to implement custom retry logic for the extraction stage
- Dataflow parallel range-based splitting on employee_id avoids the MySQL OFFSET scan performance degradation that page-based chunking incurs at high row counts
- Architecturally future-proof: as employee data grows well beyond the current volume, Dataflow scales horizontally by adding workers without any pipeline code changes
- Dataflow Monitoring UI provides granular per-step throughput metrics, bottleneck identification, and data staleness visibility beyond what Airflow task logs expose

### Cons

- Dataflow worker cold start adds 3 to 5 minutes of overhead per execution, which is unnecessary and wasteful for daily 1 GB incremental loads of structured relational data
- Substantially higher cost than Option 1 at medium volume: Dataflow n1-standard workers are billed per vCPU-hour including spin-up time, creating significant per-run cost for small daily increments
- JdbcToBigQuery Flex Template requires JDBC driver JAR packaging, Flex Template container image maintenance, and Artifact Registry management — significant additional operational surface area
- Increased operational complexity: engineers must be proficient in both Airflow DAG debugging and Dataflow pipeline diagnostics to resolve production incidents
- Architecturally disproportionate to the problem scale: enterprise-grade distributed compute infrastructure applied to a single structured table at medium volume

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Dataflow parallel reads may interleave with live MySQL writes during extraction; employee_id range split boundaries must be validated to prevent row gaps; mitigated by anchoring extraction to updated_date watermark and enforcing post-load zero-tolerance row count reconciliation as a hard DAG failure gate |
| Scaling | Dataflow scales to petabyte volumes; no scaling risk exists at projected employee data volumes; worker count and machine type must be right-sized via Terraform to avoid chronic over-provisioning cost |
| Latency | Dataflow Flex Template cold start adds 3 to 5 minutes per execution; this is acceptable within the overnight 2 AM batch window but must be accounted for in SLA calculations; Flex Template startup is consistently slower than Classic Template startup |
| Cost | Daily Dataflow worker charges for 1 GB incremental loads will substantially exceed the equivalent Cloud Composer operator execution cost; cost must be monitored via Cloud Billing budget alerts and right-sizing reviews |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 9 | 5 | 8 | 7 | **6.65** |

---

## Option 3 — Cloud Composer + Custom PythonOperator + BigQuery Storage Write API Direct Ingest

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 DAG executes a custom PythonOperator using mysql-connector-python to establish a Cloud SQL Auth Proxy connection to agentichub.employees; historical load reads data in configurable chunks using keyset pagination on employee_id (SELECT * WHERE employee_id > last_key LIMIT chunk_size) to avoid OFFSET scan degradation; each chunk is serialised and written directly to BigQuery via the Storage Write API client library in COMMITTED mode without GCS staging; incremental loads query with WHERE updated_date > watermark |
| Processing | In-operator pre-write schema validation checks field names, Python types, and null constraints against a registered schema definition before each batch write; after all chunks are committed, a BigQuery stored procedure sp_mysqltobq_load.sql executes MERGE on composite key (employee_id, updated_date) on the staging-to-target tables; subsequent Airflow tasks run BigQuery SQL for zero-tolerance row count reconciliation, PK uniqueness enforcement, and audit log record insertion into verizon_data_dea.pipeline_audit_log |
| Storage | No GCS intermediate staging; BigQuery Storage Write API committed stream writes directly to verizon_data_dea.employees_staging; BigQuery target table verizon_data_dea.employees with 60-day partition expiry; BigQuery audit table for execution records |
| Consumption | BigQuery for analytics and reporting; Cloud Monitoring for pipeline health and alerting; Cloud Logging for immutable audit trail; Looker Studio for stakeholder dashboards |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Composer 2 PythonOperator (mysql-connector-python + google-cloud-bigquery-storage client library) | Python 3.11 / Airflow 2.x | No |
| Processing | BigQuery Storage Write API (COMMITTED mode) + BigQuery MERGE stored procedure sp_mysqltobq_load.sql | — | Yes |
| Storage | BigQuery native table verizon_data_dea.employees (60-day partition expiry) — no GCS staging | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | 2.x | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + BigQuery audit table verizon_data_dea.pipeline_audit_log | — | Yes |
| Iac | Terraform (hashicorp/google provider) | >=1.5 | No |

### Pros

- Eliminates the GCS staging hop entirely: data flows directly from MySQL into BigQuery, reducing per-execution elapsed time by 2 to 5 minutes
- BigQuery Storage Write API COMMITTED mode provides exactly-once write semantics with stream-level offset tracking, preventing duplicate rows on retry
- Smallest infrastructure footprint: no GCS bucket management, no lifecycle rules, no additional services beyond Cloud Composer and BigQuery
- Custom PythonOperator allows highly tailored keyset pagination, dynamic chunk sizing, and in-line schema validation within a single operator without operator abstraction constraints

### Cons

- Ingestion layer is entirely custom code: requires full development, unit testing, integration testing, and long-term maintenance by the engineering team, increasing sprint 14 delivery risk
- Airflow worker container memory is the effective throughput ceiling: large chunk sizes on a wide employees schema risk OOMKill on worker pods requiring careful memory-based chunk size calibration
- BigQuery Storage Write API requires protobuf schema definition management and serialisation handling that native Airflow operators abstract away entirely
- Higher initial development effort than Option 1 declarative operator configuration; custom chunking logic is more prone to off-by-one errors, missed rows, or duplicate rows than the tested MySQLToGCSOperator implementation
- Debugging custom Python ingest failures requires deeper Python and BigQuery Storage Write API expertise than standard Airflow operator failures with documented error message taxonomies

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Custom chunking logic carries higher risk of edge-case row gaps or duplicates than the battle-tested MySQLToGCSOperator; keyset pagination requires employee_id to be a stable, monotonically increasing indexed key; comprehensive unit and integration tests against a MySQL snapshot are mandatory before production use |
| Scaling | Airflow worker memory ceiling constrains maximum extraction throughput; scaling requires increasing Cloud Composer worker node machine type or count, adding operational overhead not present in Option 1; this is not elastically scalable without infrastructure changes |
| Latency | Direct Storage Write API write without GCS staging reduces per-execution latency by 2 to 5 minutes; COMMITTED mode write overhead is minimal; suitable for the 2 AM daily batch window with adequate completion buffer |
| Cost | No GCS storage cost; BigQuery Storage Write API ingestion charges apply per GB written; Cloud Composer worker node must be sized to accommodate in-memory chunk buffering, potentially requiring a larger and more expensive environment than Option 1 |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 7 | 6 | 6 | 8 | 6 | **6.60** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer + Native Airflow Operators + GCS Staging + BigQuery MERGE ✅ | 8 | 7 | 8 | 7 | 9 | **7.70** |
| Cloud Composer + Dataflow JDBC Flex Template + BigQuery MERGE | 5 | 9 | 5 | 8 | 7 | **6.65** |
| Cloud Composer + Custom PythonOperator + BigQuery Storage Write API Direct Ingest | 7 | 6 | 6 | 8 | 6 | **6.60** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Composer + Native Airflow Operators + GCS Staging + BigQuery MERGE**
**Weighted Score: 7.70**

**Justification:** Option 1 achieves the highest weighted score of 7.70 by delivering the optimal balance of cost efficiency, operational simplicity, and alignment with the stakeholder-mandated toolchain. It uses Cloud Composer and native Airflow providers as explicitly preferred, requires no additional managed services, and satisfies every functional requirement — chunked historical load with retry logic, incremental MERGE via stored procedure, historical sign-off gate, pre- and post-load data quality assertions, audit logging, and 60-day BigQuery retention — entirely within the declared technology stack and within the sprint 14 timeline constraint.

**Why highest score:** Scores highest on Cost (8) and Operability (9), which together carry 40% of the total weight, by eliminating the Dataflow per-worker billing overhead of Option 2 and the custom-code maintenance burden of Option 3. A Complexity score of 8 reflects that all pipeline logic is expressible in declarative Airflow operator configuration and BigQuery SQL with no bespoke runtime code, reducing development risk and time-to-delivery within the sprint 14 deadline.

**Trade-offs accepted:** GCS staging introduces an intermediate storage hop adding 2 to 5 minutes of per-execution latency, which is fully acceptable within the overnight 2 AM batch window. Page-based LIMIT/OFFSET chunking carries a performance ceiling beyond very large row counts, but this is acceptable given the 5 GB initial volume and 1 GB/month growth trajectory; chunk size must be validated and tuned during the historical load execution phase.

---

## Rejected Options

### Cloud Composer + Dataflow JDBC Flex Template + BigQuery MERGE

Rejected because Dataflow's enterprise-scale distributed compute capabilities are architecturally disproportionate to this medium-volume structured batch use case. The per-worker billing model and cold-start latency penalise daily small incremental runs, producing a Cost score of 5 that substantially drags the weighted total to 6.65. The Flex Template container image and JDBC driver maintenance add an ongoing operational burden absent in Option 1. Option 1 delivers equivalent data quality guarantees, the same MERGE stored procedure, and full observability at significantly lower cost and operational complexity using the stakeholder-preferred Cloud Composer operator ecosystem.

### Cloud Composer + Custom PythonOperator + BigQuery Storage Write API Direct Ingest

Rejected because the custom PythonOperator approach requires bespoke development, testing, and long-term maintenance of the ingestion layer — a significant engineering investment that increases delivery risk against the sprint 14 deadline and provides no meaningful benefit over Option 1's native operators at medium volume. The Airflow worker memory ceiling limits scalability, the Storage Write API adds protobuf serialisation complexity, and the custom chunking logic introduces higher inherent data quality risk than the tested MySQLToGCSOperator. Option 1 achieves equivalent outcomes with a Complexity score of 8 versus 6, lower data quality risk, and higher operability at the same or lower cost.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| PII Data Exposure | Employee records held in GCS staging and BigQuery may contain personally identifiable information including names, contact details, or employment attributes; unauthorised access or misconfigured IAM bindings could result in a data breach and compliance violation | Enforce least-privilege IAM on the GCS staging bucket (Storage Object Admin scoped to the Composer service account only) and BigQuery dataset (no allUsers or allAuthenticatedUsers bindings); enable VPC Service Controls perimeter around the verizon-data project; evaluate column-level BigQuery security policies or data masking for sensitive PII fields; enforce 1-day GCS lifecycle deletion to minimise PII residency in staging |
| Schema Drift | New, renamed, or dropped columns in MySQL agentichub.employees will silently break or corrupt BigQuery loads if not detected before execution; this is a high-probability risk in active operational databases | Implement a mandatory pre-load Airflow task that queries MySQL INFORMATION_SCHEMA.COLUMNS and diffs against the registered BigQuery table schema; any mismatch causes an immediate DAG failure with a detailed alert before any data is written; establish a formal new-column approval workflow requiring schema review and BigQuery schema update before any new column is included in a production load |
| Historical Load Sign-Off Gate Bypass | The incremental pipeline may be inadvertently activated before historical load validation and stakeholder sign-off are documented and complete, leading to MERGE operations against an unvalidated baseline that could produce incorrect analytics results | The incremental DAG's first task is a ShortCircuitOperator reading the Airflow Variable historical_load_signoff_status; unless the value is exactly APPROVED the DAG exits with SKIPPED status for all downstream tasks; write access to this Airflow Variable in the production environment is restricted to authorised personnel only via Airflow RBAC |
| MySQL Connection Saturation | Concurrent Airflow worker tasks or high-frequency retried operators issuing chunked SELECT queries may exhaust the Cloud SQL MySQL max_connections parameter, causing connection refused errors and extraction failures during both historical and incremental load phases | Set DAG-level max_active_tasks=1 and operator-level pool allocation to serialise MySQL extraction tasks; configure Cloud SQL max_connections to accommodate the Composer worker pool plus headroom for DBA operations; instrument connection usage via Cloud SQL metrics in Cloud Monitoring with an alert at 80% utilisation |
| Data Retention Non-Compliance | Misconfiguration of BigQuery partition expiry or accidental Terraform state drift could cause premature deletion of live employee data or unbounded retention beyond the 60-day policy, both of which violate the retention requirement | Declare the BigQuery employees table resource in Terraform with explicit partitionExpirationMs = 5184000000; run terraform plan in CI before any apply to detect drift; add a Cloud Monitoring alert for unexpected row count drops greater than 10% in the employees table outside the expected nightly purge window |

---

## Assumptions

1. Cloud SQL Auth Proxy or VPC-native private IP connectivity is available and correctly authorised between the Cloud Composer 2 worker environment and Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore on TCP port 3306
2. BigQuery dataset verizon_data_dea already exists in project verizon-data; the Cloud Composer service account holds roles/bigquery.dataEditor on the dataset and roles/bigquery.jobUser on the project
3. A GCS staging bucket (e.g. gs://verizon-data-etl-staging) is provisioned in project verizon-data with a 1-day object lifecycle auto-deletion rule applied to the employees/ prefix
4. Stored procedure sp_mysqltobq_load.sql is separately authored, peer-reviewed, and deployed to BigQuery as a routine before incremental pipeline activation; its correctness against the composite merge key (employee_id, updated_date) is validated independently
5. Historical load stakeholder sign-off by Yash is enforced programmatically via an Airflow Variable (historical_load_signoff_status) that must be explicitly set to APPROVED by an authorised operator; the incremental DAG uses a ShortCircuitOperator to check this variable before proceeding
6. Employee data in agentichub.employees may contain PII; GCS staging files and BigQuery tables are encrypted at rest using Google-managed encryption keys (GMEK) as a baseline; CMEK evaluation is deferred to a separate security review engagement
7. Cloud Composer 2 environment is sized at Small or Medium to accommodate medium-volume daily batch workloads; environment sizing is validated during the historical load execution phase
8. 60-day data retention is enforced via BigQuery table-level partition expiry (partitionExpirationMs = 5184000000) on the verizon_data_dea.employees table, managed and versioned via Terraform
9. Composite merge key (employee_id, updated_date) is sufficient to correctly identify new inserts and updates without ambiguity; hard-delete scenarios in the source system are out of scope unless explicitly added as a future requirement
10. Cloud Monitoring alerting notification channels (email distribution list, Slack webhook, or PagerDuty integration) are pre-configured in the verizon-data GCP project and tested prior to incremental pipeline go-live
11. Terraform remote state is stored in a GCS backend bucket within the verizon-data project with state locking enabled; all pipeline infrastructure resources are declared in a dedicated Terraform root module

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Use MySQLToGCSOperator with configurable page_size chunking for historical load extraction | Use a chunking or batching strategy to handle the estimated 5 GB historical data volume and prevent timeouts and memory failures; include retry logic for failed historical data extractions | batch | 5 GB initial historical load |
| Execute BigQuery stored procedure sp_mysqltobq_load.sql with MERGE on composite key (employee_id, updated_date) | Use stored procedure sp_mysqltobq_load.sql with merge key based on employee_id and updated_date for incremental loads | batch | 1 GB/month incremental growth |
| Schedule incremental DAG in Cloud Composer 2 at 2 AM daily via cron schedule 0 2 * * * | Implement ongoing scheduled incremental loads running daily at 2 AM via Cloud Composer | batch | — |
| Implement ShortCircuitOperator-based historical load sign-off gate reading Airflow Variable historical_load_signoff_status | Block incremental pipeline activation until historical load is fully validated and sign-off is formally documented | — | — |
| Enforce 60-day BigQuery partition expiry via Terraform-managed partitionExpirationMs on the employees target table | Apply 60-day data retention policy in BigQuery | — | — |
| Implement post-load BigQuery SQL row count reconciliation task with zero-tolerance assertion between MySQL COUNT(*) and BigQuery COUNT(*) | Implement post-load row count reconciliation between MySQL source and BigQuery target after every load; zero tolerance for missing or duplicated records | — | — |
| Implement pre-load schema validation Airflow task comparing MySQL INFORMATION_SCHEMA column definitions to the registered BigQuery table schema | Implement pre-load schema validation covering field names, data types, and null handling before each load execution; define and enforce a handling strategy for new MySQL columns before they are included in any load | — | — |
| Enforce primary key uniqueness in BigQuery employees table post-MERGE via BigQuery SQL assertion task | Enforce primary key uniqueness in the BigQuery employees table after every load | — | — |
| Write per-execution records to BigQuery audit table verizon_data_dea.pipeline_audit_log on every DAG run regardless of outcome | Maintain audit logs for every load execution covering both historical and incremental runs | — | — |
| Configure Cloud Monitoring alerting policies on DAG task failure and missed schedule, with Looker Studio dashboard surfacing pipeline_audit_log for stakeholder self-service | Configure monitoring and alerting for pipeline failures to enable early detection; provide stakeholders with visibility into load success via logs or a dashboard without requiring engineering assistance | — | — |

---

## Open Questions — Action Required

1. Is stored procedure sp_mysqltobq_load.sql already authored, tested, and available in a version-controlled repository, or does it need to be designed and implemented as part of this engagement? Its existence is assumed but not confirmed in the provided requirements.
2. What is the current column schema of agentichub.employees (column names, data types, nullable flags, approximate row count and average row width in bytes)? This information is required to configure the MySQLToGCSOperator schema parameter, define the BigQuery target table DDL, and establish the row count reconciliation baseline before the historical load begins.
3. Does the employee data contain PII fields (e.g. national ID, salary, date of birth, personal contact details) requiring column-level BigQuery security policies, BigQuery data masking rules, or CMEK encryption beyond dataset-level IAM access control? The compliance field is currently null and PII handling scope is unconfirmed.
4. What is the formal mechanism and authorised personnel list for the historical load sign-off? Specifically, will stakeholder Yash approve via a JIRA ticket, email confirmation to be archived, or a direct Airflow Variable update in the production environment, and which GCP service account or individual holds write access to that Airflow Variable?
5. What alerting notification channel is configured or preferred for pipeline failure notifications — email distribution list, Slack channel, or PagerDuty service — and has it been validated as operational in the verizon-data GCP project?
6. Should the 60-day retention policy be enforced at the partition level (partitioned table with partitionExpirationMs, recommended) or at the dataset level (defaultTableExpirationMs), and is the employees table intended to be date-partitioned on updated_date or load_date?
7. Are there existing Terraform workspaces, GCS state backends, and naming conventions already established for the verizon-data project that this pipeline's IaC module must integrate with, or should a new Terraform root module be initialised from scratch?
8. What is the acceptable maximum SLA for pipeline failure alert notification after a missed 2 AM execution — for example, must stakeholders be notified within 15 minutes or within 1 hour of a failed or skipped run?
