#!/usr/bin/env python3
"""
test_data_model.py
──────────────────
Local test script for the Data Model Agent.

Usage:
  # Using Jira ticket — looks up latest requirements JSON from metadata DB
  python test_data_model.py --ticket SCRUM-5
  python test_data_model.py --ticket SCRUM-5 --schema source_schema.csv

  # Using requirements file directly
  python test_data_model.py --requirements output/req_SCRUM-5.json
  python test_data_model.py --requirements output/req_SCRUM-5.json --schema source_schema.csv

  # Without --schema — connects to source DB directly (requires DB_PASSWORD env var)
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO_ROOT))

from data_model import DataModelAgent
from core.utilities.db_tools.agent_output_metadata import log_agent_op, get_latest_output
from core.utilities.versioning_tools.git_manager import GitRepoManager


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


CONFIG = {
    "model": os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
    "output_root": str(Path(__file__).resolve().parent / "output"),
}


def parse_args():
    p = argparse.ArgumentParser(description="Test the Data Model Agent")
    p.add_argument("--ticket", help="Jira ticket ID — looks up latest requirements JSON automatically")
    p.add_argument("--requirements", help="Path to RequirementsOutput JSON file")
    p.add_argument("--schema", help="Path to source schema CSV (optional)")
    return p.parse_args()


def validate(args):
    errors = []
    if not args.ticket and not args.requirements:
        errors.append("Provide --ticket or --requirements")
    if args.requirements and not Path(args.requirements).exists():
        errors.append(f"Requirements file not found: {args.requirements}")
    if args.schema and not Path(args.schema).exists():
        errors.append(f"Schema CSV not found: {args.schema}")
    if not args.schema and not os.getenv("DB_PASSWORD"):
        errors.append("DB_PASSWORD env var is required when no --schema CSV is provided.")
    if errors:
        for e in errors:
            print(f"❌  {e}")
        sys.exit(1)


def main():
    args = parse_args()
    validate(args)

    if args.ticket:
        req_path = get_latest_output(args.ticket, "Requirements", "JSON", REPO_ROOT)
        print(f"\n[metadata] Requirements JSON: {req_path}")
    else:
        req_path = Path(args.requirements)

    requirements = json.loads(req_path.read_text(encoding="utf-8"))
    agent = DataModelAgent(CONFIG)

    print(f"\n🚀  Data Model Agent")
    print(f"    project    : {requirements.get('project_name')}")
    print(f"    source     : {'CSV' if args.schema else 'live connection'}")
    print(f"    model      : {CONFIG['model']}")

    print("\n⏳  Designing target schema…")
    try:
        output = agent.run(
            requirements=requirements,
            schema_csv=args.schema,
        )
    except Exception as exc:
        print(f"\n❌  Agent failed: {exc}")
        raise

    print(f"\n✅  Outputs written to {output.output_dir}\\")
    print(f"    data_model_summary.json")
    print(f"    er_diagram.mmd")
    print(f"    mapping.csv")

    identifier = requirements.get("ticket_id") or args.ticket or Path(args.requirements).stem
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H")
    meta_path = str(output.output_dir.relative_to(REPO_ROOT.parent))
    meta_ok = all(
        log_agent_op(
            identifier=identifier,
            agent="DataModel",
            artifact="GITHUB",
            request_type=requirements.get("request_type", ""),
            filename=fname.name,
            path=meta_path,
        )
        for fname in output.output_dir.glob(f"model_{identifier}_{run_id}*")
    )

    print(f"\n{'─' * 72}")
    print("Target Tables:")
    for t in output.target_schema:
        cols = len(t.get("columns", []))
        print(f"  {t['table_name']} ({t.get('layer', '')}) — {cols} columns")
    print(f"\nER Diagram:\n{output.er_diagram}")
    print(f"{'─' * 72}\n")

    commit_label = f"[DataModel] {requirements.get('project_name', identifier)} | {requirements.get('request_type', '')} | outputs"
    if meta_ok:
        _push_output_to_git(output.output_dir, commit_label)
    else:
        print("    Skipping git push — metadata not recorded.")


if __name__ == "__main__":
    main()
