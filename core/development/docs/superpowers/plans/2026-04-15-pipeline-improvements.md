# Pipeline Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three improvements to the Development Pod pipeline: per-type SQL queries for metadata retrieval, BigQuery schema check before DDL generation, and a simplified git push checkpoint (no merge-to-main).

**Architecture:** All changes are in two existing files — `input_parser.py` (document retrieval) and `agents/orchestration/orchestrator.py` (BQ check + git checkpoint). No new files, no new models, no new agents.

**Tech Stack:** Python 3.12, SQLAlchemy (metadata DB queries), google-cloud-bigquery SDK (schema check), existing `GitRepoManager` from `core/utilities/versioning_tools/git_manager.py`.

---

## File Map

| File | What changes |
|------|-------------|
| `core/development/input_parser.py` | `_get_all_ticket_documents()` replaced with 3 per-type queries |
| `core/development/agents/orchestration/orchestrator.py` | New `_check_existing_bq_tables()` method; `_checkpoint_deploy()` replaced by `_checkpoint_git_push()`; merge-to-main paths removed from `run()` |
| `core/development/tests/test_input_parser.py` | New — unit tests for the rewritten retrieval function |
| `core/development/tests/test_bq_schema_check.py` | New — unit tests for the BQ schema comparison logic |

---

## Task 1: Rewrite `_get_all_ticket_documents()` with per-type queries

**Files:**
- Modify: `core/development/input_parser.py` — `_get_all_ticket_documents()` function (lines 157–200)
- Create: `core/development/tests/__init__.py`
- Create: `core/development/tests/test_input_parser.py`

### Step 1.1: Create tests directory and write failing tests

Create `core/development/tests/__init__.py` (empty file).

Create `core/development/tests/test_input_parser.py`:

```python
"""Unit tests for _get_all_ticket_documents per-type query logic."""
from __future__ import annotations
from unittest.mock import MagicMock, patch, call
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from input_parser import _get_all_ticket_documents


def _make_row(agent, file_type, path, filename):
    row = MagicMock()
    row.AGENT = agent
    row.FILE_TYPE = file_type
    row.PATH = path
    row.FILENAME = filename
    return row


def test_fetches_three_separate_queries(tmp_path):
    """Three queries issued: one per file type (MD, CSV, JSON)."""
    md_row  = _make_row("DesignAgent", "MD",  "output/SCRUM-1", "impl.md")
    csv_row = _make_row("DataModel",   "CSV", "output/SCRUM-1", "mapping.csv")
    json_row = _make_row("RequirementsAgent", "JSON", "output/SCRUM-1", "req.json")

    mock_conn = MagicMock()
    # Returns one row per query in call order
    mock_conn.execute.side_effect = [
        MagicMock(fetchone=MagicMock(return_value=md_row)),
        MagicMock(fetchone=MagicMock(return_value=csv_row)),
        MagicMock(fetchone=MagicMock(return_value=json_row)),
    ]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    with patch("input_parser.build_metadata_engine", return_value=mock_engine):
        docs = _get_all_ticket_documents("SCRUM-1", tmp_path)

    assert mock_conn.execute.call_count == 3
    assert len(docs) == 3
    types = {d["file_type"] for d in docs}
    assert types == {"MD", "CSV", "JSON"}


def test_missing_file_type_returns_partial(tmp_path):
    """If one file type has no rows, only the found types are returned."""
    md_row = _make_row("DesignAgent", "MD", "output/SCRUM-2", "impl.md")

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = [
        MagicMock(fetchone=MagicMock(return_value=md_row)),  # MD found
        MagicMock(fetchone=MagicMock(return_value=None)),     # CSV missing
        MagicMock(fetchone=MagicMock(return_value=None)),     # JSON missing
    ]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    with patch("input_parser.build_metadata_engine", return_value=mock_engine):
        docs = _get_all_ticket_documents("SCRUM-2", tmp_path)

    assert len(docs) == 1
    assert docs[0]["file_type"] == "MD"


def test_no_rows_raises_file_not_found(tmp_path):
    """If all three queries return no rows, FileNotFoundError is raised."""
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = [
        MagicMock(fetchone=MagicMock(return_value=None)),
        MagicMock(fetchone=MagicMock(return_value=None)),
        MagicMock(fetchone=MagicMock(return_value=None)),
    ]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    import pytest
    with patch("input_parser.build_metadata_engine", return_value=mock_engine):
        with pytest.raises(FileNotFoundError, match="SCRUM-99"):
            _get_all_ticket_documents("SCRUM-99", tmp_path)
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_input_parser.py -v 2>&1 | head -40
```

Expected: 3 FAILED (function still uses old single-query implementation).

- [ ] **Step 1.3: Rewrite `_get_all_ticket_documents()` in `input_parser.py`**

Replace the function body (lines 157–200) with:

```python
def _get_all_ticket_documents(ticket_id: str, repo_root: "Path") -> list[dict]:
    """
    Query agent_output_metadata for the most recent MD, CSV, and JSON
    document for a ticket — one query per file type, LIMIT 1 each.

    Returns a list of 0–3 dicts (one per found file type).
    Raises FileNotFoundError if no documents are found at all.
    """
    from sqlalchemy import text
    from db import build_metadata_engine

    _SQL = """
        SELECT AGENT, FILE_TYPE, PATH, FILENAME, CREATED_TS
        FROM agent_output_metadata
        WHERE IDENTIFIER = :ticket_id AND FILE_TYPE = :file_type
        ORDER BY CREATED_TS DESC
        LIMIT 1
    """

    engine = build_metadata_engine()
    result: list[dict] = []

    with engine.connect() as conn:
        for file_type in ("MD", "CSV", "JSON"):
            row = conn.execute(
                text(_SQL),
                {"ticket_id": ticket_id, "file_type": file_type},
            ).fetchone()
            if row is None:
                continue
            file_path = Path(repo_root).parent / row.PATH / row.FILENAME
            result.append({
                "agent":     row.AGENT,
                "file_type": row.FILE_TYPE.upper(),
                "path":      file_path,
                "filename":  row.FILENAME,
            })

    if not result:
        raise FileNotFoundError(
            f"No outputs found for ticket {ticket_id!r} in AGENT_OUTPUT_METADATA "
            "(checked MD, CSV, JSON). Ensure the design/requirements agents have "
            "been run for this ticket first."
        )

    return result
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_input_parser.py -v
```

Expected output:
```
tests/test_input_parser.py::test_fetches_three_separate_queries PASSED
tests/test_input_parser.py::test_missing_file_type_returns_partial PASSED
tests/test_input_parser.py::test_no_rows_raises_file_not_found PASSED
3 passed
```

---

## Task 2: Add BigQuery schema check before DDL generation

**Files:**
- Modify: `core/development/agents/orchestration/orchestrator.py` — add `_check_existing_bq_tables()` method and call it in `run()`
- Create: `core/development/tests/test_bq_schema_check.py`

### Step 2.1: Write failing tests for schema comparison logic

The schema comparison logic is a standalone helper function `_parse_mapping_schema()` and a normalization helper `_normalize_bq_type()`. Both will be extracted as module-level functions in `orchestrator.py` so they can be imported in tests.

Create `core/development/tests/test_bq_schema_check.py`:

```python
"""Unit tests for BigQuery schema check helpers in orchestrator.py."""
from __future__ import annotations
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.orchestration.orchestrator import _parse_mapping_schema, _normalize_bq_type


_SAMPLE_CSV = """\
source_table,source_column,source_data_type,target_table,target_column,target_data_type,nullable,is_pk,is_pii,transformation,notes
EMPLOYEES,EMP_ID,NUMBER,stg_employees,emp_id,INT64,false,true,false,,
EMPLOYEES,FIRST_NAME,VARCHAR2,stg_employees,first_name,STRING,true,false,false,,
EMPLOYEES,HIRE_DATE,DATE,stg_employees,hire_date,DATE,true,false,false,,
DEPARTMENTS,DEPT_ID,NUMBER,stg_departments,dept_id,INT64,false,true,false,,
DEPARTMENTS,DEPT_NAME,VARCHAR2,stg_departments,dept_name,STRING,true,false,false,,
"""


def test_parse_mapping_schema_groups_by_target_table():
    schema = _parse_mapping_schema(_SAMPLE_CSV)
    assert set(schema.keys()) == {"stg_employees", "stg_departments"}


def test_parse_mapping_schema_correct_columns():
    schema = _parse_mapping_schema(_SAMPLE_CSV)
    emp_cols = schema["stg_employees"]
    assert ("emp_id", "INT64") in emp_cols
    assert ("first_name", "STRING") in emp_cols
    assert ("hire_date", "DATE") in emp_cols


def test_normalize_bq_type_aliases():
    assert _normalize_bq_type("INTEGER") == "INT64"
    assert _normalize_bq_type("FLOAT") == "FLOAT64"
    assert _normalize_bq_type("BOOLEAN") == "BOOL"


def test_normalize_bq_type_passthrough():
    assert _normalize_bq_type("STRING") == "STRING"
    assert _normalize_bq_type("NUMERIC") == "NUMERIC"
    assert _normalize_bq_type("TIMESTAMP") == "TIMESTAMP"


def test_normalize_bq_type_case_insensitive():
    assert _normalize_bq_type("integer") == "INT64"
    assert _normalize_bq_type("Float") == "FLOAT64"
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_bq_schema_check.py -v 2>&1 | head -20
```

Expected: ImportError — `_parse_mapping_schema` and `_normalize_bq_type` do not exist yet.

- [ ] **Step 2.3: Add helper functions and `_check_existing_bq_tables()` to `orchestrator.py`**

Add these two module-level helpers just before the `CodeGenPipeline` class definition (after the `logger = ...` line, before `class CodeGenPipeline`):

```python
# ── BigQuery schema helpers ────────────────────────────────────────────────────

_BQ_TYPE_ALIASES: dict[str, str] = {
    "INTEGER": "INT64",
    "FLOAT":   "FLOAT64",
    "BOOLEAN": "BOOL",
}


def _normalize_bq_type(bq_type: str) -> str:
    """Normalize BQ API type names to their canonical DDL equivalents."""
    return _BQ_TYPE_ALIASES.get(bq_type.upper(), bq_type.upper())


def _parse_mapping_schema(mapping_csv: str) -> dict[str, set[tuple[str, str]]]:
    """
    Parse mapping CSV and return {target_table: {(column_name, bq_type)}}.

    Column names are lowercased; types are normalized via _normalize_bq_type.
    """
    import csv as _csv, io as _io
    reader = _csv.DictReader(_io.StringIO(mapping_csv))
    schema: dict[str, set[tuple[str, str]]] = {}
    for row in reader:
        table = (row.get("target_table") or "").strip().lower()
        col   = (row.get("target_column") or "").strip().lower()
        dtype = (row.get("target_data_type") or "").strip()
        if not table or not col or not dtype:
            continue
        schema.setdefault(table, set()).add((col, _normalize_bq_type(dtype)))
    return schema
```

Then add `_check_existing_bq_tables()` as a method of `CodeGenPipeline`, after `__init__` and before `run()`:

```python
def _check_existing_bq_tables(self, request: "PipelineInput", ctx: "SessionContext") -> None:
    """
    Before planning, check if target tables already exist in BigQuery
    with a matching schema. Injects a pre-plan note listing tables to skip.

    Silently skips the check if:
    - project_id or dataset_id are empty
    - google-cloud-bigquery is not installed
    - BQ credentials are unavailable
    """
    if not request.project_id or not request.dataset_id:
        logger.info("BQ schema check skipped — project_id or dataset_id not set.")
        return
    if not request.mapping_csv:
        logger.info("BQ schema check skipped — no mapping CSV.")
        return

    try:
        from google.cloud import bigquery as _bq
        from google.api_core.exceptions import NotFound
    except ImportError:
        logger.warning("google-cloud-bigquery not installed — skipping BQ schema check.")
        return

    expected = _parse_mapping_schema(request.mapping_csv)
    if not expected:
        return

    try:
        client = _bq.Client(project=request.project_id)
    except Exception as exc:
        logger.warning("BQ client init failed — skipping schema check: %s", exc)
        return

    already_present: list[str] = []

    for table_name, expected_cols in expected.items():
        table_ref = f"{request.project_id}.{request.dataset_id}.{table_name}"
        try:
            bq_table = client.get_table(table_ref)
        except NotFound:
            logger.info("BQ schema check: %s not found — DDL will be generated.", table_name)
            continue
        except Exception as exc:
            logger.warning("BQ schema check error for %s — %s. Skipping check.", table_name, exc)
            continue

        bq_cols = {
            (field.name.lower(), _normalize_bq_type(field.field_type))
            for field in bq_table.schema
        }

        if bq_cols == expected_cols:
            _info(f"  [SKIP] {table_name} — artifact already present in BQ, schema matches. No DDL needed.")
            already_present.append(table_name)
        else:
            missing = expected_cols - bq_cols
            extra   = bq_cols - expected_cols
            logger.info(
                "BQ schema check: %s exists but schema differs "
                "(missing=%s, extra=%s) — DDL will be generated.",
                table_name, missing, extra,
            )

    if already_present:
        note = (
            "The following tables already exist in BigQuery with a matching schema. "
            "Do NOT generate DDL for them: "
            + ", ".join(already_present)
        )
        ctx.add_note(note)
        logger.info("BQ schema check: %d table(s) already present — injected skip note.", len(already_present))
```

- [ ] **Step 2.4: Call `_check_existing_bq_tables()` at the top of `run()` in `orchestrator.py`**

In `CodeGenPipeline.run()`, find the block that starts Stage 1 (after `out_dir.mkdir` and `ctx = SessionContext(...)` initialization). Add the BQ check call right after `ctx` is created but before `_stage("1 / 3 — PLANNING")`:

```python
        # ── Pre-plan: BigQuery schema check ───────────────────────────────────
        self._check_existing_bq_tables(request, ctx)

        # ── Stage 1: Plan ──────────────────────────────────────────────────────
        _stage("1 / 3 — PLANNING")
```

- [ ] **Step 2.5: Run tests to verify they pass**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_bq_schema_check.py -v
```

Expected output:
```
tests/test_bq_schema_check.py::test_parse_mapping_schema_groups_by_target_table PASSED
tests/test_bq_schema_check.py::test_parse_mapping_schema_correct_columns PASSED
tests/test_bq_schema_check.py::test_normalize_bq_type_aliases PASSED
tests/test_bq_schema_check.py::test_normalize_bq_type_passthrough PASSED
tests/test_bq_schema_check.py::test_normalize_bq_type_case_insensitive PASSED
5 passed
```

- [ ] **Step 2.6: Run the full test suite**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/ -v
```

Expected: 8 passed.

---

## Task 3: Replace Checkpoint 3 with git push confirmation

**Files:**
- Modify: `core/development/agents/orchestration/orchestrator.py` — replace `_checkpoint_deploy()` with `_checkpoint_git_push()`; remove merge paths from `run()`

- [ ] **Step 3.1: Add `_checkpoint_git_push()` to `orchestrator.py`**

Find `_checkpoint_deploy()` (around line 919). Replace the entire function with:

```python
def _checkpoint_git_push(
    git,
    branch_name: str,
    run_state=None,
) -> bool:
    """
    CHECKPOINT 3 — ask the user whether to push the committed feature branch
    to the remote. Returns True if the user chose to push, False otherwise.

    git        : GitRepoManager instance (already connected, branch committed)
    branch_name: the feature branch name, e.g. feature/SCRUM-75_20260415_v1
    run_state  : API run state; if provided, pause_at_checkpoint is used
    """
    prompt = (
        f"CHECKPOINT 3 — PUSH TO GIT\n\n"
        f"Artifacts committed locally to branch: {branch_name}\n\n"
        f"Push to remote? [yes / no]"
    )

    if run_state is not None:
        decision = run_state.pause_at_checkpoint(number=3, prompt=prompt)
        if decision.decision.value in ("approve", "deploy"):
            git.push()
            _info(f"Git: pushed to origin/{branch_name}")
            return True
        _info(f"Git: branch committed locally. Push manually with: git push origin {branch_name}")
        return False

    # CLI mode
    print()
    _sep()
    print("  CHECKPOINT 3 — PUSH TO GIT")
    _sep()
    print()
    _info(f"Branch  : {branch_name}")
    _info("Artifacts committed locally.")
    print()

    while True:
        raw = _input("Push to remote? [yes / no]").lower().strip()
        if raw in ("yes", "y"):
            git.push()
            _info(f"Git: pushed to origin/{branch_name}")
            return True
        if raw in ("no", "n"):
            _info(f"Git: branch committed locally.")
            _info(f"Run to publish: git push origin {branch_name}")
            return False
        print(f"  Type yes or no.")
```

- [ ] **Step 3.2: Update `run()` to use `_checkpoint_git_push()` and remove merge-to-main paths**

In `CodeGenPipeline.run()`, find the block that starts with:
```python
        # ── Git: commit approved artifacts to feature branch ─────────────────────
        git_branch: str | None = None
        if _git_manager is not None:
```

Replace everything from that comment through the line `return output` at the end of `run()` with the following. The lines **before** this block (out_dir setup, ctx, BQ check, stages 1 and 2) are unchanged.

```python
        # ── Git: commit approved artifacts to feature branch ───────────────────
        git_branch: str | None = None
        if _git_manager is not None:
            _stage("GIT — COMMITTING ARTIFACTS TO FEATURE BRANCH")
            if self._run_state:
                self._run_state.status = RunStatus.COMMITTING
            git_branch = self._commit_to_git(_git_manager, ctx)
            if self._run_state and git_branch:
                self._run_state.git_branch = git_branch

            # ── Checkpoint 3: confirm push to remote ───────────────────────────
            _stage("GIT — PUSH TO REMOTE")
            _checkpoint_git_push(
                _git_manager,
                git_branch or _git_manager.target_branch,
                self._run_state,
            )

        output = CodeGenOutput(
            request_id=ctx.request_id,
            plan=plan,
            artifacts=artifacts,
            review_results=reviews,
            quality_score=quality,
            output_directory=str(out_dir),
            approved_for_deploy=True,
            git_branch=git_branch,
        )
        _write_manifest(out_dir, output, ctx, git_branch, self._git_repo_url)

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({"input_hash": input_hash, "output_dir": str(out_dir),
                        "generated_at": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )

        _banner("PIPELINE COMPLETE")
        _info(f"Quality score       : {quality:.0f}/100")
        _info(f"Artifacts           : {out_dir}")
        if git_branch:
            _info(f"Git branch          : {git_branch}")
        return output
```

Note: `approved_for_deploy` is `True` unconditionally — checkpoint 2 approval is the gate. The old merge/deploy decision logic and the `_stage("3 / 3 — DEPLOY HAND-OFF")` block are removed entirely.

- [ ] **Step 3.3: Run all tests to confirm nothing is broken**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/ -v
```

Expected: 8 passed, 0 failed.

- [ ] **Step 3.4: Smoke test — verify the pipeline imports cleanly**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -c "
from agents.orchestration.orchestrator import CodeGenPipeline, _parse_mapping_schema, _normalize_bq_type, _checkpoint_git_push
print('imports OK')
print('_normalize_bq_type(INTEGER):', _normalize_bq_type('INTEGER'))
csv = 'target_table,target_column,target_data_type\nstg_emp,emp_id,INT64\n'
print('_parse_mapping_schema:', _parse_mapping_schema(csv))
"
```

Expected:
```
imports OK
_normalize_bq_type(INTEGER): INT64
_parse_mapping_schema: {'stg_emp': {('emp_id', 'INT64')}}
```

- [ ] **Step 3.5: Smoke test — verify input_parser imports cleanly**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -c "
from input_parser import _get_all_ticket_documents
import inspect
src = inspect.getsource(_get_all_ticket_documents)
assert 'LIMIT 1' in src, 'LIMIT 1 not found in rewritten function'
assert 'fetchone' in src, 'fetchone not found — still using fetchall?'
print('input_parser OK — per-type queries confirmed')
"
```

Expected:
```
input_parser OK — per-type queries confirmed
```

---

## Self-Review Checklist

After implementation, verify:

- [ ] `_get_all_ticket_documents()` issues exactly 3 `conn.execute()` calls (one per file type)
- [ ] `_check_existing_bq_tables()` is called before `_run_plan_with_revision()` in `run()`
- [ ] `_checkpoint_deploy()` no longer exists; `_checkpoint_git_push()` is the replacement
- [ ] The `merge` branch path (lines ~197–214 in original `orchestrator.py`) is fully removed
- [ ] `approved_for_deploy` in `CodeGenOutput` is set to `True` (not conditional on deploy decision)
- [ ] All 8 tests pass
