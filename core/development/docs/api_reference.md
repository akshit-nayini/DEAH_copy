# DEAH Development Pod — API Reference

**Base URL:** `http://35.209.107.68:8000`

All endpoints accept and return JSON.
`implementation_md` and `mapping_csv` fields carry raw file content (strings), not file paths.

---

## Quick Summary

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/runs` | POST | Start a full code generation pipeline run |
| `/api/v1/runs/{request_id}` | GET | Poll run status and read log messages |
| `/api/v1/runs/{request_id}/checkpoint` | POST | Submit a human decision at a checkpoint |
| `/api/v1/runs` | GET | List all runs (newest first) |
| `/api/v1/optimize-review` | POST | Optimize and review existing code artifacts |
| `/api/v1/deploy` | POST | Trigger deployment of approved artifacts to GCP |
| `/api/v1/deploy/{run_id}` | GET | Get deploy run status |
| `/api/v1/deploy` | GET | List all deploy runs |
| `/healthz` | GET | Health check |

---

## 1. Start a Pipeline Run

### POST /api/v1/runs

Starts a new code generation pipeline run in the background.
The pipeline runs through **Planner → Generator → Optimizer → Reviewer** and pauses at three human checkpoints.
Poll `GET /api/v1/runs/{request_id}` to track progress.

#### Request Body

| Field | Type | Required | Description |
|---|---|---|---|
| `implementation_md` | string | Yes | Raw content of the Implementation.md from the Design Pod |
| `mapping_csv` | string | Yes | Raw content of the mapping.csv / table_schema.csv |
| `project_id` | string | No | GCP project ID (falls back to `PROJECT_ID` env var) |
| `dataset_id` | string | No | BigQuery dataset ID (falls back to `DATASET_ID` env var) |
| `environment` | string | No | `dev` \| `uat` \| `prod` (default: `dev`) |
| `cloud_provider` | string | No | `gcp` \| `aws` \| `azure` \| `snowflake` (default: `gcp`) |
| `region` | string | No | GCP region (default: `us-central1`) |

```json
{
  "implementation_md": "# Implementation\n## Overview\n...",
  "mapping_csv": "source_table,source_column,target_table,target_column\n...",
  "project_id": "my-gcp-project",
  "dataset_id": "customer_360",
  "environment": "dev",
  "cloud_provider": "gcp",
  "region": "us-central1"
}
```

#### Response — `202 Accepted`

| Field | Description |
|---|---|
| `request_id` | UUID — use in all follow-up calls |
| `status` | Initial status: `pending` |
| `output_directory` | Path where artifacts will be written (`/mnt/data/development/{request_id}`) |
| `log_messages` | Running list of timestamped log lines |
| `current_task` | Most recent task description |

```json
{
  "request_id": "a3f8c1d2-4e5b-6789-abcd-ef0123456789",
  "status": "pending",
  "checkpoint_number": null,
  "checkpoint_prompt": null,
  "plan_summary": null,
  "artifacts": [],
  "quality_score": null,
  "git_branch": null,
  "error": null,
  "output_directory": "/mnt/data/development/a3f8c1d2-4e5b-6789-abcd-ef0123456789",
  "current_task": null,
  "log_messages": []
}
```

#### Sample Command

```bash
curl -X POST http://35.209.107.68:8000/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{
    "implementation_md": "'"$(cat /path/to/Implementation.md)"'",
    "mapping_csv":        "'"$(cat /path/to/mapping.csv)"'",
    "project_id":  "my-gcp-project",
    "dataset_id":  "customer_360"
  }'
```

---

## 2. Get Run Status

### GET /api/v1/runs/{request_id}

Poll this endpoint to track pipeline progress and detect checkpoint pauses.

#### Run Status Values

| Status | Meaning |
|---|---|
| `pending` | Queued, not yet started |
| `planning` | PlannerAgent running |
| `checkpoint` | **Paused — human decision required** (see POST .../checkpoint) |
| `generating` | GeneratorAgent producing code artifacts |
| `optimizing` | OptimizerAgent applying GCP best practices |
| `reviewing` | ReviewerAgent checking correctness |
| `committing` | Writing artifacts to disk / git |
| `done` | All artifacts approved and saved |
| `aborted` | Human aborted at a checkpoint |
| `failed` | Unhandled error — check `error` field |

#### Response

| Field | Description |
|---|---|
| `status` | Current pipeline status |
| `checkpoint_number` | `1`, `2`, or `3` when paused at a checkpoint; otherwise `null` |
| `checkpoint_prompt` | Human-readable description of the decision required |
| `plan_summary` | Markdown summary of the generated plan (available after planning) |
| `artifacts` | List of `{file_name, artifact_type}` objects once generation completes |
| `quality_score` | Reviewer quality score 0–100 (available after review) |
| `git_branch` | Branch name if artifacts were pushed to git |
| `log_messages` | Last 100 timestamped log lines from the pipeline |

```json
{
  "request_id": "a3f8c1d2-4e5b-6789-abcd-ef0123456789",
  "status": "checkpoint",
  "checkpoint_number": 1,
  "checkpoint_prompt": "PLAN REVIEW\n──────────────────\nArtifacts: 4 DDL, 2 DML, 1 SP, 1 DAG\n...",
  "plan_summary": "## SCRUM-75 — Customer 360 Data Platform\n...",
  "artifacts": [],
  "quality_score": null,
  "git_branch": null,
  "error": null,
  "output_directory": "/mnt/data/development/a3f8c1d2-4e5b-6789-abcd-ef0123456789",
  "current_task": "Waiting for checkpoint 1 decision",
  "log_messages": [
    "[10:31:05] Planning started for request a3f8c1d2",
    "[10:31:42] Plan generated — 4 DDL, 2 DML, 1 SP, 1 DAG",
    "[10:31:42] Paused at Checkpoint 1 — awaiting human decision"
  ]
}
```

#### Sample Command

```bash
curl http://35.209.107.68:8000/api/v1/runs/a3f8c1d2-4e5b-6789-abcd-ef0123456789
```

---

## 3. Submit Checkpoint Decision

### POST /api/v1/runs/{request_id}/checkpoint

Unblocks a paused pipeline run. The run must be in `checkpoint` status.

#### Checkpoints

| # | Triggered after | Purpose |
|---|---|---|
| 1 | PlannerAgent | Review and approve the execution plan (artifact list, tables, services) |
| 2 | Generator + Optimizer + Reviewer | Review generated code and quality score |
| 3 | Code approval | Decide whether to push the feature branch to git |

#### Request Body

| Field | Type | Required | Description |
|---|---|---|---|
| `decision` | string | Yes | `approve` \| `revise` \| `abort` \| `deploy` \| `skip` |
| `notes` | string | Required when `revise` | Instructions for the revision — can reference specific file names |

#### Decision Options

| Decision | Effect |
|---|---|
| `approve` | Advance to the next stage |
| `revise` | Re-run the current stage with notes incorporated. At Checkpoint 2, naming a file re-generates only that file. |
| `abort` | Stop the pipeline; artifacts on disk are kept |
| `deploy` | Approve and immediately trigger deployment (Checkpoint 3 only) |
| `skip` | Skip git push and finish (Checkpoint 3 only) |

```json
{ "decision": "approve", "notes": "" }
```

```json
{ "decision": "revise", "notes": "Add PARTITION BY date to stg_customers_ddl.sql and fix the merge key in dml_customers.sql" }
```

```json
{ "decision": "revise", "notes": "file dag_customers_load.py — add exponential backoff to the extract task" }
```

#### Response — same shape as GET /api/v1/runs/{request_id}

#### Sample Commands

```bash
# Approve checkpoint 1 (plan looks good)
curl -X POST http://35.209.107.68:8000/api/v1/runs/a3f8c1d2-4e5b-6789-abcd-ef0123456789/checkpoint \
  -H "Content-Type: application/json" \
  -d '{"decision": "approve", "notes": ""}'

# Revise — re-generate a specific file only
curl -X POST http://35.209.107.68:8000/api/v1/runs/a3f8c1d2-4e5b-6789-abcd-ef0123456789/checkpoint \
  -H "Content-Type: application/json" \
  -d '{"decision": "revise", "notes": "file stg_customers_ddl.sql — partition by ingestion_date"}'

# Skip git push at checkpoint 3
curl -X POST http://35.209.107.68:8000/api/v1/runs/a3f8c1d2-4e5b-6789-abcd-ef0123456789/checkpoint \
  -H "Content-Type: application/json" \
  -d '{"decision": "skip", "notes": ""}'
```

---

## 4. List All Runs

### GET /api/v1/runs

Returns all pipeline runs, newest first.

#### Response — array of run summaries

```json
[
  {
    "request_id": "a3f8c1d2-4e5b-6789-abcd-ef0123456789",
    "status": "done",
    "artifacts": [
      {"file_name": "stg_customers_ddl.sql",  "artifact_type": "ddl"},
      {"file_name": "dml_customers.sql",       "artifact_type": "dml"},
      {"file_name": "sp_log_audit.sql",        "artifact_type": "sp"},
      {"file_name": "dag_customers_load.py",   "artifact_type": "dag"}
    ],
    "quality_score": 91.5,
    "git_branch": "feature/SCRUM-75_20260422_v1",
    "output_directory": "/mnt/data/development/a3f8c1d2-4e5b-6789-abcd-ef0123456789"
  }
]
```

#### Sample Command

```bash
curl http://35.209.107.68:8000/api/v1/runs
```

---

## 5. Optimize and Review Existing Artifacts

### POST /api/v1/optimize-review

Runs only the **Optimizer + Reviewer** on existing code files — no planning or generation.
Useful for improving code written outside the pipeline or from a previous run.

#### Request Body

| Field | Type | Required | Description |
|---|---|---|---|
| `artifacts` | array | Yes | List of existing code artifacts (see below) |
| `project_id` | string | No | GCP project ID |
| `dataset_id` | string | No | BigQuery dataset ID |
| `environment` | string | No | `dev` \| `uat` \| `prod` (default: `dev`) |
| `cloud_provider` | string | No | `gcp` \| `aws` \| `azure` \| `snowflake` (default: `gcp`) |
| `human_notes` | array | No | Additional context / instructions for the reviewer |

Each artifact object:

| Field | Type | Required | Description |
|---|---|---|---|
| `file_name` | string | Yes | e.g. `stg_customers_ddl.sql` |
| `artifact_type` | string | Yes | `ddl` \| `dml` \| `sp` \| `dag` \| `pipeline` \| `config` \| `doc` |
| `content` | string | Yes | Full raw file content |
| `description` | string | No | Optional context for the reviewer |
| `target_path` | string | No | Relative target path (e.g. `ddl/stg_customers_ddl.sql`) |

```json
{
  "artifacts": [
    {
      "file_name": "stg_customers_ddl.sql",
      "artifact_type": "ddl",
      "content": "CREATE OR REPLACE TABLE `project.dataset.stg_customers` (\n  customer_id STRING,\n  ...\n)"
    },
    {
      "file_name": "dag_customers_load.py",
      "artifact_type": "dag",
      "content": "from airflow import DAG\n..."
    }
  ],
  "project_id": "my-gcp-project",
  "dataset_id": "customer_360",
  "human_notes": ["Ensure partition pruning is applied on all staging tables"]
}
```

#### Response — `202 Accepted`

Same shape as POST /api/v1/runs. Poll `GET /api/v1/runs/{request_id}` for status.

#### Sample Command

```bash
curl -X POST http://35.209.107.68:8000/api/v1/optimize-review \
  -H "Content-Type: application/json" \
  -d '{
    "artifacts": [
      {
        "file_name": "stg_customers_ddl.sql",
        "artifact_type": "ddl",
        "content": "'"$(cat stg_customers_ddl.sql)"'"
      }
    ],
    "project_id": "my-gcp-project",
    "dataset_id": "customer_360"
  }'
```

---

## 6. Trigger Deployment

### POST /api/v1/deploy

Deploys approved artifacts to GCP in five ordered steps:
1. Create audit table (if enabled in pipeline config)
2. Apply BigQuery DDL (CREATE / ALTER TABLE statements)
3. Apply stored procedures
4. Upload DAGs to Cloud Composer GCS bucket
5. Register Dataflow Flex Template

Runs pre-deploy connectivity validation before touching any GCP resource.
If any validation check fails, deployment is aborted immediately.

#### Request Body

| Field | Type | Required | Description |
|---|---|---|---|
| `request_id` | string | Yes | The `request_id` from the code gen run |
| `artifacts_dir` | string | Yes | Full path to the output directory, e.g. `/mnt/data/development/{request_id}` |
| `project_id` | string | No | GCP project ID (auto-resolved from `pipeline_config.py` or `PROJECT_ID` env var) |
| `dataset_id` | string | No | BigQuery dataset ID (auto-resolved from `pipeline_config.py` or `DATASET_ID` env var) |
| `region` | string | No | GCP region (default: `us-central1`) |
| `environment` | string | No | `dev` \| `uat` \| `prod` — selects the correct section from `pipeline_config.py` |
| `dag_bucket` | string | No | GCS bucket name for DAG upload (e.g. `my-composer-bucket`) |
| `composer_environment` | string | No | Cloud Composer environment name |
| `target` | string | No | `gcp` \| `aws` \| `snowflake` (default: `gcp`) |
| `source_db_type` | string | No | Source DB type for connectivity check (e.g. `mysql`, `postgresql`) |
| `source_db_host` | string | No | Source DB host |
| `source_db_port` | int | No | Source DB port |
| `source_db_name` | string | No | Source DB name |
| `source_db_user` | string | No | Source DB username |

> Password is always read from the `DB_PASSWORD` environment variable — never sent in the request body.

```json
{
  "request_id": "a3f8c1d2-4e5b-6789-abcd-ef0123456789",
  "artifacts_dir": "/mnt/data/development/a3f8c1d2-4e5b-6789-abcd-ef0123456789",
  "project_id": "my-gcp-project",
  "dataset_id": "customer_360",
  "environment": "dev",
  "dag_bucket": "us-central1-my-composer-bucket-abc123",
  "composer_environment": "my-composer-env"
}
```

#### Response — `202 Accepted`

```json
{
  "run_id": "d7e9f1a2-3b4c-5678-9012-cdef01234567",
  "status": "pending",
  "environment": "dev",
  "project_id": "my-gcp-project",
  "dataset_id": "customer_360"
}
```

#### Sample Command

```bash
curl -X POST http://35.209.107.68:8000/api/v1/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "request_id":   "a3f8c1d2-4e5b-6789-abcd-ef0123456789",
    "artifacts_dir": "/mnt/data/development/a3f8c1d2-4e5b-6789-abcd-ef0123456789",
    "project_id":   "my-gcp-project",
    "dataset_id":   "customer_360",
    "environment":  "dev",
    "dag_bucket":   "us-central1-my-composer-bucket-abc123"
  }'
```

---

## 7. Get Deploy Status

### GET /api/v1/deploy/{run_id}

Returns the status and results of a deploy run.

#### Response

| Field | Description |
|---|---|
| `run_id` | Deploy run UUID |
| `status` | `pending` \| `running` \| `success` \| `failed` \| `skipped` |
| `result.validation` | Pre-deploy connectivity check results |
| `result.steps` | Ordered deploy step results (audit table, DDL, SP, DAG upload, Dataflow) |
| `result.overall_status` | Final aggregated status |
| `error` | Error message if status is `failed` |

```json
{
  "run_id": "d7e9f1a2-3b4c-5678-9012-cdef01234567",
  "status": "success",
  "result": {
    "request_id": "a3f8c1d2-4e5b-6789-abcd-ef0123456789",
    "target": "gcp",
    "validation": [
      {"check": "bigquery",  "status": "pass", "message": "BigQuery API reachable"},
      {"check": "gcs",       "status": "pass", "message": "GCS bucket accessible"},
      {"check": "composer",  "status": "pass", "message": "Composer environment found"},
      {"check": "source_db", "status": "skipped", "message": "No source DB configured"}
    ],
    "steps": [
      {"step": "create_audit_table",       "status": "success", "message": "audit_pipeline_runs created"},
      {"step": "apply_bq_ddl",             "status": "success", "message": "4 DDL statements applied"},
      {"step": "apply_stored_procedures",  "status": "success", "message": "1 SP applied"},
      {"step": "upload_dags",              "status": "success", "message": "1 DAG uploaded to GCS"},
      {"step": "register_dataflow_template","status": "skipped","message": "No Dataflow template found"}
    ],
    "overall_status": "success"
  },
  "error": null
}
```

#### Sample Command

```bash
curl http://35.209.107.68:8000/api/v1/deploy/d7e9f1a2-3b4c-5678-9012-cdef01234567
```

---

## 8. List All Deploy Runs

### GET /api/v1/deploy

Returns all deploy runs, newest first.

#### Response

```json
[
  {
    "run_id": "d7e9f1a2-3b4c-5678-9012-cdef01234567",
    "request_id": "a3f8c1d2-4e5b-6789-abcd-ef0123456789",
    "status": "success",
    "environment": "dev",
    "project_id": "my-gcp-project",
    "created_at": "2026-04-22T10:35:00Z"
  }
]
```

#### Sample Command

```bash
curl http://35.209.107.68:8000/api/v1/deploy
```

---

## 9. Health Check

### GET /healthz

```bash
curl http://35.209.107.68:8000/healthz
```

```json
{"status": "ok", "service": "deah-development-pod"}
```

---

## End-to-End Walkthrough — New Pipeline from SCRUM-75

```bash
BASE="http://35.209.107.68:8000"

# 1. Start the run (Design Pod hands off implementation_md + mapping_csv)
RUN=$(curl -s -X POST $BASE/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{
    "implementation_md": "'"$(cat Implementation.md)"'",
    "mapping_csv":        "'"$(cat mapping.csv)"'",
    "project_id":  "my-gcp-project",
    "dataset_id":  "customer_360"
  }')

REQUEST_ID=$(echo $RUN | python3 -c "import sys,json; print(json.load(sys.stdin)['request_id'])")
echo "Run started: $REQUEST_ID"

# 2. Poll until checkpoint 1 (plan ready)
until [ "$(curl -s $BASE/api/v1/runs/$REQUEST_ID | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")" = "checkpoint" ]; do
  echo "Waiting..."; sleep 10
done

# 3. Review plan, then approve
curl -s $BASE/api/v1/runs/$REQUEST_ID | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['plan_summary'])"
curl -X POST $BASE/api/v1/runs/$REQUEST_ID/checkpoint \
  -H "Content-Type: application/json" \
  -d '{"decision": "approve", "notes": ""}'

# 4. Poll until checkpoint 2 (code review ready)
until [ "$(curl -s $BASE/api/v1/runs/$REQUEST_ID | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")" = "checkpoint" ]; do
  echo "Generating..."; sleep 15
done

# 5. Check quality score and approve code
curl -s $BASE/api/v1/runs/$REQUEST_ID | python3 -c "import sys,json; d=json.load(sys.stdin); print('Quality:', d['quality_score'])"
curl -X POST $BASE/api/v1/runs/$REQUEST_ID/checkpoint \
  -H "Content-Type: application/json" \
  -d '{"decision": "approve", "notes": ""}'

# 6. Skip git push at checkpoint 3
until [ "$(curl -s $BASE/api/v1/runs/$REQUEST_ID | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")" = "checkpoint" ]; do
  sleep 5
done
curl -X POST $BASE/api/v1/runs/$REQUEST_ID/checkpoint \
  -H "Content-Type: application/json" \
  -d '{"decision": "skip", "notes": ""}'

# 7. Wait for done
until [ "$(curl -s $BASE/api/v1/runs/$REQUEST_ID | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")" = "done" ]; do
  sleep 5
done
echo "Pipeline complete."

# 8. Deploy to GCP
ARTIFACTS_DIR=$(curl -s $BASE/api/v1/runs/$REQUEST_ID | python3 -c "import sys,json; print(json.load(sys.stdin)['output_directory'])")
DEPLOY=$(curl -s -X POST $BASE/api/v1/deploy \
  -H "Content-Type: application/json" \
  -d "{
    \"request_id\":    \"$REQUEST_ID\",
    \"artifacts_dir\": \"$ARTIFACTS_DIR\",
    \"project_id\":    \"my-gcp-project\",
    \"dataset_id\":    \"customer_360\",
    \"environment\":   \"dev\",
    \"dag_bucket\":    \"us-central1-my-composer-bucket-abc123\"
  }")

DEPLOY_ID=$(echo $DEPLOY | python3 -c "import sys,json; print(json.load(sys.stdin)['run_id'])")
echo "Deploy started: $DEPLOY_ID"
curl $BASE/api/v1/deploy/$DEPLOY_ID
```

---

## Error Responses

| HTTP Status | Meaning |
|---|---|
| `400` | Bad request — missing or invalid fields |
| `404` | Run not found |
| `409` | Conflict — run is not at a checkpoint when POST .../checkpoint is called |
| `422` | Validation error — incompatible field combination, or `revise` without `notes` |
| `500` | Unhandled server or agent error — check `detail` field |

All errors return:

```json
{"detail": "human-readable error message"}
```

---

## Interactive API Docs

The server exposes auto-generated Swagger UI and ReDoc at:

- `http://35.209.107.68:8000/docs` — Swagger UI (try endpoints in-browser)
- `http://35.209.107.68:8000/redoc` — ReDoc (read-only reference)
