"""Standalone CLI runner for the Generator agent.

Usage:
    python run_agent.py --impl path/to/Implementation.md --mapping path/to/mapping.csv \
        --project my-gcp-project --dataset my_dataset

    # Skip planning step using a pre-approved plan JSON:
    python run_agent.py --plan path/to/plan_<request_id>.json \
        --impl ... --mapping ... --project ... --dataset ...
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

_this_dir = Path(__file__).resolve().parent
_dev_root = _this_dir.parent.parent
_repo_root = _dev_root.parent.parent
_de_dev = _repo_root / "de_development"
for _p in [str(_dev_root), str(_repo_root), str(_de_dev)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.utilities.llm import create_llm_client
from input_parser import parse_inputs
from api.models import SessionContext
from agents.planner.agent import PlannerAgent
from agents.generator.agent import GeneratorAgent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Generator agent standalone")
    parser.add_argument("--impl",     required=True)
    parser.add_argument("--mapping",  required=True)
    parser.add_argument("--project",  required=True)
    parser.add_argument("--dataset",  required=True)
    parser.add_argument("--env",      default="dev")
    parser.add_argument("--provider", default="claude-code-sdk")
    parser.add_argument("--model",    default=None)
    parser.add_argument("--output",   default="output", help="Directory to write artifacts")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    llm_kwargs: dict = {}
    if args.model:
        llm_kwargs["model"] = args.model
    llm = create_llm_client(args.provider, **llm_kwargs)

    pipeline_input = parse_inputs(
        impl_md_path=args.impl,
        mapping_csv_path=args.mapping,
        project_id=args.project,
        dataset_id=args.dataset,
        environment=args.env,
    )

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
    print("  GENERATOR AGENT — PLANNING FIRST")
    print("=" * 60)
    plan = PlannerAgent(llm).plan(ctx)
    ctx.plan = plan
    print(f"  Plan: {len(plan.artifacts_to_generate)} artifact(s) planned")

    print("\n" + "=" * 60)
    print("  GENERATOR AGENT — GENERATING CODE")
    print("=" * 60)
    artifacts = GeneratorAgent(llm).generate(ctx)

    out_dir = _this_dir / args.output / pipeline_input.request_id
    out_dir.mkdir(parents=True, exist_ok=True)
    for a in artifacts:
        dest = out_dir / a.artifact_type.value
        dest.mkdir(exist_ok=True)
        (dest / a.file_name).write_text(a.content, encoding="utf-8")
        print(f"  [{a.artifact_type.value.upper():6}]  {a.file_name}")

    print(f"\n  Output: {out_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
