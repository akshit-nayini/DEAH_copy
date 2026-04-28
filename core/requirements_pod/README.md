# DEAH
Data engineering agent hub

# Requirements-POD — TaskFlow AI Agent

A full-stack application that ingests requirement documents, extracts structured tasks using an LLM, and optionally syncs them to Jira.

---

## Project Structure

```
Requirements-POD/
├── core/                           # All agent and shared backend code
│   ├── common/                     # Shared utilities (reusable across agents)
│   │   ├── database/               # Generic DB session factory
│   │   ├── llm/                    # LLM abstraction (Claude, Mock)
│   │   ├── scrum/                  # Jira integration
│   │   └── storage/                # Storage abstraction (local, GCS)
│   └── requirements_pod/           # Requirements POD agent
│       ├── main.py                 # FastAPI entry point
│       ├── config.py               # Pydantic Settings
│       ├── api/v1/                 # REST endpoints: health, files, tasks
│       ├── db/                     # SQLAlchemy models, session, repository
│       ├── schemas/                # Pydantic request/response models
│       ├── services/
│       │   └── extraction/         # 9-stage extraction pipeline
│       └── migrations/             # Alembic migrations
│           └── versions/
│               ├── 001_initial.py
│               └── 002_add_task_fields.py
│
├── webapp/                         # All frontend UIs
│   └── requirements_pod/           # Requirements POD React + Vite UI
│       ├── src/
│       ├── nginx.conf
│       └── Dockerfile
│
├── tests/                          # Integration tests
│   ├── conftest.py
│   ├── fixtures/
│   └── test_*.py
│
├── requirements.txt
├── config.env                      # Committed non-secret defaults
├── .env                            # Local secrets (gitignored)
├── alembic.ini
├── docker-compose.yml
└── Dockerfile                      # API image
```

---

## Prerequisites

- Python 3.11+
- Node.js 20+
- Docker & Docker Compose (for containerised setup)

---

## Local Development Setup

### 1. Clone & configure environment

```bash
git clone <repo-url>
cd Requirements-POD

# Create secrets file from template
cp .env.example .env
# Edit .env and fill in ANTHROPIC_API_KEY and any other secrets
```

### 2. Backend

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Apply database migrations
alembic upgrade head

# Start the API server (runs on http://localhost:8000)
uvicorn core.requirements_pod.main:app --reload
```

Configuration is loaded from `config.env`. Key defaults:

| Variable | Default | Description |
|---|---|---|
| `API_PORT` | `8000` | Backend port |
| `DATABASE_URL` | `sqlite:///./taskflow.db` | SQLite (swap for Postgres) |
| `STORAGE_PROVIDER` | `local` | `local` or `gcs` |
| `LLM_PROVIDER` | `mock` | `mock` or `claude` |
| `LLM_MODEL` | `claude-sonnet-4-20250514` | Model used for extraction |
| `MAX_UPLOAD_SIZE_MB` | `50` | Max upload size |
| `ALLOWED_EXTENSIONS` | `pdf,docx,txt,md,vtt,srt` | Accepted file types |

To use the real LLM, set `LLM_PROVIDER=claude` and `ANTHROPIC_API_KEY` in `.env`.

### 3. Frontend

```bash
cd webapp/requirements_pod

# Install dependencies
npm install

# Start the dev server (runs on http://localhost:5173)
npm run dev
```

Vite proxies all `/api` requests to `http://localhost:8000`, so both servers must be running simultaneously.

---

## Docker Setup

Runs both the API and UI in containers with nginx as a reverse proxy.

```bash
# Build and start all services
docker-compose up --build

# Run in background
docker-compose up --build -d

# Stop and remove containers
docker-compose down
```

| Service | Host port | Description |
|---|---|---|
| `api` | `8000` | FastAPI backend |
| `ui` | `5173` | React app served by nginx |

The UI container's nginx proxies `/api/` requests to the `api` service internally — no additional configuration needed.

---

## Database Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Roll back the last migration
alembic downgrade -1

# Generate a new migration after model changes
alembic revision --autogenerate -m "describe change"
```

Alembic reads `DATABASE_URL` from `get_settings()` via `core/requirements_pod/migrations/env.py` — no shell export needed.

---

## Running Tests

```bash
# All tests (no ANTHROPIC_API_KEY required — mock LLM is used)
pytest

# Integration tests only
pytest tests/

# Extraction pipeline unit tests
pytest core/requirements_pod/services/extraction/tests/

# Specific test file
pytest tests/test_extraction.py
```

---

## API Endpoints

Base URL: `http://localhost:8000/api/v1`

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/files/upload` | Upload a requirements document |
| `GET` | `/files/list` | List uploaded files |
| `POST` | `/files/register` | Find-or-create DB record for a storage file |
| `GET` | `/files/find?path=` | Look up DB record by storage path |
| `DELETE` | `/files/storage?path=` | Delete a file from storage and its DB record |
| `POST` | `/files/{id}/parse` | Parse file and extract tasks |
| `GET` | `/files/{id}/progress` | Poll live extraction progress |
| `GET` | `/files/{id}/status` | Get file processing status |
| `GET` | `/tasks` | List extracted tasks |
| `GET` | `/tasks/{id}` | Get a single task |
| `PATCH` | `/tasks/{id}` | Update a task |
| `DELETE` | `/tasks/{id}` | Soft-delete a task |
| `POST` | `/tasks/export` | Export tasks (JSON/CSV/MD) |
| `POST` | `/tasks/jira-push` | Push tasks to Jira |

Interactive docs: `http://localhost:8000/docs`

---

## Task Fields

Each extracted task carries the following fields. All Jira fields default to blank when they cannot be determined from the document.

| Field | Source | Description |
|---|---|---|
| `task_heading` | AI extracted | Short summary (≤80 chars, imperative verb) |
| `description` | AI extracted | Detailed description |
| `task_type` | AI extracted | `bug` / `story` / `task` / `subtask` |
| `priority` | AI extracted | `critical` / `high` / `medium` / `low` |
| `story_points` | AI extracted | Fibonacci estimate (1,2,3,5,8,13,21) |
| `acceptance_criteria` | AI extracted | Testable criteria (JSON list) |
| `reporter` | AI extracted | Reported by (when mentioned in document) |
| `sprint` | AI extracted | Sprint name (when mentioned in document) |
| `fix_version` | AI extracted | Release/version (when mentioned in document) |
| `user_name` | User-set | Assignee (blank by default) |
| `status` | System | `extracted` / `modified` / `pushed` / `deleted` |
| `created_at` | System | Task creation timestamp |
| `jira_id` | Jira push | Jira issue key after push |

---

## Google Cloud Storage (optional)

To store uploaded files in GCS instead of locally:

1. Download a service account key JSON from Google Cloud Console
2. Set in `config.env`:
   ```
   STORAGE_PROVIDER=gcs
   GCS_BUCKET_NAME=your-bucket-name
   GCS_PROJECT_ID=your-gcp-project-id
   GCS_CREDENTIALS_PATH=./credentials/gcs-sa-key.json
   ```

---

## Jira Integration (optional)

Set in `config.env`:

```
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_EMAIL=user@example.com
JIRA_API_TOKEN=your-api-token
JIRA_PROJECT_KEY=PROJ
```

Fields sent to Jira on push: summary, description (with acceptance criteria appended), issue type, priority, story points (`customfield_10016`), fix versions. The story-points custom field name (`customfield_10016`) is the Jira Software default — adjust in `core/common/scrum/jira.py` if your instance uses a different field ID.

Then use the **Push to Jira** action in the UI or call `POST /api/v1/tasks/jira-push`.

---

## UI Features

### Upload tab
- Drag-and-drop file upload (PDF, DOCX, TXT, MD, VTT, SRT)
- Live progress bar during AI extraction (100% shown before navigating to Tasks)

### Browse Files tab
- Lists files from storage with date filter (defaults to last 2 days)
- Per-file live progress bar during parsing
- Delete files directly from storage
- Batch parse up to 3 files simultaneously

### Tasks tab
- Table with sortable columns: Summary, Type, Priority, Story Points, Assigned To, Status, Created
- Date filter defaults to last 7 days; filter by source file and user
- Inline editing for type, priority, story points, assignee, status
- Full edit modal (TaskCard) with all fields: description, acceptance criteria, reporter, sprint, fix version
- Bulk export (JSON/CSV/Markdown) and Jira push

---

## Adding a New Agent

This repo is structured to support multiple independent agents sharing common utilities:

1. Create `core/<agent_name>/` with its own `main.py`, `config.py`, `api/`, `db/`, `schemas/`, `services/`, `migrations/`
2. Reuse `core/common/llm/`, `core/common/storage/`, `core/common/scrum/`, `core/common/database/`
3. Create `webapp/<agent_name>/` for its UI
4. Add a new service entry in `docker-compose.yml`
