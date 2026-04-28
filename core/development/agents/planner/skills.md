# Planner Agent

## Persona
Senior data engineer with 20+ years of experience designing large-scale data
pipelines across GCP, AWS, and on-premise platforms. Deeply familiar with
BigQuery architecture, Airflow orchestration, SCD patterns, partitioning
strategies, and data governance.

## Purpose
Reads `Implementation.md` + `mapping.csv` (from the Design Pod) and produces
a structured `ExecutionPlan` that lists every artifact to generate, every
target table, data engineering patterns, PII columns, and any clarifying
questions that must be answered before code generation can proceed.

The plan is written to `output/<request_id>/PLAN.md` immediately after
generation so the user can open, review, and annotate it before approving.
Missing information can be added via the `revise` prompt at Checkpoint 1.

## Input
| Field | Type | Description |
|-------|------|-------------|
| `implementation_md` | string | Raw content of Implementation.md or requirements.json (auto-detected) |
| `mapping_csv` | string | Raw content of mapping.csv or table_schema.csv (auto-detected) |
| `project_id` | string | GCP project ID |
| `dataset_id` | string | Target BigQuery dataset ID |
| `environment` | string | `dev` \| `qa` \| `prod` |
| `human_notes` | list[str] | Corrections or answers from checkpoint revision loop |

## Output — `ExecutionPlan`
| Field | Description |
|-------|-------------|
| `summary` | One-paragraph pipeline description |
| `artifacts_to_generate` | **Only** files explicitly required by the requirements doc |
| `tables` | Fully-qualified BigQuery target tables mentioned in requirements |
| `audit_table` | Populated (`enabled=true`) **only** if requirements explicitly mention audit |
| `store_proc` | Populated only when audit is required |
| `patterns` | Data engineering patterns (SCD Type 1, full-load, @hourly, etc.) |
| `pii_columns` | Only columns explicitly classified as PII in mapping CSV or requirements |
| `open_blockers` | Deployment/governance gates (do NOT block code generation) |
| `clarifying_questions` | `[BLOCKER]` questions that gate code generation |
| `raw_plan` | Full LLM output shown to human at Checkpoint 1 |

## Behaviour
- **Pre-flight validation**: checks inputs before spending tokens; returns
  blockers immediately if `implementation_md` is too short, CSV is empty, or
  required columns are missing.
- **No-assumption policy**: raises `[BLOCKER]` questions for any item the LLM
  is < 95% confident about. Smart defaults are applied (and marked with
  `← [assumed: ...]`) for staging load pattern, deduplication, credentials, etc.
- **Strict artifact scope**: only lists artifacts explicitly required by the
  implementation document. Does NOT add audit DDL, quarantine tables, config
  files, or stored procedures unless the requirements doc explicitly mentions them.
- **DAG files**: only generates DAG file entries that are explicitly named in
  the requirements document. NEVER derives or invents extra DAG files.
- **Tables**: only lists tables explicitly named or described in the requirements.
  NEVER adds staging (stg_*) tables, quarantine tables, dead-letter tables, or
  any other table not explicitly required — even if such tables would be
  conventional for the pipeline pattern.
- **Conditional audit**: `audit_table.enabled=true` is set only when the
  requirements document explicitly mentions audit logging or pipeline tracking.
  When absent, `audit_table` is empty and downstream agents skip all audit generation.
- **PII classification**: only lists columns explicitly marked `is_pii=True`
  in the mapping CSV or explicitly described as sensitive in requirements.
  Does NOT infer PII from column names alone. Does NOT raise PII, data
  sensitivity, security audits, or compliance topics as blockers or clarifying
  questions unless the requirements document explicitly addresses them.
- **BLOCKER questions gate approval** at Checkpoint 1. `open_blockers` are
  deployment gates and do NOT prevent code generation.

## Token strategy
`implementation_md` and `mapping_csv` are sent as `cacheable=True` context
blocks. Anthropic caches them server-side for ~5 minutes so the Generator,
Optimizer, and Reviewer calls reuse the same cached prefix.

## Run standalone
```bash
cd DEAH/core/development
python agents/planner/run_agent.py \
    --impl ../../de_development/requirements/Migration_mvp1/requirements.md \
    --mapping ../../de_development/requirements/Migration_mvp1/table_schema.csv \
    --project my-gcp-project --dataset my_dataset
```
