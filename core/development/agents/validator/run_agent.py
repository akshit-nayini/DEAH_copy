"""Standalone CLI runner for the PreDeployValidator agent.

Usage:
    python run_agent.py \
        --project my-gcp-project --dataset my_dataset \
        --region us-central1 \
        --dag-bucket my-dag-bucket \
        --composer-env my-composer-env
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_this_dir = Path(__file__).resolve().parent
_dev_root = _this_dir.parent.parent
_repo_root = _dev_root.parent.parent
_de_dev = _repo_root / "de_development"
for _p in [str(_dev_root), str(_repo_root), str(_de_dev)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from api.models import DeployInput, DeployTarget
from agents.validator.agent import PreDeployValidator


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PreDeployValidator standalone")
    parser.add_argument("--project",        required=True)
    parser.add_argument("--dataset",        required=True)
    parser.add_argument("--region",         default="us-central1")
    parser.add_argument("--dag-bucket",     default="")
    parser.add_argument("--composer-env",   default="")
    parser.add_argument("--source-db-type", default="")
    parser.add_argument("--source-db-host", default="")
    parser.add_argument("--source-db-port", type=int, default=0)
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    request = DeployInput(
        request_id="validate-standalone",
        artifacts_dir="",
        project_id=args.project,
        dataset_id=args.dataset,
        region=args.region,
        environment="dev",
        dag_bucket=args.dag_bucket,
        composer_environment=args.composer_env,
        source_db_type=args.source_db_type,
        source_db_host=args.source_db_host,
        source_db_port=args.source_db_port,
        target=DeployTarget.GCP,
    )

    print("\n" + "=" * 60)
    print("  PRE-DEPLOY VALIDATOR — STARTING")
    print("=" * 60)

    results = PreDeployValidator().validate(request)

    _icons = {"pass": "✓", "fail": "✗", "skipped": "~"}
    all_pass = True
    for r in results:
        icon = _icons.get(r.status.value, "?")
        print(f"  {icon}  {r.check:<25}  {r.status.value:<8}  {r.message}")
        if r.status.value == "fail":
            all_pass = False

    print()
    if all_pass:
        print("  All checks PASSED or SKIPPED — safe to deploy.")
    else:
        print("  One or more checks FAILED — fix connectivity issues before deploying.")
    print("=" * 60)


if __name__ == "__main__":
    main()
