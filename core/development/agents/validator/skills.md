# PreDeploy Validator Agent

## Purpose
Runs six connectivity and service availability checks before any GCP
artifacts are applied. If any check fails, the Deployer agent aborts
immediately without touching GCP.

## Checks
| Check | What it verifies |
|-------|-----------------|
| `bigquery` | BigQuery API is accessible and the target dataset exists |
| `gcs_dag_bucket` | GCS bucket for Composer DAGs is accessible |
| `composer_env` | Cloud Composer environment is running |
| `dataflow_api` | Dataflow API is enabled on the project |
| `secret_manager` | Secret Manager API is accessible |
| `source_db` | TCP connection to source DB host:port succeeds |

## Behaviour
- All six checks run unconditionally (no short-circuit on first failure).
- Checks are SKIPPED (not FAIL) when the relevant config field is empty
  (e.g. `dag_bucket=""` → `gcs_dag_bucket=SKIPPED`).
- `source_db` check is SKIPPED unless both `source_db_host` and
  `DB_PASSWORD` env var are set.

## Run standalone
```bash
cd DEAH/core/development

python agents/validator/run_agent.py \
    --project my-gcp-project --dataset my_dataset \
    --region us-central1 \
    --dag-bucket my-dag-bucket \
    --composer-env my-composer-env
```
