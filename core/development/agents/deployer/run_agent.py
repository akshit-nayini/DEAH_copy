"""Standalone CLI runner for the Deployer agent.

Usage (explicit values):
    python run_agent.py \\
        --artifacts-dir output/req-abc123 \\
        --project my-gcp-project --dataset my_dataset \\
        --environment uat \\
        --region us-central1

Usage (ENV-driven — reads from generated pipeline_config.py):
    ENV=uat python run_agent.py --artifacts-dir output/req-abc123

    When --project / --dataset are omitted the script reads them from
    output/req-abc123/config/pipeline_config.py using the ENV variable
    (or --environment) to pick the right section (dev / uat / prod).
    PROJECT_ID and DATASET_ID env vars are the final fallback.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
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
from agents.deployer.agent import DeployerAgent


def _load_from_pipeline_config(config_path: Path, env: str) -> tuple[str, str, str]:
    """Parse project_id, dataset_id, region from generated pipeline_config.py.

    Uses simple regex so we never exec() arbitrary code.
    Returns (project_id, dataset_id, region) — empty strings if not found.
    """
    prefix = env.upper()
    project_id = dataset_id = region = ""
    try:
        text = config_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            m = re.match(rf'^{prefix}_PROJECT_ID\s*=\s*"([^"]*)"', line)
            if m:
                project_id = m.group(1)
            m = re.match(rf'^{prefix}_DATASET_NAME\s*=\s*"([^"]*)"', line)
            if m:
                dataset_id = m.group(1)
            m = re.match(rf'^{prefix}_REGION\s*=\s*"([^"]*)"', line)
            if m:
                region = m.group(1)
    except Exception:
        pass
    return project_id, dataset_id, region


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Deployer agent standalone")
    parser.add_argument(
        "--artifacts-dir", required=True,
        help="Path to code-gen output directory (contains ddl/, sp/, dag/, config/ sub-dirs)",
    )
    parser.add_argument(
        "--project", default="",
        help="GCP project ID (falls back to pipeline_config.py → PROJECT_ID env var)",
    )
    parser.add_argument(
        "--dataset", default="",
        help="Target BigQuery dataset ID (falls back to pipeline_config.py → DATASET_ID env var)",
    )
    parser.add_argument("--region",        default="",     help="GCP region (falls back to pipeline_config.py → us-central1)")
    parser.add_argument("--environment",   default="",     help="dev | uat | prod (falls back to ENV env var, default dev)")
    parser.add_argument("--dag-bucket",    default="",     help="GCS bucket for Composer DAGs")
    parser.add_argument("--composer-env",  default="",     help="Cloud Composer environment name")
    parser.add_argument("--source-db-type", default="",   help="oracle | mysql | postgres | mssql")
    parser.add_argument("--source-db-host", default="")
    parser.add_argument("--source-db-port", type=int, default=0)
    parser.add_argument("--source-db-name", default="")
    parser.add_argument("--source-db-user", default="")
    parser.add_argument("--request-id",    default=None)
    parser.add_argument("--log-level",     default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    )

    # ── Resolve environment ────────────────────────────────────────────────────
    environment = args.environment or os.environ.get("ENV", "dev").lower()

    # ── Try to load from generated pipeline_config.py ─────────────────────────
    artifacts_dir = Path(args.artifacts_dir)
    config_file = artifacts_dir / "config" / "pipeline_config.py"

    cfg_project = cfg_dataset = cfg_region = ""
    if config_file.exists():
        cfg_project, cfg_dataset, cfg_region = _load_from_pipeline_config(
            config_file, environment
        )
        if cfg_project or cfg_dataset:
            logging.getLogger("deployer").info(
                "Loaded config from %s (env=%s): project=%s, dataset=%s",
                config_file, environment, cfg_project, cfg_dataset,
            )

    # ── Resolve project / dataset / region: CLI > config file > env var ────────
    project_id = (
        args.project
        or cfg_project
        or os.environ.get("PROJECT_ID", "")
    )
    dataset_id = (
        args.dataset
        or cfg_dataset
        or os.environ.get("DATASET_ID", "")
    )
    region = (
        args.region
        or cfg_region
        or os.environ.get("REGION", "us-central1")
    )

    if not project_id:
        parser.error(
            "project_id could not be resolved. Provide --project, set PROJECT_ID env var, "
            "or ensure pipeline_config.py exists in artifacts-dir/config/."
        )
    if not dataset_id:
        parser.error(
            "dataset_id could not be resolved. Provide --dataset, set DATASET_ID env var, "
            "or ensure pipeline_config.py exists in artifacts-dir/config/."
        )

    request_id = args.request_id or artifacts_dir.name

    deploy_input = DeployInput(
        request_id=request_id,
        artifacts_dir=str(artifacts_dir),
        project_id=project_id,
        dataset_id=dataset_id,
        region=region,
        environment=environment,
        dag_bucket=args.dag_bucket,
        composer_environment=args.composer_env,
        source_db_type=args.source_db_type,
        source_db_host=args.source_db_host,
        source_db_port=args.source_db_port,
        source_db_name=args.source_db_name,
        source_db_user=args.source_db_user,
        target=DeployTarget.GCP,
    )

    print("\n" + "=" * 60)
    print(f"  DEPLOYER AGENT — STARTING  [{environment.upper()}]")
    print(f"  Project : {project_id}")
    print(f"  Dataset : {dataset_id}")
    print(f"  Region  : {region}")
    print("=" * 60)

    output = DeployerAgent().deploy(deploy_input)

    print("\n" + "=" * 60)
    print("  DEPLOYER AGENT — RESULT")
    print("=" * 60)
    _icons = {"success": "✓", "skipped": "~", "failed": "✗", "pending": "?", "running": "→"}

    print(f"\n  Validation ({len(output.validation)} check(s)):")
    for v in output.validation:
        icon = _icons.get(v.status.value, "?")
        print(f"    {icon}  {v.check:<25}  {v.status.value:<8}  {v.message}")

    print(f"\n  Deploy Steps ({len(output.steps)}):")
    for s in output.steps:
        icon = _icons.get(s.status.value, "?")
        print(f"    {icon}  {s.step:<35}  {s.status.value:<8}  {s.message}")

    overall_icon = _icons.get(output.overall_status.value, "?")
    print(f"\n  {overall_icon} Overall: {output.overall_status.value.upper()}")
    print("=" * 60)

    out_dir = _this_dir / "output"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"deploy_{request_id}.json"
    out_file.write_text(json.dumps(output.model_dump(), indent=2), encoding="utf-8")
    print(f"\n  Report: {out_file}")


if __name__ == "__main__":
    main()
