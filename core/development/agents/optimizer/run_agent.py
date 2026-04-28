"""Standalone CLI runner for the Optimizer agent.

Usage:
    # Optimize a local file (saves <name>_optimized.<ext> beside original):
    python run_agent.py --files output/SCRUM-75/dag/dag_file.py

    # Optimize from a GitHub blob URL:
    python run_agent.py --files https://github.com/org/repo/blob/feature/branch/path/to/file.py

    # Optimize all .sql and .py files in a directory:
    python run_agent.py --dir output/SCRUM-75/

    # Skip the interactive notes prompt (CI / non-interactive mode):
    python run_agent.py --files my_dag.py --no-interactive

    # Push approved _optimized files to a git branch afterwards:
    python run_agent.py --files my_dag.py --push --branch feature/my-branch
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import NamedTuple

_this_dir = Path(__file__).resolve().parent
_dev_root  = _this_dir.parent.parent           # core/development/
_repo_root = _dev_root.parent.parent           # DEAH/
_de_dev    = _repo_root / "de_development"
for _p in [str(_dev_root), str(_repo_root), str(_de_dev)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.utilities.llm import create_llm_client
from api.models import ArtifactType, GeneratedArtifact, SessionContext
from agents.optimizer.agent import OptimizerAgent

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("development.optimizer")


# ── Data classes ───────────────────────────────────────────────────────────────

class SourceFile(NamedTuple):
    """A file to be optimized, with its resolved content and source location."""
    path: Path          # local path or synthetic path derived from git URL
    content: str        # file content
    from_git: bool      # True when content was fetched from a git URL
    git_url: str = ""   # original git blob URL (empty for local files)


# ── File type detection ────────────────────────────────────────────────────────

def _infer_type(path: Path, content: str) -> ArtifactType:
    ext   = path.suffix.lower()
    upper = content.upper()
    if ext == ".py":
        return ArtifactType.DAG if ("DAG(" in upper or "WITH DAG" in upper) else ArtifactType.PIPELINE
    if ext == ".sql":
        if "CREATE OR REPLACE PROCEDURE" in upper or "CREATE PROCEDURE" in upper:
            return ArtifactType.SP
        if "MERGE" in upper or "INSERT INTO" in upper:
            return ArtifactType.DML
        return ArtifactType.DDL
    return ArtifactType.CONFIG


# ── Git URL helpers ────────────────────────────────────────────────────────────

_GITHUB_BLOB_RE = re.compile(
    r"https://github\.com/([^/]+)/([^/]+)/blob/(.+)"
)


def _is_git_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def _fetch_git_url(url: str) -> SourceFile:
    """
    Fetch file content from a GitHub blob URL.

    Converts  https://github.com/<user>/<repo>/blob/<branch>/<path>
    to        https://raw.githubusercontent.com/<user>/<repo>/<branch>/<path>
    """
    m = _GITHUB_BLOB_RE.match(url)
    if not m:
        raise ValueError(
            f"Cannot parse git URL: {url}\n"
            "Expected: https://github.com/<user>/<repo>/blob/<branch>/<path/to/file>"
        )
    user, repo, rest = m.group(1), m.group(2), m.group(3)
    raw_url  = f"https://raw.githubusercontent.com/{user}/{repo}/{rest}"
    file_name = rest.split("/")[-1]
    logical_path = Path(file_name)

    pat = os.environ.get("GIT_PAT", "")
    req = urllib.request.Request(raw_url)
    if pat:
        req.add_header("Authorization", f"token {pat}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch {raw_url}: {exc}") from exc

    print(f"  Fetched [{file_name}] from {url}")
    return SourceFile(path=logical_path, content=content, from_git=True, git_url=url)


# ── Interactive helpers ────────────────────────────────────────────────────────

def _prompt_choice(prompt: str, valid: tuple[str, ...]) -> str:
    """Read a single valid character choice from stdin."""
    while True:
        print(prompt, end="", flush=True)
        try:
            c = sys.stdin.readline().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return valid[0]
        if c in valid:
            return c
        print(f"  Please enter one of: {' / '.join(valid)}")


def _ask_notes(prompt: str = "Additional notes for the optimizer?") -> str:
    """Ask user for optional free-text notes. Returns empty string if skipped."""
    print(f"\n  {prompt}")
    print("  (Press Enter to skip)")
    print("  > ", end="", flush=True)
    try:
        return sys.stdin.readline().strip()
    except (EOFError, KeyboardInterrupt):
        return ""


# ── Optimization helpers ───────────────────────────────────────────────────────

def _is_already_optimized(original: str, optimized: str) -> bool:
    """True when the LLM returned content that is functionally identical to the original."""
    return original.strip() == optimized.strip()


def _optimized_path(source: Path) -> Path:
    """Return <same-dir>/<stem>_optimized<suffix> for a source file."""
    return source.parent / f"{source.stem}_optimized{source.suffix}"


# ── Single-file review / revise / approve loop ────────────────────────────────

def _review_one(
    source:    SourceFile,
    artifact:  GeneratedArtifact,
    optimized: GeneratedArtifact,
    ctx:       SessionContext,
    llm,
    git_output_dir: Path,
) -> Path | None:
    """
    Interactive loop for one artifact.
    Returns the path where the _optimized file was saved, or None if rejected/skipped.
    """
    current = optimized

    while True:
        print()
        print("─" * 60)
        print(f"  REVIEW: {artifact.file_name}")
        print("─" * 60)

        already_optimal = _is_already_optimized(artifact.content, current.content)

        if already_optimal:
            print("  Code is already optimized — no changes were necessary.")
            print()
            print("  [s]  Skip  — no file will be written (already optimal)")
            print("  [r]  Revise — add notes and attempt further optimization")
            print("  [x]  Reject / cancel")
            choice = _prompt_choice("\n  Choice [s/r/x]: ", ("s", "r", "x"))
            if choice in ("s", "x"):
                return None
        else:
            orig_lines = set(artifact.content.splitlines())
            new_lines  = set(current.content.splitlines())
            added   = len(new_lines - orig_lines)
            removed = len(orig_lines - new_lines)
            print(f"  Changes: ~{added} line(s) added / ~{removed} line(s) changed")
            print()
            print("  [a]  Approve — save _optimized file")
            print("  [r]  Revise  — add notes and re-optimize")
            print("  [x]  Reject  — discard this optimization")
            choice = _prompt_choice("\n  Choice [a/r/x]: ", ("a", "r", "x"))

            if choice == "a":
                # Determine where to save
                if source.from_git:
                    out_path = git_output_dir / f"{Path(artifact.file_name).stem}_optimized{Path(artifact.file_name).suffix}"
                else:
                    out_path = _optimized_path(source.path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(current.content, encoding="utf-8")
                print(f"\n  Saved → {out_path}")
                return out_path

            elif choice == "x":
                print("  Discarded.")
                return None

        # ── Revise: collect notes and re-run ──────────────────────────────────
        note = _ask_notes("What should be revised or improved further?")
        if note:
            ctx.add_note(note)
        print("\n  Re-optimizing...")
        results = OptimizerAgent(llm).optimize(ctx, [artifact])
        current = results[0] if results else current


# ── Git push of _optimized files ───────────────────────────────────────────────

def _push_optimized(
    saved_paths: list[Path],
    branch:      str,
    repo_url:    str,
    pat:         str,
) -> None:
    """Copy _optimized files into the git workspace and push to remote branch."""
    from core.utilities.versioning_tools import GitRepoManager

    workspace   = _dev_root / "output" / "git_workspace"
    branch_url  = f"{repo_url.rstrip('/')}/tree/{branch}"

    git = GitRepoManager(branch_url=branch_url, pat=pat,
                         local_path=str(workspace))
    git.connect()
    git.pull()

    dest_dir = workspace / "optimized"
    dest_dir.mkdir(exist_ok=True)
    staged: list[str] = []

    for src in saved_paths:
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        staged.append(str(Path("optimized") / src.name))
        print(f"  Staged → {dest}")

    result = subprocess.run(
        ["git", "add", "--"] + staged,
        cwd=str(workspace), capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.warning("git add warning: %s", result.stderr.strip())

    names = ", ".join(Path(p).stem for p in staged)
    git.commit(f"feat: add optimized artifacts [{names}]", add_all=False)
    git.push()
    print(f"\n  Pushed {len(staged)} _optimized file(s) to origin/{branch}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    # Load .env if present
    try:
        from dotenv import load_dotenv
        env_file = _dev_root / ".env"
        if env_file.exists():
            load_dotenv(env_file)
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="Run the Optimizer agent standalone",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--files", nargs="+",
        help="Local file paths OR GitHub blob URLs to optimize",
    )
    group.add_argument(
        "--dir",
        help="Directory — optimize all .sql and .py files inside it",
    )
    parser.add_argument("--project",        default="")
    parser.add_argument("--dataset",        default="")
    parser.add_argument("--env",            default="dev")
    parser.add_argument("--provider",       default="claude-code-sdk")
    parser.add_argument("--model",          default=None)
    parser.add_argument("--no-interactive", action="store_true",
                        help="Skip all interactive prompts (for CI)")
    parser.add_argument("--push",           action="store_true",
                        help="Push approved _optimized files to git after optimization")
    parser.add_argument("--branch",         default=None,
                        help="Git branch to push to (or GIT_BRANCH env var)")
    parser.add_argument("--repo",           default=None,
                        help="Git repo URL (or GIT_REPO_URL env var)")
    parser.add_argument("--pat",            default=None,
                        help="Git PAT (or GIT_PAT env var)")
    parser.add_argument("--log-level",      default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.getLogger().setLevel(getattr(logging, args.log_level))
    interactive = not args.no_interactive

    # ── Build LLM client ──────────────────────────────────────────────────────
    llm_kwargs: dict = {}
    if args.model:
        llm_kwargs["model"] = args.model
    llm = create_llm_client(args.provider, **llm_kwargs)

    # ── Collect source files ──────────────────────────────────────────────────
    sources: list[SourceFile] = []

    if args.files:
        for f in args.files:
            if _is_git_url(f):
                sources.append(_fetch_git_url(f))
            else:
                p = Path(f)
                if not p.exists():
                    print(f"  ERROR: file not found: {p}")
                    sys.exit(1)
                sources.append(SourceFile(
                    path=p.resolve(),
                    content=p.read_text(encoding="utf-8"),
                    from_git=False,
                ))
    else:
        d = Path(args.dir)
        if not d.exists():
            print(f"  ERROR: directory not found: {d}")
            sys.exit(1)
        for p in list(d.rglob("*.sql")) + list(d.rglob("*.py")):
            sources.append(SourceFile(
                path=p.resolve(),
                content=p.read_text(encoding="utf-8"),
                from_git=False,
            ))

    if not sources:
        print("  No files to optimize.")
        sys.exit(0)

    print()
    print("=" * 60)
    print("  OPTIMIZER AGENT — STARTING")
    print("=" * 60)
    for s in sources:
        label = f"[git] {s.git_url}" if s.from_git else str(s.path)
        print(f"  File : {label}")
    print()

    # ── Ask for additional notes (interactive) ────────────────────────────────
    initial_note = ""
    if interactive:
        initial_note = _ask_notes(
            "Any additional notes or focus areas for the optimizer?\n"
            "  (e.g. 'focus on partition pruning', 'add structured logging')"
        )

    # ── Build SessionContext ──────────────────────────────────────────────────
    ctx = SessionContext(
        request_id="opt-standalone",
        implementation_md="",
        mapping_csv="",
        project_id=args.project,
        dataset_id=args.dataset,
        environment=args.env,
        cloud_provider="gcp",
    )
    if initial_note:
        ctx.add_note(initial_note)

    # ── Build artifact list ───────────────────────────────────────────────────
    artifacts: list[GeneratedArtifact] = []
    for s in sources:
        art_type = _infer_type(s.path, s.content)
        artifacts.append(GeneratedArtifact(
            file_name=s.path.name,
            artifact_type=art_type,
            content=s.content,
            target_path=f"{art_type.value}/{s.path.name}",
        ))
        print(f"  Loaded [{art_type.value.upper():8}]  {s.path.name}")

    print(f"\n  Optimizing {len(artifacts)} file(s)...")
    print()

    # ── Run optimization (all files concurrently) ─────────────────────────────
    optimized_list = OptimizerAgent(llm).optimize(ctx, artifacts)

    # ── Output dir for git-sourced files ──────────────────────────────────────
    git_output_dir = _this_dir / "output"
    git_output_dir.mkdir(parents=True, exist_ok=True)

    # ── Review / approve / revise loop (one file at a time) ──────────────────
    saved_paths: list[Path] = []

    for source, artifact, optimized in zip(sources, artifacts, optimized_list):
        if not interactive:
            # Non-interactive: auto-approve if changed, skip if already optimal
            if _is_already_optimized(artifact.content, optimized.content):
                print(f"  [{artifact.file_name}] Already optimized — skipped.")
                continue
            if source.from_git:
                out = git_output_dir / f"{Path(artifact.file_name).stem}_optimized{Path(artifact.file_name).suffix}"
            else:
                out = _optimized_path(source.path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(optimized.content, encoding="utf-8")
            print(f"  Saved → {out}")
            saved_paths.append(out)
        else:
            result = _review_one(
                source=source,
                artifact=artifact,
                optimized=optimized,
                ctx=ctx,
                llm=llm,
                git_output_dir=git_output_dir,
            )
            if result:
                saved_paths.append(result)

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    if saved_paths:
        print(f"  Optimization complete — {len(saved_paths)} file(s) saved:")
        for p in saved_paths:
            print(f"    {p}")
    else:
        print("  No files were saved (all already optimal or rejected).")
    print("=" * 60)

    if not saved_paths:
        return

    # ── Offer git push of _optimized files ───────────────────────────────────
    do_push = args.push
    if interactive and not do_push:
        print()
        choice = _prompt_choice(
            "  Push _optimized file(s) to git branch? [y/n]: ",
            ("y", "n"),
        )
        do_push = (choice == "y")

    if do_push:
        repo_url = args.repo or os.environ.get("GIT_REPO_URL", "")
        pat      = args.pat  or os.environ.get("GIT_PAT", "")
        branch   = args.branch or os.environ.get("GIT_BRANCH", "")

        missing = [n for n, v in [("repo URL", repo_url), ("PAT", pat), ("branch", branch)] if not v]
        if missing:
            print(f"\n  ERROR: missing git config for push: {', '.join(missing)}")
            print("  Set GIT_REPO_URL, GIT_PAT, GIT_BRANCH in .env or pass --repo/--pat/--branch")
        else:
            _push_optimized(saved_paths, branch=branch, repo_url=repo_url, pat=pat)


if __name__ == "__main__":
    main()
