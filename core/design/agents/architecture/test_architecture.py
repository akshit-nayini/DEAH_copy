#!/usr/bin/env python3
"""
test_architecture.py
────────────────────
Local test script for the Architecture Agent.

Usage:
    # Using Jira ticket — looks up latest requirements JSON from metadata DB
    python test_architecture.py --ticket SCRUM-5

    # Using requirements file directly
    python test_architecture.py --input requirements_output.json

    # Using built-in sample input
    python test_architecture.py --sample

    # Dry-run only (validate input, no LLM call)
    python test_architecture.py --sample --dry-run

    # Save manifest to a specific path
    python test_architecture.py --ticket SCRUM-5 --out output/architecture_manifest.json
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(REPO_ROOT))

_DEAH_ROOT = Path(__file__).resolve().parents[4]
if str(_DEAH_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEAH_ROOT))

from core.utilities.llm import create_llm_client
from agent import ArchitectureAgent, validate_input
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
    "model": {
        "model_id": os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        "max_tokens": 16000,
        "temperature": 0.0,
    },
    "confidence_threshold": 0.7,
    "paths": {
        "output_dir": str(ROOT / "outputs"),
    },
}

SAMPLE_INPUT = {
    "source": "jira",
    "ticket_id": "DE-1042",
    "request_type": "new development",
    "run_plan": ["data_model", "architecture", "impl_steps", "validator"],
    "project_name": "Customer 360 Data Platform",
    "objective": (
        "Build a unified customer data pipeline that consolidates customer "
        "information from CRM, e-commerce, and support systems into BigQuery."
    ),
    "business_context": (
        "Marketing and customer success teams need a single source of truth "
        "for customer data to reduce churn and improve targeting."
    ),
    "functional_requirements": [
        "Consolidate customer profiles from Salesforce CRM, Shopify, and Zendesk",
        "Track customer purchase history with order line-item detail",
        "Provide daily-refreshed aggregated metrics per customer",
        "Support customer segmentation by LTV, recency, and frequency",
    ],
    "data_requirements": {
        "source_systems": ["Salesforce CRM", "Shopify", "Zendesk"],
        "data_types": "structured",
        "volume": "~5M customer records, ~50M orders, ~20M support tickets",
        "frequency": "daily batch",
    },
    "technology": {
        "stack": "BigQuery",
        "environment": "production",
        "cloud_or_onprem": "GCP",
    },
    "non_functional": {
        "performance": "Dashboard queries within 5 seconds",
        "scalability": "Must support 2x data growth over 18 months",
        "latency": "T+1 day acceptable",
        "sla": "99.5% pipeline uptime",
    },
    "security": {
        "data_sensitivity": "Contains PII: names, emails, phone numbers",
        "access_controls": "Role-based access via IAM",
        "compliance": "GDPR",
    },
    "constraints": {
        "budget": "Use existing GCP commitment",
        "timeline": "MVP in 8 weeks",
        "technical_limitations": "Salesforce API rate limits: 15,000 calls/day",
    },
    "assumptions": [
        "Customer email is the natural key across all three systems",
        "Historical data for the past 2 years will be backfilled",
    ],
    "acceptance_criteria": [
        "All three source systems are integrated",
        "Data refreshed daily by 06:00 UTC",
        "PII columns are tagged",
    ],
    "expected_outputs": [
        "Architecture Decision Document",
        "Recommended GCP tech stack",
        "Risk and assumption register",
    ],
    "classification": {
        "ingestion_type": "batch",
        "output_type": "pipeline",
    },
    "confidence": 0.88,
    "low_confidence_warning": None,
    "raw_text": "Original Jira ticket DE-1042 content...",
}


def parse_args():
    p = argparse.ArgumentParser(description="Test the Architecture Agent")
    p.add_argument("--ticket", help="Jira ticket ID — looks up latest requirements JSON automatically")
    p.add_argument("--input", help="Path to requirements JSON file")
    p.add_argument("--sample", action="store_true", help="Use built-in sample input")
    p.add_argument("--dry-run", action="store_true", help="Validate only, no LLM call")
    p.add_argument("--out", help="Save manifest JSON to this path")
    return p.parse_args()


def validate_args(args):
    errors = []
    if not args.ticket and not args.sample and not args.input:
        errors.append("Provide --ticket, --sample, or --input <file>")
    if args.input and not Path(args.input).exists():
        errors.append(f"File not found: {args.input}")
    if errors:
        for e in errors:
            print(f"  {e}")
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

    if args.ticket:
        req_path = get_latest_output(args.ticket, "Requirements", "JSON", REPO_ROOT)
        print(f"\n  Architecture Agent")
        print(f"    source  : metadata → {req_path}")
        with open(req_path) as f:
            requirements = json.load(f)
    elif args.sample:
        requirements = SAMPLE_INPUT
        print("\n  Architecture Agent")
        print("    source  : sample (Customer 360)")
    else:
        with open(args.input) as f:
            requirements = json.load(f)
        print(f"\n  Architecture Agent")
        print(f"    source  : {args.input}")

    print(f"    model   : {CONFIG['model']['model_id']}")

    if args.dry_run:
        print("\n  DRY RUN — Validating input only")
        errors = validate_input(requirements)
        if errors:
            print("\n  VALIDATION FAILED:")
            for e in errors:
                print(f"    x {e}")
            sys.exit(1)
        print("  Validation PASSED")
        sys.exit(0)

    agent = ArchitectureAgent(CONFIG)

    print("\n  Running architecture agent...")
    result = agent.run(requirements)

    if not result.success:
        print(f"\n  Agent failed: {result.error}")
        sys.exit(1)

    if result.skipped:
        print(f"\n  Agent skipped: {result.skip_reason}")
        sys.exit(0)

    m = result.manifest
    options = m.get("options", [])
    rec = m.get("recommendation", {})

    print_section("ARCHITECTURE SUMMARY", "\n".join([
        f"  Cloud:          {m.get('cloud_platform')}",
        f"  Pattern:        {m.get('inferred_pattern_type')}",
        f"  Options:        {len(options)}",
        f"  Recommended:    {rec.get('selected_option')}",
        f"  Justification:  {rec.get('justification', '')[:120]}",
    ]))

    print_section("SCORING TABLE", "")
    header = f"  {'Option':<40} {'Cost':>5} {'Scale':>6} {'Cplx':>5} {'Lat':>4} {'Ops':>4} {'Score':>6}"
    print(header)
    print(f"  {'─'*40} {'─'*5} {'─'*6} {'─'*5} {'─'*4} {'─'*4} {'─'*6}")
    for row in m.get("scoring_table", []):
        print(
            f"  {row.get('option', ''):<40} "
            f"{row.get('cost', 0):>5} "
            f"{row.get('scalability', 0):>6} "
            f"{row.get('complexity', 0):>5} "
            f"{row.get('latency', 0):>4} "
            f"{row.get('operability', 0):>4} "
            f"{row.get('weighted_score', 0.0):>6.2f}"
        )

    if result.validation_warnings:
        print_section(f"WARNINGS ({len(result.validation_warnings)})", "\n".join(
            f"  ! {w}" for w in result.validation_warnings
        ))

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(m, indent=2), encoding="utf-8")
        print(f"\n  Saved manifest to {out_path}")

    print(f"\n{'='*72}")
    print(f"  Cloud Platform   : {m.get('cloud_platform')}")
    print(f"  Pattern Type     : {m.get('inferred_pattern_type')}")
    print(f"  Options          : {len(options)}")
    print(f"  Recommended      : {rec.get('selected_option')}")
    print(f"  Global Risks     : {len(m.get('global_risks', []))}")
    print(f"  Traceability     : {len(m.get('traceability', []))} items")
    print(f"  Open Questions   : {len(m.get('open_questions', []))}")
    print(f"  Run ID           : {result.run_id}")
    print(f"  Duration         : {result.duration_seconds}s")
    print(f"{'='*72}\n")

    identifier = requirements.get("ticket_id") or "unknown"
    output_dir = Path(CONFIG["paths"]["output_dir"])
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H")
    meta_path = str(output_dir.relative_to(REPO_ROOT.parent))
    meta_ok = all(
        log_agent_op(
            identifier=identifier,
            agent="Architecture",
            artifact="GITHUB",
            request_type=requirements.get("request_type", ""),
            filename=fname.name,
            path=meta_path,
        )
        for fname in output_dir.glob(f"arc_{identifier}_{run_id}*")
    )

    commit_label = f"[Architecture] {requirements.get('project_name', identifier)} | {requirements.get('request_type', '')} | outputs"
    if meta_ok:
        _push_output_to_git(output_dir, commit_label)
    else:
        print("    Skipping git push — metadata not recorded.")


if __name__ == "__main__":
    main()
