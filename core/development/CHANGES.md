# Development Pod — Change Log

> Date: 2026-04-16
> Branch: rakesh_0415

This document describes the enhancements and bug-fixes applied to
`core/development`.  All changes are backward-compatible.

---

## 1. Planner — Precise Document Parsing

**Files:** `api/models.py`, `agents/planner/prompts.py`, `agents/planner/agent.py`

Three new fields are now captured in every `ExecutionPlan`:

| Field | Purpose |
|---|---|
| `connection_details` | Every JDBC URL, GCS path, host:port, API endpoint, or env-var name explicitly stated in the doc |
| `logging_mechanisms` | Cloud Logging, Stackdriver, BQ audit tables — only what the doc names |
| `alerting_mechanisms` | Cloud Monitoring, PagerDuty, Email/Slack — only what the doc names |

New models added to `api/models.py`:
- `ConnectionDetailSpec` — `service`, `type`, `value`, `env_var`
- `LoggingSpec` — `type`, `description`
- `AlertingSpec` — `type`, `description`

Planner system prompt extended with requirements 12–14 that instruct the LLM
to capture all connection strings / paths / logging / alerting verbatim from
the document.  The JSON output schema now includes three new keys.

---

## 2. Mermaid (.mmd) File Support + DB Latest-File Query

**File:** `core/development/input_parser.py`

`_get_all_ticket_documents()` now queries these file types from
`agent_output_metadata` (each with `ORDER BY CREATED_TS DESC LIMIT 1`):

```
MD, MERMAID, MMD, CSV, JSON, DOC, DOCX
```

Previously only `MD`, `CSV`, `JSON` were fetched.
**MERMAID / MMD** diagram files (from the Design pod) are merged into the
implementation doc so the Planner can use architecture / data-flow diagrams.
`ORDER BY CREATED_TS DESC LIMIT 1` guarantees the newest version per type.

---

## 3. No Duplicate Artifacts — Strict Overwrite

**File:** `agents/generator/agent.py`

`_extract_artifacts()` deduplicates code blocks from LLM output.
Same file name → only the last occurrence is kept (last wins).

```python
seen: dict[str, GeneratedArtifact] = {}   # keyed on file_name.lower()
seen[dedup_key] = artifact                # overwrites earlier duplicate
return list(seen.values())
```

Combined with `_write_artifacts()` already using `write_text()` (overwrite),
identical file names can never produce twin output files.

---

## 4. Selective File Modification — No Cascade for Explicit Selection

**File:** `agents/orchestration/orchestrator.py`

### Rule
When the user types `file <name>` at Checkpoint 2 and requests a change,
**only that file is touched** — regardless of change type (major or minor).
No other artifacts are regenerated or cascaded.

### Implementation
- `_checkpoint_code` returns notes prefixed with `[FILE_EXPLICIT:<name>]`
  when the user uses the `file` command.
- `_run_codegen_with_revision` detects this prefix, skips cascade
  expansion, and patches the single file via the Optimizer.

### Freeform "revise" notes (unchanged behaviour)
- **Minor** keywords (comments, formatting, logging) → optimizer patches
  selected file(s) in-place, no cascade.
- **Major** keywords (column, schema, join, transform) → `_cascade_targets()`
  expands to related artifacts only.  Unaffected artifacts are served from
  the review cache — never regenerated unnecessarily.

---

## 5. Git Push — Output Folder Only

**File:** `core/development/run_git.py`

### Whitelist `.gitignore`
`_ensure_workspace_gitignore()` now writes a whitelist style file:

```gitignore
*                       # ignore everything

!.gitignore             # allow .gitignore itself
![A-Z]*-[0-9]*/        # allow ticket folders: SCRUM-75/, JIRA-100/
![A-Z]*-[0-9]*/**
```

### Full index clear
Immediately after writing the `.gitignore`:

```bash
git rm --cached -r --quiet --ignore-unmatch .
```

This untracks everything in the index (including previously committed
`core/`, `design/`, `requirements/`, `webapp/` content).
Only files added by subsequent `git add --` calls enter the commit,
which are always the ticket output artifacts.

---

## 6. DELIVERY_MANIFEST.json — Testing-Team Format

**File:** `core/development/run_git.py`

New fields and corrections in the manifest written before every git commit:

| Field | Before | After |
|---|---|---|
| `table` | absent | primary staging table (unqualified name from `plan.json`) |
| `files[].file_path` | absolute OS path | relative path within ticket folder (e.g. `ddl/stg_employees.sql`) |
| `files[].file_type` | raw (`dag`) | labelled (`airflow_dag`) |
| Deduplication | basic | strict by `folder/filename` |

#### File-type label mapping

| Internal | Delivery label |
|---|---|
| `ddl` | `bigquery_ddl` |
| `dml` | `bigquery_dml` |
| `sp` | `stored_procedure` |
| `dag` | `airflow_dag` |
| `pipeline` | `dataflow_pipeline` |
| `config` | `pipeline_config` |
| `doc` | `documentation` |

Sample output:

```json
{
  "project":        "VZ-CUST-MIGRATION",
  "sprint":         "SCRUM-75",
  "table":          "stg_employees",
  "version":        "1.0",
  "repo":           "https://github.com/verizon/data-migration",
  "branch":         "feature/SCRUM-75_20260416_v1",
  "target_branch":  "main",
  "commit_message": "feat: SCRUM-75 — pipeline artifacts",
  "files": [
    {
      "file_path":        "ddl/stg_employees.sql",
      "file_type":        "bigquery_ddl",
      "change_type":      "created",
      "columns_affected": [],
      "owner":            ""
    },
    {
      "file_path":        "dag/dag_scrum75_stg_employees.py",
      "file_type":        "airflow_dag",
      "change_type":      "created",
      "columns_affected": [],
      "owner":            ""
    }
  ]
}
```

The `DELIVERY_MANIFEST.json` is committed alongside code artifacts on every
`git commit` action so the testing team always has the latest manifest on
the feature branch before deployment.

---

## Compatibility Notes

- No new Python packages required.
- `ExecutionPlan` new fields default to `[]` — old `plan.json` files without
  these keys parse cleanly (graceful degradation).
- `.gitignore` whitelist approach replaces the previous blacklist.
  Existing feature branches that have committed non-output content will
  have those paths **untracked** on the next commit; a PR merge cleans
  them from the target branch.
