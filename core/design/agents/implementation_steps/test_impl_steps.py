#!/usr/bin/env python3
"""
test_impl_steps.py
──────────────────
Local test script for the Implementation Steps Agent.

Usage:
  # Using Jira ticket — resolves type, project, and all input files from metadata DB
  python test_impl_steps.py --ticket SCRUM-5

  # Using file paths directly
  # New development — requires both architecture and data model summaries
  python test_impl_steps.py --type "new development" --project "My Project" \\
      --architecture arc_summary.json --data-model model_summary.json

  # Enhancement — architecture summary only
  python test_impl_steps.py --type enhancement --project "My Project" \\
      --architecture arc_summary.json

  # Bug — requirements summary only
  python test_impl_steps.py --type bug --project "My Project" \\
      --requirements req_summary.json
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO_ROOT))

from implementation_steps.agent import ImplStepsAgent
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
    p = argparse.ArgumentParser(description="Test the Implementation Steps Agent")
    p.add_argument("--ticket", help="Jira ticket ID — looks up all inputs automatically")
    p.add_argument("--type", choices=["bug", "enhancement", "new development"],
                   help="Request type (derived from ticket metadata when --ticket is used)")
    p.add_argument("--project", help="Project name (derived from ticket metadata when --ticket is used)")
    p.add_argument("--architecture", help="Path to architecture summary JSON")
    p.add_argument("--data-model", help="Path to data model summary JSON")
    p.add_argument("--requirements", help="Path to requirements summary JSON")
    return p.parse_args()


def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate(args):
    if args.ticket:
        return  # all inputs resolved from metadata
    errors = []
    if not args.type:
        errors.append("--type is required when --ticket is not provided")
    if not args.project:
        errors.append("--project is required when --ticket is not provided")
    if args.type == "bug" and not args.requirements:
        errors.append("--requirements is required for bug.")
    if args.type == "enhancement" and not args.architecture:
        errors.append("--architecture is required for enhancement.")
    if args.type == "new development" and not (args.architecture and args.data_model):
        errors.append("--architecture and --data-model are both required for new development.")
    if errors:
        for e in errors:
            print(f"❌  {e}")
        sys.exit(1)


def main():
    args = parse_args()
    validate(args)

    agent = ImplStepsAgent(CONFIG)

    if args.ticket:
        # Resolve all inputs from metadata
        req_path = get_latest_output(args.ticket, "Requirements", "JSON", REPO_ROOT)
        req_data = load_json(str(req_path))
        request_type = req_data.get("request_type", "new development").lower()
        project_name = req_data.get("project_name", args.ticket)

        print(f"\n🚀  Implementation Steps Agent")
        print(f"    ticket  : {args.ticket}")
        print(f"    type    : {request_type}  (from metadata)")
        print(f"    project : {project_name}  (from metadata)")
        print(f"    model   : {CONFIG['model']}")

        if request_type in ("new development", "enhancement"):
            arch_path = get_latest_output(args.ticket, "Architecture", "JSON", REPO_ROOT)
            print(f"\n[metadata] Architecture JSON : {arch_path}")
            requirements_summary = None
            architecture_summary = load_json(str(arch_path))
            if request_type == "new development":
                dm_path = get_latest_output(args.ticket, "DataModel", "JSON", REPO_ROOT)
                print(f"[metadata] DataModel JSON    : {dm_path}")
                data_model_summary = load_json(str(dm_path))
            else:
                data_model_summary = None
        else:  # bug
            requirements_summary = req_data
            architecture_summary = None
            data_model_summary   = None

        identifier = args.ticket
    else:
        request_type = args.type
        project_name = args.project
        requirements_summary = load_json(args.requirements) if args.requirements else None
        architecture_summary = load_json(args.architecture) if args.architecture else None
        data_model_summary   = load_json(args.data_model)   if args.data_model   else None

        print(f"\n🚀  Implementation Steps Agent")
        print(f"    type    : {request_type}")
        print(f"    project : {project_name}")
        print(f"    model   : {CONFIG['model']}")

        summary = (
            load_json(args.data_model)    if args.data_model    else
            load_json(args.architecture)  if args.architecture  else
            load_json(args.requirements)  if args.requirements  else {}
        )
        identifier = summary.get("ticket_id") or project_name

    print("\n⏳  Generating implementation steps…")
    try:
        output = agent.run(
            request_type=request_type,
            project_name=project_name,
            requirements_summary=requirements_summary,
            architecture_summary=architecture_summary,
            data_model_summary=data_model_summary,
        )
    except Exception as exc:
        print(f"\n❌  Agent failed: {exc}")
        raise

    print(f"\n✅  Written to {output.output_path}")
    print(f"\n{'─' * 72}")
    print(output.markdown)
    print(f"{'─' * 72}\n")

    commit_label = f"[ImplSteps] {project_name} | {request_type} | outputs"
    meta_ok = log_agent_op(
        identifier=identifier,
        agent="ImplSteps",
        artifact="GITHUB",
        request_type=request_type,
        filename=output.output_path.name,
        path=str(output.output_path.parent.relative_to(REPO_ROOT.parent)),
    )

    if meta_ok:
        _push_output_to_git(output.output_path.parent, commit_label)
    else:
        print("    Skipping git push — metadata not recorded.")


if __name__ == "__main__":
    main()
