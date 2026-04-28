#!/usr/bin/env python3
"""
test_requirements.py
────────────────────
Local test script for the Requirements Gathering module.

Usage:
  # Test with a Jira ticket
  python test_requirements.py --source jira --ticket SCRUM-5

  # Test with a local document
  python test_requirements.py --source document --file requirements_template.txt

  # Test with a Jira ticket AND write the summary comment back
  python test_requirements.py --source jira --ticket SCRUM-5 --write-back

  # Save output to a file
  python test_requirements.py --source jira --ticket SCRUM-5 --out output/requirements.md
"""

import argparse
import json
import os
import sys
from pathlib import Path

# ── make sure the repo root is on the path ───────────────────────────────────

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from gathering import RequirementsAgent
from gathering.agent import RequirementsRejected


# ── config ────────────────────────────────────────────────────────────────────
# Values are read from env vars first, then fall back to the defaults
# matching your jira_rw.py so you can run without any extra setup.

CONFIG = {
    "api_key": os.getenv("ANTHROPIC_API_KEY", ""),          # required
    "model": os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
    "jira_base_url": os.getenv("JIRA_BASE_URL", "https://prodapt-deah.atlassian.net"),
    "jira_email": os.getenv("JIRA_EMAIL", "vijayram.sridhar@prodapt.com"),
    "jira_api_key": os.getenv(
        "JIRA_API_KEY",
        "ATATT3xFfGF0gn8NL8AtwuPetG-_30dLCbj4pzmxedNhK0IsqwT6w8RMMrjX4juLdYWPl60N6Rn_tYh6fvvELsy7rk4cpLuSOuSMtcPXxo2yk9Z4sPZOwqeaSRaScIORzuCdYRYjaA6mDc3qRduhxO37Ig4pPHvuM1MYMK-LD2rl15RrtV-X4i0=0251480C",
    ),
    "write_back_to_jira": False,  # overridden by --write-back flag
}


def parse_args():
    p = argparse.ArgumentParser(description="Test the Requirements Gathering Agent")
    p.add_argument(
        "--source",
        choices=["jira", "document"],
        required=True,
        help="Where to read requirements from",
    )
    p.add_argument("--ticket", help="Jira ticket ID (e.g. SCRUM-5)")
    p.add_argument("--file", help="Path to requirements document")
    p.add_argument(
        "--write-back",
        action="store_true",
        help="Post a summary comment back to the Jira ticket",
    )
    p.add_argument("--out", help="Save Markdown output to this path")
    p.add_argument(
        "--format",
        choices=["markdown", "json", "both"],
        default="both",
        help="Output format (default: both)",
    )
    return p.parse_args()


def validate_args(args):
    errors = []
    if not CONFIG["api_key"]:
        errors.append("ANTHROPIC_API_KEY env var is not set.")
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
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output.to_markdown(), encoding="utf-8")
        print(f"\n✅  Saved to {out_path}")

    # ── quick summary ─────────────────────────────────────────────────────────
    print(f"\n{'═' * 72}")
    print(f"  Ingestion Type : {output.classification.get('ingestion_type')}")
    print(f"  Output Type    : {output.classification.get('output_type')}")
    print(f"  Confidence     : {output.confidence:.0%}")
    print(f"  Project        : {output.project_name}")
    print(f"  Func. reqs     : {len(output.functional_requirements)}")
    print(f"{'═' * 72}\n")


if __name__ == "__main__":
    main()
