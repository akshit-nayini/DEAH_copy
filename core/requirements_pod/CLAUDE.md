# CLAUDE.md

## Project
**Requirements-POD (TaskFlow AI Agent)** — full-stack web app: ingest docs (PDF, DOCX, TXT, MD, VTT, SRT) → Claude AI extracts structured tasks → review/edit → push to Jira.

**9-Stage Pipeline** (`core/requirements_pod/services/extraction/`): normalise → token-aware chunker (2000-token windows, 200-token overlap) → parallel LLM extract+retry (asyncio.Semaphore, exponential backoff) → Jaccard dedup → global task pool → Union-Find merge → temporal reasoning (override/initial-marker) → confidence scoring → normalise to `TaskOut`. Entry point: `parse_file()`. Raises `RuntimeError` for empty/unreadable files; chunk failures log and return `[]`.

## Repository Structure

```
Requirements-POD/
├── core/                           # All agent and shared backend code
│   ├── common/                     # Shared utilities (reusable across agents)
│   │   ├── database/               # Generic DB session factory (make_session_factory)
│   │   ├── llm/                    # LLM abstraction: BaseLLMProvider, ClaudeProvider, MockProvider
│   │   ├── scrum/                  # Jira integration: JiraService
│   │   └── storage/                # Storage abstraction: BaseStorageProvider, LocalProvider, GCSProvider
│   └── requirements_pod/           # Requirements POD agent
│       ├── main.py                 # FastAPI entry point
│       ├── config.py               # Pydantic Settings (reads config.env + .env)
│       ├── api/v1/                 # REST endpoints: health, files, tasks
│       ├── db/                     # DB layer: models.py, session.py, repository.py
│       ├── schemas/                # Pydantic schemas: file.py, task.py
│       ├── services/
│       │   ├── extraction/         # 9-stage extraction pipeline
│       │   └── _extraction_legacy.py  # Original single-pass (reference only)
│       └── migrations/             # Alembic migrations for this agent
│           └── versions/001_initial.py
│
├── webapp/                         # All frontend UIs
│   └── requirements_pod/           # Requirements POD React UI
│       ├── src/                    # React components, API client
│       ├── vite.config.js          # Dev server: proxies /api → :8000
│       └── Dockerfile
│
├── tests/                          # Top-level integration tests
│   ├── conftest.py
│   ├── test_files.py
│   ├── test_tasks.py
│   ├── test_extraction.py
│   ├── test_jira.py
│   └── fixtures/mock_llm_response.json
│
├── config.env                      # Committed non-secret defaults
├── .env                            # Local secrets (gitignored)
├── alembic.ini                     # script_location = core/requirements_pod/migrations
├── Dockerfile                      # CMD: uvicorn core.requirements_pod.main:app
├── docker-compose.yml
└── project_context.md              # LLM system prompt template
```

## Commands

```bash
# Backend
pip install -r requirements.txt
alembic upgrade head
uvicorn core.requirements_pod.main:app --reload   # :8000
pytest                                             # all tests
pytest tests/test_extraction.py
pytest core/requirements_pod/services/extraction/tests/
alembic revision --autogenerate -m "msg"
alembic downgrade -1
```
```bash
# Frontend
cd webapp/requirements_pod && npm install
npm run dev    # :5173, proxies /api → :8000
npm run build
```
```bash
# Docker
docker-compose up --build      # api :8000, ui :5173
docker-compose up --build -d
docker-compose down
```

## Architecture

### Backend entry point
`core/requirements_pod/main.py` — FastAPI; lifespan: DB init + local storage dir; JSON structured logging + request IDs; CORS via `CORS_ORIGINS` (default `*`); `allow_credentials=False`

### Configuration
`core/requirements_pod/config.py` — Pydantic `Settings` from `config.env`; `.env` for secrets; `CORS_ORIGINS` comma-separated

### API Routers
`core/requirements_pod/api/v1/` — `health`, `files`, `tasks`

### Common Utilities (`core/common/`)
- **`database/session.py`** — `make_session_factory(url, debug)` → `(engine, SessionLocal)`; `make_get_db(SessionLocal)` → FastAPI dependency. Each agent wires its own session in `db/session.py`.
- **`llm/`** — `BaseLLMProvider` ABC: `extract_tasks(text,prompt)->list[dict]` + `call_raw(system,user)->str`. `ClaudeProvider` (Anthropic SDK). `MockProvider` reads `tests/fixtures/mock_llm_response.json`. Provider via `LLM_PROVIDER`; per-request override: `?llm_provider=claude|mock`
- **`storage/`** — `BaseStorageProvider` ABC; `LocalProvider` (`./local_storage/`) + `GCSProvider`; blocking I/O via `asyncio.to_thread()`
- **`scrum/jira.py`** — `JiraService.push_task(task, settings)` + `update_existing_task(task, settings)`; Jira Cloud REST v3; writes back `jira_id`+`jira_url`; result includes `action: "created"|"updated"`. Uses duck-typing for `task` and `settings` — works with any object providing the expected attributes.

### Requirements POD DB (`core/requirements_pod/db/`)
- **`models.py`** — `SourceFile`, `Task` (soft-delete via `status=deleted`); `Base(DeclarativeBase)`
- **`session.py`** — Wires `make_session_factory` with agent config; exports `engine`, `SessionLocal`, `get_db`
- **`repository.py`** — DAO; `task_id` is a slug (`SRC-001`); generated via `MAX(task_id)` + retry-on-`IntegrityError` (5 attempts)

### Schemas
`core/requirements_pod/schemas/` — Pydantic models separate from ORM

### Extraction Pipeline (`core/requirements_pod/services/extraction/`)
Modules: `config.py` (ExtractionConfig+env overrides), `chunker.py` (S2), `llm.py` (S3, RawTask, SYSTEM_PROMPT), `dedup.py` (S4-5), `merge.py` (S6, UnionFind), `temporal.py` (S7, TemporalTask), `scoring.py` (S8), `output.py` (S9), `pipeline.py` (orchestrator + `parse_file` public interface)

### Frontend (`webapp/requirements_pod/src/`)
- **`App.jsx`** — Tab SPA: Upload | Browse Files | Tasks; LLM provider toggle (state here, passed to children as `?llm_provider=`)
- **`api/client.js`** — centralised API client; errors include `.code`, `.status`, `.endpoint`
- **`components/FileUpload.jsx`** — upload+parse; amber warning on 0 tasks
- **`components/GCSBrowser.jsx`** — browse GCS; `guestName`→`user_name`→prefix `{GCS_PREFIX}/{user_name}/`; up to 3 files, batch-parse; `resolveFileRecord`: `findFileByPath` → on 404 → `POST /files/register`; per-file status: green/amber/red
- **`components/TaskTable.jsx`** — inline edit, bulk export/Jira-push/delete, modal via `TaskCard`; collapsible filter panel (source file + user); export timestamp suffix `yymmddhh`; Jira push confirm dialog (created vs updated count)
- Guest username in `localStorage`, shown in editable header

### Database
Controlled by `DATABASE_URL` in `config.env` (`.env` overrides):
- **SQLite** (default): `sqlite:///./taskflow.db`
- **PostgreSQL**: `postgresql://USER:PASSWORD@/DBNAME?host=/cloudsql/PROJECT:REGION:INSTANCE` (Unix socket) or `postgresql://USER:PASSWORD@HOST:5432/DBNAME`

**Special chars in password** must be percent-encoded: `#`→`%23`, `+`→`%2B`, `>`→`%3E`, `@`→`%40`.

Tables: `SourceFile`, `Task`. `migrations/env.py` reads `DATABASE_URL` from `get_settings()` — no shell export needed. `psycopg2-binary` in requirements.

### Configuration Files
- `config.env` — committed, non-secret defaults
- `.env` — local overrides; needs `ANTHROPIC_API_KEY` for real extraction
- `project_context.md` — LLM system prompt template; bracketed placeholders filled at runtime
- `GCS_PREFIX` — optional bucket path prefix; GCS path: `{GCS_PREFIX}/{user}/{YYYY-MM-DD}/{filename}_{yymmddHHMMSS}.{ext}`

## Task Fields (DB columns)

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| `task_heading` | String 512 | AI | Maps to Jira summary |
| `description` | Text | AI | |
| `task_type` | String 32 | AI | bug/story/task/subtask |
| `priority` | String 32 | AI | critical/high/medium/low |
| `story_points` | Integer | AI | Fibonacci (1,2,3,5,8,13,21) |
| `acceptance_criteria` | Text | AI | JSON-encoded list[str] |
| `reporter` | String 256 | AI | Extracted when mentioned in doc |
| `sprint` | String 256 | AI/manual | Sprint name when mentioned |
| `fix_version` | String 256 | AI/manual | Release version when mentioned |
| `user_name` | String 256 | Manual | Assignee; blank by default |
| `jira_id` | String 64 | Jira | Set after push |

## Key API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/files/upload` | Upload document (multipart) |
| `GET /api/v1/files/find?path=` | Look up DB file record by storage path |
| `POST /api/v1/files/register` | Find-or-create DB record for GCS file; idempotent |
| `DELETE /api/v1/files/storage?path=` | Delete file from storage and its DB record |
| `POST /api/v1/files/{id}/parse?llm_provider=` | Trigger extraction; `llm_provider=claude\|mock` overrides config |
| `GET /api/v1/files/{id}/progress` | Live extraction progress `{stage, chunks_done, chunks_total, pct}` |
| `GET /api/v1/files/{id}/status` | Poll parse status |
| `GET /api/v1/files/list?user_name=` | List GCS objects for user (excludes folder entries) |
| `GET /api/v1/tasks` | List tasks (`?source_file=&user_name=&status=`) |
| `PATCH /api/v1/tasks/{id}` | Update task (all fields including new Jira fields) |
| `DELETE /api/v1/tasks/{id}` | Soft-delete task |
| `POST /api/v1/tasks/export` | Export JSON/CSV/MD |
| `POST /api/v1/tasks/jira-push` | Push to Jira; sends priority, story points, fix version, acceptance criteria |

## Jira Push
`core/common/scrum/jira.py` `_build_fields()` sends: summary, description+acceptance criteria (ADF), issuetype, priority, `customfield_10016` (story points), fixVersions. Sprint name sent as label `sprint:<name>`. Reporter not auto-sent (requires Atlassian account ID).

## Migrations
- `001_initial.py` — initial schema
- `002_add_task_fields.py` — adds priority, reporter, sprint, fix_version, story_points, acceptance_criteria

## Testing
pytest + pytest-asyncio + respx; in-memory SQLite via `tests/conftest.py`; mock LLM auto-activated — no `ANTHROPIC_API_KEY` needed.

## Adding a New Agent
1. Create `core/<agent_name>/` with its own `main.py`, `config.py`, `api/`, `db/`, `schemas/`, `services/`, `migrations/`
2. Reuse `core/common/llm/`, `core/common/storage/`, `core/common/scrum/`, `core/common/database/`
3. Create `webapp/<agent_name>/` for its UI
4. Add a new service entry in `docker-compose.yml`
