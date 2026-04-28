# Optimizer Agent

## Persona
Senior data engineer with 20+ years of experience in query optimisation,
BigQuery cost reduction, and Airflow DAG reliability. Applies best practices
without altering business logic — every change is structural, not semantic.

## Purpose
Applies GCP best-practice structural improvements to Python/DAG artifacts.
One LLM call per artifact, all run concurrently. Returns improved versions
without changing business logic.

## Scope — when the optimizer runs
| Artifact type | First generation | Revision | Standalone mode |
|---------------|-----------------|----------|-----------------|
| DDL           | **Skipped** — generator applies best practices | Skipped | Optimized |
| DML           | **Skipped** — generator applies best practices | Skipped | Optimized |
| SP (Stored Procedure) | **Optimized** — complex SQL benefits from structural improvements | Optimized | Optimized |
| DAG / Python  | **Optimized** — retries, Variable.get(), logging | Optimized | Optimized |
| Pipeline      | **Optimized** | Optimized | Optimized |

**Rationale**: DDL and DML are straightforward statements where the Generator
already enforces BigQuery best practices (partitioning, `SAFE_CAST`, MERGE
column-change conditions). Running the optimizer on them adds latency with no
measurable benefit. Stored procedures and Python DAGs contain complex logic
where structural improvements (filter-before-join, retry policies, etc.) add real value.

## Input
| Field | Type | Description |
|-------|------|-------------|
| `ctx` | `SessionContext` | `plan` optional — used as cached context when available |
| `artifacts` | `list[GeneratedArtifact]` | Artifacts to optimize (DDL, DML, SP, DAG, Pipeline) |

## Output — `list[GeneratedArtifact]`
Same list, with `content` replaced by the optimized version.
If the LLM cannot improve an artifact, the original content is preserved.

## What it improves

**SQL (DDL / DML / Stored Procedure)**
- Moves predicates into CTEs (filter-before-join)
- Ensures `QUALIFY ROW_NUMBER() = 1` for deduplication
- Adds `require_partition_filter = true` where missing
- Adds column-change condition to bare `WHEN MATCHED` in MERGE
- Ensures `SAFE_CAST` for uncertain data quality
- Preserves all `-- ASSUMPTION:` comments (never removes them)

**Python / Airflow DAG**
- Adds `retries`, `retry_delay`, `dagrun_timeout` if missing
- Replaces hardcoded credentials with `Variable.get()` calls
- Ensures `ExternalTaskSensor` has `timeout` and `poke_interval`
- Adds structured JSON logging

## Modes
- **Full pipeline**: plan is available → plan cached; optimizer reads from cache
- **Standalone**: plan is `None` → optimizer uses system prompt checklist only

## Run standalone
```bash
cd DEAH/core/development

# Optimize specific files
python agents/optimizer/run_agent.py \
    --files output/req-abc123/ddl/stg_employees.sql \
             output/req-abc123/dag/dag_employees_extract.py \
    --project my-project --dataset my_dataset

# Optimize all artifacts in a directory
python agents/optimizer/run_agent.py \
    --dir output/req-abc123/ --project my-project --dataset my_dataset
```
