#!/usr/bin/env python3
"""
Development Pod — CLI Entry Point

Three modes:
  Mode 1a (ticket):     --ticket SCRUM-XX
  Mode 1b (files):      --impl <path> --mapping <path>
  Mode 2 (optimize):    --optimize --files <file> [<file> ...]

--project and --dataset are optional in all modes (falls back to
PROJECT_ID / DATASET_ID env vars; planner proceeds without them if absent).

Run commands:
  cd DEAH/core/development

  # Mode 1a — full pipeline via ticket ID (fetches all docs from metadata DB)
  python main.py --ticket SCRUM-75

  # Mode 1b — full pipeline via explicit files
  python main.py \
    --impl ../../de_development/requirements/Migration_mvp1/requirements.md \
    --mapping ../../de_development/requirements/Migration_mvp1/table_schema.csv

  # Mode 2 — optimize + review existing code
  python main.py --optimize --files path/to/dag.py path/to/schema.sql
"""
from __future__ import annotations
import argparse
import logging
import os
import sys
from pathlib import Path

# Windows terminals default to cp1252; pipeline output uses UTF-8 box-drawing chars
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# sys.path setup — must run before any local imports
_dev_root = Path(__file__).resolve().parent          # core/development/
_repo_root = _dev_root.parent.parent                  # DEAH/
_de_dev = _repo_root / "de_development"
for _p in [str(_dev_root), str(_repo_root), str(_de_dev)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Load .env file if present (mirrors run_git.py behaviour)
try:
    from dotenv import load_dotenv as _load_dotenv
    _env_file = _dev_root / ".env"
    if _env_file.exists():
        _load_dotenv(_env_file)
except ImportError:
    pass  # python-dotenv not installed — rely on raw env vars

# Configure logging early so any SDK init messages use the right format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("development.main")

# ── Step 0: Pre-flight — check and install required packages ──────────────────
# Runs before any third-party imports; installs missing packages automatically.
import preflight
preflight.run()
# ─────────────────────────────────────────────────────────────────────────────

from core.utilities.llm import create_llm_client
from input_parser import parse_inputs, parse_inputs_from_ticket
from agents.orchestration.orchestrator import CodeGenPipeline
from api.models import ArtifactType, GeneratedArtifact


_CORRECT_COMMAND = """\

  Run command (Mode 1a — full pipeline via ticket ID):
  ──────────────────────────────────────────────────────────────────────
  cd "DEAH/core/development" && python main.py --ticket SCRUM-75

  Optional: add --project "my-gcp-project" --dataset my_dataset
            if not set via PROJECT_ID / DATASET_ID env vars.
  ──────────────────────────────────────────────────────────────────────

  Run command (Mode 1b — full pipeline via files):
  ──────────────────────────────────────────────────────────────────────
  cd "DEAH/core/development" && python main.py \\
    --impl "requirements/my_project/requirements.md" \\
    --mapping "requirements/my_project/table_schema.csv"
  ──────────────────────────────────────────────────────────────────────

  Run command (Mode 2 — optimize existing code):
  ──────────────────────────────────────────────────────────────────────
  python main.py --optimize --files my_dag.py schema.sql
  ──────────────────────────────────────────────────────────────────────
"""


class _HelpfulParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"\n  ERROR: {message}", file=sys.stderr)
        print(_CORRECT_COMMAND, file=sys.stderr)
        sys.exit(2)


def main() -> None:
    parser = _HelpfulParser(
        description="DEAH Development Pod — generate, optimize, and review data pipeline code"
    )
    parser.add_argument("--ticket",   required=False, default=None,
                        help="Jira/SCRUM ticket ID — fetches impl doc + mapping CSV from metadata DB (e.g. SCRUM-75)")
    parser.add_argument("--optimize", action="store_true",
                        help="Standalone mode: optimize and review existing files (no planner/generator)")
    parser.add_argument("--files", nargs="+", default=[],
                        help="Existing code files for --optimize mode")
    parser.add_argument("--impl",     required=False, default=None,
                        help="Path to Implementation.md or requirements.json (required unless --ticket or --optimize)")
    parser.add_argument("--mapping",  required=False, default=None,
                        help="Path to mapping.csv or table_schema.csv (required unless --ticket or --optimize)")
    parser.add_argument("--project",  required=False, default=None,
                        help="GCP project ID (or set PROJECT_ID env var)")
    parser.add_argument("--dataset",  required=False, default=None,
                        help="Target BigQuery dataset ID (or set DATASET_ID env var)")
    parser.add_argument("--env",      default="dev",         help="Environment: dev | qa | prod  (default: dev)")
    parser.add_argument("--cloud",    default="gcp",         help="Cloud provider: gcp | aws | snowflake  (default: gcp)")
    parser.add_argument("--region",   default="us-central1", help="Primary region  (default: us-central1)")
    parser.add_argument("--output",   default="output",      help="Output directory  (default: output/)")
    parser.add_argument("--provider", default="claude-code-sdk", help="LLM provider: claude-code-sdk | anthropic | openai | gemini  (default: claude-code-sdk)")
    parser.add_argument("--model",    default=None,             help="Model override (e.g. claude-sonnet-4-6)")
    parser.add_argument("--git-repo-url",   default=None, help="Git repo URL — commits artifacts to a feature branch (e.g. https://github.com/org/repo)")
    parser.add_argument("--git-pat",        default=None, help="Personal Access Token for git auth (or set GIT_PAT env var)")
    parser.add_argument("--git-local-path", default=None, help="Local directory for git clone workspace (default: output/git_workspace/)")
    parser.add_argument("--git-branch",     default=None, help="Git branch to fetch files from for --optimize mode (e.g. feature/SCRUM-75_20260416_v1)")
    parser.add_argument("--git-folder",     default=None, help="Folder path within the git branch to load files from for --optimize mode")
    parser.add_argument("--push",     action="store_true",   help="Push feature branch to remote after commit")
    parser.add_argument("--dry-run",  action="store_true",   help="Plan only — show plan and assumptions, skip code generation")
    parser.add_argument("--force",    action="store_true",   help="Ignore cached run, regenerate all artifacts from scratch")
    args = parser.parse_args()

    if args.optimize:
        if not args.files and not args.git_branch:
            print("\n  ERROR: --optimize requires --files or (--git-branch + --git-repo-url).")
            print("  Examples:")
            print("    python main.py --optimize --files my_dag.py schema.sql")
            print("    python main.py --optimize --git-branch feature/SCRUM-75_20260416_v1 \\")
            print("                             --git-repo-url https://github.com/org/repo \\")
            print("                             --git-pat ghp_xxx [--git-folder pipelines/SCRUM-75]")
            sys.exit(1)
        if args.git_branch and not args.git_repo_url:
            print("\n  ERROR: --git-branch requires --git-repo-url.")
            print("  Example: --git-repo-url https://github.com/org/repo")
            sys.exit(1)
    elif not args.ticket:
        missing = [flag for flag, val in [("--impl", args.impl), ("--mapping", args.mapping)] if not val]
        if missing:
            parser.error(
                f"{' and '.join(missing)} are required unless --ticket or --optimize is used. "
                "Use --ticket SCRUM-XX to fetch from the metadata DB."
            )

    llm_kwargs: dict = {}
    if args.model:
        llm_kwargs["model"] = args.model

    import os as _os
    llm_api_key = _os.environ.get("ANTHROPIC_API_KEY") or _os.environ.get("LLM_API_KEY")
    _show_provider_mode(args.provider, llm_api_key)

    try:
        llm = create_llm_client(args.provider, **llm_kwargs)
    except (ValueError, ImportError) as e:
        print(f"\n  ERROR: Could not create LLM client — {e}")
        print(_CORRECT_COMMAND)
        sys.exit(1)

    # ── Optimize + Review mode ─────────────────────────────────────────────────
    if args.optimize:
        if args.git_branch:
            import os as _os2
            artifacts = _load_artifacts_from_git(
                repo_url=args.git_repo_url,
                branch=args.git_branch,
                folder=args.git_folder,
                pat=args.git_pat or _os2.environ.get("GIT_PAT", ""),
                local_path=args.git_local_path,
            )
        else:
            artifacts = _load_artifacts_from_files(args.files)
        pipeline = CodeGenPipeline(llm=llm, output_root=args.output)
        pipeline.optimize_and_review(
            artifacts=artifacts,
            project_id=args.project or "",
            dataset_id=args.dataset or "",
            environment=args.env,
            cloud_provider=args.cloud,
        )
        return

    # ── Full pipeline ──────────────────────────────────────────────────────────
    try:
        if args.ticket:
            # Mode 1a: fetch impl doc + mapping CSV from metadata DB by ticket ID
            logger.info("Fetching inputs from metadata DB for ticket: %s", args.ticket)
            request = parse_inputs_from_ticket(
                ticket_id=args.ticket,
                project_id=args.project,
                dataset_id=args.dataset,
                environment=args.env,
                cloud_provider=args.cloud,
                region=args.region,
            )
            logger.info("Ticket %s resolved to request_id: %s", args.ticket, request.request_id)
        else:
            # Mode 1b: explicit file paths
            request = parse_inputs(
                impl_md_path=args.impl,
                mapping_csv_path=args.mapping,
                project_id=args.project,
                dataset_id=args.dataset,
                environment=args.env,
                cloud_provider=args.cloud,
                region=args.region,
            )
    except FileNotFoundError as e:
        print(f"\n  ERROR: File not found — {e}")
        print(_CORRECT_COMMAND)
        sys.exit(1)
    except ValueError as e:
        print(f"\n  ERROR: {e}")
        print(_CORRECT_COMMAND)
        sys.exit(1)

    logger.info("Request ID: %s", request.request_id)
    logger.info("LLM provider: %s | model: %s", args.provider, args.model or "default")

    import os as _os
    git_pat = args.git_pat or _os.environ.get("GIT_PAT", "")
    git_repo_url = args.git_repo_url or _os.environ.get("GIT_REPO_URL", "") or None

    pipeline = CodeGenPipeline(
        llm=llm,
        output_root=args.output,
        git_repo_url=git_repo_url,
        git_pat=git_pat or None,
        git_local_path=args.git_local_path,
        push_to_remote=args.push,
        dry_run=args.dry_run,
        force=args.force,
    )
    pipeline.run(request)


def _show_provider_mode(provider: str, api_key: str | None) -> None:
    """
    Print a one-line banner at startup showing which LLM provider is active
    and whether its credentials look valid.

    Exits with code 1 if the provider requires an API key but none is found.

    Two supported modes
    ───────────────────
    anthropic (API key mode)
        • Requires ANTHROPIC_API_KEY env var (or --api-key argument).
        • Sends requests directly to api.anthropic.com.
        • Prompt caching is active — large repeated context blocks are
          cached server-side for ~5 min, cutting input token cost by ~90%.
        • Best for production / CI runs where you have a billing account.

    claude-code-sdk (SDK / OAuth mode)  ← default
        • Requires `claude login` to have been run at least once.
        • Requests are routed through the local Claude Code CLI OAuth session.
        • No API key is read or required — ANTHROPIC_API_KEY is temporarily
          popped from the environment before each SDK call so the CLI uses
          OAuth, then restored.  Having the variable set does NOT conflict.
        • Block-level prompt caching is not available; context blocks are
          concatenated into a single string instead.
        • Best for local development and contributor workflows.

    Override via environment
    ────────────────────────
        LLM_PROVIDER=anthropic          # switch to API key mode
        LLM_MODEL=claude-sonnet-4-6     # override model for either mode
        ANTHROPIC_API_KEY=sk-ant-...    # required for anthropic mode
    """
    import os as _os

    # Respect the same env-var override as the factory
    effective = (_os.environ.get("LLM_PROVIDER", "").strip() or provider).lower()

    sep  = "  " + "─" * 56
    print(sep)

    if effective == "claude-code-sdk":
        # Check that the SDK package is importable (CLI may not be installed)
        try:
            import claude_agent_sdk  # noqa: F401
            sdk_ok = True
        except ImportError:
            sdk_ok = False

        status = "OK — CLI OAuth session will be used" if sdk_ok else \
                 "WARNING — claude-agent-sdk not installed (run: pip install claude-agent-sdk)"
        print(f"  LLM mode  : SDK  (claude-code-sdk)")
        print(f"  Auth      : Claude Code CLI OAuth  [no API key required]")
        print(f"  Caching   : disabled  (blocks concatenated, not cached)")
        print(f"  Status    : {status}")
        if not sdk_ok:
            print(sep)
            sys.exit(1)

    else:  # anthropic or any key-based provider
        resolved_key = (
            api_key
            or _os.environ.get("ANTHROPIC_API_KEY", "")
            or _os.environ.get("LLM_API_KEY", "")
        )
        if resolved_key:
            masked = f"{resolved_key[:8]}{'*' * (len(resolved_key) - 12)}{resolved_key[-4:]}" \
                     if len(resolved_key) > 12 else "****"
            key_status = f"found  ({masked})"
        else:
            key_status = "MISSING  — set ANTHROPIC_API_KEY or pass --api-key"

        print(f"  LLM mode  : API key  ({effective})")
        print(f"  Auth      : ANTHROPIC_API_KEY  [{key_status}]")
        print(f"  Caching   : enabled  (prompt-cache active — ~90% cheaper on repeated context)")
        print(f"  Status    : {'OK' if resolved_key else 'ERROR — no API key found'}")

        if not resolved_key:
            print()
            print("  Fix: export ANTHROPIC_API_KEY=sk-ant-<your-key>")
            print("       or switch to SDK mode: --provider claude-code-sdk")
            print(sep)
            sys.exit(1)

    print(sep)
    print()


def _load_artifacts_from_files(file_paths: list[str]) -> list[GeneratedArtifact]:
    artifacts = []
    for path_str in file_paths:
        p = Path(path_str)
        if not p.exists():
            print(f"\n  ERROR: File not found — {path_str}")
            sys.exit(1)
        content = p.read_text(encoding="utf-8")
        ext = p.suffix.lower()
        upper = content.upper()

        if ext == ".py":
            art_type = ArtifactType.DAG if "DAG(" in upper or "WITH DAG" in upper else ArtifactType.PIPELINE
        elif ext == ".sql":
            if "CREATE OR REPLACE PROCEDURE" in upper or "CREATE PROCEDURE" in upper:
                art_type = ArtifactType.SP
            elif "MERGE" in upper or "INSERT INTO" in upper:
                art_type = ArtifactType.DML
            else:
                art_type = ArtifactType.DDL
        elif ext in (".yaml", ".yml", ".json"):
            art_type = ArtifactType.CONFIG
        elif ext == ".md":
            art_type = ArtifactType.DOC
        else:
            art_type = ArtifactType.CONFIG

        artifacts.append(GeneratedArtifact(
            file_name=p.name,
            artifact_type=art_type,
            content=content,
            target_path=f"{art_type.value}/{p.name}",
        ))
        logger.info("Loaded %s as %s", p.name, art_type.value)
    return artifacts


def _load_artifacts_from_git(
    repo_url: str,
    branch: str,
    folder: str | None,
    pat: str,
    local_path: str | None,
) -> list[GeneratedArtifact]:
    """
    Clone/connect to repo at the given branch, collect all .sql and .py files
    from the specified folder (or repo root if not specified), and return them
    as GeneratedArtifact objects ready for the optimizer.
    """
    import tempfile
    from pathlib import Path as _Path
    from core.utilities.versioning_tools import GitRepoManager

    branch_url = f"{repo_url.rstrip('/')}/tree/{branch}"
    workspace = local_path or tempfile.mkdtemp(prefix="deah_opt_")

    print()
    print(f"  Connecting to : {repo_url}")
    print(f"  Branch        : {branch}")
    print(f"  Folder        : {folder or '(repo root)'}")

    git = GitRepoManager(branch_url=branch_url, pat=pat, local_path=workspace)
    try:
        git.connect()
        git.pull()
    except Exception as e:
        print(f"\n  ERROR: Could not access git branch '{branch}' — {e}")
        sys.exit(1)

    search_root = _Path(workspace) / (folder or "")
    if not search_root.exists():
        print(f"\n  ERROR: Folder not found in branch: {folder!r}")
        print(f"  Workspace root: {workspace}")
        sys.exit(1)

    files = sorted(search_root.rglob("*.sql")) + sorted(search_root.rglob("*.py"))
    # Exclude __pycache__ and hidden dirs
    files = [f for f in files if "__pycache__" not in f.parts and not any(p.startswith(".") for p in f.parts)]

    if not files:
        print(f"\n  ERROR: No .sql or .py files found under {search_root}")
        sys.exit(1)

    print(f"\n  Found {len(files)} file(s):")
    for f in files:
        print(f"    {f.relative_to(_Path(workspace))}")

    return _load_artifacts_from_files([str(f) for f in files])


if __name__ == "__main__":
    main()
