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


# ── _do_pull_direct ───────────────────────────────────────────────────────────

def test_do_pull_direct_runs_git_pull(tmp_path):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
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
        result = subprocess.CompletedProcess(cmd, 0, stdout="staged_file.py", stderr="")
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
