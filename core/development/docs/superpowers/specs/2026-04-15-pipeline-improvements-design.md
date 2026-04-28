# Pipeline Improvements Design
**Date:** 2026-04-15
**Ticket scope:** SCRUM-75 and future tickets

## Summary

Three targeted improvements to the Development Pod pipeline:

1. Per-type SQL queries for document retrieval from the metadata DB
2. BigQuery schema check before DDL generation (skip already-deployed tables)
3. Simplified git integration — feature branch push with confirmation, merge-to-main removed

---

## Section 1: Per-Type Document Retrieval

### Problem
`_get_all_ticket_documents()` in `input_parser.py` issues one bulk SQL query fetching all rows for a ticket across all agents and file types, then deduplicates in Python by `(AGENT, FILE_TYPE)`. This is inconsistent with the operational convention of "latest wins per file type".

### Solution
Replace the single bulk query with 3 separate queries — one per supported file type — each returning exactly 1 row (`LIMIT 1 ORDER BY CREATED_TS DESC`):

```sql
-- MD document (most recent, any agent)
SELECT AGENT, FILE_TYPE, PATH, FILENAME, CREATED_TS
FROM agent_output_metadata
WHERE IDENTIFIER = :ticket_id AND FILE_TYPE = 'MD'
ORDER BY CREATED_TS DESC LIMIT 1

-- CSV document
SELECT AGENT, FILE_TYPE, PATH, FILENAME, CREATED_TS
FROM agent_output_metadata
WHERE IDENTIFIER = :ticket_id AND FILE_TYPE = 'CSV'
ORDER BY CREATED_TS DESC LIMIT 1

-- JSON document
SELECT AGENT, FILE_TYPE, PATH, FILENAME, CREATED_TS
FROM agent_output_metadata
WHERE IDENTIFIER = :ticket_id AND FILE_TYPE = 'JSON'
ORDER BY CREATED_TS DESC LIMIT 1
```

Each query returns 0 or 1 rows. Results are merged into the existing `docs` list. Downstream logic in `parse_inputs_from_ticket()` is unchanged — MD goes to `impl_parts`, CSV goes to `mapping_csv`, JSON is converted to markdown.

### Files changed
- `core/development/input_parser.py` — `_get_all_ticket_documents()` rewritten

---

## Section 2: BigQuery Schema Check Before DDL Generation

### Problem
The planner generates DDL artifacts for all target tables in the mapping file unconditionally. If a table already exists in BigQuery with a matching schema, the DDL generation wastes LLM calls and risks confusing the planner with tables that should not be re-created.

### Solution
Add a `_check_existing_bq_tables()` method to `CodeGenPipeline` in `orchestrator.py`, called at the top of `run()` before `_run_plan_with_revision()`.

**Flow:**

1. Parse `request.mapping_csv` → build `{ target_table → set[(column_name, bq_type)] }`
2. For each distinct `target_table`, call `BigQueryClient.get_table_schema(project_id, dataset_id, table_name)` 
3. Compare BQ columns (name + type) against the mapping-derived set:
   - All columns match → table is "already present", skip DDL
   - Table missing OR any column differs → needs DDL
4. For each already-present table, print to console:
   ```
     [SKIP] stg_employees — artifact already present in BQ, schema matches. No DDL needed.
   ```
5. Inject a pre-plan note into `SessionContext` before planning:
   ```
   The following tables already exist in BigQuery with a matching schema.
   Do NOT generate DDL for them: stg_employees, stg_departments
   ```
   The planner already respects `SessionContext.human_notes`.

**Graceful degradation:** If `project_id` or `dataset_id` are empty, or if `BigQueryClient` raises a credentials/connection error, the check is silently skipped with a warning log. The pipeline continues without the pre-check.

### Files changed
- `core/development/agents/orchestration/orchestrator.py` — new `_check_existing_bq_tables()` method, called in `run()`

---

## Section 3: Simplified Git Integration — Feature Branch Push With Confirmation

### Problem
Checkpoint 3 presents a 3-option deploy menu (merge to main / deploy directly / skip). The merge-to-main path is not needed; the team workflow is: push to feature branch → raise PR manually. The 3-option menu adds unnecessary complexity.

### Solution

**Remove entirely:**
- The `merge` branch path in `run()` (the `deploy_choice == "merge"` block)
- The 3-option `[1]/[2]/[3]` menu in `_checkpoint_deploy()`
- The `approved_for_deploy` / `direct` / `merge` decision values from checkpoint 3
- `DeployPipeline` hand-off from checkpoint 3 (deploy remains a separate workflow)

**Replace with `_checkpoint_git_push(git, branch_name)`:**

After checkpoint 2 approval and local commit, display:

```
  ── CHECKPOINT 3 — PUSH TO GIT ──

  Artifacts committed locally to: feature/SCRUM-75_20260415_v1
  Repo: https://github.com/org/repo

  Push to remote? [yes / no]:
```

- `yes` → `git.push()`, print confirmation
- `no` → print "Branch committed locally. Run `git push origin feature/SCRUM-75_20260415_v1` to publish."

API mode (run_state): checkpoint 3 prompt contains the branch name; decision maps `approve → push`, `skip → local only`.

**When git is not configured** (no `--git-repo-url`): Checkpoint 3 is skipped entirely. The pipeline ends after checkpoint 2 approval and artifact write. No confirmation prompt is shown.

**Branch naming** stays unchanged: `feature/{SCRUM-ID}_{YYYYMMDD}_v{N}` via existing `_resolve_branch_name()`.

**No new scripts needed** — `GitRepoManager` from `core/utilities/versioning_tools/git_manager.py` already supports `push()`.

### Files changed
- `core/development/agents/orchestration/orchestrator.py` — `_checkpoint_deploy()` replaced by `_checkpoint_git_push()`, merge branch paths removed from `run()`

---

## Out of Scope

- Changes to deployer agent (`agents/deployer/agent.py`) — DDL application logic unchanged
- New git scripts in `core/utilities/versioning_tools/` — existing `GitRepoManager` is sufficient
- Support for file types beyond MD, CSV, JSON in the per-type query (DOCX, MERMAID, etc. are no longer fetched via this path)

---

## Risk Notes

- **DOCX/MERMAID drop**: The current `_get_all_ticket_documents()` also fetches DOCX and MERMAID files. The new 3-query approach only fetches MD, CSV, JSON. If any ticket relies on DOCX or MERMAID inputs, those will be silently ignored. Confirm this is acceptable.
- **BQ credential requirement**: The schema check requires valid GCP credentials at plan time, not just deploy time. Teams running the pipeline locally without `GOOGLE_APPLICATION_CREDENTIALS` will see the check silently skipped.
