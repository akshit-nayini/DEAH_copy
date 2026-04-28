"""
Git integration script for the Development Pod.

Connects to your Git repository using GitRepoManager, stages generated
artifacts from the output directory, and pushes them to a feature branch.

Configuration (set in .env or as environment variables):
  GIT_REPO_URL    — full repo URL, e.g. https://github.com/org/repo
  GIT_PAT         — Personal Access Token (read from env, never hardcoded)
  GIT_BRANCH      — target feature branch, e.g. feature/my-pipeline-dev
  GIT_LOCAL_PATH  — local clone directory (default: output/git_workspace)
  OUTPUT_DIR      — directory containing generated artifacts (default: output)

Usage:
  cd DEAH/core/development

  # Full workflow: connect → pull → commit → push
  python run_git.py

  # Step-by-step
  python run_git.py --action setup          # clone / verify connection
  python run_git.py --action pull           # pull latest from default branch
  python run_git.py --action commit         # commit artifacts to feature branch
  python run_git.py --action push           # push feature branch to remote
  python run_git.py --action status         # show current branch + staged files

  # Override config on the command line
  python run_git.py \\
    --repo  https://github.com/org/repo \\
    --branch feature/employees-dev-20250413 \\
    --output output/req-abc123

  # Push immediately after commit
  python run_git.py --push

Example .env (place in DEAH/core/development/.env):
  GIT_REPO_URL=https://github.com/your-org/your-repo
  GIT_PAT=ghp_xxxxxxxxxxxxxxxxxxxx
  GIT_BRANCH=feature/data-migration-dev
  GIT_LOCAL_PATH=output/git_workspace
  OUTPUT_DIR=output
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── sys.path setup ─────────────────────────────────────────────────────────────
_dev_root = Path(__file__).resolve().parent          # core/development/
_repo_root = _dev_root.parent.parent                  # DEAH/
for _p in [str(_dev_root), str(_repo_root)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Load .env file if present (python-dotenv)
try:
    from dotenv import load_dotenv
    _env_file = _dev_root / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
        print(f"  [config] Loaded .env from {_env_file}")
except ImportError:
    pass  # python-dotenv not installed — use raw env vars

from core.utilities.versioning_tools import GitRepoManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("development.git")


# ── Config helpers ─────────────────────────────────────────────────────────────

def _require(value: str | None, name: str, env_var: str) -> str:
    if value:
        return value
    print(f"\n  ERROR: {name} is required.")
    print(f"  Set the {env_var} environment variable in .env or pass --{name.lower().replace(' ', '-')}.")
    sys.exit(1)


def _build_branch(project_id: str = "") -> str:
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    if project_id:
        # Match orchestrator: feature/SCRUM-123_20260420_v1
        return f"feature/{project_id}_{date_str}_v1"
    return f"feature/pipeline-dev-{date_str}"


def _ticket_id_from_path(output_dir: Path) -> str:
    """
    Extract a ticket ID from the output directory name.
    Matches names like SCRUM-123, JIRA-42, PROJ-999.
    Returns '' if the folder name doesn't look like a ticket ID.
    """
    import re
    name = output_dir.name
    if re.match(r'^[A-Za-z]+-\d+$', name):
        return name.upper()
    return ""


# ── Workspace helpers ──────────────────────────────────────────────────────────

def _is_workspace_initialized(local_path: str) -> bool:
    """Return True if local_path is already a git repository."""
    return (Path(local_path) / ".git").exists()


def _fix_remote_auth(local_path: str, pat: str = "") -> None:
    """
    Ensure the origin remote URL uses https://x-access-token:<PAT>@host format.

    Two problems this solves:
    1. git_manager stores PAT as the URL username (https://<PAT>@host) with no
       password — git then prompts interactively for the missing password.
    2. The stored PAT may be expired; if GIT_PAT env var (or --pat flag) provides
       a fresh token, it replaces whatever is currently in the remote URL.

    Priority for the token: explicit pat arg > GIT_PAT env var > token already in URL.
    """
    import re
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=local_path, capture_output=True, text=True,
    )
    url = result.stdout.strip()

    # Parse the existing URL to get the host/path portion
    # Handles both https://<token>@host and https://x-access-token:<token>@host
    m = re.match(r'^https://(?:[^:@/]+(?::[^@/]*)?@)?(.+)$', url)
    if not m:
        return  # not an https URL we can rewrite
    host_and_path = m.group(1)

    # Resolve which token to use
    token = pat or os.environ.get("GIT_PAT", "")
    if not token:
        # Fall back to whatever token is already embedded in the URL
        embedded = re.match(r'^https://([^:@/]+)(?::[^@/]*)?@', url)
        if embedded:
            token = embedded.group(1)
    if not token:
        return  # no token available — leave URL unchanged

    fixed_url = f"https://x-access-token:{token}@{host_and_path}"
    subprocess.run(
        ["git", "remote", "set-url", "origin", fixed_url],
        cwd=local_path, capture_output=True, text=True,
    )


def _get_workspace_branch(local_path: str) -> str:
    """Return the currently checked-out branch name, or '' on failure."""
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=local_path, capture_output=True, text=True,
    )
    return result.stdout.strip()


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


# ── Artifact helpers ───────────────────────────────────────────────────────────

_ARTIFACT_EXTENSIONS = {".sql", ".py", ".yaml", ".yml", ".json", ".md"}

# File-type label mapping for DELIVERY_MANIFEST (human-readable format).
_ARTIFACT_TYPE_LABELS = {
    "ddl":      "bigquery_ddl",
    "dml":      "bigquery_dml",
    "sp":       "stored_procedure",
    "dag":      "airflow_dag",
    "pipeline": "dataflow_pipeline",
    "config":   "pipeline_config",
    "doc":      "documentation",
}


def _ensure_workspace_gitignore(workspace: Path) -> None:
    """
    Write a strict whitelist .gitignore so that ONLY ticket output folders
    (e.g. SCRUM-75/, JIRA-123/) and the .gitignore file itself are ever
    tracked in the git workspace.

    Strategy:
      1. Ignore everything by default (*).
      2. Un-ignore ticket-ID-shaped folders  (pattern: UPPER-digits/).
      3. Un-ignore the .gitignore file itself.
      4. Untrack ALL currently indexed content with `git rm --cached -r .`
         so that subsequent explicit `git add` calls are the sole authority
         on what ends up in the commit.  This removes any previously committed
         core/, design/, requirements/, webapp/, or other repo content.
    """
    gitignore = workspace / ".gitignore"
    lines = [
        "# Auto-generated by DEAH run_git.",
        "# Only ticket output folders (e.g. SCRUM-75/) are tracked.",
        "# Everything else — core/, design/, requirements/, webapp/, etc. — is ignored.",
        "",
        "# 1. Ignore everything by default",
        "*",
        "",
        "# 2. Allow .gitignore itself",
        "!.gitignore",
        "",
        "# 3. Allow top-level ticket-ID folders (UPPER_LETTERS-DIGITS/ pattern)",
        "#    e.g. SCRUM-75/, JIRA-100/, REQ-001/",
        "![A-Z]*-[0-9]*/",
        "![A-Z]*-[0-9]*/**",
        "",
    ]
    gitignore.write_text("\n".join(lines), encoding="utf-8")

    # Untrack EVERYTHING currently in the git index so only what we
    # explicitly `git add` below will appear in the next commit.
    # This is the most reliable guard against accidentally pushing
    # core/, design/, requirements/, or any other repo content.
    subprocess.run(
        ["git", "rm", "--cached", "-r", "--quiet", "--ignore-unmatch", "."],
        cwd=str(workspace), capture_output=True, text=True,
    )
    logger.debug("Workspace index cleared — only output artifacts will be staged.")


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


def _generate_delivery_manifest(
    output_dir: Path,
    git_repo_url: str,
    git_branch: str,
) -> Path | None:
    """
    Build an enriched DELIVERY_MANIFEST.json for the testing team.

    Format (matches the VZ-CUST-MIGRATION sample):
      {
        "project":       "...",
        "sprint":        "SCRUM-75",
        "table":         "<primary target table>",
        "version":       "1.0",
        "repo":          "https://...",
        "branch":        "feature/SCRUM-75_..._v1",
        "target_branch": "main",
        "commit_message": "feat: ...",
        "files": [
          {
            "file_path":        "ddl/stg_employees.sql",   ← relative to ticket folder
            "file_type":        "bigquery_ddl",
            "change_type":      "created",
            "columns_affected": [],
            "owner":            ""
          }
        ]
      }

    Reads MANIFEST.json (artifact list) and plan.json (summary / services / tables).
    Writes to:
      • output_dir/DELIVERY_MANIFEST.json   ← copied to git workspace by the caller
      • agents/deployer/output/delivery_<ticket>.json  ← local reference copy

    Returns the local deployer-output path, or None if MANIFEST.json is absent.
    """
    manifest_path = output_dir / "MANIFEST.json"
    if not manifest_path.exists():
        logger.warning("No MANIFEST.json found in %s — skipping delivery manifest.", output_dir)
        return None

    manifest  = json.loads(manifest_path.read_text(encoding="utf-8"))
    ticket_id = manifest.get("request_id", output_dir.name)

    # ── Optional: enrich from plan.json ───────────────────────────────────────
    plan_summary  = ""
    plan_services: list[dict] = []
    plan_tables:   list[dict] = []
    plan_path = output_dir / "plan.json"
    if plan_path.exists():
        try:
            plan      = json.loads(plan_path.read_text(encoding="utf-8"))
            plan_summary  = plan.get("summary", "")
            plan_services = plan.get("services", [])
            plan_tables   = plan.get("tables", [])
        except Exception:
            pass  # plan.json is optional — keep going

    # Primary table: first staging table in plan, or first table overall, or ticket id
    primary_table = ""
    if plan_tables:
        staging = [t for t in plan_tables if str(t.get("layer", "")).lower() == "staging"]
        first   = (staging or plan_tables)[0]
        primary_table = first.get("name", "").split(".")[-1]  # unqualified table name

    # ── Build deduplicated file list ──────────────────────────────────────────
    seen_paths: set[str] = set()
    delivery_files: list[dict] = []

    for f in manifest.get("files", []):
        abs_path  = f.get("file_path", "")
        file_name = Path(abs_path).name if abs_path else ""
        folder    = Path(abs_path).parent.name if abs_path else ""

        # Deduplicate by (folder, file_name) — MANIFEST.json sometimes has duplicates
        dedup_key = f"{folder}/{file_name}"
        if dedup_key in seen_paths:
            logger.debug("Delivery manifest: skipping duplicate entry %s", dedup_key)
            continue
        seen_paths.add(dedup_key)

        # Relative file_path within the ticket folder (e.g. "ddl/stg_employees.sql")
        rel_file_path = f"{folder}/{file_name}" if folder else file_name

        # Human-readable file_type label
        raw_type   = f.get("file_type", "")
        typed_label = _ARTIFACT_TYPE_LABELS.get(raw_type.lower(), raw_type)

        owner = f.get("owner", "")
        if owner in ("Development Agent", "development_agent"):
            owner = ""

        delivery_files.append({
            "file_path"       : rel_file_path,           # relative to ticket folder
            "file_type"       : typed_label,              # e.g. airflow_dag, bigquery_ddl
            "change_type"     : f.get("change_type", "created"),
            "columns_affected": f.get("columns_affected", []),
            "owner"           : owner,
        })

    # ── Assemble the full delivery payload ────────────────────────────────────
    delivery: dict = {
        "project"            : manifest.get("project", ""),
        "sprint"             : manifest.get("sprint", "") or ticket_id,
        "table"              : primary_table,
        "version"            : manifest.get("version", "1.0"),
        "repo"               : git_repo_url,
        "branch"             : git_branch,
        "target_branch"      : manifest.get("target_branch", "main"),
        "commit_message"     : manifest.get("commit_message", ""),
        "quality_score"      : manifest.get("quality_score"),
        "approved_for_deploy": manifest.get("approved_for_deploy"),
        "generated_at"       : datetime.now(timezone.utc).isoformat(),
        "total_artifacts"    : len(delivery_files),
    }

    if plan_summary:
        delivery["pipeline_summary"] = plan_summary
    if plan_tables:
        delivery["target_tables"] = [
            {
                "name"  : t.get("name", ""),
                "layer" : t.get("layer", ""),
                "type"  : t.get("type", ""),
            }
            for t in plan_tables
        ]
    if plan_services:
        delivery["services"] = [
            {"name": s.get("name", ""), "type": s.get("type", "")}
            for s in plan_services
        ]

    delivery["files"] = delivery_files

    payload = json.dumps(delivery, indent=2)

    # ── Write locally beside MANIFEST.json (will be picked up by copy step) ──
    (output_dir / "DELIVERY_MANIFEST.json").write_text(payload, encoding="utf-8")
    logger.info(
        "Delivery manifest written: %d artifact(s), primary table=%r",
        len(delivery_files), primary_table,
    )

    # ── Write a reference copy for the deployer team ──────────────────────────
    deployer_out = _dev_root / "agents" / "deployer" / "output"
    deployer_out.mkdir(parents=True, exist_ok=True)
    deployer_path = deployer_out / f"delivery_{ticket_id}.json"
    deployer_path.write_text(payload, encoding="utf-8")

    return deployer_path


# ── Actions ────────────────────────────────────────────────────────────────────

def action_setup(git: GitRepoManager) -> None:
    print("\n── SETUP: connect & verify ──────────────────────────────────────")
    git.connect()
    print(f"  Connected to   : {git.repo_url}")
    print(f"  Default branch : {git._default_branch}")
    print(f"  Feature branch : {git.target_branch}")
    print(f"  Local workspace: {git.local_path}")
    print("  Setup complete.")


def action_pull(git: GitRepoManager) -> None:
    print("\n── PULL: latest from default branch ─────────────────────────────")
    git.pull()
    print("  Pull complete.")


def action_commit(
    git: GitRepoManager,
    output_dir: Path,
    message: str,
    git_repo_url: str = "",
    git_branch: str = "",
) -> None:
    print("\n── COMMIT: stage artifacts to feature branch ────────────────────")
    if not output_dir.exists():
        print(f"\n  WARNING: output directory does not exist: {output_dir}")
        print("  Run the pipeline first to generate artifacts.")
        return

    workspace = Path(git.local_path)

    # ── Write .gitignore + untrack non-output folders ─────────────────────
    _ensure_workspace_gitignore(workspace)

    # ── Reset any previously staged changes so we start clean ─────────────
    subprocess.run(
        ["git", "reset", "HEAD", "--", "."],
        cwd=git.local_path, capture_output=True, text=True,
    )

    # ── Generate delivery manifest FIRST so the copy step picks it up ─────
    # DELIVERY_MANIFEST.json is written into output_dir here, then
    # _copy_artifacts_to_workspace() copies it to the workspace as a .json
    # file — no separate staging step needed.
    delivery_manifest = _generate_delivery_manifest(
        output_dir=output_dir,
        git_repo_url=git_repo_url,
        git_branch=git_branch,
    )

    # ── Copy artifact files + DELIVERY_MANIFEST.json into the workspace ───
    copied = _copy_artifacts_to_workspace(output_dir, workspace)

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

    # ── Stage the .gitignore first (so untracking takes effect) ───────────
    subprocess.run(
        ["git", "add", "--", ".gitignore"],
        cwd=git.local_path, capture_output=True, text=True,
    )

    # ── Stage only the copied output files (not the whole workspace) ──────
    git_add = subprocess.run(
        ["git", "add", "--"] + [str(p) for p in copied],
        cwd=git.local_path, capture_output=True, text=True,
    )
    if git_add.returncode != 0:
        logger.warning("git add warning: %s", git_add.stderr.strip())

    git.commit(message, add_all=False)
    print("  Commit complete.")


def action_push(git: GitRepoManager) -> None:
    print("\n── PUSH: feature branch to remote ───────────────────────────────")
    git.push()
    print(f"  Pushed to      : origin/{git.target_branch}")
    print(f"  Create a PR at : {git.repo_url.rstrip('.git')}/compare/{git.target_branch}")


def action_status(git: GitRepoManager) -> None:
    print("\n── STATUS ────────────────────────────────────────────────────────")
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=git.local_path, capture_output=True, text=True,
    )
    branch_result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=git.local_path, capture_output=True, text=True,
    )
    print(f"  Local path     : {git.local_path}")
    print(f"  Current branch : {branch_result.stdout.strip() or 'unknown'}")
    print(f"  Feature branch : {git.target_branch}")
    if result.stdout.strip():
        print("  Changed files  :")
        for line in result.stdout.strip().splitlines():
            print(f"    {line}")
    else:
        print("  Working tree is clean.")


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
    result = subprocess.run(
        ["git", "push", "--set-upstream", "origin", branch],
        cwd=local_path, capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"  Pushed to      : origin/{branch}")
    else:
        # Show git's actual error (auth failures, network issues, etc.)
        err = (result.stderr or result.stdout).strip()
        print(f"\n  ERROR: git push failed (exit {result.returncode})")
        for line in err.splitlines():
            print(f"    {line}")
        if "Invalid username or token" in err or "Authentication failed" in err:
            print()
            print("  The stored PAT has expired or been revoked.")
            print("  Generate a new token at: https://github.com/settings/tokens")
            print("  Then update the workspace remote:")
            print(f"    git -C {local_path} remote set-url origin https://x-access-token:<NEW_PAT>@github.com/...")
        sys.exit(1)


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


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Git integration for the DEAH Development Pod",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--action",
        choices=["setup", "pull", "commit", "push", "status", "full"],
        default="full",
        help="Git action to perform (default: full = setup + pull + commit + push)",
    )
    parser.add_argument("--repo",       default=None, help="Git repo URL (or GIT_REPO_URL env var)")
    parser.add_argument("--pat",        default=None, help="Personal Access Token (or GIT_PAT env var)")
    parser.add_argument("--branch",     default=None, help="Target feature branch (or GIT_BRANCH env var)")
    parser.add_argument("--local-path", default=None, help="Local clone directory (or GIT_LOCAL_PATH env var)")
    parser.add_argument("--output",     default=None, help="Output artifacts directory (or OUTPUT_DIR env var)")
    parser.add_argument("--project",    default=None, help="Project ID — used to auto-name feature branch")
    parser.add_argument("--message",    default=None, help="Commit message override")
    parser.add_argument("--push",       action="store_true", help="Push after commit (used with --action commit)")
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
    args = parser.parse_args()

    # ── Resolve config (CLI > env var > default) ───────────────────────────────
    repo_url   = args.repo       or os.environ.get("GIT_REPO_URL", "")
    pat        = args.pat        or os.environ.get("GIT_PAT", "")
    local_path = args.local_path or os.environ.get("GIT_LOCAL_PATH", "")
    output_str = args.output     or os.environ.get("OUTPUT_DIR", "output")

    # Local workspace resolved early — needed for workspace detection
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

    # Feature branch priority:
    #   1. --branch flag
    #   2. GIT_BRANCH env var
    #   3. Ticket ID from --output folder (e.g. output/SCRUM-123 → feature/SCRUM-123_<date>_v1)
    #   4. Current workspace branch (fallback only when output folder has no ticket ID)
    #   5. Auto-generated name
    _ticket_from_output = _ticket_id_from_path(output_dir)
    branch = (
        args.branch
        or os.environ.get("GIT_BRANCH", "")
        or (_ticket_from_output and _build_branch(_ticket_from_output))
        or (workspace_ready and _get_workspace_branch(local_path))
        or _build_branch(args.project or "")
    )

    # ── Resolve file selection (only relevant for commit/full actions) ─────────
    _needs_selection = args.action in ("commit", "full") or (
        args.action == "commit" and args.push
    )
    selected: set[str] | None = None   # None means "all files"

    if _needs_selection:
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
    if _needs_selection:
        print(f"  Files         : {len(selected) if selected is not None else 'all'}")
    print("=" * 65)

    action = args.action

    # ── Dispatch ─────────────────────────────────────────────────────────────
    if workspace_ready:
        # Workspace already has auth configured — use subprocess directly (no PAT needed)
        if action == "status":
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
                print("  Changed files  :")
                for line in result.stdout.strip().splitlines():
                    print(f"    {line}")
            else:
                print("  Working tree is clean.")
            return

        # Fix remote URL auth format before any network operation.
        # Uses GIT_PAT env var / --pat flag if set (refreshes an expired token),
        # otherwise reformats the existing embedded token into the correct format.
        _fix_remote_auth(local_path, pat=pat)

        # Pull only when explicitly requested — 'full' skips pull because the
        # workspace remote already has the PAT embedded from the initial setup,
        # and git's interactive credential prompt fires via /dev/tty even when
        # capture_output=True.  Commit + push work fine without a prior pull.
        if action == "pull":
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
        # First-time setup — workspace not initialized; use GitRepoManager (needs PAT)
        branch_url = f"{repo_url.rstrip('/')}/tree/{branch}"
        git = GitRepoManager(branch_url=branch_url, pat=pat, local_path=local_path)

        if action in ("setup", "full"):
            action_setup(git)

        if action in ("pull", "full"):
            action_pull(git)

        if action == "status":
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


if __name__ == "__main__":
    main()
