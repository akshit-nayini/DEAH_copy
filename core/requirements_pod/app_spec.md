# TaskFlow AI Agent — Spec (Claude Code Edition)
> Version 1.0.0 | Status: Draft

## What this is
A Claude-powered app that ingests documents/transcripts, extracts tasks via LLM, lets users review/edit them, and pushes to Jira. Browser UI → FastAPI backend → SQLite/PostgreSQL + GCS + Anthropic API + Jira.

## Do NOT build (out of scope for this iteration)
- Authentication / user accounts
- Multi-user namespacing
- Async task queues (Cloud Tasks / Pub/Sub)
- Additional LLM providers (Gemini, GPT)
- Additional issue trackers (GitHub Issues, Linear)
- GCS webhooks
- Cross-file vector deduplication
- PostgreSQL migration (config-only swap — no code needed)

---

## 1. Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Web framework | FastAPI |
| ORM + migrations | SQLAlchemy 2.x + Alembic |
| DB (dev) | SQLite |
| DB (prod) | PostgreSQL (one config line swap) |
| Object storage | Google Cloud Storage (dev: local filesystem) |
| LLM | Anthropic Claude `claude-sonnet-4-20250514` (dev: mock provider) |
| Issue tracker | Jira Cloud REST API v3 |
| UI | React + TailwindCSS |
| HTTP client | `httpx` (async) |
| Config | `pydantic-settings` + `.env` |
| Testing | `pytest` + `pytest-asyncio` |
| Containerisation | Docker + `docker-compose` |

---

## 2. Key design principles

- **UI-agnostic backend** — all business logic in FastAPI services; UI talks only via versioned REST endpoints.
- **LLM abstraction** — `BaseLLMProvider` ABC; `ClaudeProvider` for prod, `MockLLMProvider` for dev (no API key needed).
- **Storage abstraction** — `BaseStorageProvider` ABC; `GCSProvider` for prod, `LocalStorageProvider` writing to `./local_storage/` for dev.
- **DB abstraction** — SQLAlchemy ORM; swap connection string via `DATABASE_URL` in `.env`.

---

## 3. Dev mode rules (all defaults in `config.env`)

| Setting | Dev value | Effect |
|---|---|---|
| `LLM_PROVIDER=mock` | mock | Reads from `tests/fixtures/mock_llm_response.json`. No Claude calls. |
| `STORAGE_PROVIDER=local` | local | Writes files to `./local_storage/`. No GCS needed. |
| `DATABASE_URL` | `sqlite:///./taskflow.db` | Zero-config local DB. |

To test with real Claude: set `LLM_PROVIDER=claude` + `ANTHROPIC_API_KEY`.
To test with real GCS: set `STORAGE_PROVIDER=gcs` + GCS config vars.

---

## 4. Feature specifications

### 4.1 Guest identity
- Default display name: `"Guest"`. Editable inline text field.
- Name stored in `localStorage` (UI) and sent as `created_by` on all API requests.
- No auth in MVP.

### 4.2 File upload
- **Formats:** `.pdf`, `.docx`, `.txt`, `.md`, `.vtt`, `.srt`
- **Max size:** 50 MB
- **Flow:** `POST /api/v1/files/upload` (multipart) → validate → write to GCS at `gs://{BUCKET}/{user_name}/{YYYY-MM-DD}/{uuid}_{filename}` → insert `source_files` row (`status=uploaded`) → return `file_id` + `gcs_path`.
- Dev: writes to `./local_storage/{user_name}/`.

### 4.3 GCS file browser
- `GET /api/v1/files/list?prefix={user_name}` — paginated file list.
- UI: filter by date range + filename search. Selected file → same extraction flow as upload.

### 4.4 Task extraction pipeline
Triggered by `POST /api/v1/files/{file_id}/parse`.

1. Read raw text from GCS (or local)
2. Load `project_context.md` as system context
3. Chunk text: `chunk_size=3000` tokens, `overlap=200`
4. Per chunk → LLM with extraction prompt → structured JSON array
5. Deduplication pass (fuzzy match on `task_heading` + `location`)
6. Persist tasks with `status=extracted`
7. Return task list

**Prompt rules:**
- System prompt = `project_context.md` content.
- Instruct model to return **only valid JSON**, no markdown fences.
- Parse + validate against `TaskSchema` Pydantic model.
- Model identifies: requirements, action items, bugs, stories.

**Extraction failures:** log per-chunk; save partial results; do not abort entire job.

### 4.5 Task management UI
Each task is an editable card/row.

| Field | Editable | Notes |
|---|---|---|
| `task_id` | No | Human-readable: `SRC-001` |
| `task_heading` | Yes | Short title |
| `description` | Yes | Full detail |
| `task_type` | Yes | `bug` / `story` / `task` / `subtask` |
| `user_name` | Yes | Assignee |
| `task_source` | No | Source filename |
| `location` | No | Page / section / timestamp in source |
| `created_at` | No | Extraction timestamp |
| `jira_id` | No | Populated after push |
| `jira_url` | No | Deep link |
| `status` | Yes | `extracted` / `modified` / `pushed` / `deleted` |

**Per-task actions:** Edit (inline), Delete (soft — `status=deleted`, hidden but retained), Save (`PATCH /api/v1/tasks/{task_id}`).

**Bulk actions:** checkbox per row + Select All → Download Selected, Push to Jira.

### 4.6 Task export
- `POST /api/v1/tasks/export` — body: `{ "task_ids": [...], "format": "json"|"csv"|"md" }`
- Response: file download with appropriate `Content-Disposition` header.

### 4.7 Jira integration
- `POST /api/v1/tasks/jira-push` — body: `{ "task_ids": [...] }`
- Per task: call Jira `POST /rest/api/3/issue`, write back `jira_id` + `jira_url` to DB.
- Tasks with existing `jira_id` → skip with warning shown in UI.
- Report per-task success/failure individually (partial success is fine).

### 4.8 Session resume
- `GET /api/v1/tasks?source_file={filename}&user_name={name}` — all non-deleted tasks.
- UI autocompletes `source_file` from distinct values in DB.
- Loaded tasks are fully editable and re-pushable.

---

## 5. Data models

### Pydantic schemas (source of truth — ORM models derive from these)

```python
# schemas/task.py
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum

class TaskType(str, Enum):
    bug = "bug"
    story = "story"
    task = "task"
    subtask = "subtask"

class TaskStatus(str, Enum):
    extracted = "extracted"
    modified = "modified"
    pushed = "pushed"
    deleted = "deleted"

class TaskBase(BaseModel):
    task_heading: str
    description: Optional[str]
    task_type: TaskType
    user_name: Optional[str]
    location: Optional[str]

class TaskCreate(TaskBase):
    task_source: str
    source_file_id: str

class TaskUpdate(BaseModel):
    task_heading: Optional[str]
    description: Optional[str]
    task_type: Optional[TaskType]
    user_name: Optional[str]
    status: Optional[TaskStatus]

class TaskOut(TaskBase):
    id: str
    task_id: str
    task_source: str
    created_at: datetime
    updated_at: Optional[datetime]
    status: TaskStatus
    jira_id: Optional[str]
    jira_url: Optional[str]

    class Config:
        from_attributes = True
```

### `source_files` columns
`id` (UUID PK), `filename`, `gcs_path`, `uploaded_by`, `upload_time`, `status` (`uploaded`/`parsed`/`error`), `file_size`, `mime_type`

### `tasks` columns
`id` (UUID PK), `task_id` (human-readable, unique), `task_heading`, `description`, `task_type`, `user_name`, `task_source`, `source_file_id` (FK → source_files), `location`, `created_at`, `updated_at`, `status`, `jira_id`, `jira_url`, `raw_llm_json` (audit log of original LLM output)

---

## 6. API design

Base path: `/api/v1`

### Files
| Method | Endpoint | Description | Success |
|---|---|---|---|
| `POST` | `/files/upload` | Upload → GCS → returns `file_id` | 201 |
| `GET` | `/files/list` | List files (`?prefix=`) | 200 |
| `POST` | `/files/{file_id}/parse` | Trigger LLM extraction | 202 |
| `GET` | `/files/{file_id}/status` | Poll parse status | 200 |

### Tasks
| Method | Endpoint | Description | Success |
|---|---|---|---|
| `GET` | `/tasks` | List tasks (`?source_file=&user_name=&status=`) | 200 |
| `GET` | `/tasks/{task_id}` | Single task | 200 |
| `PATCH` | `/tasks/{task_id}` | Update fields | 200 |
| `DELETE` | `/tasks/{task_id}` | Soft delete | 200 |
| `POST` | `/tasks/export` | Export selected (JSON/CSV/MD) | 200 file |
| `POST` | `/tasks/jira-push` | Push selected to Jira | 200 |

### Health
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Liveness + config check |

**Error shape (all endpoints):**
```json
{ "detail": "Human-readable message", "code": "SNAKE_CASE_CODE" }
```

---

## 7. Configuration (`config.env` — commit with dummy values)

```dotenv
APP_NAME=TaskFlow AI Agent
APP_ENV=development
DEBUG=true
API_HOST=0.0.0.0
API_PORT=8000

# DB — swap to postgresql+psycopg2://... for prod
DATABASE_URL=sqlite:///./taskflow.db

# Storage
STORAGE_PROVIDER=local                 # local | gcs
GCS_BUCKET_NAME=your-bucket-name
GCS_PROJECT_ID=your-gcp-project-id
GCS_CREDENTIALS_PATH=./credentials/gcs-sa-key.json
LOCAL_STORAGE_PATH=./local_storage

# LLM
LLM_PROVIDER=mock                      # mock | claude
ANTHROPIC_API_KEY=sk-ant-REPLACE_ME
LLM_MODEL=claude-sonnet-4-20250514
LLM_MAX_TOKENS=4096
LLM_CHUNK_SIZE=3000
LLM_CHUNK_OVERLAP=200

# Jira
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_EMAIL=user@example.com
JIRA_API_TOKEN=REPLACE_ME
JIRA_PROJECT_KEY=PROJ
JIRA_ISSUE_TYPE_MAP={"bug":"Bug","story":"Story","task":"Task","subtask":"Sub-task"}

# Context + upload
PROJECT_CONTEXT_FILE=./project_context.md
MAX_UPLOAD_SIZE_MB=50
ALLOWED_EXTENSIONS=pdf,docx,txt,md,vtt,srt
```

---

## 8. Project context file

`project_context.md` lives at the repo root. It is loaded as the LLM system prompt for every extraction call. Do not embed its content here — edit it directly. Template is in the repo. Fill in all bracketed fields before first use; richer context = better extraction.

---

## 9. File & folder structure

```
taskflow-ai-agent/
├── project_context.md
├── config.env
├── .env                            # local overrides (gitignored)
├── requirements.txt
├── alembic.ini
├── docker-compose.yml
├── app/
│   ├── main.py
│   ├── config.py                   # pydantic-settings Config
│   ├── api/v1/
│   │   ├── files.py
│   │   ├── tasks.py
│   │   └── health.py
│   ├── services/
│   │   ├── llm/
│   │   │   ├── base.py             # BaseLLMProvider ABC
│   │   │   ├── claude_provider.py
│   │   │   └── mock_provider.py    # reads tests/fixtures/mock_llm_response.json
│   │   ├── storage/
│   │   │   ├── base.py             # BaseStorageProvider ABC
│   │   │   ├── gcs_provider.py
│   │   │   └── local_provider.py
│   │   ├── extraction.py           # chunking + LLM pipeline
│   │   └── jira.py                 # Jira REST client
│   ├── db/
│   │   ├── session.py
│   │   ├── models.py               # ORM models (derive from Pydantic schemas)
│   │   └── repository.py           # data access layer
│   └── schemas/
│       ├── task.py
│       └── file.py
├── ui/
│   └── src/
│       ├── components/
│       │   ├── GuestHeader.jsx
│       │   ├── FileUpload.jsx
│       │   ├── GCSBrowser.jsx
│       │   ├── TaskTable.jsx
│       │   ├── TaskCard.jsx
│       │   └── SessionResume.jsx
│       ├── api/client.js           # all API calls here, nowhere else
│       └── App.jsx
├── migrations/versions/
└── tests/
    ├── fixtures/mock_llm_response.json
    ├── test_extraction.py
    ├── test_tasks.py
    ├── test_files.py
    └── test_jira.py
```


## 10. Coding rules
- Soft deletes only — no hard deletes anywhere.
- Structured JSON logging on all requests; attach a `request_id` to every log line.
- API keys never logged.
- Backend is stateless — no in-process session state.
- All API calls centralised in `ui/src/api/client.js` — no fetch calls elsewhere in the UI.
