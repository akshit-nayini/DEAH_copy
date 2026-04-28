"""Standalone CLI runner for the Reviewer agent.

Usage:
    # Review generated artifacts:
    python run_agent.py --dir output/req-abc123/ --project my-project --dataset my_dataset

    # Review with logic_preservation (compare original vs optimized):
    python run_agent.py \
        --original output/req-abc123/original/ \
        --optimized output/req-abc123/optimized/ \
        --project my-project --dataset my_dataset
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
from api.models import ArtifactType, GeneratedArtifact, SessionContext
from agents.reviewer.agent import ReviewerAgent


def _load_dir(d: Path) -> list[GeneratedArtifact]:
    artifacts = []
    for p in sorted(d.rglob("*")):
        if not p.is_file() or p.suffix not in (".sql", ".py"):
            continue
        content = p.read_text(encoding="utf-8")
        ext = p.suffix.lower()
        upper = content.upper()
        if ext == ".py":
            art_type = ArtifactType.DAG if ("DAG(" in upper or "WITH DAG" in upper) else ArtifactType.PIPELINE
        elif "CREATE OR REPLACE PROCEDURE" in upper or "CREATE PROCEDURE" in upper:
            art_type = ArtifactType.SP
        elif "MERGE" in upper or "INSERT INTO" in upper:
            art_type = ArtifactType.DML
        else:
            art_type = ArtifactType.DDL
        artifacts.append(GeneratedArtifact(
            file_name=p.name,
            artifact_type=art_type,
            content=content,
            target_path=f"{art_type.value}/{p.name}",
        ))
    return artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Reviewer agent standalone")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dir",      help="Directory of artifacts to review")
    mode.add_argument("--original", help="Directory of ORIGINAL artifacts (for logic_preservation mode)")
    parser.add_argument("--optimized", help="Directory of OPTIMIZED artifacts (required with --original)")
    parser.add_argument("--project",  default="")
    parser.add_argument("--dataset",  default="")
    parser.add_argument("--env",      default="dev")
    parser.add_argument("--provider", default="claude-code-sdk")
    parser.add_argument("--model",    default=None)
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    if args.original and not args.optimized:
        parser.error("--optimized is required when --original is provided")

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    llm_kwargs: dict = {}
    if args.model:
        llm_kwargs["model"] = args.model
    llm = create_llm_client(args.provider, **llm_kwargs)

    ctx = SessionContext(
        request_id="review-standalone",
        implementation_md="",
        mapping_csv="",
        project_id=args.project,
        dataset_id=args.dataset,
        environment=args.env,
        cloud_provider="gcp",
    )

    reviewer = ReviewerAgent(llm)
    print("\n" + "=" * 60)
    print("  REVIEWER AGENT — STARTING")
    print("=" * 60)

    if args.dir:
        artifacts = _load_dir(Path(args.dir))
        print(f"  Loaded {len(artifacts)} artifact(s) from {args.dir}")
        results = reviewer.review(ctx, artifacts)
    else:
        original = _load_dir(Path(args.original))
        optimized = _load_dir(Path(args.optimized))
        print(f"  Original  : {len(original)} artifact(s)")
        print(f"  Optimized : {len(optimized)} artifact(s)")
        results = reviewer.review_optimized(ctx, original, optimized)

    # Quality score
    score = 100.0
    for r in results:
        for f in r.findings:
            if f.severity.value == "CRITICAL":
                score -= 10
            elif f.severity.value == "WARNING":
                score -= 3
            else:
                score -= 1
    score = max(0.0, score)

    print(f"\n  Quality Score: {score:.0f}/100")
    print()
    for r in results:
        icon = {"PASS": "✓", "CONDITIONAL_PASS": "⚠", "FAIL": "✗"}.get(r.verdict.value, "?")
        print(f"  {icon}  {r.dimension.upper():<20}  {r.verdict.value}  ({len(r.findings)} finding(s))")
        for f in r.findings:
            print(f"       [{f.severity.value}]  {f.check_name}: {f.description}")

    out_dir = _this_dir / "output"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "REVIEW_REPORT.json"
    out_file.write_text(
        json.dumps([r.model_dump() for r in results], indent=2),
        encoding="utf-8",
    )
    print(f"\n  Report: {out_file}")
    print("=" * 60)


if __name__ == "__main__":
    main()
