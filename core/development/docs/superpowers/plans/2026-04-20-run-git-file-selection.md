# run_git.py — Independent Push with File Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance `run_git.py` so it can push output artifacts to a git feature branch independently — no PAT needed when the workspace already exists — with interactive or CLI-flag-driven file selection.

**Architecture:** All changes are confined to `core/development/run_git.py`. The core commit logic is extracted from `action_commit` into a new `_do_commit()` helper that uses only subprocess (no `GitRepoManager`). When the git workspace is already initialized (`.git` exists), the main flow uses this subprocess-only path and skips `GitRepoManager` entirely. File selection is handled by two new helpers: `_list_output_files()` and `_interactive_select_files()`.

**Tech Stack:** Python 3.12, subprocess (stdlib), pytest, unittest.mock

---

## File Map

| File | Change |
|---|---|
| `core/development/run_git.py` | Modify — add helpers, refactor `action_commit`, update `main()` |
| `core/development/tests/test_run_git.py` | Create — unit tests for new helpers |

---

### Task 1: Add workspace-detection helpers and test them

**Files:**
- Create: `core/development/tests/test_run_git.py`
- Modify: `core/development/run_git.py` (append two helpers after the `_build_branch` function, around line 95)

- [ ] **Step 1: Create the test file with failing tests for both helpers**

Create `core/development/tests/test_run_git.py`:

```python
"""Tests for run_git.py helpers."""
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure run_git is importable from the tests/ directory
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_git


# ── _is_workspace_initialized ─────────────────────────────────────────────────

def test_is_workspace_initialized_true(tmp_path):
    (tmp_path / ".git").mkdir()
    assert run_git._is_workspace_initialized(str(tmp_path)) is True


def test_is_workspace_initialized_false(tmp_path):
    assert run_git._is_workspace_initialized(str(tmp_path)) is False


# ── _get_workspace_branch ─────────────────────────────────────────────────────

def test_get_workspace_branch_returns_branch_name(tmp_path):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "feature/SCRUM-123_20260420_v1\n"
        result = run_git._get_workspace_branch(str(tmp_path))
    assert result == "feature/SCRUM-123_20260420_v1"
    mock_run.assert_called_once_with(
        ["git", "branch", "--show-current"],
        cwd=str(tmp_path), capture_output=True, text=True,
    )


def test_get_workspace_branch_empty_returns_empty(tmp_path):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "\n"
        result = run_git._get_workspace_branch(str(tmp_path))
    assert result == ""
```

- [ ] **Step 2: Run the tests — confirm they fail with ImportError or AttributeError**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_run_git.py -v 2>&1 | head -30
```

Expected: `AttributeError: module 'run_git' has no attribute '_is_workspace_initialized'`

- [ ] **Step 3: Add the two helpers to `run_git.py` after the `_build_branch` function (after line 95)**

In `run_git.py`, after the `_build_branch` function and before `# ── Artifact helpers`, add:

```python
# ── Workspace helpers ──────────────────────────────────────────────────────────

def _is_workspace_initialized(local_path: str) -> bool:
    """Return True if local_path is already a git repository."""
    return (Path(local_path) / ".git").exists()


def _get_workspace_branch(local_path: str) -> str:
    """Return the currently checked-out branch name, or '' on failure."""
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=local_path, capture_output=True, text=True,
    )
    return result.stdout.strip()

```

- [ ] **Step 4: Run the tests — confirm they pass**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_run_git.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/varun_akarapu/DEAH/core/development
git add run_git.py tests/test_run_git.py
git commit -m "feat(run_git): add workspace-detection helpers"
```

---

### Task 2: Add `_list_output_files()` helper

**Files:**
- Modify: `core/development/run_git.py` (append after `_get_workspace_branch`)
- Modify: `core/development/tests/test_run_git.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/test_run_git.py`:

```python
# ── _list_output_files ────────────────────────────────────────────────────────

def test_list_output_files_returns_relative_paths(tmp_path):
    (tmp_path / "dag").mkdir()
    (tmp_path / "dag" / "dag_employees.py").write_text("# dag")
    (tmp_path / "ddl").mkdir()
    (tmp_path / "ddl" / "stg_employees.sql").write_text("-- ddl")
    (tmp_path / "ddl" / "target.sql").write_text("-- ddl2")
    # Non-artifact extension — should be excluded
    (tmp_path / "dag" / "notes.txt").write_text("ignore me")

    result = run_git._list_output_files(tmp_path)

    assert result == [
        "dag/dag_employees.py",
        "ddl/stg_employees.sql",
        "ddl/target.sql",
    ]


def test_list_output_files_empty_dir(tmp_path):
    assert run_git._list_output_files(tmp_path) == []


def test_list_output_files_excludes_pycache(tmp_path):
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "dag.cpython-312.pyc").write_text("")
    (tmp_path / "dag.py").write_text("# real")

    result = run_git._list_output_files(tmp_path)
    assert result == ["dag.py"]
```

- [ ] **Step 2: Run the tests — confirm they fail**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_run_git.py::test_list_output_files_returns_relative_paths -v
```

Expected: `AttributeError: module 'run_git' has no attribute '_list_output_files'`

- [ ] **Step 3: Implement `_list_output_files` in `run_git.py` after `_get_workspace_branch`**

```python
def _list_output_files(output_dir: Path) -> list[str]:
    """
    Return sorted relative paths of all artifact files under output_dir.
    Excludes __pycache__ and hidden directories.
    Only files with extensions in _ARTIFACT_EXTENSIONS are included.
    """
    results: list[str] = []
    for src in output_dir.rglob("*"):
        if not src.is_file():
            continue
        if "__pycache__" in src.parts:
            continue
        if any(part.startswith(".") for part in src.relative_to(output_dir).parts):
            continue
        if src.suffix.lower() not in _ARTIFACT_EXTENSIONS:
            continue
        results.append(str(src.relative_to(output_dir)))
    return sorted(results)

```

- [ ] **Step 4: Run all tests — confirm they pass**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_run_git.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/varun_akarapu/DEAH/core/development
git add run_git.py tests/test_run_git.py
git commit -m "feat(run_git): add _list_output_files helper"
```

---

### Task 3: Add `_interactive_select_files()` helper

**Files:**
- Modify: `core/development/run_git.py` (append after `_list_output_files`)
- Modify: `core/development/tests/test_run_git.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/test_run_git.py`:

```python
# ── _interactive_select_files ─────────────────────────────────────────────────

FILES = [
    "dag/dag_employees.py",
    "ddl/stg_employees.sql",
    "ddl/target.sql",
    "dml/merge.sql",
    "config/pipeline.yaml",
]


def test_interactive_select_all(capsys):
    with patch("builtins.input", return_value="all"):
        result = run_git._interactive_select_files(FILES)
    assert result == set(FILES)


def test_interactive_select_specific_numbers(capsys):
    with patch("builtins.input", return_value="1 3"):
        result = run_git._interactive_select_files(FILES)
    # FILES[0] and FILES[2] (1-indexed)
    assert result == {"dag/dag_employees.py", "ddl/target.sql"}


def test_interactive_select_range(capsys):
    with patch("builtins.input", return_value="2-4"):
        result = run_git._interactive_select_files(FILES)
    assert result == {"ddl/stg_employees.sql", "ddl/target.sql", "dml/merge.sql"}


def test_interactive_select_quit_returns_none(capsys):
    with patch("builtins.input", return_value="quit"):
        result = run_git._interactive_select_files(FILES)
    assert result is None


def test_interactive_select_invalid_then_valid(capsys):
    # First input is invalid, second is valid
    with patch("builtins.input", side_effect=["999", "2"]):
        result = run_git._interactive_select_files(FILES)
    assert result == {"ddl/stg_employees.sql"}


def test_interactive_select_out_of_range_ignored(capsys):
    with patch("builtins.input", side_effect=["0 1 6", "1"]):
        result = run_git._interactive_select_files(FILES)
    # 0 and 6 are out of range (1-5 valid), only 1 is accepted
    assert result == {"dag/dag_employees.py"}
```

- [ ] **Step 2: Run the tests — confirm they fail**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_run_git.py::test_interactive_select_all -v
```

Expected: `AttributeError: module 'run_git' has no attribute '_interactive_select_files'`

- [ ] **Step 3: Implement `_interactive_select_files` in `run_git.py` after `_list_output_files`**

```python
def _interactive_select_files(files: list[str]) -> set[str] | None:
    """
    Display a numbered list of files and prompt the user to select.

    Returns:
        set[str]  — selected relative paths (non-empty)
        None      — user typed 'quit'
    """
    sep = "  " + "─" * 52
    print()
    print(sep)
    print("  FILES AVAILABLE TO PUSH")
    print(sep)
    for i, f in enumerate(files, start=1):
        print(f"  [{i:2d}]  {f}")
    print(sep)
    print("  all       push all files")
    print("  1 2 5     push specific files by number")
    print("  1-4       push a range")
    print("  quit      cancel")
    print()

    while True:
        raw = input("  Select files > ").strip().lower()

        if raw == "quit":
            return None

        if raw == "all":
            return set(files)

        selected: set[str] = set()
        valid = True

        # Parse space-separated tokens; each token is either a number or a range
        for token in raw.split():
            if "-" in token:
                parts = token.split("-", 1)
                try:
                    lo, hi = int(parts[0]), int(parts[1])
                    indices = range(lo, hi + 1)
                except ValueError:
                    valid = False
                    break
            else:
                try:
                    indices = [int(token)]
                except ValueError:
                    valid = False
                    break

            for idx in indices:
                if 1 <= idx <= len(files):
                    selected.add(files[idx - 1])
                # out-of-range indices are silently ignored

        if not valid:
            print("  Invalid input. Use numbers, a range like 1-3, 'all', or 'quit'.")
            continue

        if not selected:
            print("  No valid files selected. Try again or type 'quit'.")
            continue

        return selected

```

- [ ] **Step 4: Run all tests — confirm they pass**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_run_git.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/varun_akarapu/DEAH/core/development
git add run_git.py tests/test_run_git.py
git commit -m "feat(run_git): add interactive file selection helper"
```

---

### Task 4: Add `selected` parameter to `_copy_artifacts_to_workspace`

**Files:**
- Modify: `core/development/run_git.py` — update `_copy_artifacts_to_workspace` signature and body (around line 160)
- Modify: `core/development/tests/test_run_git.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/test_run_git.py`:

```python
# ── _copy_artifacts_to_workspace with selected ────────────────────────────────

def _make_output_dir(tmp_path: Path) -> Path:
    """Helper: create a fake SCRUM-99 output dir with several artifact files."""
    out = tmp_path / "SCRUM-99"
    (out / "dag").mkdir(parents=True)
    (out / "ddl").mkdir()
    (out / "dml").mkdir()
    (out / "dag" / "dag_employees.py").write_text("# dag")
    (out / "ddl" / "stg.sql").write_text("-- stg")
    (out / "dml" / "merge.sql").write_text("-- merge")
    return out


def test_copy_all_files_when_selected_is_none(tmp_path):
    out = _make_output_dir(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    copied = run_git._copy_artifacts_to_workspace(out, workspace, selected=None)

    rel_strs = {str(p) for p in copied}
    assert "SCRUM-99/dag/dag_employees.py" in rel_strs
    assert "SCRUM-99/ddl/stg.sql" in rel_strs
    assert "SCRUM-99/dml/merge.sql" in rel_strs


def test_copy_selected_files_only(tmp_path):
    out = _make_output_dir(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    selected = {"dag/dag_employees.py"}
    copied = run_git._copy_artifacts_to_workspace(out, workspace, selected=selected)

    rel_strs = {str(p) for p in copied}
    assert "SCRUM-99/dag/dag_employees.py" in rel_strs
    assert "SCRUM-99/ddl/stg.sql" not in rel_strs
    assert "SCRUM-99/dml/merge.sql" not in rel_strs
    assert len(copied) == 1
```

- [ ] **Step 2: Run the tests — confirm they fail**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_run_git.py::test_copy_selected_files_only -v
```

Expected: FAIL — `_copy_artifacts_to_workspace()` ignores the `selected` argument (doesn't exist yet)

- [ ] **Step 3: Update `_copy_artifacts_to_workspace` in `run_git.py`**

Current signature is at line ~160. Replace the entire function with:

```python
def _copy_artifacts_to_workspace(
    output_dir: Path,
    workspace: Path,
    selected: set[str] | None = None,
) -> list[Path]:
    """
    Copy artifact files from output_dir into the git workspace.

    Parameters
    ----------
    output_dir : ticket-specific output dir, e.g. output/SCRUM-75/
    workspace  : root of the git workspace clone
    selected   : if given, only copy these relative paths (e.g. {"dag/dag.py"});
                 if None, copy all files matching _ARTIFACT_EXTENSIONS
    """
    ticket_id = output_dir.name          # e.g. "SCRUM-75"
    dest_root = workspace / ticket_id    # e.g. <workspace>/SCRUM-75/
    copied: list[Path] = []

    for src in output_dir.rglob("*"):
        if not src.is_file():
            continue
        if src.suffix not in _ARTIFACT_EXTENSIONS:
            continue
        rel = src.relative_to(output_dir)          # dag/dag_file.py
        if selected is not None and str(rel) not in selected:
            continue
        dst = dest_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(Path(ticket_id) / rel)        # relative to workspace root
        logger.debug("  copied: %s → %s", src, dst)

    return copied
```

- [ ] **Step 4: Run all tests — confirm they pass**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_run_git.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/varun_akarapu/DEAH/core/development
git add run_git.py tests/test_run_git.py
git commit -m "feat(run_git): add selective file copy to _copy_artifacts_to_workspace"
```

---

### Task 5: Extract `_do_commit()` + add `_do_pull_direct()` and `_do_push_direct()`

These three helpers are the PAT-free execution path used when the workspace already exists.

**Files:**
- Modify: `core/development/run_git.py` — add three new functions after `action_status`, before `# ── Main`
- Modify: `core/development/tests/test_run_git.py` (append tests)

- [ ] **Step 1: Add failing tests**

Append to `tests/test_run_git.py`:

```python
# ── _do_pull_direct ───────────────────────────────────────────────────────────

def test_do_pull_direct_runs_git_pull(tmp_path):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        run_git._do_pull_direct(str(tmp_path))
    mock_run.assert_called_once_with(
        ["git", "pull"],
        cwd=str(tmp_path), capture_output=True, text=True,
    )


# ── _do_push_direct ───────────────────────────────────────────────────────────

def test_do_push_direct_runs_git_push(tmp_path):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        run_git._do_push_direct(str(tmp_path), "feature/SCRUM-99_20260420_v1")
    mock_run.assert_called_once_with(
        ["git", "push", "--set-upstream", "origin", "feature/SCRUM-99_20260420_v1"],
        cwd=str(tmp_path), capture_output=True, text=True, check=True,
    )


# ── _do_commit ────────────────────────────────────────────────────────────────

def test_do_commit_stages_and_commits_selected_files(tmp_path):
    out = _make_output_dir(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()   # fake initialized workspace

    call_log: list = []

    def fake_run(cmd, **kwargs):
        call_log.append(cmd)
        result = subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return result

    with patch("subprocess.run", side_effect=fake_run), \
         patch("run_git._ensure_workspace_gitignore"), \
         patch("run_git._generate_delivery_manifest", return_value=None), \
         patch("run_git._copy_artifacts_to_workspace", return_value=[Path("SCRUM-99/dag/dag_employees.py")]):
        run_git._do_commit(
            local_path=str(workspace),
            branch="feature/SCRUM-99_20260420_v1",
            output_dir=out,
            message="feat(SCRUM-99): generate pipeline artifacts",
            git_repo_url="https://github.com/org/repo",
            git_branch="feature/SCRUM-99_20260420_v1",
            selected={"dag/dag_employees.py"},
        )

    # Must have switched to the target branch
    branch_cmds = [c for c in call_log if "checkout" in c]
    assert any("feature/SCRUM-99_20260420_v1" in str(c) for c in branch_cmds)

    # Must have committed
    commit_cmds = [c for c in call_log if "commit" in c]
    assert commit_cmds, "Expected a git commit call"
```

- [ ] **Step 2: Run the tests — confirm they fail**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_run_git.py::test_do_pull_direct_runs_git_pull -v
```

Expected: `AttributeError: module 'run_git' has no attribute '_do_pull_direct'`

- [ ] **Step 3: Add the three helpers to `run_git.py` before `# ── Main` (after `action_status`)**

```python
# ── Direct (no-GitRepoManager) git helpers ─────────────────────────────────────
# Used when the workspace is already initialized — PAT is embedded in the remote.

def _do_pull_direct(local_path: str) -> None:
    """Pull latest changes using the workspace's existing remote config."""
    print("\n── PULL (direct) ────────────────────────────────────────────────")
    result = subprocess.run(
        ["git", "pull"],
        cwd=local_path, capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"  {result.stdout.strip() or 'Already up to date.'}")
    else:
        logger.warning("git pull warning: %s", result.stderr.strip())


def _do_push_direct(local_path: str, branch: str) -> None:
    """Push the current branch to origin using the workspace's existing auth."""
    print(f"\n── PUSH (direct) → origin/{branch} ──────────────────────────────")
    subprocess.run(
        ["git", "push", "--set-upstream", "origin", branch],
        cwd=local_path, capture_output=True, text=True, check=True,
    )
    print(f"  Pushed to      : origin/{branch}")


def _do_commit(
    local_path: str,
    branch: str,
    output_dir: Path,
    message: str,
    git_repo_url: str = "",
    git_branch: str = "",
    selected: set[str] | None = None,
) -> None:
    """
    Stage and commit selected (or all) artifacts via subprocess only.
    No GitRepoManager required — the workspace remote is already configured.
    """
    workspace = Path(local_path)

    if not output_dir.exists():
        print(f"\n  WARNING: output directory does not exist: {output_dir}")
        print("  Run the pipeline first to generate artifacts.")
        return

    print("\n── COMMIT (direct) ──────────────────────────────────────────────")

    # Ensure we are on the target branch (create it if absent)
    subprocess.run(
        ["git", "checkout", "-B", branch],
        cwd=local_path, capture_output=True, text=True,
    )

    _ensure_workspace_gitignore(workspace)

    subprocess.run(
        ["git", "reset", "HEAD", "--", "."],
        cwd=local_path, capture_output=True, text=True,
    )

    delivery_manifest = _generate_delivery_manifest(
        output_dir=output_dir,
        git_repo_url=git_repo_url,
        git_branch=git_branch,
    )

    copied = _copy_artifacts_to_workspace(output_dir, workspace, selected=selected)

    print(f"  Output dir      : {output_dir}")
    print(f"  Workspace       : {workspace}")
    print(f"  Files to commit : {len(copied)}")
    for rel in sorted(copied)[:15]:
        tag = " [DELIVERY MANIFEST]" if "DELIVERY_MANIFEST" in str(rel) else ""
        print(f"    {rel}{tag}")
    if len(copied) > 15:
        print(f"    ... and {len(copied) - 15} more")

    if not copied:
        print("  No artifact files found — nothing to commit.")
        return

    if delivery_manifest:
        print(f"  Delivery manifest: {delivery_manifest}")

    subprocess.run(
        ["git", "add", "--", ".gitignore"],
        cwd=local_path, capture_output=True, text=True,
    )
    git_add = subprocess.run(
        ["git", "add", "--"] + [str(p) for p in copied],
        cwd=local_path, capture_output=True, text=True,
    )
    if git_add.returncode != 0:
        logger.warning("git add warning: %s", git_add.stderr.strip())

    # Check if there is anything staged before committing
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=local_path, capture_output=True, text=True,
    )
    if not staged.stdout.strip():
        print("  Nothing to commit — working tree clean.")
        return

    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=local_path, capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("  Commit complete.")
    else:
        logger.warning("git commit stderr: %s", result.stderr.strip())
        print(f"  Commit output: {result.stdout.strip()}")

```

- [ ] **Step 4: Run all tests — confirm they pass**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_run_git.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/varun_akarapu/DEAH/core/development
git add run_git.py tests/test_run_git.py
git commit -m "feat(run_git): add _do_commit/_do_pull_direct/_do_push_direct subprocess helpers"
```

---

### Task 6: Wire everything in `main()` — `--files` flag, file selection, and PAT-free path

This is the final wiring task. `main()` currently lives at line ~458 in `run_git.py`.

**Files:**
- Modify: `core/development/run_git.py` — update `main()` only

- [ ] **Step 1: Add the `--files` argparse argument**

In `main()`, after the existing `parser.add_argument("--push", ...)` line, add:

```python
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        metavar="FILE",
        help=(
            "Relative file paths to push (e.g. dag/dag_employees.py ddl/stg.sql), "
            "or 'all' to push everything. Interactive selection shown if omitted."
        ),
    )
```

- [ ] **Step 2: Replace the unconditional `_require` calls and GitRepoManager creation**

Find this block in `main()` (around line 480–526):

```python
    _require(repo_url, "repo URL", "GIT_REPO_URL")
    _require(pat,      "PAT",      "GIT_PAT")

    # Feature branch: CLI > env var > auto-generate from project/date
    branch = (
        args.branch
        or os.environ.get("GIT_BRANCH", "")
        or _build_branch(args.project or "")
    )

    # Local workspace: default to output/git_workspace beside the output dir
    if not local_path:
        local_path = str(_dev_root / output_str / "git_workspace")

    # Build the branch URL expected by GitRepoManager
    branch_url = f"{repo_url.rstrip('/')}/tree/{branch}"

    commit_msg = (
        args.message
        or f"feat: generate pipeline artifacts [{datetime.now(timezone.utc).strftime('%Y-%m-%d')}]"
    )

    output_dir = Path(output_str) if Path(output_str).is_absolute() else _dev_root / output_str

    # ── Print resolved config ─────────────────────────────────────────────────
    print()
    print("=" * 65)
    print("  DEAH — Git Integration")
    print("=" * 65)
    print(f"  Repo URL      : {repo_url}")
    print(f"  Feature branch: {branch}")
    print(f"  Local path    : {local_path}")
    print(f"  Output dir    : {output_dir}")
    print(f"  Action        : {args.action}")
    print("=" * 65)

    git = GitRepoManager(
        branch_url=branch_url,
        pat=pat,
        local_path=local_path,
    )

    action = args.action

    # ── Dispatch ─────────────────────────────────────────────────────────────
    if action in ("setup", "full"):
        action_setup(git)

    if action in ("pull", "full"):
        action_pull(git)

    if action in ("status",):
        action_status(git)

    if action in ("commit", "full"):
        action_commit(git, output_dir, commit_msg,
                      git_repo_url=repo_url, git_branch=branch)

    if action == "push" or (action == "commit" and args.push) or action == "full":
        action_push(git)

    print()
    print("=" * 65)
    print("  Done.")
    print(f"  Feature branch : {branch}")
    print(f"  Repo           : {repo_url.rstrip('.git')}/tree/{branch}")
    print("=" * 65)
    print()
```

Replace it with:

```python
    # Local workspace: default to output/git_workspace beside the output dir
    if not local_path:
        local_path = str(_dev_root / "output" / "git_workspace")

    output_dir = Path(output_str) if Path(output_str).is_absolute() else _dev_root / output_str

    commit_msg = (
        args.message
        or f"feat: generate pipeline artifacts [{datetime.now(timezone.utc).strftime('%Y-%m-%d')}]"
    )

    workspace_ready = _is_workspace_initialized(local_path)

    # PAT + repo required only for first-time setup (workspace not yet cloned)
    if not workspace_ready:
        _require(repo_url, "repo URL", "GIT_REPO_URL")
        _require(pat,      "PAT",      "GIT_PAT")

    # Feature branch: CLI > env var > current workspace branch > auto-generate
    branch = (
        args.branch
        or os.environ.get("GIT_BRANCH", "")
        or (workspace_ready and _get_workspace_branch(local_path))
        or _build_branch(args.project or "")
    )

    # ── Resolve file selection ────────────────────────────────────────────────
    selected: set[str] | None = None   # None means "all files"

    if args.action in ("commit", "full") or (args.action == "commit" and args.push):
        if args.files is not None:
            # CLI flag provided
            if len(args.files) == 1 and args.files[0] == "all":
                selected = None  # explicit "all"
            else:
                selected = set(args.files)
        else:
            # Interactive selection
            all_files = _list_output_files(output_dir)
            if not all_files:
                print(f"\n  WARNING: No artifact files found in {output_dir}")
                print("  Run the pipeline first to generate output.")
                sys.exit(1)
            chosen = _interactive_select_files(all_files)
            if chosen is None:
                print("  Aborted.")
                return
            selected = chosen

    # ── Print resolved config ─────────────────────────────────────────────────
    print()
    print("=" * 65)
    print("  DEAH — Git Integration")
    print("=" * 65)
    print(f"  Repo URL      : {repo_url or '(from workspace remote)'}")
    print(f"  Feature branch: {branch}")
    print(f"  Local path    : {local_path}")
    print(f"  Output dir    : {output_dir}")
    print(f"  Action        : {args.action}")
    print(f"  Workspace     : {'initialized' if workspace_ready else 'new (will clone)'}")
    if selected is not None:
        print(f"  Files         : {len(selected)} selected")
    else:
        print(f"  Files         : all")
    print("=" * 65)

    action = args.action

    # ── Dispatch ─────────────────────────────────────────────────────────────
    if workspace_ready:
        # Workspace already has auth configured — use subprocess directly
        if action in ("status",):
            # status still needs GitRepoManager for branch display
            if repo_url and pat:
                branch_url = f"{repo_url.rstrip('/')}/tree/{branch}"
                git = GitRepoManager(branch_url=branch_url, pat=pat, local_path=local_path)
                git._default_branch = _get_workspace_branch(local_path)
                action_status(git)
            else:
                # Minimal status without GitRepoManager
                result = subprocess.run(
                    ["git", "status", "--short"], cwd=local_path, capture_output=True, text=True,
                )
                branch_result = subprocess.run(
                    ["git", "branch", "--show-current"], cwd=local_path, capture_output=True, text=True,
                )
                print(f"\n── STATUS ───────────────────────────────────────────────────────")
                print(f"  Local path     : {local_path}")
                print(f"  Current branch : {branch_result.stdout.strip() or 'unknown'}")
                if result.stdout.strip():
                    for line in result.stdout.strip().splitlines():
                        print(f"    {line}")
                else:
                    print("  Working tree is clean.")
            return

        if action in ("pull", "full"):
            _do_pull_direct(local_path)

        if action in ("commit", "full"):
            _do_commit(
                local_path=local_path,
                branch=branch,
                output_dir=output_dir,
                message=commit_msg,
                git_repo_url=repo_url,
                git_branch=branch,
                selected=selected,
            )

        if action == "push" or (action == "commit" and args.push) or action == "full":
            _do_push_direct(local_path, branch)

    else:
        # First-time setup — use GitRepoManager (needs repo_url + pat)
        branch_url = f"{repo_url.rstrip('/')}/tree/{branch}"
        git = GitRepoManager(branch_url=branch_url, pat=pat, local_path=local_path)

        if action in ("setup", "full"):
            action_setup(git)

        if action in ("pull", "full"):
            action_pull(git)

        if action in ("status",):
            action_status(git)

        if action in ("commit", "full"):
            action_commit(git, output_dir, commit_msg,
                          git_repo_url=repo_url, git_branch=branch)

        if action == "push" or (action == "commit" and args.push) or action == "full":
            action_push(git)

    print()
    print("=" * 65)
    print("  Done.")
    print(f"  Feature branch : {branch}")
    if repo_url:
        print(f"  Repo           : {repo_url.rstrip('.git')}/tree/{branch}")
    print("=" * 65)
    print()
```

- [ ] **Step 3: Run all tests to make sure nothing is broken**

```bash
cd /home/varun_akarapu/DEAH/core/development
python -m pytest tests/test_run_git.py -v
```

Expected: all tests PASS

- [ ] **Step 4: Smoke-test the help output to verify new flags appear**

```bash
cd /home/varun_akarapu/DEAH/core/development
python run_git.py --help
```

Expected output includes:
```
--files [FILE ...]    Relative file paths to push ... or 'all' ...
```

- [ ] **Step 5: Commit**

```bash
cd /home/varun_akarapu/DEAH/core/development
git add run_git.py
git commit -m "feat(run_git): wire --files flag, file selection, and PAT-free workspace path in main()"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| PAT not required when workspace exists | Task 1 (detection) + Task 6 (wiring) |
| Push all files under ticket output dir | Task 4 (copy), Task 5 (`_do_commit`), Task 6 (selected=None) |
| `--files` CLI flag for scripted use | Task 6 (argparse + wiring) |
| Interactive fallback when no `--files` | Task 3 (helper) + Task 6 (wiring) |
| Interactive: `all`, numbers, ranges, `quit` | Task 3 |
| Only files matching artifact extensions | Task 2 (`_list_output_files`) + Task 4 |
| All changes in `run_git.py` only | Confirmed — no other files touched |
| No PAT prompt for already-initialized workspace | Task 6 (`if not workspace_ready: _require(...)`) |

**Placeholder scan:** No TBDs or TODOs in any step. All code blocks are complete.

**Type consistency:**
- `selected: set[str] | None` — consistent across Task 4, 5, 6
- `_do_commit(local_path, branch, output_dir, message, git_repo_url, git_branch, selected)` — signature matches call site in Task 6
- `_interactive_select_files` returns `set[str] | None` — matches Task 6 `if chosen is None` check
- `_list_output_files` returns `list[str]` — passed correctly to `_interactive_select_files` in Task 6
