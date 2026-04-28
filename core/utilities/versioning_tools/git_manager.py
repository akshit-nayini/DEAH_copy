"""
Git Repository Manager
-----------------------
Establishes a connection to a Git repository using a branch URL and Personal Access Token (PAT).

- Pull  → always from the default branch (e.g. main / master)
- Commit → stages and commits changes locally
- Push   → always to the branch supplied at connection time
"""

import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"stdout: {result.stdout.strip()}\n"
            f"stderr: {result.stderr.strip()}"
        )
    return result


def _inject_pat(url: str, pat: str) -> str:
    """
    Inject a PAT into an HTTPS remote URL so that git authenticates silently.

    https://github.com/user/repo.git
    → https://<pat>@github.com/user/repo.git
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only HTTP/HTTPS URLs are supported. Got: {url}")
    authed = parsed._replace(netloc=f"{pat}@{parsed.hostname}{(':' + str(parsed.port)) if parsed.port else ''}")
    return authed.geturl()


def _parse_branch_from_url(branch_url: str) -> tuple[str, str]:
    """
    Accept two common branch URL formats and return (repo_url, branch_name).

    GitHub tree URL:
        https://github.com/user/repo/tree/my-branch
    Plain repo URL with #fragment:
        https://github.com/user/repo.git#my-branch
    """
    # GitHub/GitLab "tree" style  →  .../tree/<branch>
    tree_match = re.search(r"(https?://[^/]+/[^/]+/[^/]+)/tree/(.+)$", branch_url)
    if tree_match:
        return tree_match.group(1) + ".git", tree_match.group(2)

    # Fragment style  →  <repo_url>#<branch>
    if "#" in branch_url:
        repo_url, branch = branch_url.split("#", 1)
        return repo_url, branch

    raise ValueError(
        "Cannot determine branch from URL.\n"
        "Supported formats:\n"
        "  https://github.com/user/repo/tree/my-branch\n"
        "  https://github.com/user/repo.git#my-branch"
    )


# ---------------------------------------------------------------------------
# GitRepoManager
# ---------------------------------------------------------------------------

class GitRepoManager:
    """
    Manages a local clone of a remote Git repository.

    Parameters
    ----------
    branch_url : str
        URL that identifies both the repository and the target branch.
        Supported formats:
          • https://github.com/user/repo/tree/feature-branch
          • https://github.com/user/repo.git#feature-branch
    pat : str
        Personal Access Token used for authentication.
    local_path : str
        Directory where the repository will be cloned / is already cloned.
    """

    def __init__(self, branch_url: str, pat: str, local_path: str) -> None:
        self.pat = pat
        self.local_path = str(Path(local_path).resolve())

        repo_url, self.target_branch = _parse_branch_from_url(branch_url)
        self.repo_url = repo_url                        # clean URL (no PAT)
        self._authed_url = _inject_pat(repo_url, pat)  # URL with PAT embedded

        self._default_branch: str | None = None  # resolved lazily after clone

    # ------------------------------------------------------------------
    # Connection / clone
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Clone the repository if it does not exist locally, then configure
        the remote to use the PAT-authenticated URL.
        """
        repo_dir = Path(self.local_path)

        if not (repo_dir / ".git").exists():
            print(f"[connect] Cloning {self.repo_url} → {self.local_path} …")
            _run(["git", "clone", self._authed_url, self.local_path])
        else:
            print(f"[connect] Repository already exists at {self.local_path}")

        # Always refresh the remote URL (PAT may have changed)
        _run(["git", "remote", "set-url", "origin", self._authed_url], cwd=self.local_path)

        self._default_branch = self._resolve_default_branch()
        print(f"[connect] Default branch : {self._default_branch}")
        print(f"[connect] Push branch    : {self.target_branch}")

    def _resolve_default_branch(self) -> str:
        """Ask the remote which branch HEAD points to."""
        result = _run(
            ["git", "remote", "show", "origin"],
            cwd=self.local_path,
        )
        for line in result.stdout.splitlines():
            if "HEAD branch" in line:
                return line.split(":")[-1].strip()

        # Fallback: inspect symbolic-ref on origin/HEAD
        result = _run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=self.local_path,
            check=False,
        )
        if result.returncode == 0:
            # refs/remotes/origin/main  →  main
            return result.stdout.strip().split("/")[-1]

        raise RuntimeError("Could not determine the default branch of the repository.")

    # ------------------------------------------------------------------
    # Pull  (always from default branch)
    # ------------------------------------------------------------------

    def pull(self) -> None:
        """
        Pull the latest changes from the **default branch** of origin.
        The working tree is switched to the default branch first if necessary.
        """
        self._ensure_connected()
        print(f"[pull] Fetching origin …")
        _run(["git", "fetch", "origin"], cwd=self.local_path)

        current = self._current_branch()
        if current != self._default_branch:
            print(f"[pull] Switching from '{current}' to default branch '{self._default_branch}' …")
            _run(["git", "checkout", self._default_branch], cwd=self.local_path)

        print(f"[pull] Pulling origin/{self._default_branch} …")
        _run(["git", "pull", "origin", self._default_branch], cwd=self.local_path)
        print(f"[pull] Done. Working tree is up to date with '{self._default_branch}'.")

    # ------------------------------------------------------------------
    # Commit  (local only)
    # ------------------------------------------------------------------

    def commit(self, message: str, add_all: bool = True) -> None:
        """
        Stage changes and create a local commit on the **target branch**.

        Parameters
        ----------
        message  : Commit message.
        add_all  : When True, run `git add -A` before committing (default).
        """
        self._ensure_connected()
        self._ensure_on_target_branch()

        if add_all:
            print("[commit] Staging all changes (git add -A) …")
            _run(["git", "add", "-A"], cwd=self.local_path)

        # Check if there is anything to commit
        status = _run(["git", "status", "--porcelain"], cwd=self.local_path)
        staged = _run(["git", "diff", "--cached", "--name-only"], cwd=self.local_path)

        if not staged.stdout.strip():
            print("[commit] Nothing to commit — working tree clean.")
            return

        print(f"[commit] Committing with message: '{message}' …")
        _run(["git", "commit", "-m", message], cwd=self.local_path)
        print("[commit] Commit created successfully.")

    # ------------------------------------------------------------------
    # Push  (always to target branch)
    # ------------------------------------------------------------------

    def push(self) -> None:
        """
        Push committed changes to **origin/<target_branch>**.
        The upstream tracking branch is set automatically on first push.
        """
        self._ensure_connected()
        self._ensure_on_target_branch()

        print(f"[push] Pushing to origin/{self.target_branch} …")
        _run(
            ["git", "push", "--set-upstream", "origin", self.target_branch],
            cwd=self.local_path,
        )
        print(f"[push] Changes pushed to origin/{self.target_branch} successfully.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if self._default_branch is None:
            raise RuntimeError("Not connected. Call connect() first.")

    def _current_branch(self) -> str:
        result = _run(["git", "branch", "--show-current"], cwd=self.local_path)
        return result.stdout.strip()

    def _ensure_on_target_branch(self) -> None:
        """Switch to target branch, creating it from origin if it doesn't exist locally."""
        current = self._current_branch()
        if current == self.target_branch:
            return

        print(f"[branch] Switching to target branch '{self.target_branch}' …")

        # Does the branch exist locally?
        local_branches = _run(["git", "branch"], cwd=self.local_path).stdout
        branch_exists_locally = any(
            b.strip().lstrip("* ") == self.target_branch
            for b in local_branches.splitlines()
        )

        if branch_exists_locally:
            _run(["git", "checkout", self.target_branch], cwd=self.local_path)
        else:
            # Try to check out from remote
            _run(
                ["git", "checkout", "-b", self.target_branch,
                 f"origin/{self.target_branch}"],
                cwd=self.local_path,
                check=False,  # may fail if remote branch doesn't exist yet
            )
            # If still not on target branch, create it fresh
            if self._current_branch() != self.target_branch:
                _run(["git", "checkout", "-b", self.target_branch], cwd=self.local_path)


# ---------------------------------------------------------------------------
# Direct execution is not supported — use run_git_workflow.py instead
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(
        "\n"
        "  [error] git_manager.py cannot be run directly.\n"
        "  Use the wrapper script instead:\n\n"
        "      python run_git_workflow.py\n"
    )