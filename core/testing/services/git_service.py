"""
services/git_service.py
-----------------------
Thin wrapper around the DEAH common GitRepoManager utility.
All git operations for the Testing POD go through this service.
"""

from __future__ import annotations
import importlib.util
import subprocess
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DEAH_ROOT, GITHUB_PAT, GITHUB_BRANCH_URL


def _load_git_manager():
    """Dynamically load GitRepoManager from DEAH common utilities."""
    git_mgr_path = DEAH_ROOT / "core/utilities/versioning_tools/git_manager.py"
    spec = importlib.util.spec_from_file_location("git_manager", git_mgr_path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.GitRepoManager


class GitService:
    """
    Wraps GitRepoManager for Testing POD use.
    Provides simple pull() and path-resolution helpers.
    """

    def __init__(self):
        GitRepoManager   = _load_git_manager()
        self._manager    = GitRepoManager(
            branch_url=GITHUB_BRANCH_URL,
            pat=GITHUB_PAT,
            local_path=str(DEAH_ROOT),
        )
        self._connected  = False

    def _ensure_connected(self):
        if not self._connected:
            self._manager.connect()
            self._connected = True

    def pull(self) -> None:
        """Pull latest from remote main branch."""
        self._ensure_connected()
        self._manager.pull()

    @staticmethod
    def current_branch() -> str:
        """Return the current git branch name, fallback to 'main'."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(DEAH_ROOT),
                capture_output=True, text=True, timeout=10,
            )
            branch = result.stdout.strip()
            return branch if branch and branch != "HEAD" else "main"
        except Exception:
            return "main"

    def soft_pull(self) -> None:
        """
        Pull without raising on error — used in web routes where
        we want to continue even if git is unavailable.
        """
        try:
            if (DEAH_ROOT / ".git").exists():
                branch = self.current_branch()
                subprocess.run(
                    ["git", "pull", "origin", branch],
                    cwd=str(DEAH_ROOT),
                    capture_output=True,
                    timeout=30,
                )
        except Exception:
            pass

    @staticmethod
    def _file_date_key(path: Path) -> tuple:
        """Sort key: (filename YYYYMMDD_HH, st_mtime) — filename date takes priority,
        st_mtime breaks ties when filenames share the same timestamp."""
        import re as _re
        m = _re.search(r'(\d{8}_\d{2,6})', path.name)
        return (m.group(1) if m else "00000000_00", path.stat().st_mtime)

    def latest_file(self, directory: Path, *extensions: str) -> Path | None:
        """
        Return the file with the latest date embedded in its filename,
        falling back to st_mtime. This is immune to git pull timestamps.
        """
        candidates = [
            f for ext in extensions
            for f in directory.glob(ext)
            if f.is_file()
        ]
        if not candidates:
            return None
        return max(candidates, key=self._file_date_key)

    def list_files(self, directory: Path, *extensions: str) -> list[Path]:
        """
        Return all files in `directory` matching any of the given extensions,
        sorted newest-first by filename date.
        """
        candidates = [
            f for ext in extensions
            for f in directory.glob(ext)
            if f.is_file()
        ]
        return sorted(candidates, key=self._file_date_key, reverse=True)

    def file_by_name(self, directory: Path, filename: str) -> Path | None:
        """Return a specific file by name from directory, or None if not found."""
        p = directory / filename
        return p if p.exists() else None

    def commit_and_push(self, files: list[Path], message: str) -> dict:
        """
        Stage the given files, commit, and push to origin/main.

        Returns
        -------
        dict with keys:
            ok      : bool
            message : human-readable result or error
            stdout  : raw git output (for diagnostics)
        """
        if not files:
            return {"ok": False, "message": "No files to commit."}

        rel_paths = [str(f.relative_to(DEAH_ROOT)) for f in files if f.exists()]
        if not rel_paths:
            return {"ok": False, "message": "Files not found on disk."}

        try:
            branch = self.current_branch()

            # Pull latest first to avoid non-fast-forward rejection
            subprocess.run(
                ["git", "pull", "--rebase", "origin", branch],
                cwd=str(DEAH_ROOT),
                capture_output=True, text=True, timeout=60,
            )

            # Stage
            add_result = subprocess.run(
                ["git", "add"] + rel_paths,
                cwd=str(DEAH_ROOT),
                capture_output=True, text=True, timeout=30,
            )
            if add_result.returncode != 0:
                return {"ok": False, "message": f"git add failed: {add_result.stderr}", "stdout": add_result.stderr}

            # Check if there's anything to commit
            status = subprocess.run(
                ["git", "status", "--porcelain"] + rel_paths,
                cwd=str(DEAH_ROOT),
                capture_output=True, text=True, timeout=15,
            )
            if not status.stdout.strip():
                return {"ok": True, "message": "Already up to date — no changes to commit.", "stdout": ""}

            # Commit
            commit_result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(DEAH_ROOT),
                capture_output=True, text=True, timeout=30,
            )
            if commit_result.returncode != 0:
                return {"ok": False, "message": f"git commit failed: {commit_result.stderr}", "stdout": commit_result.stderr}

            # Push to current branch
            push_result = subprocess.run(
                ["git", "push", "origin", branch],
                cwd=str(DEAH_ROOT),
                capture_output=True, text=True, timeout=60,
            )
            if push_result.returncode != 0:
                return {"ok": False, "message": f"git push failed: {push_result.stderr}", "stdout": push_result.stderr}

            filenames = ", ".join(f.name for f in files if f.exists())
            return {"ok": True, "message": f"Saved and pushed: {filenames}", "stdout": push_result.stdout}

        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "Git operation timed out."}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
