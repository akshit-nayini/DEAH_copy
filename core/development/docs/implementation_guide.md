# DEAH Development Pod — Implementation Guide

**Version:** 1.0  
**Server:** `http://35.209.107.68:8000`  
**Output directory:** `/mnt/data/development/`

---

## What This Pod Does

The Development Pod is an end-to-end, agent-driven code generator that sits between the **Design Pod** (which produces `Implementation.md + mapping.csv`) and a live GCP environment.

Given a Jira ticket ID (or raw `Implementation.md + mapping.csv` content), the pod **plans**, **generates**, **optimizes**, **reviews**, and optionally **deploys** production-ready BigQuery DDL/DML, stored procedures, and Airflow DAGs — with a human approval gate at every stage.

---

## Where This Pod Fits

```
Design Pod
  └── Implementation.md + mapping.csv
         │
         ▼
  Development Pod  (this pod)
  ├── Planner        →  Execution plan (tables, artifacts, services)
  ├── Generator      →  DDL / DML / Stored Procedures / Airflow DAGs
  ├── Optimizer      →  GCP best-practice enforcement
  ├── Reviewer       →  Syntax + audit + data integrity + PII checks
  └── Deployer       →  BigQuery + Composer + Dataflow deployment
         │
         ▼
  Live GCP Environment
  └── BigQuery tables · Stored procedures · Airflow DAGs · Dataflow templates
```

---

## System Components

### Server

| Component | Location | Description |
|---|---|---|
| FastAPI server | `api/server.py` | Runs on port 8000; mounts all routes |
| Code Gen routes | `api/routes/code_gen.py` | `/api/v1/runs` and `/api/v1/optimize-review` |
| Deploy routes | `api/routes/deploy.py` | `/api/v1/deploy` |
| Pydantic models | `api/models.py` | All request/response contracts |

### Agents

| Agent | Location | Role |
|---|---|---|
| PlannerAgent | `agents/planner/` | Extracts clarifying questions, then generates a full JSON execution plan |
| GeneratorAgent | `agents/generator/` | Produces DDL, DML, stored procedures, and Airflow DAGs |
| OptimizerAgent | `agents/optimizer/` | Applies GCP best practices per artifact (partition pruning, filter-before-join, etc.) |
| ReviewerAgent | `agents/reviewer/` | Runs one LLM call per artifact across four dimensions: syntax, audit, data_integrity, pii |
| DeployerAgent | `agents/deployer/` | Applies artifacts to GCP in five ordered steps |
| PreDeployValidator | `agents/validator/` | Runs six connectivity checks before any GCP resource is touched |

### Supporting Modules

| Module | Description |
|---|---|
| `agents/orchestration/orchestrator.py` | `CodeGenPipeline` class — drives the full flow, manages checkpoints, caching, and git |
| `input_parser.py` | Parses `PipelineInput` from files or ticket ID |
| `config_generator.py` | Generates `pipeline_config.py` with dev/uat/prod sections |
| `connection_checker.py` | Tests TCP, GCS, BigQuery, Pub/Sub reachability |
| `db.py` | Builds SQLAlchemy engine for Cloud SQL metadata DB |
| `preflight.py` | Checks and installs required packages at startup |

---

## Pipeline Flow

### Mode 1 — Full Pipeline (via API or CLI)

```
POST /api/v1/runs  →  background thread
│
├── PlannerAgent (two-pass)
│     Pass 1: extract clarifying questions (lightweight)
│     Pass 2: generate full JSON execution plan
│
├── ─── CHECKPOINT 1 — Plan Review ──────────────────────────────────
│     Decision:  approve | revise (+ notes) | abort
│     On revise: notes appended to context; Planner re-runs
│
├── GeneratorAgent
│     Produces: DDL · DML · Stored Procedures · Airflow DAGs
│     Applies:  version headers · ALTER detection
│     Auto-fix: Ruff lint + format on Python files
│
├── OptimizerAgent
│     GCP checklist: partition pruning, filter-before-join, streaming inserts,
│     Composer Variable.get(), Dataflow COST_OPTIMIZED, Cloud Logging JSON
│
├── ReviewerAgent
│     One LLM call per artifact, four dimensions:
│     syntax · audit · data_integrity · pii
│     Produces: REVIEW_REPORT.md + quality score (0–100)
│
├── ─── CHECKPOINT 2 — Code Review ──────────────────────────────────
│     Decision:  approve | revise (+ notes) | file <name> | abort
│     On revise with file name: only that file re-generated
│     On revise without file name: file picker for targeted selection
│
├── Write artifacts to /mnt/data/development/{request_id}/
│     ddl/ · dml/ · sp/ · dag/ · config/ · PLAN.md · REVIEW_REPORT.md · MANIFEST.json
│
├── ─── CHECKPOINT 3 — Git Push ─────────────────────────────────────
│     Decision:  approve (push) | skip
│     Branch:    feature/{ticket}_{YYYYMMDD}_v{N}  (auto-increments)
│     Config:    GIT_REPO_URL + GIT_PAT env vars (or prompted interactively)
│
└── Status → done
```

### Mode 2 — Optimize + Review Existing Code

```
POST /api/v1/optimize-review  →  background thread
│
├── OptimizerAgent  (GCP best-practice pass)
├── ReviewerAgent   (+ logic_preservation check)
│
└── Optimized artifacts written to /mnt/data/development/{request_id}/
```

---

## Output Directory Structure

Every run writes to `/mnt/data/development/{request_id}/`:

```
{request_id}/
├── ddl/
│   ├── stg_customers_ddl.sql
│   └── core_customers_ddl.sql
├── dml/
│   └── dml_customers.sql
├── sp/
│   └── sp_log_audit.sql
├── dag/
│   └── dag_customers_load.py
├── config/
│   └── pipeline_config.py           ← dev / uat / prod sections
├── PLAN.md                          ← human-readable execution plan
├── REVIEW_REPORT.md                 ← quality scores and findings per file
└── MANIFEST.json                    ← all files, change types, owners
```

---

## Deployment Flow

```
POST /api/v1/deploy  →  background thread
│
├── PreDeployValidator
│   Checks: BigQuery API · GCS bucket · Cloud Composer · Dataflow API ·
│           Secret Manager · Source DB TCP reachability
│   → if any FAIL: deploy aborted immediately
│
└── DeployerAgent (GCP steps in order)
    ├── Step 1: Create audit_pipeline_runs table (if enabled)
    ├── Step 2: Apply BigQuery DDL (CREATE / ALTER TABLE)
    ├── Step 3: Apply stored procedures (CREATE OR REPLACE PROCEDURE)
    ├── Step 4: Upload DAGs to Cloud Composer GCS bucket
    └── Step 5: Register Dataflow Flex Template
```

---

## Human Checkpoints

No code reaches disk or any GCP environment without an explicit human decision.

| # | Triggered after | Options | On revise |
|---|---|---|---|
| 1 | PlannerAgent | `approve` · `revise` · `abort` | Notes → `ctx.human_notes`; Planner re-runs |
| 2 | Generator + Optimizer + Reviewer | `approve` · `revise` · `file <name>` · `abort` | Only named file(s) re-generated; others untouched |
| 3 | Code approval | `approve` (push) · `skip` | Push to `feature/{ticket}_{YYYYMMDD}_v{N}` or finish |

### Targeted Revision at Checkpoint 2

At Checkpoint 2 the `revise` decision supports surgical per-file changes:

- **Name a file in notes** → only that file is re-generated  
  `"notes": "file stg_customers_ddl.sql — add partition by ingestion_date"`

- **Name multiple files** → all listed files are re-generated  
  `"notes": "fix the merge key in dml_customers.sql and add retry logic in dag_customers_load.py"`

- **No file named** → all artifacts re-generated with the notes as guidance

---

## Artifact Types

| Type | Value | Generated content |
|---|---|---|
| DDL | `ddl` | BigQuery `CREATE OR REPLACE TABLE` / `ALTER TABLE` |
| DML | `dml` | BigQuery `MERGE` / `INSERT INTO` / `SELECT INTO` |
| Stored Procedure | `sp` | `CREATE OR REPLACE PROCEDURE` |
| Airflow DAG | `dag` | Python DAG using `BigQueryInsertJobOperator` |
| Pipeline | `pipeline` | Generic Python pipeline script |
| Config | `config` | `pipeline_config.py` with dev/uat/prod sections |
| Doc | `doc` | Markdown documentation artifact |

---

## Run Status Lifecycle

```
pending → planning → [checkpoint 1] → generating → optimizing → reviewing
                                                                      │
                                                              [checkpoint 2]
                                                                      │
                                                                 committing
                                                                      │
                                                              [checkpoint 3]
                                                                      │
                                                                    done
```

Error states: `aborted` (human decision) · `failed` (unhandled error)

---

## Configuration — Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OUTPUT_ROOT` | `/mnt/data/development` | Root directory for all pipeline output |
| `LLM_PROVIDER` | `claude-code-sdk` | `claude-code-sdk` \| `anthropic` \| `openai` \| `gemini` |
| `ANTHROPIC_API_KEY` | — | Required when `LLM_PROVIDER=anthropic` |
| `LLM_MODEL` | provider default | Model override e.g. `claude-sonnet-4-6` |
| `PROJECT_ID` | — | GCP project ID fallback |
| `DATASET_ID` | — | BigQuery dataset fallback |
| `ENV` | `dev` | Environment: `dev` \| `uat` \| `prod` |
| `REGION` | `us-central1` | GCP region fallback |
| `GIT_REPO_URL` | — | Git repo URL for feature branch commit |
| `GIT_PAT` | — | Personal Access Token for git auth |
| `GIT_LOCAL_PATH` | `{OUTPUT_ROOT}/git_workspace` | Local clone workspace |
| `GIT_PUSH_REMOTE` | `false` | Auto-push to remote after commit |
| `DB_PASSWORD` | — | Source database password (never sent in API body) |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins |

---

## Starting the Server

```bash
cd /home/varun_akarapu/DEAH/core/development

# Set required environment variables
export ANTHROPIC_API_KEY=sk-ant-...       # if using API key mode
export OUTPUT_ROOT=/mnt/data/development  # already the default
export PROJECT_ID=my-gcp-project
export DATASET_ID=customer_360

# Start the server (binds to all interfaces on port 8000)
python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
```

Server will be reachable at:
- API: `http://35.209.107.68:8000`
- Swagger UI: `http://35.209.107.68:8000/docs`
- ReDoc: `http://35.209.107.68:8000/redoc`
- Health: `http://35.209.107.68:8000/healthz`

---

## Integration with Design Pod

The Design Pod (port 9190) produces `Implementation.md` and `mapping.csv` for each ticket.
The Development Pod consumes them via `POST /api/v1/runs`.

Typical integration flow:

```
1. Design Pod: POST /pipeline  { ticket_id: "SCRUM-5" }
   → produces implementation_steps output: impl_SCRUM-5_*.md
   → produces data model output:           mapping.csv

2. Development Pod: POST /api/v1/runs
   { implementation_md: <content of impl_SCRUM-5_*.md>,
     mapping_csv:       <content of mapping.csv>,
     project_id:  "my-gcp-project",
     dataset_id:  "customer_360" }

3. Poll GET /api/v1/runs/{request_id} and submit decisions at checkpoints

4. On done: POST /api/v1/deploy  { artifacts_dir: "/mnt/data/development/{request_id}" }
```

---

## Quality Score Interpretation

The ReviewerAgent produces a score from 0 to 100 based on findings across all artifacts.

| Score | Interpretation |
|---|---|
| 90–100 | Excellent — production ready with minor notes |
| 75–89 | Good — conditional pass; review WARNING findings |
| 60–74 | Acceptable — revise recommended for CRITICAL findings |
| < 60 | Failing — at least one CRITICAL issue must be resolved |

Finding severities:

| Severity | Meaning |
|---|---|
| `CRITICAL` | Must fix before deploy — incorrect logic, missing partitions, data loss risk |
| `WARNING` | Should fix — suboptimal but not blocking |
| `INFO` | Suggestion — style or minor improvement |

---

## CLI Usage (Alternative to API)

The CLI entry point provides the same pipeline without the HTTP layer.

```bash
cd /home/varun_akarapu/DEAH/core/development

# Mode 1a — full pipeline from ticket ID (fetches from metadata DB)
python main.py --ticket SCRUM-75

# Mode 1b — full pipeline from local files
python main.py \
  --impl /path/to/Implementation.md \
  --mapping /path/to/mapping.csv \
  --project my-gcp-project \
  --dataset customer_360

# Mode 1 with git push
python main.py --ticket SCRUM-75 \
  --git-repo-url https://github.com/org/repo \
  --git-pat ghp_xxx \
  --push

# Mode 1 — dry run (plan only, no code generation)
python main.py --ticket SCRUM-75 --dry-run

# Mode 2 — optimize + review local files
python main.py --optimize --files stg_customers_ddl.sql dag_customers_load.py

# Mode 2 — optimize + review from a git branch folder
python main.py --optimize \
  --git-repo-url https://github.com/org/repo \
  --git-branch feature/SCRUM-75_20260422_v1 \
  --git-folder pipelines/SCRUM-75 \
  --git-pat ghp_xxx
```

---

## Supported Artifact Patterns

### BigQuery DDL (`.sql`)

- `CREATE OR REPLACE TABLE` with partition by `DATE(ingestion_timestamp)` or `ingestion_date`
- `OPTIONS(require_partition_filter=TRUE)` on large tables
- Clustering on frequently filtered columns
- Version history block at top of file
- ALTER TABLE for schema evolution (when `is_alter=True`)

### BigQuery DML (`.sql`)

- `MERGE` statements with explicit `WHEN MATCHED` / `WHEN NOT MATCHED`
- `INSERT INTO ... SELECT` with filter-before-join pattern
- Staging → core table transformation

### Stored Procedures (`.sql`)

- `CREATE OR REPLACE PROCEDURE` with `BEGIN ... END`
- `sp_log_audit` reusable audit logging procedure
- Error handling with `EXCEPTION WHEN ERROR THEN`

### Airflow DAGs (`.py`)

- `BigQueryInsertJobOperator` for all BQ operations
- `Variable.get("PROJECT_ID")` / `Variable.get("DATASET_ID")` — no hardcoded values
- Retry logic with exponential backoff
- `depends_on_past = False`, `catchup = False`
- `COST_OPTIMIZED` mode for Dataflow tasks
- Cloud Logging JSON structured logging

---

## File Naming Conventions

| Artifact | Pattern | Example |
|---|---|---|
| Staging DDL | `stg_{table}_ddl.sql` | `stg_customers_ddl.sql` |
| Core DDL | `core_{table}_ddl.sql` | `core_customers_ddl.sql` |
| DML / Merge | `dml_{table}.sql` | `dml_customers.sql` |
| Stored Procedure | `sp_{name}.sql` | `sp_log_audit.sql` |
| Airflow DAG | `dag_{pipeline_name}.py` | `dag_customers_load.py` |
| Pipeline Config | `pipeline_config.py` | `pipeline_config.py` |
| Plan | `PLAN.md` | `PLAN.md` |
| Review Report | `REVIEW_REPORT.md` | `REVIEW_REPORT.md` |
| Manifest | `MANIFEST.json` | `MANIFEST.json` |

Git feature branches follow the pattern: `feature/{ticket_id}_{YYYYMMDD}_v{N}` — e.g. `feature/SCRUM-75_20260422_v1`
