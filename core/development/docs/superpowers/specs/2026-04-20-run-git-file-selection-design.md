# run_git.py — Independent Push with File Selection

**Date:** 2026-04-20  
**Scope:** `core/development/run_git.py` only  
**Status:** Approved

---

## Problem

After the main pipeline runs and artifacts are saved to `output/SCRUM-XX/`, users need an independent way to push those files to the git feature branch without re-running the full pipeline. Additionally, users need the ability to push either all generated files or a specific subset.

Currently `run_git.py` exists but:
- Requires `--pat` even when the git workspace is already initialized (PAT already embedded in remote URL)
- Does not support selective file pushing (always copies everything)

---

## Goals

1. Make `run_git.py` runnable independently of the main pipeline with no PAT required when the workspace already exists
2. Push all files in a ticket output dir (e.g. `output/SCRUM-123/`) to the feature branch
3. Allow pushing a selected subset of files via CLI flag or interactive prompt

---

## Auth Strategy

`--pat` and `--repo` are made **fully optional**.

When `output/git_workspace/.git` already exists (the normal case after a pipeline run), git operations (`commit`, `push`) are performed via subprocess directly — the PAT is already embedded in the configured remote URL from the prior pipeline connect. `GitRepoManager.connect()` is **skipped** when the workspace is already initialized.

When the workspace does **not** exist, `--repo` and `--pat` are still required to perform the initial clone. This preserves the existing first-time-setup path.

---

## File Selection

Two mechanisms, composable:

### CLI flag (`--files`)
Space-separated relative paths within the output dir, or the literal string `all`.

```bash
# All files, non-interactive
python run_git.py --output output/SCRUM-123 --files all

# Specific files
python run_git.py --output output/SCRUM-123 \
  --files "dag/dag_employees.py" "ddl/ddl_stg_employees.sql"
```

### Interactive fallback
When `--files` is not given, a numbered file list is shown and the user selects interactively.

```
── FILES IN output/SCRUM-123/ ──────────────────────
  [1]  dag/dag_employees_full_load.py
  [2]  ddl/ddl_employees_staging.sql
  [3]  ddl/ddl_stg_employees.sql
  [4]  dml/dml_merge_employees.sql
  [5]  config/pipeline_config.py
  [6]  MANIFEST.json
  [7]  REVIEW_REPORT.md
────────────────────────────────────────────────────
  all       push all files
  1 2 5     push specific files by number
  1-4       push a range
  quit      cancel
>
```

Accepted input forms:
- `all` — select all files
- `1 2 5` — space-separated numbers
- `1-4` — inclusive range
- `quit` — abort without pushing

---

## Code Changes

All changes are confined to `core/development/run_git.py`.

### New helpers

**`_list_output_files(output_dir: Path) -> list[str]`**  
Scans `output_dir` recursively. Returns a sorted list of relative path strings (e.g. `"dag/dag_employees.py"`). Filters by `_ARTIFACT_EXTENSIONS` (same set already defined in the file).

**`_interactive_select_files(files: list[str]) -> set[str]`**  
Prints the numbered list, reads user input in a loop, returns the selected relative paths as a set. Returns empty set if user types `quit` (caller treats this as abort).

**`_is_workspace_initialized(local_path: str) -> bool`**  
Returns `True` if `Path(local_path) / ".git"` exists. Used to decide whether to require PAT and whether to call `connect()`.

### Modified functions

**`_copy_artifacts_to_workspace(output_dir, workspace, selected=None)`**  
Adds optional `selected: set[str] | None` parameter. When `selected` is not `None`, only paths in `selected` are copied. When `None`, all files are copied (existing behaviour preserved).

**`action_commit(git, output_dir, message, git_repo_url, git_branch, selected=None)`**  
Passes `selected` through to `_copy_artifacts_to_workspace`.

**`main()`**  
- `--pat` and `--repo` marked `required=False`
- Before requiring PAT: check `_is_workspace_initialized(local_path)`
  - If initialized: skip `action_setup` (connect), proceed with pull → commit → push using existing remote
  - If not initialized: require `--repo` + `--pat`, run `action_setup` as before
- After resolving `output_dir` and before `action_commit`:
  - If `--files all` or `--files` with paths: use those as `selected` (or `None` for all)
  - If `--files` not given: call `_list_output_files` then `_interactive_select_files`
  - If interactive returns empty set (quit): print "Aborted." and exit cleanly

### argparse additions

```
--files   nargs="*"   Relative file paths to push, or "all". Interactive if omitted.
```

`--pat` and `--repo` become `required=False` (were implicitly required via `_require()`).

---

## Execution Flow

```
python run_git.py --output output/SCRUM-123
                         │
          workspace .git exists?
         ┌──────┴──────┐
        yes            no
         │              └── require --repo + --pat → connect()
         │
      pull latest from default branch
         │
      --files provided?
     ┌───┴───┐
    yes      no
     │        └── _list_output_files() → _interactive_select_files()
     │
  parse selected set (None = all)
         │
      action_commit(selected=...)
         │
      action_push()
         │
      print branch + PR link
```

---

## Out of Scope

- Changes to `core/utilities/versioning_tools/git_manager.py`
- Changes to `main.py` or `orchestrator.py`
- Pushing multiple ticket output dirs in one command
- Dry-run / preview mode

---

## Test Cases (manual)

| Scenario | Command | Expected |
|---|---|---|
| All files, workspace exists | `python run_git.py --output output/SCRUM-123` → type `all` | All files pushed to feature branch |
| Specific files via flag | `--files "dag/dag_employees.py"` | Only that file staged and pushed |
| Range selection | Interactive → type `1-3` | Files 1, 2, 3 pushed |
| Quit | Interactive → type `quit` | Prints "Aborted." and exits 0 |
| Workspace not initialized | No `.git` in workspace | Prints error: `--repo` and `--pat` required |
