# Architecture Decision Document — Product Catalog Analytics Platform

| Field | Value |
|---|---|
| **Project** | Product Catalog Analytics Platform |
| **Request Type** | New Development |
| **Cloud** | GCP |
| **Pattern** | Batch |
| **Generated** | Architecture Agent v1.0 |
| **Status** | Draft — Pending Engineering Review |

---

## Decision Summary

> **Build with:** Cloud Composer Native Batch Pipeline (PostgresHook → GCS → BigQuery MERGE)
>
> **Why:** Option 1 is the optimal architecture for the Product Catalog Analytics Platform. It directly satisfies every stated functional requirement — full historical load, watermark-based daily incremental sync, full reload for reference tables, UPSERT via BigQuery MERGE, COUNT(*) reconciliation, audit logging to pipeline_audit.pipeline_run_log, and the 03:00 AM UTC SLA — using the preferred Airflow toolchain with no additional managed compute services. The current data profile (~20GB historical, ~500MB daily incremental, batch latency tier) is well within the processing capacity of a properly sized Cloud Composer 2 environment, making the scalability advantages of Dataflow and Dataproc academic rather than practical at this stage. The architecture minimizes cost, operational complexity, required engineering skill breadth, and time-to-delivery while maintaining full GCP managed-service alignment.
>
> **Score:** 8.05 / 10 (highest across all options)

---

## Options at a Glance

| | Option 1 ✅ | Option 2  | Option 3  |
|---|---||---||---|
| **Name** | Cloud Composer Native Batch Pipeline (PostgresHook → GCS → BigQuery MERGE) | Cloud Composer + Dataflow (Apache Beam JdbcIO) → BigQuery | Cloud Composer + Dataproc Ephemeral PySpark Cluster → BigQuery |
| **Pattern** | Batch | Batch | Batch |
| **Processing** | BigQuery — LOAD JOB + MERGE SQL via BigQueryInsertJobOperator | Dataflow (Apache Beam Runner v2) + BigQuery MERGE SQL via BigQueryInsertJobOperator | Dataproc PySpark (ephemeral cluster) + BigQuery LOAD JOB + MERGE SQL via BigQueryInsertJobOperator |
| **Storage** | GCS (Parquet staging, 7-day lifecycle) + BigQuery verizon-data.verizon_catalog_deah | GCS (Dataflow temp/shuffle) + BigQuery verizon-data.verizon_catalog_deah + transient staging dataset | GCS (Parquet intermediate, Spark staging) + BigQuery verizon-data.verizon_catalog_deah |
| **Weighted Score** | **8.05**  ✅ | **7.15** | **6.15** |

---

## Option 1 — Cloud Composer Native Batch Pipeline (PostgresHook → GCS → BigQuery MERGE) ✅ Recommended

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 DAG executes nightly at 01:00 AM UTC. On first run, a full historical extraction of all 4 tables (~20 GB) is performed via Airflow PostgresHook (psycopg2) using chunked cursor reads to protect the operational source DB. On subsequent daily runs, watermark-based incremental extraction using MAX(updated_at) stored as Airflow XCom is applied to products and inventory; categories and suppliers undergo a full daily reload. Extracted batches are serialized as Parquet files and written to a dedicated GCS staging bucket partitioned by table name and execution_date. |
| Processing | A BigQueryInsertJobOperator executes a BigQuery LOAD JOB from GCS Parquet files into a transient staging table (_stg_<table>) per source. A parameterized BigQuery MERGE statement then UPSERTs records from each staging table into the corresponding target table keyed on the source primary key, handling both net-new inserts and late-arriving updates atomically. A reconciliation task queries COUNT(*) from PostgreSQL via PostgresHook and from the BigQuery target table after each load; mismatches trigger a DAG failure and PagerDuty/email alert. A final Airflow task writes run metadata (run_id, table_name, execution_date, status, source_count, target_count, duration_seconds, error_message) to pipeline_audit.pipeline_run_log via BigQueryInsertJobOperator. |
| Storage | GCS staging bucket holds intermediate Parquet files with a 7-day object lifecycle policy that auto-deletes files after confirmed successful load, preventing unbounded accumulation. BigQuery dataset verizon_catalog_deah in project verizon-data stores the four production tables: products, categories, suppliers, inventory — each partitioned by ingestion_date (DATE) and clustered on primary key columns for downstream query efficiency and cost optimization. pipeline_audit.pipeline_run_log captures execution audit history. Transient _stg_ staging tables are truncated after each successful MERGE. |
| Consumption | Downstream BI tools (Looker, Looker Studio, or equivalent) and ad-hoc BigQuery SQL clients access verizon_catalog_deah directly for product performance reporting and inventory trend analysis. All analytical consumers read from BigQuery; no additional serving layer is required at current data volumes. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Composer 2 — Airflow PostgresHook + PythonOperator (psycopg2 chunked reads) | Composer 2.x / Airflow 2.7+ | Yes |
| Processing | BigQuery — LOAD JOB + MERGE SQL via BigQueryInsertJobOperator | — | Yes |
| Storage | GCS (Parquet staging, 7-day lifecycle) + BigQuery verizon-data.verizon_catalog_deah | — | Yes |
| Orchestration | Cloud Composer 2 | Composer 2.x / Airflow 2.7+ | Yes |
| Monitoring | Cloud Monitoring + Cloud Logging + Airflow UI (DAG/task-level SLA callbacks) | — | Yes |
| Iac | Terraform | >=1.5 | No |

### Pros

- Directly satisfies the preferred_tools constraint — Airflow is the single orchestration and extraction engine with no additional compute services required beyond Cloud Composer and BigQuery
- Lowest operational footprint of all three options: no Dataflow Flex Template authoring, no Dataproc cluster lifecycle management, and no distributed compute framework expertise required
- Native BigQuery MERGE SQL handles UPSERT and late-arriving updates with full ACID guarantees, idempotency on re-runs, and zero custom deduplication code
- Chunked PostgresHook cursor reads with configurable page size protect the operational PostgreSQL source database from long-running full-table locks and connection exhaustion
- COUNT(*) reconciliation and pipeline_audit logging are atomic, independently retriable Airflow tasks requiring no external tooling or separate observability stack
- GCS Parquet staging provides a durable, inspectable, and replayable intermediate layer — failed BigQuery loads can be retried from GCS without re-extracting from the source DB
- Lowest cost profile at current volumes: Composer environment baseline plus BigQuery on-demand LOAD JOB costs with no serverless compute surcharge per execution
- Fastest time-to-delivery: all logic is expressed as standard Airflow DAG operators familiar to any Airflow-literate engineer, with no Beam or Spark skill ramp required
- Fully observable at task granularity in the Airflow UI with native retry, SLA miss callback, and email/PagerDuty alerting out of the box

### Cons

- Airflow worker memory and CPU limits constrain single-task extraction chunk size; tables exceeding ~5GB per chunk require careful LIMIT/OFFSET or keyset pagination strategy to avoid worker OOM
- Extraction throughput is bound by Airflow worker resources rather than horizontally scaled distributed compute — vertical scaling of the Composer environment is the only lever if volumes grow significantly
- PostgresHook maintains a persistent JDBC connection to the source DB for the duration of each extraction task; PostgreSQL max_connections and statement_timeout must be tuned to accommodate concurrent DAG task executions
- No built-in schema evolution detection — DDL changes on PostgreSQL source tables (column additions, type changes, renames) require manual DAG updates and BigQuery schema alterations, risking silent data corruption if undetected
- Hard-deleted rows in PostgreSQL are not propagated to BigQuery by the watermark-based incremental strategy; stale deleted records persist in BigQuery indefinitely unless a separate full-reconciliation cadence is implemented

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | Watermark-based incremental extraction on updated_at will silently miss records that are physically deleted from PostgreSQL (hard deletes) or whose updated_at is back-dated or not updated on all write paths. If any ETL process or direct DB write omits updating updated_at, those records will be missed until the next full table reload. |
| Scaling | If daily incremental volume grows significantly beyond 500MB (e.g., to 5GB+) or if the total dataset exceeds ~100GB, single Airflow worker extraction may approach or breach the 03:00 AM UTC SLA window without vertical scaling of the Composer environment. No automatic horizontal scale-out path exists within the Airflow task execution model. |
| Latency | Network latency, transient TCP failures, or DNS resolution issues between GCP Composer workers and the on-premises catalog-db.corp.com:5432 will delay or abort extraction. Without idempotent checkpointing within a single extraction task, a mid-extraction network failure requires a full task retry from the beginning of the chunk. |
| Cost | If the GCS lifecycle policy is misconfigured or the cleanup task fails, Parquet staging files accumulate indefinitely and incur unbounded GCS storage cost. Cloud Composer environment incurs a 24/7 baseline cost regardless of pipeline execution frequency. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 8 | 7 | 9 | 8 | 9 | **8.05** |

---

## Option 2 — Cloud Composer + Dataflow (Apache Beam JdbcIO) → BigQuery

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 DAG triggers per-table Dataflow Flex Template jobs via DataflowStartFlexTemplateOperator. Each Flex Template encapsulates an Apache Beam pipeline with a JdbcIO source connecting to PostgreSQL via the official PostgreSQL JDBC driver. On first run, four parallel full-table Dataflow jobs extract all 4 source tables (~20GB total). On subsequent daily runs, watermark-filtered Dataflow jobs extract incremental records from products and inventory; separate full-read jobs process categories and suppliers. All jobs write extracted records to a transient BigQuery staging dataset using BigQueryIO with WRITE_APPEND disposition. |
| Processing | After all Dataflow jobs complete (polled via DataflowJobStateSensor), Cloud Composer triggers BigQueryInsertJobOperator tasks executing parameterized MERGE SQL statements that UPSERT from each staging table into the corresponding target table in verizon_catalog_deah on primary key. COUNT(*) reconciliation tasks query PostgreSQL source counts via PostgresHook and compare against BigQuery target counts. Pipeline run results are written to pipeline_audit.pipeline_run_log via a final BigQueryInsertJobOperator task. |
| Storage | GCS serves as the Dataflow temporary and shuffle location for intermediate records. A transient BigQuery staging dataset (_stg_verizon_catalog) holds pre-MERGE extractions and is truncated after each successful MERGE cycle. BigQuery dataset verizon_catalog_deah stores the four production tables partitioned by ingestion_date and clustered on primary key columns. |
| Consumption | BI tools and BigQuery SQL clients access verizon_catalog_deah directly for product performance reporting and inventory trend analysis. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Composer 2 (DataflowStartFlexTemplateOperator) + Apache Beam JdbcIO (PostgreSQL JDBC driver) | Beam 2.55+ / Dataflow Runner v2 | Yes |
| Processing | Dataflow (Apache Beam Runner v2) + BigQuery MERGE SQL via BigQueryInsertJobOperator | Dataflow Runner v2 / Beam 2.55+ | Yes |
| Storage | GCS (Dataflow temp/shuffle) + BigQuery verizon-data.verizon_catalog_deah + transient staging dataset | — | Yes |
| Orchestration | Cloud Composer 2 | Composer 2.x / Airflow 2.7+ | Yes |
| Monitoring | Cloud Monitoring + Dataflow Monitoring UI + Cloud Logging + Airflow UI | — | Yes |
| Iac | Terraform | >=1.5 | No |

### Pros

- Dataflow auto-scaling (Horizontal Autoscaling + Flexible Resource Scheduling) provides elastic horizontal compute for large full historical loads and accommodates significant future volume growth without architecture changes
- Parallel per-table Dataflow jobs during the 20GB historical load can saturate available network bandwidth and process all tables concurrently, reducing total historical load wall-clock time
- Fully managed Dataflow service eliminates cluster lifecycle management — no explicit create/delete cluster tasks required in the DAG
- Apache Beam JdbcIO handles JDBC connection pooling, read retries, and partial-failure recovery more robustly than raw psycopg2 at scale
- Dataflow Shuffle service reduces GCS I/O cost for large-scale GroupByKey and reshuffle operations if complex transformations are added in future iterations

### Cons

- Highest development overhead of the three options: Apache Beam Flex Template pipelines must be authored in Python or Java, containerized, pushed to Artifact Registry, and registered before the first DAG run — significant pre-delivery effort
- Disproportionate cost for 500MB daily incremental workloads: Dataflow per-vCPU/hour pricing plus Dataflow Shuffle billing creates a cost structure poorly matched to small, frequent batch jobs
- Dataflow job startup latency (typically 2-4 minutes per job) consumes a material portion of the 2-hour SLA window and adds non-trivial overhead for small tables like categories and suppliers
- JdbcIO parallelism against a live PostgreSQL operational database requires careful max_num_workers bounding and partitionColumn/numPartitions configuration to prevent source DB connection saturation
- Three-surface debugging complexity: DAG failures may originate in Composer, Dataflow worker, or BigQuery — requiring engineers to correlate logs across Airflow UI, Dataflow Monitoring UI, and Cloud Logging simultaneously

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | JdbcIO partitioned reads require a numeric split column with approximately uniform value distribution across workers. Skewed primary key distributions cause uneven partition sizes, leading to worker stragglers, potential read timeouts on large partitions, or duplicate boundary-row reads if partition bounds are not computed precisely. |
| Scaling | Dataflow auto-scaling is optimized for throughput maximization, not for protecting a transactional OLTP source. Aggressive parallelism without explicit max_num_workers and connection throttling may spike concurrent connections on catalog-db.corp.com beyond its max_connections limit, causing pipeline failure and source DB instability. |
| Latency | Dataflow job startup overhead (2-4 min) plus worker warm-up time reduces the effective extraction and processing window. For very small tables (categories, suppliers), the job overhead may exceed actual extraction time, making Dataflow economically irrational for those specific table loads. |
| Cost | Running 4 separate Dataflow jobs nightly for a total of ~500MB incremental data creates 4x the per-job startup overhead (VM allocation, shuffle service initialization) and results in cost-per-GB metrics significantly higher than equivalent BigQuery LOAD JOB or direct Airflow extraction approaches. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 6 | 9 | 6 | 8 | 7 | **7.15** |

---

## Option 3 — Cloud Composer + Dataproc Ephemeral PySpark Cluster → BigQuery

**Pattern:** Batch

### End-to-End Flow

| Stage | Description |
|---|---|
| Ingestion | Cloud Composer 2 DAG provisions an ephemeral Dataproc cluster at pipeline start via DataprocCreateClusterOperator. PySpark jobs are submitted via DataprocSubmitJobOperator; each job reads from PostgreSQL using the PySpark JDBC connector (PostgreSQL JDBC driver distributed across workers via --jars). On first run, 4 parallel PySpark jobs perform full historical extractions of all source tables (~20GB). On daily incremental runs, watermark-filtered JDBC reads extract new/updated records from products and inventory; full-read jobs handle categories and suppliers. Extracted DataFrames are written to GCS as Parquet files via df.write.parquet(). |
| Processing | Post-Spark, Cloud Composer triggers BigQueryInsertJobOperator LOAD JOBs from GCS Parquet files into BigQuery staging tables, followed by parameterized MERGE SQL statements for UPSERT into target tables. COUNT(*) reconciliation and pipeline_audit.pipeline_run_log writes are executed as Composer Python tasks after the Dataproc cluster is terminated (DataprocDeleteClusterOperator) to ensure cluster cost is not incurred during reconciliation I/O. |
| Storage | GCS stores Spark intermediate output Parquet files and Dataproc staging artifacts. BigQuery dataset verizon_catalog_deah stores the four production tables partitioned by ingestion_date and clustered on primary key columns. The ephemeral Dataproc cluster is deleted after each successful pipeline run to minimize compute cost. |
| Consumption | BI tools and BigQuery SQL clients access verizon_catalog_deah for product performance reporting and inventory trend analysis. |

### Tool Stack

| Component | Tool | Version | Managed |
|---|---|---|---|
| Ingestion | Cloud Composer 2 (DataprocCreateClusterOperator + DataprocSubmitJobOperator) + PySpark JDBC (PostgreSQL JDBC driver) | Dataproc 2.1 / Spark 3.4+ | Yes |
| Processing | Dataproc PySpark (ephemeral cluster) + BigQuery LOAD JOB + MERGE SQL via BigQueryInsertJobOperator | Dataproc 2.1 / Spark 3.4+ | Yes |
| Storage | GCS (Parquet intermediate, Spark staging) + BigQuery verizon-data.verizon_catalog_deah | — | Yes |
| Orchestration | Cloud Composer 2 | Composer 2.x / Airflow 2.7+ | Yes |
| Monitoring | Cloud Monitoring + Dataproc Job UI + Spark History Server + Cloud Logging | — | Yes |
| Iac | Terraform | >=1.5 | No |

### Pros

- Spark distributed in-memory processing handles the 20GB historical load with high parallelism and can be right-sized for faster initial load completion relative to single-worker extraction
- Ephemeral cluster pattern (create-at-start, delete-at-end) avoids 24/7 VM cost — compute billing is restricted to active processing time only
- PySpark provides the richest ecosystem for complex future transformations, window functions, cross-table joins, and advanced data quality checks if analytical requirements expand significantly
- Dataproc Serverless for Spark (if applicable to JDBC workloads) could eliminate cluster management overhead entirely in a future iteration

### Cons

- Highest operational complexity of all three options: Dataproc cluster lifecycle management (create, configure, monitor, delete), JDBC driver --jars distribution, Spark executor memory/parallelism/shuffle tuning, and Spark History Server log management all require dedicated Spark engineering expertise
- Cluster bootstrap time (typically 3-5 minutes) plus Spark application initialization overhead adds fixed latency to every pipeline run, consuming a material portion of the 2-hour SLA window before any extraction begins
- Most expensive option at current data volumes: Dataproc VM-hours (master + worker nodes) for 500MB daily incremental workloads represent a severe cost-per-GB inefficiency relative to Option 1 and Option 2
- PySpark JDBC reads require careful partition configuration (numPartitions, lowerBound, upperBound, partitionColumn) — incorrect values cause data skew, duplicate boundary rows, or missed records entirely
- Broadest required skill set: pipeline development, debugging, and incident response require simultaneous expertise in Airflow, PySpark, Dataproc, GCS, and BigQuery — the largest cross-functional knowledge demand of all options
- If the DataprocDeleteClusterOperator task fails (e.g., due to an upstream task exception in the finally block), Dataproc VMs continue running and incur cost until manually terminated; requires robust DAG error-handling and Dataproc cluster auto-delete TTL configuration as a safety net
- Four-surface debugging complexity: failures span Composer DAG, Dataproc cluster management, Spark executor logs (Spark UI / History Server), GCS writes, and BigQuery operations — the highest incident mean-time-to-resolution of all options

### Option Risks

| Risk Area | Description |
|---|---|
| Data Quality | PySpark JDBC partition bounds (lowerBound, upperBound) must be statically configured or dynamically computed per run. Misconfigured bounds cause data skew (most records on a single executor), missing boundary rows, or duplicated records across partition edges. JDBC schema inference may produce type mismatches between PostgreSQL types (e.g., NUMERIC, TIMESTAMP WITH TIME ZONE) and Spark DataTypes, requiring explicit schema definition to prevent silent precision loss. |
| Scaling | Ephemeral cluster right-sizing is an iterative empirical process; an under-sized cluster (insufficient executors or executor memory) during the 20GB historical load may breach the SLA window. No automatic horizontal scale-out equivalent to Dataflow Horizontal Autoscaling exists for Dataproc batch JDBC reads without manual cluster reconfiguration. |
| Latency | Cluster bootstrap latency (3-5 minutes) plus Spark job initialization (30-60 seconds) consumes 10-15% of the 2-hour SLA window before extraction begins. For 500MB daily incremental, total pipeline wall-clock time including cluster lifecycle may approach 20-30 minutes on a minimally-sized cluster, reducing the available buffer before the SLA deadline. |
| Cost | Cluster teardown failures leave Dataproc VMs running indefinitely, incurring unbudgeted VM-hour costs. Even with auto-delete configured, improperly handled DAG failure modes may prevent the delete task from executing. Dataproc cluster cost for a nightly 500MB incremental batch represents among the highest cost-per-GB of any GCP data processing option. |

### Scores

| Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | Weighted Score |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 5 | 8 | 5 | 7 | 6 | **6.15** |

---

## Scoring Table

| Option | Cost (×0.30) | Scalability (×0.25) | Complexity (×0.20) | Latency (×0.15) | Operability (×0.10) | **Weighted Score** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Cloud Composer Native Batch Pipeline (PostgresHook → GCS → BigQuery MERGE) ✅ | 8 | 7 | 9 | 8 | 9 | **8.05** |
| Cloud Composer + Dataflow (Apache Beam JdbcIO) → BigQuery | 6 | 9 | 6 | 8 | 7 | **7.15** |
| Cloud Composer + Dataproc Ephemeral PySpark Cluster → BigQuery | 5 | 8 | 5 | 7 | 6 | **6.15** |

> `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Recommended Architecture

**Cloud Composer Native Batch Pipeline (PostgresHook → GCS → BigQuery MERGE)**
**Weighted Score: 8.05**

**Justification:** Option 1 is the optimal architecture for the Product Catalog Analytics Platform. It directly satisfies every stated functional requirement — full historical load, watermark-based daily incremental sync, full reload for reference tables, UPSERT via BigQuery MERGE, COUNT(*) reconciliation, audit logging to pipeline_audit.pipeline_run_log, and the 03:00 AM UTC SLA — using the preferred Airflow toolchain with no additional managed compute services. The current data profile (~20GB historical, ~500MB daily incremental, batch latency tier) is well within the processing capacity of a properly sized Cloud Composer 2 environment, making the scalability advantages of Dataflow and Dataproc academic rather than practical at this stage. The architecture minimizes cost, operational complexity, required engineering skill breadth, and time-to-delivery while maintaining full GCP managed-service alignment.

**Why highest score:** Option 1 achieves the highest weighted score of 8.05 by excelling in the three highest-weighted evaluation dimensions: Cost (8/10, weight 0.30) — no serverless compute surcharge; the pipeline runs exclusively on Cloud Composer and BigQuery LOAD JOBs, which are among the lowest-cost GCP data services at this volume. Complexity (9/10, weight 0.20) — the entire pipeline is expressed as a single Airflow DAG using native operators (PostgresHook, BigQueryInsertJobOperator) with no Beam pipelines, Flex Templates, or Spark cluster management. Operability (9/10, weight 0.10) — atomic, independently retriable tasks, native Airflow SLA callbacks, a single observability surface (Composer UI + Cloud Logging), and no distributed framework to debug. Latency (8/10, weight 0.15) is comfortably met: 500MB incremental Parquet load and BigQuery MERGE complete in under 15 minutes on a standard Composer 2 environment. Only Scalability is rated below Options 2 and 3 (7 vs. 9 and 8 respectively), but this gap is an accepted trade-off given that current volumes do not justify distributed compute overhead.

**Trade-offs accepted:** The lower Scalability score (7/10) relative to Dataflow Option 2 (9/10) is explicitly accepted for three reasons: (1) Current and 12-month projected volumes (~500MB/day) are comfortably within Airflow worker extraction capacity with appropriate chunking, leaving headroom before any SLA risk materializes. (2) Vertical scaling of the Cloud Composer environment (increasing worker CPU/RAM or worker count) is a straightforward, low-disruption operational lever available before a full architectural pivot to Dataflow is warranted. (3) The cost and complexity savings from eliminating Dataflow Flex Template development, Artifact Registry container management, and Beam job monitoring deliver immediate, tangible value that outweighs a marginal scalability hedge at sub-1GB daily incremental volumes. Hard-delete non-propagation is also accepted as a known limitation pending stakeholder confirmation of whether delete propagation is a business requirement.

---

## Rejected Options

### Cloud Composer + Dataflow (Apache Beam JdbcIO) → BigQuery

Rejected in favor of Option 1. Dataflow's primary value proposition — horizontal auto-scaling for high-throughput distributed processing — is unnecessary and cost-inefficient at the current data profile (~20GB historical, ~500MB daily incremental). The Apache Beam Flex Template development overhead, Artifact Registry container management, per-job startup latency (2-4 minutes), and disproportionate per-vCPU/hour pricing for small batch workloads introduce cost and complexity penalties that are not justified by any functional or non-functional requirement at current volumes. Option 1 achieves identical functional outcomes with a simpler, lower-cost, and more operable single-tool architecture. Dataflow should be revisited only if daily incremental volume grows beyond ~5GB or if sub-30-minute processing SLAs are imposed in a future phase.

### Cloud Composer + Dataproc Ephemeral PySpark Cluster → BigQuery

Rejected in favor of Option 1. Dataproc PySpark introduces the highest cost, complexity, latency overhead, and operational risk of all three options for a pipeline that is fundamentally simple: extract from one PostgreSQL source, stage to GCS, and load to BigQuery with UPSERT semantics. The Spark skill requirement, cluster lifecycle management, JDBC partition tuning, 3-5 minute cluster bootstrap fixed latency, and four-surface debugging complexity are entirely unwarranted at 500MB daily incremental volumes. The ephemeral cluster pattern does not mitigate cost sufficiently — Dataproc VM-hours for nightly 500MB loads remain the most expensive per-GB option. Option 1 achieves all functional and non-functional requirements with a fraction of the operational surface area and cost.

---

## Risks & Mitigations

| Risk | Description | Mitigation |
|---|---|---|
| Network Connectivity | The PostgreSQL source (catalog-db.corp.com:5432) resides outside GCP. Any Cloud VPN tunnel degradation, BGP route withdrawal, firewall rule misconfiguration, DNS resolution failure, or TCP timeout between Cloud Composer worker VMs and the source host will abort the extraction phase entirely, causing a full pipeline SLA breach with no partial data available in BigQuery. | Provision Cloud VPN with BGP routing or Cloud Interconnect with redundant tunnels for reliable private connectivity. Configure Airflow PostgresHook retry with exponential backoff (3 retries, 60-second delay). Implement Cloud Monitoring uptime checks on catalog-db.corp.com:5432 with alerting thresholds set to fire 30 minutes before the pipeline execution window begins at 01:00 AM UTC so on-call engineers can investigate proactively. |
| Schema Drift | Unannounced DDL changes on PostgreSQL source tables — column additions, data type changes, column renames, or column drops — will propagate as BigQuery load job failures (type mismatch) or silent data corruption (missing columns defaulting to NULL) without a schema change detection gate in the pipeline. | Implement a pre-extraction schema fingerprint check as the first DAG task: query PostgreSQL information_schema.columns for all 4 tables and compare column names and data types against a stored baseline snapshot; fail the DAG with a P1 alert if drift is detected before any extraction begins. Establish a formal change management process requiring data engineering sign-off on DDL changes to any of the 4 source tables. |
| Incremental Completeness — Hard Deletes | Watermark-based incremental extraction on updated_at captures INSERT and UPDATE operations but cannot detect or propagate physical DELETE operations from PostgreSQL source tables. Hard-deleted rows will persist indefinitely in BigQuery target tables, resulting in stale analytical data for product status, inventory quantities, and supplier records. | Explicitly document the hard-delete limitation in the data dictionary and data SLA agreement. Confirm with stakeholder John whether hard-delete propagation is a business requirement. If required, evaluate either (a) weekly full reload of products and inventory as a reconciliation cadence or (b) enabling PostgreSQL logical replication and introducing a CDC layer (e.g., Debezium) in a future platform phase. Implement a monthly row-count trend alert that flags anomalous growth deceleration as a proxy indicator of potential delete accumulation. |
| Operational Database Load | Extraction queries running against a live PostgreSQL OLTP database during low-traffic hours may still contend with background autovacuum, streaming replication, or scheduled maintenance tasks. Full historical reload queries on large tables (products, inventory) may hold AccessShareLocks for extended periods, impacting concurrent OLTP write latency. | Schedule all extraction tasks to execute during the lowest-traffic window (01:00 AM–03:00 AM UTC). Use keyset-based chunked cursor reads (WHERE pk > :last_pk LIMIT :chunk_size) rather than OFFSET pagination to minimize lock duration per query. Set statement_timeout and lock_timeout session parameters on the extraction connection at the Airflow connection level. Coordinate the initial 20GB historical load timing with the source DB DBA to avoid overlap with maintenance windows. |
| Pipeline SLA Breach | The 2-hour processing window (01:00–03:00 AM UTC) is adequate at current volumes but provides limited headroom. Compounding factors — slower-than-expected network throughput, PostgreSQL query plan degradation on large incremental extracts, BigQuery MERGE duration growth as target tables scale, or COUNT(*) reconciliation query timeout — could individually or cumulatively cause the DAG to miss the 03:00 AM UTC SLA. | Configure DAG-level execution_timeout set to 110 minutes (buffer before 03:00 AM) and task-level sla parameters in Airflow with email and PagerDuty callbacks. Instrument each task with Cloud Logging duration metrics and create Cloud Monitoring dashboards tracking DAG p95 execution time trends. Conduct a monthly SLA capacity review; proactively right-size the Composer worker pool or implement table-level parallel extraction task groups if p95 DAG duration exceeds 90 minutes. |
| Cost Governance | Cloud Composer environments incur a 24/7 baseline cost regardless of pipeline execution frequency. BigQuery MERGE statement slot consumption on growing tables, GCS staging file accumulation from lifecycle policy misconfiguration, and unmonitored BigQuery query costs from downstream consumers accessing verizon_catalog_deah may cause budget overruns without active cost controls. | Apply and verify GCS lifecycle policies (7-day TTL) on the staging bucket via Terraform. Tag all pipeline GCP resources (Composer environment, GCS bucket, BigQuery dataset) with cost-center and project labels for GCP Billing attribution. Set BigQuery dataset-level billing project controls and implement Cloud Billing budget alerts at 80% and 100% of the monthly pipeline cost estimate. Review BigQuery on-demand query costs for downstream consumer queries and recommend reservation slots if query costs exceed threshold. |

---

## Assumptions

1. GCP project verizon-data has BigQuery, GCS, Cloud Composer, Secret Manager, Cloud Monitoring, and Cloud Logging APIs enabled with active billing configured in the target region
2. Network connectivity between Cloud Composer worker VMs and catalog-db.corp.com:5432 is established via Cloud VPN with BGP routing or Cloud Interconnect; public internet exposure of the PostgreSQL host is not assumed and is not an accepted connectivity model
3. The PostgreSQL service account 'sa' has at minimum SELECT privileges on all 4 source tables (products, categories, suppliers, inventory) in schema public of database product_db, with no row-level security policies that would silently filter rows during extraction
4. The updated_at columns in the products and inventory tables are reliably populated on every INSERT and UPDATE operation by all write paths (application, ORM, and direct DB writes), and are indexed with a B-tree index to support efficient watermark predicate pushdown without sequential scans
5. Primary keys are defined, enforced (NOT NULL + UNIQUE constraint), and stable (not recycled or reassigned) in all 4 source tables to support idempotent BigQuery MERGE operations without risk of false-positive matches
6. The BigQuery dataset verizon_catalog_deah exists or will be provisioned in project verizon-data in the designated GCP region prior to the first pipeline run, with appropriate IAM permissions granted to the Cloud Composer service account (roles/bigquery.dataEditor minimum)
7. The pipeline_audit.pipeline_run_log BigQuery table exists or will be provisioned as part of this engagement with a defined schema including at minimum: run_id (STRING), table_name (STRING), execution_date (DATE), status (STRING), source_count (INTEGER), target_count (INTEGER), duration_seconds (FLOAT), error_message (STRING)
8. A dedicated GCS staging bucket will be provisioned for this pipeline with a 7-day object lifecycle policy configured to auto-delete Parquet files after confirmed successful BigQuery load, preventing unbounded storage accumulation
9. PostgreSQL credentials for service account 'sa' will be stored as a GCP Secret Manager secret and accessed by Cloud Composer via an Airflow Connection backed by the Secret Manager secrets backend (not stored in plaintext in the Airflow DB or DAG code)
10. Technology environment is assumed to be production given the operational PostgreSQL source and a hard daily SLA; no separate dev or staging environment pipeline deployment is scoped in this document
11. Cloud Composer 2 is assumed as the managed Airflow runtime given the GCP + BigQuery target; the specific Composer environment name, GCP region, and node configuration are to be determined by the platform team
12. BigQuery target tables will be partitioned by ingestion_date (DATE partition type) and clustered on primary key columns to optimize downstream analytical query cost and performance for time-series inventory and catalog reporting patterns
13. The Airflow DAG is scheduled with a cron trigger targeting 01:00 AM UTC providing a 2-hour processing buffer before the 03:00 AM UTC SLA deadline; the Composer environment will be configured with a DAG-level execution_timeout and task-level SLA miss callbacks

---

## Requirement Traceability

| Architecture Decision | Requirement Field | Latency Need | Data Volume |
|---|---|---|---|
| Full historical extraction of all 4 PostgreSQL source tables on first DAG run using PostgresHook chunked reads, staged to GCS Parquet, loaded via BigQuery LOAD JOB | functional_requirements[0]: Perform a full historical load of all 4 source tables (products, categories, suppliers, inventory) on the first pipeline run | batch | ~20GB total |
| Watermark-based incremental extraction using MAX(updated_at) stored as Airflow XCom variable for products and inventory tables on all subsequent daily runs | functional_requirements[1]: Perform daily incremental sync using updated_at watermark for products and inventory tables | < 1 hour from source update to BigQuery availability | ~500MB daily incremental |
| Full daily reload (no watermark filter) for categories and suppliers tables on every pipeline run after the initial historical load | functional_requirements[2]: Perform a full daily reload for categories and suppliers as small reference tables | batch — daily | small reference tables, volume not material |
| BigQuery parameterized MERGE SQL statement executed post-load from transient _stg_ staging table into target table keyed on source primary key, handling both INSERT and UPDATE semantics | functional_requirements[3]: Apply UPSERT logic on primary key in BigQuery to handle late-arriving updates | — | — |
| Cloud Composer 2 DAG scheduled at 01:00 AM UTC with DAG-level execution_timeout of 110 minutes and task-level SLA miss callbacks to guarantee completion before 03:00 AM UTC | functional_requirements[4] / non_functional.performance: Airflow DAG must complete before 03:00 AM UTC every day | batch — 2-hour SLA processing window | ~500MB daily incremental |
| BigQuery target configured as project verizon-data, dataset verizon_catalog_deah, table names: products, categories, suppliers, inventory exactly mirroring source PostgreSQL table names | functional_requirements[5]: Load data into BigQuery project verizon-data, dataset verizon_catalog_deah, into tables mirroring source names | — | — |
| Dedicated terminal Airflow task writes pipeline run metadata (run_id, table_name, execution_date, status, source_count, target_count, duration_seconds, error_message) to pipeline_audit.pipeline_run_log via BigQueryInsertJobOperator after each table load cycle | functional_requirements[6]: Log all pipeline run results to pipeline_audit.pipeline_run_log | — | — |
| Post-MERGE reconciliation Airflow task queries COUNT(*) from PostgreSQL source via PostgresHook and from BigQuery target via BigQueryCheckOperator; raises DAG failure and P1 alert on count mismatch exceeding configurable threshold | functional_requirements[7]: Perform COUNT(*) reconciliation between source and target after every run | — | — |
| Cloud Composer 2 (managed Airflow) selected as orchestration engine, satisfying the explicit preferred_tools: Airflow requirement and aligning with GCP default managed orchestration service | technology.preferred_tools: [Airflow] / inferred_assumptions: Airflow assumed to run on GCP Cloud Composer given BigQuery target on GCP project verizon-data | — | — |
| GCS staging bucket with 7-day object lifecycle TTL configured as durable intermediate layer between PostgreSQL extraction and BigQuery LOAD JOB, enabling task-level retry from GCS without re-extracting from the source | data_requirements.volume: ~20GB total; ~500MB daily incremental — durable intermediate staging required for reliable large-file transfer and replay capability | batch | ~20GB historical / ~500MB daily |
| BigQuery target tables partitioned by ingestion_date (DATE) and clustered on primary key columns to optimize analytical query performance and cost for time-series inventory trend and product performance reporting patterns | objective: downstream product performance reporting and inventory trend analysis for stakeholder John | — | cumulative growth at ~500MB/day |

---

## Open Questions — Action Required

1. What is the precise network connectivity mechanism between the Cloud Composer worker environment and catalog-db.corp.com:5432 — Cloud VPN, Cloud Interconnect, or public internet with TLS? This determines firewall rule scope, connectivity SLA, and whether a VPC-native Composer environment is required.
2. Is hard-delete propagation required? If records are physically deleted from products, inventory, categories, or suppliers in PostgreSQL, must those deletes be reflected in the corresponding BigQuery target tables? The current watermark-based incremental design cannot detect hard deletes; this determines whether a CDC mechanism is required in scope or a future phase.
3. What is the target GCP region for all pipeline resources (Cloud Composer environment, GCS staging bucket, BigQuery dataset verizon_catalog_deah)? Co-locating all resources in a single region eliminates cross-region GCS-to-BigQuery data transfer charges and minimizes latency within the processing pipeline.
4. Does pipeline_audit.pipeline_run_log already exist in BigQuery, and if so, what is its current schema and which BigQuery project and dataset host it? If it does not yet exist, which team (data engineering or DBA) is responsible for provisioning it, and is there a schema standard to conform to?
5. Is an existing Cloud Composer 2 environment available for this pipeline to share, or does a net-new Composer environment need to be provisioned? If sharing, what is the existing environment's worker node configuration, and is there available worker capacity within the execution window without contention from other DAGs?
6. Are there any PII, PCI-DSS, or otherwise sensitive fields in any of the 4 source tables (e.g., supplier bank details, personal contact information embedded in product records) that require column-level masking, BigQuery column-level security policies, or data loss prevention (DLP) scanning before data is accessible to BI consumers?
7. Should the full historical load be a strictly one-time, manually triggered DAG run, or must the DAG support an idempotent on-demand full-reload mode triggerable at any time via an Airflow DAG Run configuration parameter or Airflow Variable? This determines whether truncate-and-reload vs. MERGE-only logic is needed for the historical run path.
8. What is the expected 12-month growth trajectory for the daily incremental volume beyond the baseline 500MB/day? If incremental volume is projected to grow to 5GB/day or beyond, Option 2 (Dataflow) should be revisited as the recommended architecture before significant DAG development investment is made in Option 1.
9. Are there downstream BI dashboards, scheduled queries, or ML feature pipelines consuming verizon_catalog_deah with their own SLA dependencies more stringent than 03:00 AM UTC? If so, the pipeline start time may need to be advanced from 01:00 AM UTC to provide adequate downstream processing buffer.
10. Who is the designated on-call engineer and escalation path for pipeline SLA breach incidents outside business hours? Airflow SLA miss callbacks require a configured SMTP server or PagerDuty integration endpoint — is this already provisioned in the target Cloud Composer environment?
