#!/usr/bin/env python3
"""
test_requirements.py
────────────────────
Local test script for the Requirements Gathering module.

Usage:
  # Fetch from Jira ticket (--source defaults to jira when --ticket is given)
  python test_requirements.py --ticket SCRUM-5
  python test_requirements.py --source jira --ticket SCRUM-5

  # Fetch from Jira and write summary comment back to the ticket
  python test_requirements.py --ticket SCRUM-5 --write-back

  # Read from a local document
  python test_requirements.py --source document --file requirements_template.txt

  # Output is always saved to output/ under the requirements_gathering folder
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── make sure the repo root is on the path ───────────────────────────────────

ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[4]
OUTPUT_DIR = ROOT / "output"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO_ROOT))

from gathering.agent import RequirementsAgent
from gathering.agent import RequirementsRejected
from core.utilities.db_tools.agent_output_metadata import log_agent_op
from core.utilities.versioning_tools.git_manager import GitRepoManager

logger = logging.getLogger(__name__)


# ── git push ──────────────────────────────────────────────────────────────────

def _push_output_to_git(output_dir: Path, commit_label: str) -> None:
    """Push output_dir contents to git. Skips silently if env vars not set."""
    branch_url = os.environ.get("GIT_BRANCH_URL")
    pat        = os.environ.get("GIT_PAT")
    if not branch_url or not pat:
        print("\n⚠️  GIT_BRANCH_URL or GIT_PAT not set — push outputs manually:")
        print(f"    git add {output_dir} && git commit -m '{commit_label}' && git push")
        return
    if not output_dir.exists():
        print(f"\n⚠️  Output directory not found: {output_dir}")
        return

    try:
        print(f"\n[git] Pushing {output_dir.name}/ to {branch_url} …")
        git = GitRepoManager(branch_url=branch_url, pat=pat, local_path=str(REPO_ROOT))
        git.connect()

        stash = subprocess.run(
            ["git", "stash", "--include-untracked", "--quiet"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
        stashed = stash.returncode == 0 and "No local changes" not in stash.stdout

        try:
            git.pull()
        finally:
            if stashed:
                subprocess.run(["git", "stash", "pop", "--quiet"], cwd=str(REPO_ROOT), check=False)

        subprocess.run(["git", "add", str(output_dir)], cwd=str(REPO_ROOT), check=True)
        git.commit(commit_label, add_all=False)
        git.push()
        print("[git] Outputs pushed successfully.")
    except Exception as exc:
        print(f"\n⚠️  Git push failed: {exc}")
        print(f"    Push manually:")
        print(f"    git add {output_dir} && git commit -m '{commit_label}' && git push")


# ── config ────────────────────────────────────────────────────────────────────
# Values are read from env vars first, then fall back to the defaults
# matching your jira_rw.py so you can run without any extra setup.

CONFIG = {
    "model": os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
    "jira_base_url": os.getenv("JIRA_BASE_URL", "https://prodapt-deah.atlassian.net"),
    "jira_email": os.getenv("JIRA_EMAIL", ""),
    "jira_api_key": os.getenv("JIRA_API_KEY", ""),
    "write_back_to_jira": False,  # overridden by --write-back flag
}


def parse_args():
    p = argparse.ArgumentParser(description="Test the Requirements Gathering Agent")
    p.add_argument(
        "--source",
        choices=["jira", "document"],
        default=None,
        help="Where to read requirements from (default: jira when --ticket is given)",
    )
    p.add_argument("--ticket", help="Jira ticket ID (e.g. SCRUM-5)")
    p.add_argument("--file", help="Path to requirements document")
    p.add_argument(
        "--write-back",
        action="store_true",
        help="Post a summary comment back to the Jira ticket",
    )
    p.add_argument(
        "--format",
        choices=["markdown", "json", "both"],
        default="both",
        help="Output format (default: both)",
    )
    return p.parse_args()


def validate_args(args):
    if args.ticket and not args.source:
        args.source = "jira"
    errors = []
    if not args.source:
        errors.append("--source is required when --ticket is not provided")
    if args.source == "jira" and not args.ticket:
        errors.append("--ticket is required when --source=jira")
    if args.source == "document" and not args.file:
        errors.append("--file is required when --source=document")
    if args.source == "document" and args.file and not Path(args.file).exists():
        errors.append(f"File not found: {args.file}")
    if errors:
        for e in errors:
            print(f"❌  {e}")
        sys.exit(1)


def print_section(title: str, content: str):
    width = 72
    print(f"\n{'─' * width}")
    print(f"  {title}")
    print(f"{'─' * width}")
    print(content)


def main():
    args = parse_args()
    validate_args(args)

    CONFIG["write_back_to_jira"] = args.write_back

    print(f"\n🚀  Requirements Gathering Agent")
    print(f"    source  : {args.source}")
    if args.source == "jira":
        print(f"    ticket  : {args.ticket}")
    else:
        print(f"    file    : {args.file}")
    print(f"    model   : {CONFIG['model']}")
    print(f"    writeback: {CONFIG['write_back_to_jira']}")

    agent = RequirementsAgent(CONFIG)

    print("\n⏳  Fetching and extracting requirements…")
    try:
        if args.source == "jira":
            output = agent.run_from_jira(args.ticket)
        else:
            output = agent.run_from_document(args.file)
    except RequirementsRejected as e:
        print(f"\n⚠️  Requirements rejected — {e.message}")
        print(f"    Missing fields: {', '.join(e.missing_fields)}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n❌  Agent failed: {exc}")
        raise

    # ── display ───────────────────────────────────────────────────────────────
    if args.format in ("markdown", "both"):
        print_section("MARKDOWN OUTPUT", output.to_markdown())

    if args.format in ("json", "both"):
        data = output.to_dict()
        data.pop("raw_text", None)   # omit verbose field in terminal print
        print_section("JSON OUTPUT", json.dumps(data, indent=2))

    # ── save ──────────────────────────────────────────────────────────────────
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H")
    id = output.ticket_id if output.ticket_id else Path(args.file).stem
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prefix = OUTPUT_DIR / f"req_{id}_{run_id}"
    out_path = prefix.with_suffix(".md")
    json_path = prefix.with_suffix(".json")
    out_path.write_text(output.to_markdown(), encoding="utf-8")
    json_path.write_text(json.dumps(output.to_dict(), indent=2), encoding="utf-8")
    print(f"\n✅  Saved to {out_path}")
    print(f"✅  Saved to {json_path}")

    meta_path = str(OUTPUT_DIR.relative_to(REPO_ROOT.parent))
    meta_ok = all([
        log_agent_op(
            identifier=id,
            agent="Requirements",
            artifact="GITHUB",
            request_type=output.request_type,
            filename=out_path.name,
            path=meta_path,
        ),
        log_agent_op(
            identifier=id,
            agent="Requirements",
            artifact="GITHUB",
            request_type=output.request_type,
            filename=json_path.name,
            path=meta_path,
        ),
    ])

    # ── quick summary ─────────────────────────────────────────────────────────
    print(f"\n{'═' * 72}")
    print(f"  Ingestion Type : {output.classification.get('ingestion_type')}")
    print(f"  Output Type    : {output.classification.get('output_type')}")
    print(f"  Confidence     : {output.confidence:.0%}")
    print(f"  Project        : {output.project_name}")
    print(f"  Func. reqs     : {len(output.functional_requirements)}")
    print(f"{'═' * 72}\n")

    if meta_ok:
        _push_output_to_git(
            OUTPUT_DIR,
            f"[Requirements] {output.project_name} | {output.request_type} | outputs",
        )
    else:
        print("    Skipping git push — metadata not recorded.")


if __name__ == "__main__":
    main()
