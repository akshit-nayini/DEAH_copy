# Deployer Agent

## Purpose
Applies approved code-gen artifacts to GCP. Runs pre-deploy connectivity
checks first, then applies artifacts in order: audit table → BigQuery DDL
→ stored procedures → Composer DAGs → Dataflow template.

## Input — `DeployInput`
| Field | Description |
|-------|-------------|
| `request_id` | ID of the code-gen run whose artifacts are being deployed |
| `artifacts_dir` | Path to `output/<request_id>/` (contains `ddl/`, `sp/`, `dag/`, `pipeline/`) |
| `project_id` | GCP project ID |
| `dataset_id` | Target BigQuery dataset |
| `region` | GCP region (default: us-central1) |
| `dag_bucket` | GCS bucket name for Composer DAGs |
| `composer_environment` | Cloud Composer environment name |
| `source_db_*` | Optional source DB connection for pre-deploy TCP probe |

## Output — `DeployOutput`
| Field | Description |
|-------|-------------|
| `validation` | List of `ValidationResult` (bigquery, gcs_dag_bucket, composer_env, …) |
| `steps` | List of `DeployStepResult` (create_audit_table, apply_bq_ddl, apply_sp, upload_dags, …) |
| `overall_status` | `success` \| `failed` \| `skipped` |

## Behaviour
1. `PreDeployValidator.validate()` runs **all** connectivity checks unconditionally.
2. If **any** check is FAIL → deploy aborts; no GCP changes are made.
3. All checks PASS or SKIPPED → deploy steps execute in order.
4. Steps that have no corresponding artifacts directory are automatically SKIPPED.

## Run standalone
```bash
cd DEAH/core/development

python agents/deployer/run_agent.py \
    --artifacts-dir output/req-abc123 \
    --project my-gcp-project --dataset my_dataset \
    --region us-central1 \
    --dag-bucket my-dag-bucket \
    --composer-env my-composer-env
```

## Environment variables
| Variable | Required | Description |
|----------|----------|-------------|
| `DB_PASSWORD` | Optional | Source DB password — read at runtime, never stored |
