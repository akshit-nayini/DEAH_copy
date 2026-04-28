"""
run_agent.py — Simple CLI runner for the Architecture Agent.

Usage:
    # Run with a JSON file (RequirementsAgent output):
    python run_agent.py --input requirements_output.json

    # Run with the built-in sample:
    python run_agent.py --sample

    # Dry-run (validate only, no LLM call):
    python run_agent.py --input requirements_output.json --dry-run

    # With debug logging:
    python run_agent.py --sample --log-level DEBUG

    # Save raw LLM response for inspection:
    python run_agent.py --sample --log-level DEBUG
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from init import get_agent
from agent import validate_input


# ──────────────────────────────────────────────
# Built-in sample input (mirrors data_model_agent sample)
# ──────────────────────────────────────────────

SAMPLE_INPUT = {
    "source": "jira",
    "ticket_id": "DE-1042",
    "request_type": "new development",
    "run_plan": ["data_model", "architecture", "impl_steps", "validator"],
    "project_name": "Customer 360 Data Platform",
    "objective": (
        "Build a unified customer data pipeline that consolidates customer "
        "information from CRM, e-commerce, and support systems into BigQuery "
        "to enable a 360-degree customer view."
    ),
    "business_context": (
        "Marketing and customer success teams need a single source of truth "
        "for customer data to reduce churn and improve targeting."
    ),
    "functional_requirements": [
        "Consolidate customer profiles from Salesforce CRM, Shopify, and Zendesk",
        "Track customer purchase history with order line-item detail",
        "Provide daily-refreshed aggregated metrics per customer",
        "Support customer segmentation by lifetime value, recency, and frequency",
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
        "performance": "Dashboard queries must return within 5 seconds",
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
        "Data is refreshed daily by 06:00 UTC",
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


def main():
    parser = argparse.ArgumentParser(description="Run the Architecture Agent")
    parser.add_argument("--input", "-i", type=str, help="Path to requirements JSON file")
    parser.add_argument("--sample", "-s", action="store_true", help="Use built-in sample input")
    parser.add_argument("--dry-run", action="store_true", help="Validate input only, no LLM call")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Load input
    if args.sample:
        requirements = SAMPLE_INPUT
        print("Using built-in sample input (Customer 360)\n")
    elif args.input:
        path = Path(args.input)
        if not path.exists():
            print(f"Error: file not found: {path}", file=sys.stderr)
            sys.exit(1)
        with open(path) as f:
            requirements = json.load(f)
        print(f"Loaded input from {path}\n")
    else:
        parser.print_help()
        print("\nError: provide --input <file> or --sample", file=sys.stderr)
        sys.exit(1)

    # Dry-run: validate only
    if args.dry_run:
        print("=" * 50)
        print("  DRY RUN — Validating input only")
        print("=" * 50)
        errors = validate_input(requirements)
        if errors:
            print("\n  VALIDATION FAILED:\n")
            for e in errors:
                print(f"    x {e}")
            sys.exit(1)
        else:
            print(f"\n  Validation PASSED")
            print(f"    request_type:    {requirements.get('request_type')}")
            print(f"    ingestion_type:  {requirements.get('classification', {}).get('ingestion_type')}")
            print(f"    output_type:     {requirements.get('classification', {}).get('output_type')}")
            print(f"    confidence:      {requirements.get('confidence')}")
            print(f"    func_reqs:       {len(requirements.get('functional_requirements', []))}")
        sys.exit(0)

    # Full run
    print("=" * 60)
    print("  ARCHITECTURE AGENT — STARTING")
    print("=" * 60)
    print()

    agent = get_agent()
    result = agent.run(requirements)

    print()
    print("=" * 60)
    print("  ARCHITECTURE AGENT — RESULT")
    print("=" * 60)
    print(f"  Success:         {result.success}")
    print(f"  Skipped:         {result.skipped}")
    print(f"  Run ID:          {result.run_id}")
    print(f"  Duration:        {result.duration_seconds}s")

    if result.token_usage:
        print(f"  Input tokens:    {result.token_usage.get('input', 'N/A')}")
        print(f"  Output tokens:   {result.token_usage.get('output', 'N/A')}")

    if result.error:
        print(f"\n  ERROR: {result.error}")

    if result.skip_reason:
        print(f"\n  Skip reason: {result.skip_reason}")

    if result.validation_warnings:
        print(f"\n  Warnings ({len(result.validation_warnings)}):")
        for w in result.validation_warnings:
            print(f"    ! {w}")

    if result.manifest:
        m = result.manifest
        options = m.get("options", [])
        rec = m.get("recommendation", {})

        print(f"\n  Cloud Platform:      {m.get('cloud_platform')}")
        print(f"  Pattern Type:        {m.get('inferred_pattern_type')}")
        print(f"  Options Generated:   {len(options)}")
        print(f"  Recommended:         {rec.get('selected_option')}")
        print(f"  Global Risks:        {len(m.get('global_risks', []))}")
        print(f"  Traceability Items:  {len(m.get('traceability', []))}")
        print(f"  Open Questions:      {len(m.get('open_questions', []))}")

        print(f"\n  Scoring Summary:")
        for row in m.get("scoring_table", []):
            print(f"    {row.get('option'):40s}  weighted={row.get('weighted_score'):.2f}")

    print()
    print(f"  Outputs: outputs/")
    print("=" * 60)


if __name__ == "__main__":
    main()
