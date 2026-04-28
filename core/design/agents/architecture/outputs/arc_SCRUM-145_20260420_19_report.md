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

> **Build with:** Cloud Run Chunked Extractor + Cloud Workflows Orchestration + BigQuery Native Load
>
> **Why:** Cloud Run Jobs + Cloud Workflows achieves the highest weighted score (7.50) by delivering optimal cost efficiency and operational simplicity while fully satisfying all 14 functional requirements. The serverless execution model eliminates the always-on infrastructure cost of Cloud Composer and Dataflow worker pools, which are economically unjustifiable for a single bounded medium-volume daily batch pipeline with a 60-day retention policy capping steady-state data at approximately 7 GB. Every functional requirement is addressed: keyset chunking prevents historical load memory failures; per-chunk retry satisfies fault tolerance; Cloud Workflows conditional branching enforces the historical sign-off gate before activating incremental schedule; pre-load schema validation covers field names, data types, and null handling; BigQuery scripted SQL delivers row count reconciliation and PK uniqueness assertion; GCS chunk manifest provides audit trail; Cloud Monitoring alerting fires on pipeline failures; and Looker Studio over BigQuery audit_log gives stakeholder Yash self-service load validation visibility without engineering assistance.
>
> **Score:** 7.50 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1  | Option 2  | Option 3 ✅ |
|---|---||---||---|
| **Name** | Dataflow JDBC Parallel Extraction + Cloud Composer Orchestration | Dataproc Ephemeral Spark Cluster + Cloud Composer Orchestration | Cloud Run Chunked Extractor + Cloud Workflows Orchestration + BigQuery Native Load |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | Cloud Dataflow (Apache Beam 2.x transforms + BigQuery Scripted SQL) | Apache Spark 3.x on Dataproc + BigQuery Scripted SQL (reconciliation) | Cloud Run Jobs (in-process schema validation + chunked extraction) + BigQuery Scripted SQL (post-load reconciliation and PK uniqueness assertion) |
| **Storage** | BigQuery + GCS (Dataflow staging) | GCS (staging Parquet) + BigQuery (target + audit_log) | GCS (transient chunked NDJSON staging) + BigQuery (target employees table + audit_log) |
| **Weighted Score** | **7.25** | **6.15** | **7.50**  ✅ |

---

## Option 1 — Dataflow JDBC Parallel Extraction + Cloud Composer Orchestration

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer triggers Dataflow job with Apache Beam JDBC IO connector; parallel reads from Cloud SQL MySQL using partitioned JDBC queries (partition by employee_id key ranges, configurable parallelism) with Cloud SQL Auth Proxy sidecar for secure private connectivity; chunk size controlled via numPartitions and partition boundaries |
| Processing | Dataflow pipeline applies pre-load schema validation (field names, data types, null constraints) against stored schema manifest; transforms MySQL types to BigQuery-compatible types; enforces PK deduplication step; post-load row count reconciliation and PK uniqueness assertion executed as BigQuery scripted SQL invoked from Composer; audit events written to BigQuery audit_log table |
| Storage | BigQuery verizon_data_dea.employees as primary target with load_date partitioning (WRITE_TRUNCATE for historical load, MERGE/UPSERT keyed on employee_id for incremental); GCS bucket for Dataflow staging and temp files; BigQuery audit_log table for load_id, source_count, target_count, status, timestamps |
| Consumption | Looker Studio self-service dashboard over BigQuery audit_log for stakeholder Yash; Cloud Monitoring alerting on Dataflow job failures and Composer task failures; Cloud Logging structured logs; BigQuery dataset access for stakeholder ad-hoc validation queries |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Dataflow with Apache Beam JDBC IO + Cloud SQL Auth Proxy | — | Yes |
| Processing | Cloud Dataflow (Apache Beam 2.x transforms + BigQuery Scripted SQL) | — | Yes |
| Storage | BigQuery + GCS (Dataflow staging) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio | — | Yes |
| Iac | Terraform | — | No |

### Pros

- Native auto-scaling handles the 5 GB historical load and ongoing 1 GB/month growth without reconfiguration
- JDBC partitioned reads natively support chunking by primary key range, preventing memory failures during extraction
- Built-in retry semantics at Beam bundle and element level; configurable retry policy covers failed chunk scenarios
- Cloud Composer provides enterprise-grade DAG management with dependency enforcement and conditional historical load sign-off gating
- Tight BigQuery integration with direct write and native MERGE support for incremental upsert semantics
- Rich observability: Dataflow job metrics, Composer task-level logs, and Cloud Monitoring dashboards available out of the box

### Cons

- Dataflow workers incur per-vCPU/hour cost even for short daily batch jobs at medium volume, reducing cost efficiency
- Cloud Composer environment runs 24/7 and adds significant baseline cost (~$300-500/month for small environment) regardless of pipeline frequency
- Apache Beam programming model has a non-trivial learning curve; JDBC IO connector requires MySQL JDBC driver JAR management
- Cold start latency of 2-3 minutes for worker provisioning adds overhead to short daily incremental jobs
- Overkill architectural weight for a single structured JDBC-to-BigQuery pipeline at 5-7 GB steady-state volume

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | JDBC partitioned reads may produce duplicate records if partition boundaries are not strictly exclusive; mitigated by closed-open range partitioning on employee_id with validated bounds |
| Scaling | Cloud SQL connection limits may be exhausted by parallel Dataflow workers during the 5 GB historical load; mitigated by Cloud SQL Auth Proxy connection pooling and setting max worker parallelism below connection limit |
| Latency | Daily batch schedule is fully sufficient; no sub-minute latency risk for this use case |
| Cost | Composer environment cost (~$400/month) is disproportionate if no additional DAGs are planned; total monthly cost exceeds Option 3 by 3-4x at current volume |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 9 | 6 | 8 | 8 | **7.25** |

---

## Option 2 — Dataproc Ephemeral Spark Cluster + Cloud Composer Orchestration

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer spins up ephemeral Dataproc cluster; Spark job reads MySQL employees table via Spark JDBC connector with partitionColumn, lowerBound, upperBound, and numPartitions parameters for parallel chunked extraction; Cloud SQL Auth Proxy sidecar enables private IP connectivity; cluster terminated after job completion to avoid idle compute cost |
| Processing | Spark DataFrame applies pre-load schema validation, MySQL-to-BigQuery type mapping, null constraint checks, and PK deduplication; output written to GCS as Parquet; post-load BigQuery scripted SQL performs COUNT reconciliation and PK uniqueness assertion; schema diff check compares live MySQL INFORMATION_SCHEMA against stored manifest; audit records written to BigQuery audit_log table |
| Storage | GCS bucket stores intermediate Parquet output from Spark (transient, deleted after successful BigQuery load job); BigQuery verizon_data_dea.employees loaded via BigQuery Load Jobs from GCS (WRITE_TRUNCATE for historical, MERGE for incremental); BigQuery audit_log table for all execution metadata |
| Consumption | Looker Studio self-service dashboard over BigQuery audit_log; Cloud Monitoring alerting on Dataproc job and Composer task failures; Dataproc History Server for Spark job diagnostics; Cloud Logging for structured pipeline logs |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Dataproc Ephemeral Cluster (Apache Spark 3.x JDBC + Cloud SQL Auth Proxy) | — | Yes |
| Processing | Apache Spark 3.x on Dataproc + BigQuery Scripted SQL (reconciliation) | — | Yes |
| Storage | GCS (staging Parquet) + BigQuery (target + audit_log) | — | Yes |
| Orchestration | Cloud Composer 2 (Apache Airflow 2.x) | — | Yes |
| Monitoring | Cloud Monitoring + Dataproc History Server + Cloud Logging | — | Yes |
| Iac | Terraform | — | No |

### Pros

- Ephemeral cluster model eliminates idle compute cost; Dataproc nodes only run during active job execution
- Spark JDBC numPartitions provides fine-grained control over extraction parallelism and chunking strategy
- GCS Parquet staging creates a durable intermediate checkpoint enabling safe full reruns after any downstream failure
- Spark task-level fault tolerance and speculative execution handle partial extraction failures automatically
- Familiar ecosystem for teams with existing Spark expertise; rich community documentation for JDBC patterns

### Cons

- Dataproc cluster initialization adds 3-5 minutes of overhead to every daily incremental job execution
- GCS staging introduces an extra architectural layer, Parquet serialization risk, and additional storage and transfer costs
- Spark cluster configuration, autoscaling policies, and executor memory tuning require specialist knowledge beyond standard data engineering
- Cloud Composer environment baseline cost persists regardless of ephemeral cluster strategy (~$300-500/month)
- Three-layer architecture (Dataproc → GCS → BigQuery Load Job) increases failure surface area relative to simpler alternatives
- Distributed Spark is architecturally overweight for structured JDBC ETL at 5-7 GB scale; does not benefit from in-memory processing at this volume

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | GCS Parquet staging introduces a serialization layer where MySQL DECIMAL precision or DATETIME timezone semantics may be lost; mitigated by explicit Spark schema enforcement on DataFrame write with BigQuery-compatible types |
| Scaling | Spark JDBC partitioning on employee_id requires accurate lowerBound/upperBound values; skewed primary key distribution may create heavily unbalanced partitions causing one executor to time out while others finish |
| Latency | Cluster spin-up and GCS staging add 5-8 minutes of pipeline overhead; fully acceptable for a daily batch schedule with no sub-minute SLA |
| Cost | Dataproc n1-standard worker nodes during historical 5 GB load plus always-on Composer environment makes this the highest per-run and per-month cost option among the three candidates |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 8 | 5 | 7 | 6 | **6.15** |

---

## Option 3 — Cloud Run Chunked Extractor + Cloud Workflows Orchestration + BigQuery Native Load ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Scheduler triggers Cloud Workflows on daily cron; Workflows invokes a Cloud Run Job (containerized Python with mysql-connector-python) that connects to Cloud SQL MySQL via Cloud SQL Auth Proxy serverless connector; historical load uses keyset/cursor-based chunking (ORDER BY employee_id with configurable chunk_size, default 100K rows per chunk) to prevent memory failures and timeouts; each chunk written atomically to GCS as newline-delimited JSON files with chunk manifest tracking; per-chunk retry logic applies exponential backoff with 3 attempts before marking chunk as failed and raising alert |
| Processing | Pre-load step: Cloud Run job reads stored schema manifest from GCS and executes INFORMATION_SCHEMA comparison against live MySQL employees table, asserting field names, data types, NOT NULL constraints, and detecting unexpected new columns before any extraction begins; each extracted chunk validated against schema on read; post-load step: Cloud Workflows invokes BigQuery scripted SQL job to compare SOURCE_COUNT (MySQL COUNT(*) snapshot taken at job start) vs TARGET_COUNT (BigQuery COUNT(*)) and assert equality within tolerance; PK uniqueness enforced via BigQuery EXCEPT DISTINCT query after every load execution; new column detection triggers Cloud Monitoring alert and halts pipeline pending schema policy resolution; all validation outcomes written to BigQuery audit_log table with load_id, chunk_count, source_count, target_count, validation_status, and execution timestamps |
| Storage | GCS bucket stores chunked NDJSON staging files (auto-deleted after successful BigQuery load job via lifecycle policy); BigQuery verizon_data_dea.employees as primary target with load_date partitioning and 60-day partition expiry enforced natively (WRITE_TRUNCATE for historical full load, WRITE_APPEND followed by MERGE keyed on employee_id for daily incremental); BigQuery audit_log table in verizon_data_dea stores immutable execution metadata for all historical and incremental runs |
| Consumption | Looker Studio self-service dashboard connected to BigQuery audit_log provides stakeholder Yash independent visibility into load success, row counts, validation status, and failure history without engineering involvement; Cloud Monitoring custom alerting policies fire on Cloud Run Job non-zero exit codes and Cloud Workflows execution failures within configurable SLA window; Cloud Logging structured log sink captures all pipeline steps; BigQuery dataset access provisioned for stakeholder ad-hoc SQL validation queries |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Run Jobs (Python, mysql-connector-python, Cloud SQL Auth Proxy serverless connector) | — | Yes |
| Processing | Cloud Run Jobs (in-process schema validation + chunked extraction) + BigQuery Scripted SQL (post-load reconciliation and PK uniqueness assertion) | — | Yes |
| Storage | GCS (transient chunked NDJSON staging) + BigQuery (target employees table + audit_log) | — | Yes |
| Orchestration | Cloud Workflows + Cloud Scheduler | — | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Looker Studio | — | Yes |
| Iac | Terraform | — | No |

### Pros

- Serverless execution model: Cloud Run Jobs bill only during active execution (millisecond granularity), eliminating always-on orchestrator and worker pool costs that dominate Options 1 and 2
- Keyset/cursor-based chunking on employee_id is deterministic, resumable from any checkpoint, and directly prevents memory failures on the 5 GB historical load without distributed framework overhead
- Per-chunk retry with exponential backoff is transparent, auditable Python logic that satisfies the retry requirement without framework-specific internals
- Cloud Workflows native conditional branching enforces the historical load sign-off gate by checking an approval record in GCS or Firestore before activating the incremental schedule branch
- BigQuery scripted SQL for row count reconciliation and PK uniqueness assertions requires no additional tooling and produces results directly queryable by stakeholder Yash via Looker Studio
- 60-day BigQuery partition expiry natively enforces data retention policy with zero operational overhead
- GCS chunk manifest enables safe partial reruns: completed chunks are skipped on retry, only failed chunks are re-extracted
- Lowest total cost of ownership: Cloud Run per-execution billing + Cloud Workflows free tier (5K steps/month) + minimal transient GCS staging cost
- Standard Python and SQL skill set; no Beam, Spark, or Airflow expertise required, reducing implementation risk within sprint 14 timeline
- Linear pipeline dependency graph (validate schema → extract chunks → load to BQ → reconcile → audit) maps cleanly to Cloud Workflows steps without requiring Airflow DAG complexity

### Cons

- Cloud Run Jobs have a 24-hour maximum execution timeout; extremely large historical reruns spanning multiple days must be split across multiple Workflows invocations with GCS checkpoint resumption
- Single-container execution lacks native horizontal auto-scaling of Dataflow; future volume growth beyond ~50 GB monthly would require migration to parallel Cloud Run Jobs array pattern or Dataflow
- Cloud Workflows YAML DSL has limited expressiveness compared to Airflow DAGs for hypothetical future multi-dependency pipelines; acceptable for current linear pipeline graph
- Schema validation logic resides in application code rather than a managed data catalog; requires code change to update schema manifest when MySQL schema evolves

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Keyset chunking on employee_id assumes records with higher IDs are not inserted with IDs below the current cursor (e.g., ID reuse or gap-fill inserts); mitigated by taking a MySQL COUNT(*) snapshot at job start and comparing against BigQuery post-load for any unexplained discrepancy; incremental watermark column reliability must be confirmed during sprint 14 discovery |
| Scaling | Sequential keyset chunking is bounded by single-container throughput; at projected 1 GB/month growth, steady-state remains ~7 GB under 60-day retention, well within Cloud Run capacity; if volume unexpectedly exceeds 50 GB/month, the parallel Cloud Run Jobs array pattern provides a clear scale-out path before requiring Dataflow migration |
| Latency | Not applicable; daily batch schedule carries no sub-minute or intra-day latency requirement; full pipeline including historical 5 GB load is expected to complete within 2-3 hours at 100K-row chunk size |
| Cost | GCS transient staging costs are negligible; BigQuery storage cost is bounded by 60-day partition expiry at ~7 GB steady-state; Cloud Run execution cost for a daily job processing ~33 MB/day incremental is under $5/month; total cost risk is low |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 7 | 8 | 7 | 7 | **7.50** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Dataflow JDBC Parallel Extraction + Cloud Composer Orchestration | 6 | 9 | 6 | 8 | 8 | **7.25** |
| Dataproc Ephemeral Spark Cluster + Cloud Composer Orchestration | 5 | 8 | 5 | 7 | 6 | **6.15** |
| Cloud Run Chunked Extractor + Cloud Workflows Orchestration + BigQuery Native Load ✅ | 8 | 7 | 8 | 7 | 7 | **7.50** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Run Chunked Extractor + Cloud Workflows Orchestration + BigQuery Native Load**
**Weighted Score: 7.50**

**Justification:** Cloud Run Jobs + Cloud Workflows achieves the highest weighted score (7.50) by delivering optimal cost efficiency and operational simplicity while fully satisfying all 14 functional requirements. The serverless execution model eliminates the always-on infrastructure cost of Cloud Composer and Dataflow worker pools, which are economically unjustifiable for a single bounded medium-volume daily batch pipeline with a 60-day retention policy capping steady-state data at approximately 7 GB. Every functional requirement is addressed: keyset chunking prevents historical load memory failures; per-chunk retry satisfies fault tolerance; Cloud Workflows conditional branching enforces the historical sign-off gate before activating incremental schedule; pre-load schema validation covers field names, data types, and null handling; BigQuery scripted SQL delivers row count reconciliation and PK uniqueness assertion; GCS chunk manifest provides audit trail; Cloud Monitoring alerting fires on pipeline failures; and Looker Studio over BigQuery audit_log gives stakeholder Yash self-service load validation visibility without engineering assistance.

**Why highest score:** Option 3 achieves the top weighted score because its advantages are concentrated in the two highest-weight scoring dimensions: Cost (weight 0.30, score 8, contribution 2.40) and Complexity (weight 0.20, score 8, contribution 1.60), together contributing 4.00 of 7.50 total — 53% of the winning score. Option 1's superior Scalability score (9 vs 7) at weight 0.25 contributes only 0.50 more than Option 3, which is fully offset by Option 1's inferior Cost score contributing 0.60 less. The 60-day retention policy is the decisive factor: it caps steady-state volume at ~7 GB, making Dataflow's auto-scaling advantages theoretical rather than realized at current and projected load, invalidating the cost premium required to access them.

**Trade-offs accepted:** Accepting lower Scalability score (7 vs 9 for Dataflow) because the 60-day BigQuery partition expiry policy bounds the steady-state employees table to approximately 7 GB regardless of ingestion growth rate, making distributed auto-scaling irrelevant at current and near-term projected volumes. The parallel Cloud Run Jobs array pattern provides a documented migration path if monthly incremental volume unexpectedly exceeds 10 GB before a Dataflow migration is warranted. Accepting Cloud Workflows' simpler DSL over Airflow DAGs because the pipeline dependency graph is strictly linear and does not require complex multi-DAG dependencies, sensor operators, or cross-pipeline coordination that would justify Composer's baseline cost.

---

## Rejected Options

### Dataflow JDBC Parallel Extraction + Cloud Composer Orchestration

Higher cost profile driven by always-on Cloud Composer environment and Dataflow worker billing is economically unjustifiable for a bounded medium-volume daily batch pipeline where 60-day partition expiry caps steady-state BigQuery table size at approximately 7 GB. The Apache Beam programming model adds implementation risk within the sprint 14 constraint without delivering scalability benefits that are relevant at current or projected volumes. Option 3 satisfies all 14 functional requirements at materially lower cost and complexity.

### Dataproc Ephemeral Spark Cluster + Cloud Composer Orchestration

Lowest weighted score (6.15) across all options. Dataproc Spark introduces unnecessary architectural complexity — cluster management, GCS staging layer, Spark tuning, and Parquet type mapping — for a medium-volume structured ETL workload that provides no benefit from distributed in-memory processing at 5-7 GB steady-state scale. The three-layer pipeline (Dataproc → GCS → BigQuery Load Job) multiplies failure surface without delivering reliability advantages over a simpler architecture. Combined Composer and Dataproc compute costs make this the most expensive option per execution cycle.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Data Completeness — Missing Watermark Column | If the MySQL employees table lacks a reliable watermark column (updated_at, modified_at), daily incremental loads cannot filter by change date and will miss updated records that retain their original primary key, producing stale data in BigQuery over time | Confirm watermark column existence and update semantics during sprint 14 schema discovery before pipeline development begins; if absent, implement full-scan with MERGE/UPSERT strategy for all incremental loads and document the performance and cost implications for stakeholder awareness |
| Cloud SQL Connectivity | Cloud Run Jobs must reach Cloud SQL via the serverless connector; misconfigured Cloud SQL Auth Proxy IAM permissions, incorrect instance connection name, or VPC Service Controls restrictions will cause 100% extraction failure on first run | Execute a Cloud Run connectivity smoke test (SELECT 1 from employees LIMIT 1) as the mandatory first step in the Cloud Workflows historical load workflow, before any chunked extraction begins; fail fast with a Cloud Monitoring alert if the smoke test fails; validate IAM bindings via Terraform plan before deployment |
| Historical Load Sign-Off Gate Bypass | Incremental loads may be activated before stakeholder Yash formally validates historical load completeness if the Cloud Workflows gate condition is misconfigured, the approval object is pre-created accidentally, or Cloud Scheduler is enabled manually | Implement gate as a required Cloud Workflows condition that reads and validates a signed approval JSON object from GCS (containing load_id, approver, timestamp, and a confirmation hash); Cloud Scheduler incremental trigger is created in PAUSED state via Terraform and requires a manual Terraform apply with approval_flag=true to activate; document the gate activation procedure in the operational runbook |
| Schema Drift | New, renamed, or type-changed columns added to MySQL employees table without prior notification will cause pre-load schema validation to fail or silently load incorrect data into BigQuery if the schema manifest is not updated in sync | Schema diff check is a mandatory first Cloud Workflows step on every load execution, comparing live MySQL INFORMATION_SCHEMA.COLUMNS against the stored GCS schema manifest; any mismatch triggers a Cloud Monitoring CRITICAL alert and halts the pipeline; define and document a column handling policy (reject load vs. pass-through with alert vs. quarantine) before go-live to enable consistent automated decisions |
| Audit Log Accessibility and Stakeholder Confidence | Stakeholder Yash requires independent, self-service visibility into load validation results; if BigQuery permissions or Looker Studio sharing are not correctly configured at launch, the business outcome of stakeholder confidence is not met even if the pipeline executes correctly | Provision stakeholder BigQuery Data Viewer access on verizon_data_dea and Looker Studio dashboard share link as part of the sprint 14 deployment acceptance criteria; conduct a walkthrough with stakeholder Yash before historical load execution to validate dashboard access and confirm audit_log fields meet reporting expectations |
| Cloud Run Job Timeout on Historical Load | The 5 GB historical extraction at 100K-row chunks requires approximately 50 Cloud Run job iterations; if total elapsed time approaches the 24-hour Cloud Run Job timeout due to network latency or Cloud SQL throttling, the job will be terminated and require manual resumption | Implement GCS-based chunk manifest (completed_chunks.json) that Cloud Run reads at startup to skip already-completed chunks; Cloud Workflows re-invokes the Cloud Run Job automatically on non-zero exit until all chunks in the manifest are marked complete; monitor Cloud Run job execution time during historical load and tune chunk_size upward if per-chunk latency is unexpectedly low |

---

## Assumptions

1. Cloud SQL instance verizon-data:us-central1:mysql-druid-metadatastore is accessible from Cloud Run Jobs via the Cloud SQL Auth Proxy serverless connector using Workload Identity IAM authentication; no additional firewall rules or VPC peering are required
2. MySQL employees table has a stable, monotonically non-decreasing integer primary key (employee_id) suitable for keyset-based chunking; if this assumption is invalidated during sprint 14 discovery, chunking will fall back to LIMIT/OFFSET with a consistent ORDER BY clause
3. An incremental load watermark column (e.g., updated_at or created_at timestamp) exists on the employees table; if absent, the incremental strategy will switch to full-scan with MERGE/UPSERT keyed on employee_id, accepting higher per-run extraction cost
4. Historical load sign-off by stakeholder Yash will be documented as a signed GCS object (e.g., gs://5gcore-pipeline/approvals/historical_load_signoff.json) or Firestore document that Cloud Workflows can programmatically evaluate as a condition gate before activating the incremental schedule
5. BigQuery dataset verizon_data_dea already exists in project verizon-data; Terraform will manage creation of the employees table and audit_log table with appropriate partitioning and expiry configuration
6. The Cloud Run service account will be granted IAM roles: Cloud SQL Client, BigQuery Data Editor (on verizon_data_dea dataset), GCS Object Admin (on pipeline staging bucket), and Logging Writer; provisioned via Terraform IAM bindings
7. 60-day data retention policy is implemented as BigQuery table partition expiry (partition_expiration_ms equivalent to 60 days) on the load_date-partitioned employees table; no separate deletion job is required
8. No PII classification, data masking, or regulatory compliance requirements (GDPR, HIPAA, etc.) are in scope for this architecture iteration; data protection relies on GCP IAM, encrypted storage at rest (GCP default AES-256), and encrypted data in transit (TLS)
9. Looker Studio dashboard will connect to BigQuery audit_log using a dedicated service account with BigQuery Data Viewer permissions; stakeholder Yash access will be provisioned via Looker Studio share link as part of the sprint 14 deployment checklist
10. The GCS staging bucket for chunked NDJSON files will have an object lifecycle policy deleting files older than 7 days to prevent staging data accumulation

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Cloud Run Jobs selected for MySQL extraction over Dataflow or Dataproc | constraints.technical_limitations + non_functional.performance + constraints.timeline | — | 5 GB historical; ~7 GB steady-state under 60-day retention |
| Keyset/cursor-based chunking with configurable chunk_size (default 100K rows) for historical load | functional_requirements[2]: implement chunking or batching strategy to handle 5 GB volume and prevent timeouts and memory failures | — | 5 GB |
| Per-chunk exponential backoff retry with 3 attempts implemented in Cloud Run job | functional_requirements[3]: implement retry logic for failed extraction chunks during the historical load | — | — |
| Daily Cloud Scheduler trigger activating Cloud Workflows for incremental orchestration | functional_requirements[4] + data_requirements.frequency: daily scheduled incremental loads following historical load sign-off | — | ~33 MB/day average incremental based on 1 GB/month growth |
| Cloud Workflows conditional gate checking GCS approval object before activating incremental schedule branch | functional_requirements[5]: block incremental pipeline activation until historical load validation sign-off is formally documented | — | — |
| Pre-load schema validation step in Cloud Run job comparing INFORMATION_SCHEMA against GCS schema manifest | functional_requirements[6]: implement pre-load schema validation covering field names, data types, and null handling | — | — |
| Post-load BigQuery scripted SQL COUNT comparison (MySQL snapshot vs BigQuery actual) after every load execution | functional_requirements[7]: perform post-load row count reconciliation between MySQL and BigQuery after every load execution | — | — |
| BigQuery PK uniqueness assertion via EXCEPT DISTINCT query on employee_id after every load | functional_requirements[8]: enforce primary key uniqueness checks in BigQuery employees table after every load execution | — | — |
| Schema diff check as mandatory Workflows step detecting new or unexpected MySQL columns | functional_requirements[10]: define and enforce a handling strategy for new or unexpected MySQL columns prior to their inclusion in loads | — | — |
| BigQuery audit_log table capturing load_id, chunk_count, source_count, target_count, validation_status, timestamps for every execution | functional_requirements[11]: maintain audit logs for every historical and incremental load execution | — | — |
| Cloud Monitoring alerting policies on Cloud Run Job exit codes and Cloud Workflows execution failures | functional_requirements[12] + non_functional.sla: configure monitoring and alerting for pipeline failures with early detection capability | — | — |
| Looker Studio self-service dashboard over BigQuery audit_log for stakeholder Yash | functional_requirements[13] + business_context: provide stakeholders visibility into load success and data quality via self-service dashboard | — | — |
| BigQuery table partition expiry set to 60 days on load_date partition column | data_requirements.volume: 60-day data retention policy | — | ~7 GB steady-state bounded by retention |
| Terraform as IaC for all GCP resource provisioning | technology.stack: GCP cloud environment; enterprise-grade reproducibility and auditability of infrastructure | — | — |

---

## Open Questions — Action Required

1. Does the MySQL employees table in agentichub have a reliable watermark column (e.g., updated_at, modified_at, last_modified_timestamp) for incremental load filtering? If not, the incremental strategy must switch to full-scan with MERGE/UPSERT, increasing daily extraction cost and duration.
2. What is the formal sign-off process for stakeholder Yash's historical load validation — will approval be recorded in a JIRA ticket, email confirmation, or a pipeline-accessible artifact such as a GCS object or Firestore document that Cloud Workflows can programmatically evaluate?
3. Is there a VPC Service Controls perimeter configured on project verizon-data that could restrict Cloud Run serverless connector access to Cloud SQL private IP, requiring additional perimeter rules or access policy exceptions?
4. What is the required alerting channel and response SLA for pipeline failures — immediate PagerDuty escalation, business-hours email to a distribution list, or Slack webhook notification — to correctly configure Cloud Monitoring notification channels?
5. Are there additional tables beyond employees in the agentichub database planned for onboarding to this pipeline pattern in future sprints? If so, a parameterized Cloud Run job accepting table_name, schema_manifest_path, and watermark_column at runtime would enable code reuse without redesign.
6. Latency SLA not specified in requirements — daily batch pattern confirmed as appropriate; if any stakeholder requires intra-day data freshness (e.g., hourly refresh or near-real-time reporting), the architecture requires re-evaluation toward micro-batch Cloud Run Jobs on sub-hourly Cloud Scheduler triggers or a streaming PubSub + Dataflow pattern.
7. What is the expected cardinality and distribution of employee_id values in the MySQL employees table? Highly non-uniform distributions (e.g., large ID gaps) may require adaptive chunk boundary calculation rather than fixed-size keyset steps to ensure even load distribution across chunks.
