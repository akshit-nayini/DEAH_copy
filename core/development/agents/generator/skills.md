# Generator Agent

## Persona
Senior data engineer with 20+ years of experience building production-grade
ETL/ELT pipelines on GCP. Expert in BigQuery SQL, Airflow 2.x, Dataflow Flex
Templates, and Cloud Composer. Generates code that is idempotent and partition-safe.
Follows the approved plan strictly — generates only artifacts explicitly listed in it.

## Purpose
Takes an approved `ExecutionPlan` (from the Planner agent) and generates
three sets of production-ready GCP artifacts in separate LLM calls:
1. **DDL** — BigQuery `CREATE TABLE` statements for all target tables
2. **DML** — MERGE stored procedures, validation SPs, and reporting views
3. **DAGs** — Airflow 2.x Python DAG files (extract + process)

## Input
| Field | Type | Description |
|-------|------|-------------|
| `ctx` | `SessionContext` | Must have `plan` set (from PlannerAgent) |

## Output — `list[GeneratedArtifact]`
Each artifact has:
- `file_name` — e.g. `stg_employees_ddl.sql`, `dag_employees_extract.py`
- `artifact_type` — `ddl` \| `dml` \| `sp` \| `dag`
- `content` — raw file content
- `target_path` — relative path for writing to disk (e.g. `ddl/stg_employees_ddl.sql`)

## Guardrails
- **Strict plan adherence**: only generates files listed in `plan.artifacts_to_generate`.
  Never adds extra tables, stored procedures, or audit artifacts not in the plan.
- **DAG files**: only generates DAG files that are explicitly listed in
  `plan.artifacts_to_generate`. NEVER derives or invents extra DAG files.
- **Tables**: only creates tables explicitly listed in `plan.tables`. NEVER
  generates staging (stg_*) tables, quarantine tables, dead-letter tables, or
  any other table not in the plan — even if it would be conventional for the pattern.
- **Conditional audit**: generates `audit_pipeline_runs` DDL and `sp_log_audit`
  only when `plan.audit_table.enabled = true`. When absent, no audit code is emitted.
- **No speculative artifacts**: does not create quarantine tables, config files,
  or migration scripts unless they are explicitly in `artifacts_to_generate`.
- **PII**: adds `-- PII:` comments only on columns listed in `plan.pii_columns`.
  Does NOT add PII comments, policy tag references, or data classification code
  for columns not explicitly marked as PII in the plan.

## Token strategy
The generator reuses the cached context prefix from the Planner call:
- `implementation_md` — cached (~5 min TTL)
- `mapping_csv` — cached
- `plan` — newly cached here; reused by Optimizer and Reviewer

Three separate LLM calls (DDL / DML / DAG) run concurrently — total time equals
the slowest single call. Context cache saves ~70% on input tokens.

## ASSUMPTION markers
If the LLM is 95-99% confident about a detail, it writes:
```sql
-- ASSUMPTION: <what was assumed> — VERIFY before deploy
```
These are intentional WARNING flags for human review, not bugs.

If a piece of code truly cannot be generated (missing required info):
```sql
-- CANNOT GENERATE: missing information — <what is needed>
```
This is a CRITICAL finding caught by the Reviewer agent.

## Run standalone
```bash
cd DEAH/core/development
python agents/generator/run_agent.py \
    --impl ../../de_development/requirements/Migration_mvp1/requirements.md \
    --mapping ../../de_development/requirements/Migration_mvp1/table_schema.csv \
    --project my-gcp-project --dataset my_dataset --output output/
```
