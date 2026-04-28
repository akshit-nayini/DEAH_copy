# Reviewer Agent

## Persona
Senior data engineer with 20+ years of experience reviewing data pipelines
across GCP, AWS, and enterprise platforms. Pragmatic reviewer: enforces
correctness, security, and data integrity with CRITICAL findings, but does
not penalise early-development code for aspirational best practices or
incomplete edge-case handling.

## Purpose
Self-reviews generated (or existing) artifacts across up to five dimensions
and produces a structured report with severity-rated findings.

## Review Dimensions
| Dimension | Active When | Description |
|-----------|-------------|-------------|
| `syntax` | Always | SQL/Python syntax, imports, unclosed brackets, keyword errors |
| `audit_compliance` | Only if `plan.audit_table.enabled = true` | Verifies audit table DDL completeness and sp_log_audit calls in DAGs |
| `data_integrity` | Always | MERGE correctness, WRITE_TRUNCATE on staging, task dependency order |
| `pii_encryption` | Only if PII columns in plan | PII column exposure in core tables, missing policy tag comments |
| `logic_preservation` | Mode 2 only (`review_optimized`) | Compares ORIGINAL vs OPTIMIZED — catches business logic drift |

## Token Strategy
Per-artifact review: one LLM call per artifact, only active dimensions.
- Plan block is cached throughout (established by the Generator).
- Inactive dimensions (`audit_compliance` when audit disabled, `pii_encryption`
  when no PII in plan) are excluded from every call — fewer tokens, faster responses.
- All artifact reviews run concurrently via `ThreadPoolExecutor`.

## Parallelism (full pipeline)
In the full pipeline, SQL artifact review runs **in parallel** with DAG optimization:
- `ReviewerAgent.review(sql_arts)` and `OptimizerAgent.optimize(dag_arts)` run concurrently.
- DAG artifacts are reviewed after optimization completes.
- This halves the wall-clock time for mixed SQL+DAG pipelines.

## Input
| Field | Type | Description |
|-------|------|-------------|
| `ctx` | `SessionContext` | `plan` optional — used as context when available |
| `artifacts` | `list[GeneratedArtifact]` | Artifacts to review |
| `original_artifacts` | `list[GeneratedArtifact]` | Required for `review_optimized()` |
| `optimized_artifacts` | `list[GeneratedArtifact]` | Required for `review_optimized()` |

## Methods
- `review(ctx, artifacts)` — reviews across active dimensions only (syntax, data_integrity, + conditional audit_compliance / pii_encryption)
- `review_optimized(ctx, original, optimized)` — standard review + logic_preservation comparison

## Output — `list[ReviewResult]`
Each `ReviewResult` has:
- `dimension` — review dimension name
- `verdict` — `PASS` | `CONDITIONAL_PASS` | `FAIL`
- `summary` — one-paragraph verdict
- `findings` — list of `ReviewFinding` (severity, check_name, file_name, description, suggested_fix)

## Quality scoring
```
score = 100 − (10 × CRITICAL) − (3 × WARNING) − (1 × INFO)
```
Development-phase thresholds (lenient — this is not production code):
- 70–100: Healthy — proceed
- 50–69: Warnings present — human should review
- < 50: Critical findings — fix before approving

## ASSUMPTION markers
`# ASSUMPTION:` and `-- ASSUMPTION:` lines are WARNING (intentional early-dev flags).
Only `-- CANNOT GENERATE:` lines are CRITICAL.

## Run standalone
```bash
cd DEAH/core/development

# Review artifacts in a directory
python agents/reviewer/run_agent.py \
    --dir output/req-abc123/ --project my-project --dataset my_dataset

# Logic preservation review (original vs optimized)
python agents/reviewer/run_agent.py \
    --original output/req-abc123/original/ \
    --optimized output/req-abc123/optimized/ \
    --project my-project --dataset my_dataset
```
