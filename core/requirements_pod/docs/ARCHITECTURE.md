# Requirements POD — Architecture Document

## Overview

**Requirements POD (TaskFlow AI Agent)** is a full-stack AI-powered application that ingests unstructured documents, extracts structured software requirements using Claude LLM, and optionally syncs them to Jira.

```
Document Input (PDF/DOCX/TXT/MD/VTT/SRT)
        ↓
  [Storage Layer]  ←→  GCS or Local Filesystem
        ↓
  [9-Stage Extraction Pipeline]  ←→  Claude LLM (API / SDK / Mock)
        ↓
  [MySQL on Cloud SQL]
        ↓
  [React UI]  ←→  Export (JSON/CSV/MD)  |  Jira Push
```

---

## System Components

```
DEAH/
├── core/requirements_pod/          # FastAPI backend
│   ├── main.py                     # App entry point, CORS, logging, lifespan
│   ├── config.py                   # Pydantic Settings (config.env + .env)
│   ├── api/v1/                     # REST routers: health, files, tasks
│   ├── db/                         # ORM models, session, repository (DAO)
│   ├── schemas/                    # Pydantic request/response models
│   ├── services/extraction/        # 9-stage extraction pipeline
│   └── migrations/versions/        # Alembic migrations (001–005)
│
├── core/utilities/
│   ├── llm/                        # LLM abstraction: Claude, SDK, Mock
│   ├── storage/                    # Storage abstraction: GCS, Local
│   └── db_tools/                   # Cloud SQL connector, DB config loader
│
└── webapp/requirements_pod/src/    # React + Vite frontend
    ├── App.jsx                     # Tab SPA: Upload | Browse Files | Tasks
    ├── api/client.js               # Centralised API client
    └── components/
        ├── FileUpload.jsx          # Upload + extraction UI
        ├── GCSBrowser.jsx          # Browse & parse from GCS
        ├── TaskTable.jsx           # View, filter, edit, export tasks
        └── TaskCard.jsx            # Task detail/edit modal
```

---

## API Layer

**Base URL**: `http://localhost:8000/api/v1`

### Files Router (`/files`)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/upload` | Upload a document (multipart) |
| `GET` | `/list` | List files in a project |
| `GET` | `/find?path=` | Lookup DB record by storage path |
| `POST` | `/register` | Find-or-create DB record for a storage file |
| `POST` | `/{id}/parse` | Extract tasks from a single file |
| `POST` | `/parse-merged` | Merge multiple files and extract together |
| `GET` | `/{id}/progress` | Poll live extraction progress |
| `GET` | `/{id}/status` | Get file processing status |
| `DELETE` | `/storage?path=` | Delete file from storage + DB |

### Tasks Router (`/tasks`)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `` | List tasks (filter by source, user, status) |
| `GET` | `/{id}` | Get single task |
| `PATCH` | `/{id}` | Update task fields |
| `DELETE` | `/{id}` | Soft-delete task |
| `POST` | `/export` | Export tasks as JSON / CSV / Markdown |
| `POST` | `/jira-push` | Push selected tasks to Jira |

---

## Agent Flow — 9-Stage Extraction Pipeline

Entry point: `core/requirements_pod/services/extraction/pipeline.py → parse_file()`

```
┌─────────────────────────────────────────────────────────────────────┐
│                    EXTRACTION PIPELINE                               │
│                                                                     │
│  Input: raw file bytes (PDF / DOCX / TXT / MD / VTT / SRT)         │
│                                                                     │
│  Stage 1 ── NORMALISE (3%)                                          │
│    Remove null bytes, normalise line endings                        │
│    Output: clean text string                                        │
│                           │                                         │
│  Stage 2 ── CHUNK (8%)                                              │
│    Split into overlapping token windows                             │
│    chunk_size=2000 tokens, overlap=200 tokens                       │
│    Output: list[Chunk]                                              │
│                           │                                         │
│  Stage 3 ── LLM EXTRACT (12% → 90%)        ┌──────────────────┐   │
│    Fan out to 5 parallel Claude LLM calls   │  Claude LLM      │   │
│    Retry with exponential backoff (3x)      │  (API/SDK/Mock)  │   │
│    Parse JSON → RawTask objects             └──────────────────┘   │
│    Fields: summary, description, task_type,                         │
│      priority, story_points, acceptance_criteria,                   │
│      reporter, sprint, fix_version, schedule_interval,              │
│      objective, expected_outcome, connections,                      │
│      success_conditions, validation_rules                           │
│    Output: list[RawTask]                                            │
│                           │                                         │
│  Stage 4 ── LOCAL DEDUP (92%)                                       │
│    Jaccard similarity per document                                  │
│    Threshold: 0.75 — drop near-duplicates within same file          │
│    Output: filtered list[RawTask]                                   │
│                           │                                         │
│  Stage 5 ── GLOBAL POOL (92%)                                       │
│    Flatten per-file results into one list                           │
│    Output: global list[RawTask]                                     │
│                           │                                         │
│  Stage 6 ── GRAPH MERGE (95%)                                       │
│    Union-Find clustering: link tasks with Jaccard > 0.55            │
│    Merge cluster into one canonical task:                           │
│      • Highest confidence wins                                      │
│      • Union labels (max 5), acceptance criteria                    │
│      • Highest priority, max story points                           │
│    Output: list[MergedTask] with cluster_size                       │
│                           │                                         │
│  Stage 7 ── TEMPORAL REASONING (97%)                                │
│    Sort by (file_index, chunk_index)                                │
│    Rule 1: Later task with override markers kills earlier match     │
│      (e.g. "updated", "revised", "replaced by") — Jaccard > 0.35   │
│    Rule 2: Initial-marker tasks die if superseded later             │
│      (e.g. "originally", "preliminary", "tbd") — Jaccard > 0.40    │
│    Output: list[TemporalTask] (dead tasks filtered out)             │
│                           │                                         │
│  Stage 8 ── CONFIDENCE SCORE (97%)                                  │
│    score = extraction_confidence                                     │
│           + 0.04 × cluster_size (max +0.12)                         │
│           + 0.10 if cross-source (multi-file)                       │
│           + 0.02 × acceptance_criteria count (max +0.06)            │
│    Sort descending by confidence                                     │
│    Output: list[TemporalTask] with confidence (0.0–1.0)             │
│                           │                                         │
│  Stage 9 ── PERSIST (100%)                                          │
│    Map pipeline fields → DB schema                                  │
│    Store metadata as JSON in raw_llm_json                           │
│    Create Task records (SRC-001 slugs, 5-attempt unique retry)      │
│    Update SourceFile status → "parsed"                              │
│    Output: list[TaskOut]                                            │
└─────────────────────────────────────────────────────────────────────┘
```

### Live Progress

Progress is stored in-memory per `file_id` and polled by the frontend every 800ms:

```
GET /files/{file_id}/progress
→ { stage: "extracting", chunks_done: 4, chunks_total: 10, pct: 52 }
```

---

## End-to-End Request Flows

### Single File Upload & Extract

```
User (Browser)
  │
  ├─ POST /files/upload  [multipart: file, user_name, project_name]
  │     └─ Validate extension & size
  │     └─ storage.write() → GCS or local
  │     └─ repository.create_source_file()  [status=uploaded]
  │     └─ Returns FileOut {id, filename, file_path, ...}
  │
  ├─ POST /files/{id}/parse  [?llm_provider=claude|mock|claude-sdk]
  │     └─ Resolve LLM provider
  │     └─ pipeline.parse_file()  [9 stages]
  │     └─ Returns list[TaskOut]
  │
  └─ GET /files/{id}/progress  [polled every 800ms]
        └─ Returns {stage, chunks_done, chunks_total, pct}
        └─ Frontend updates progress bar
```

### Merged File Extract

```
User (Browser)
  │
  └─ POST /files/parse-merged  [body: {file_ids: [...]}, ?llm_provider=...]
        └─ Download all files from storage
        └─ Concatenate with "=== Document: {filename} ===" separators
        └─ Single pipeline.parse_files_merged() run
        └─ All tasks linked to primary file
        └─ Returns list[TaskOut]
```

### Task Edit & Export

```
User (Browser)
  │
  ├─ PATCH /tasks/{id}  [body: updated fields]
  │     └─ repository.update_task()
  │     └─ Auto-sets status=modified (if not pushed/deleted)
  │
  └─ POST /tasks/export  [body: {task_ids, format: json|csv|md}]
        └─ Bulk fetch tasks
        └─ Serialize to format
        └─ StreamingResponse → browser download
```

### Jira Push

```
User (Browser)
  │
  └─ POST /tasks/jira-push  [body: {task_ids: [...]}]
        └─ For each task:
              ├─ task.jira_id exists → JiraService.update_existing_task()
              └─ no jira_id          → JiraService.push_task()  [creates issue]
        └─ Write back jira_id, jira_url, status=pushed
        └─ Returns {results: [{task_id, success, jira_id, action}, ...]}
```

---

## LLM Provider Abstraction

```
BaseLLMProvider (ABC)
  ├── extract_tasks(text, system_prompt) → list[dict]
  └── call_raw(system, user) → str

Implementations:
  ├── ClaudeProvider         Direct Anthropic API (AsyncAnthropic SDK)
  ├── _ClaudeSDKProvider     Claude Agent SDK (bridged via anyio thread)
  └── MockLLMProvider        Returns fixture from tests/fixtures/mock_llm_response.json

Selection (per-request override takes priority):
  config.env LLM_PROVIDER  →  "claude" | "claude-sdk" | "mock"
  query param ?llm_provider →  overrides config for that request
```

---

## Storage Abstraction

```
BaseStorageProvider (ABC)
  ├── write(path, data) → str
  ├── read(path) → bytes
  ├── list_files(prefix) → list[dict]
  └── delete(path)

Implementations:
  ├── GCSStorageProvider   Google Cloud Storage (deah bucket, verizon-data project)
  └── LocalStorageProvider  Filesystem under ./local_storage/

GCS Path format: {GCS_PREFIX}/{user}/{YYYY-MM-DD}/{filename}_{yymmddHHMMSS}.{ext}
```

---

## Database Schema

**Cloud SQL (MySQL)** — `verizon-data:us-central1:mysql-druid-metadatastore`

### `req_agent_input` (SourceFile)

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `filename` | str(512) | Original filename |
| `file_path` | str(1024) | Storage path (GCS or local) |
| `storage_location` | str(64) | `gcs` \| `local` |
| `uploaded_by` | str(256) | User who uploaded |
| `upload_time` | DateTime | UTC |
| `status` | str(32) | `uploaded` \| `parsed` \| `error` |
| `file_size` | BigInt | Bytes |
| `mime_type` | str(256) | MIME type |

### `req_agent_tasks` (Task)

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `task_id` | str(32) | `SRC-001` slug, unique |
| `task_heading` | str(512) | Short summary ≤80 chars |
| `description` | Text | Rich markdown |
| `task_type` | str(32) | `bug` \| `story` \| `task` \| `subtask` |
| `priority` | str(32) | `critical` \| `high` \| `medium` \| `low` |
| `story_points` | Int | Fibonacci (1,2,3,5,8,13,21) |
| `acceptance_criteria` | Text | JSON-encoded list[str] |
| `reporter` | str(256) | Extracted from document |
| `sprint` | str(256) | Sprint name if mentioned |
| `fix_version` | str(256) | Release version if mentioned |
| `schedule_interval` | str(32) | `hourly` \| `daily` \| `weekly` \| `on-demand` |
| `user_name` | str(256) | Assignee (manual) |
| `status` | str(32) | `extracted` \| `modified` \| `pushed` \| `deleted` |
| `jira_id` | str(64) | Set after Jira push |
| `jira_url` | str(1024) | Jira issue URL |
| `confidence_score` | Float | 0.0–1.0 |
| `raw_llm_json` | Text | Full pipeline metadata (JSON) |
| `source_file_id` | FK | → req_agent_input.id |

### Migration History

| Revision | Change |
|----------|--------|
| 001 | Initial schema (source_files, tasks) |
| 002 | Add priority, reporter, sprint, fix_version, story_points, acceptance_criteria |
| 003 | Add confidence_score |
| 004 | Rename tables → req_agent_input, req_agent_tasks; add storage_location |
| 005 | Add schedule_interval |

---

## External Integrations

| Service | Purpose | Auth |
|---------|---------|------|
| **Anthropic API** | LLM extraction (Claude Sonnet) | `ANTHROPIC_API_KEY` |
| **Google Cloud Storage** | File storage (`deah` bucket) | Service account JSON |
| **Cloud SQL (MySQL)** | Persistence | Cloud SQL Connector + SA key |
| **Jira Cloud** | Issue tracking | `JIRA_EMAIL` + `JIRA_API_KEY` |

---

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `mock` | `mock` \| `claude` \| `claude-sdk` |
| `ANTHROPIC_API_KEY` | — | Required for `claude` / `claude-sdk` |
| `LLM_MODEL` | `claude-sonnet-4-20250514` | Claude model |
| `LLM_CHUNK_SIZE` | `3000` | Tokens per chunk |
| `LLM_CHUNK_OVERLAP` | `200` | Overlap tokens between chunks |
| `STORAGE_PROVIDER` | `gcs` | `gcs` \| `local` |
| `GCS_BUCKET_NAME` | `deah` | GCS bucket |
| `GCS_PREFIX` | `requirements-pod` | Path prefix in bucket |
| `GCS_CREDENTIALS_PATH` | `./credentials/gcs-sa-key.json` | SA key path |
| `MAX_UPLOAD_SIZE_MB` | `50` | Upload size limit |
| `ALLOWED_EXTENSIONS` | `pdf,docx,txt,md,vtt,srt` | Accepted file types |
| `JIRA_BASE_URL` | — | Jira Cloud instance URL |
| `JIRA_PROJECT_KEY` | `SCRUM` | Default Jira project |
| `CORS_ORIGINS` | `*` | Allowed frontend origins |
