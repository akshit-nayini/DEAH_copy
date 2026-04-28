"""Standalone CLI runner for the Planner agent.

Usage:
    # Full run — requires Implementation.md and mapping.csv:
    python run_agent.py --impl path/to/Implementation.md --mapping path/to/mapping.csv \
        --project my-gcp-project --dataset my_dataset

    # From the design pod output (JSON + source schema CSV):
    python run_agent.py --impl requirements.json --mapping table_schema.csv \
        --project my-gcp-project --dataset my_dataset

    # Dry-run (validate inputs only, no LLM call):
    python run_agent.py --impl ... --mapping ... --project ... --dataset ... --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Resolve sys.path so imports work whether this script is run from any directory
_this_dir = Path(__file__).resolve().parent
_dev_root = _this_dir.parent.parent        # core/development/
_repo_root = _dev_root.parent.parent       # DEAH/
_de_dev = _repo_root / "de_development"
for _p in [str(_dev_root), str(_repo_root), str(_de_dev)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.utilities.llm import create_llm_client
from input_parser import parse_inputs
from api.models import SessionContext
from agents.planner.agent import PlannerAgent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Planner agent standalone")
    parser.add_argument("--impl",     required=True,  help="Path to Implementation.md or requirements.json")
    parser.add_argument("--mapping",  required=True,  help="Path to mapping.csv or table_schema.csv")
    parser.add_argument("--project",  required=True,  help="GCP project ID")
    parser.add_argument("--dataset",  required=True,  help="Target BigQuery dataset ID")
    parser.add_argument("--env",      default="dev",         help="Environment (default: dev)")
    parser.add_argument("--provider", default="claude-code-sdk", help="LLM provider (default: claude-code-sdk)")
    parser.add_argument("--model",    default=None,             help="Model override")
    parser.add_argument("--dry-run",  action="store_true",   help="Validate inputs only, no LLM call")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )


    pipeline_input = parse_inputs(
        impl_md_path=args.impl,
        mapping_csv_path=args.mapping,
        project_id=args.project,
        dataset_id=args.dataset,
        environment=args.env,
    )

    if args.dry_run:
        print("\n  DRY RUN — inputs validated successfully")
        print(f"  Request ID : {pipeline_input.request_id}")
        print(f"  Project    : {pipeline_input.project_id} / {pipeline_input.dataset_id}")
        print(f"  impl_md    : {len(pipeline_input.implementation_md)} chars")
        print(f"  mapping    : {len(pipeline_input.mapping_csv)} chars")
        sys.exit(0)

    llm_kwargs: dict = {}
    if args.model:
        llm_kwargs["model"] = args.model
    llm = create_llm_client(args.provider, **llm_kwargs)

    ctx = SessionContext(
        request_id=pipeline_input.request_id,
        implementation_md=pipeline_input.implementation_md,
        mapping_csv=pipeline_input.mapping_csv,
        project_id=pipeline_input.project_id,
        dataset_id=pipeline_input.dataset_id,
        environment=pipeline_input.environment,
        cloud_provider=pipeline_input.cloud_provider.value,
    )

    print("\n" + "=" * 60)
    print("  PLANNER AGENT — STARTING")
    print("=" * 60)

    plan = PlannerAgent(llm).plan(ctx)

    print("\n" + "=" * 60)
    print("  PLANNER AGENT — RESULT")
    print("=" * 60)
    print(f"  Request ID  : {plan.request_id}")
    print(f"  Artifacts   : {len(plan.artifacts_to_generate)}")
    print(f"  Tables      : {len(plan.tables)}")
    print(f"  Questions   : {len(plan.clarifying_questions)}")
    print(f"  Blockers    : {len(plan.open_blockers)}")
    print()
    print("── Plan Summary ──")
    print(plan.summary)
    print()
    print("── Raw Plan (saved to output/) ──")

    out_dir = _this_dir / "output"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"plan_{plan.request_id}.md"
    out_file.write_text(plan.raw_plan, encoding="utf-8")
    print(f"  {out_file}")
    print("=" * 60)


if __name__ == "__main__":
    main()
