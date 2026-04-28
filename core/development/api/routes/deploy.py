"""Deploy Pod — FastAPI routes.

Endpoint surface
────────────────
  POST  /api/v1/deploy           — trigger a deploy from an approved run
  GET   /api/v1/deploy/{run_id}  — get deploy status / result
  GET   /api/v1/deploy           — list all deploy runs (latest first)

Environment-driven deployment
──────────────────────────────
project_id, dataset_id, environment are all optional in the request body.
Resolution order:
  1. Value in request body (if non-empty)
  2. Parsed from artifacts_dir/config/pipeline_config.py using ENV
  3. PROJECT_ID / DATASET_ID / ENV environment variables
  4. Defaults: region=us-central1, environment=dev
"""
from __future__ import annotations
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.models import DeployInput, DeployOutput, DeployStatus

logger = logging.getLogger("api.routes.deploy")

router = APIRouter(prefix="/api/v1", tags=["deploy-pod"])


def _load_from_pipeline_config(config_path: Path, env: str) -> tuple[str, str, str]:
    """Parse project_id, dataset_id, region from generated pipeline_config.py."""
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


def _resolve_deploy_input(req: DeployInput) -> DeployInput:
    """Fill empty project_id / dataset_id / environment / region from config file or env vars."""
    environment = req.environment or os.environ.get("ENV", "dev").lower()

    # Try generated pipeline_config.py inside artifacts_dir
    cfg_project = cfg_dataset = cfg_region = ""
    config_file = Path(req.artifacts_dir) / "config" / "pipeline_config.py"
    if config_file.exists():
        cfg_project, cfg_dataset, cfg_region = _load_from_pipeline_config(
            config_file, environment
        )
        if cfg_project or cfg_dataset:
            logger.info(
                "Deploy resolved config from %s (env=%s): project=%s dataset=%s",
                config_file, environment, cfg_project, cfg_dataset,
            )

    project_id = req.project_id or cfg_project or os.environ.get("PROJECT_ID", "")
    dataset_id = req.dataset_id or cfg_dataset or os.environ.get("DATASET_ID", "")
    region = req.region or cfg_region or os.environ.get("REGION", "us-central1")

    return req.model_copy(update={
        "project_id": project_id,
        "dataset_id": dataset_id,
        "environment": environment,
        "region": region,
    })


class _DeployRun:
    def __init__(self, run_id: str, request: DeployInput) -> None:
        self.run_id = run_id
        self.request = request
        self.status: DeployStatus = DeployStatus.PENDING
        self.result: Optional[DeployOutput] = None
        self.error: Optional[str] = None
        self.created_at: datetime = datetime.now(timezone.utc)


_deploy_runs: dict[str, _DeployRun] = {}
_lock = threading.Lock()


def _run_deploy(run_id: str) -> None:
    run = _deploy_runs[run_id]
    run.status = DeployStatus.RUNNING
    try:
        from agents.deployer.agent import DeployerAgent
        result = DeployerAgent().deploy(run.request)
        run.result = result
        run.status = result.overall_status
    except Exception as exc:
        logger.exception("Deploy run %s failed: %s", run_id, exc)
        run.error = str(exc)
        run.status = DeployStatus.FAILED


@router.post("/deploy", response_model=dict, status_code=202)
def start_deploy(req: DeployInput, background_tasks: BackgroundTasks) -> dict:
    """Start a deploy run in the background.

    project_id, dataset_id, and environment are optional — when omitted
    they are resolved from artifacts_dir/config/pipeline_config.py (using
    the ENV env variable to select dev/uat/prod) or from PROJECT_ID /
    DATASET_ID / ENV environment variables.
    """
    resolved = _resolve_deploy_input(req)

    if not resolved.project_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "project_id could not be resolved. "
                "Pass it in the request body, set PROJECT_ID env var, "
                "or ensure pipeline_config.py exists in artifacts_dir/config/."
            ),
        )
    if not resolved.dataset_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "dataset_id could not be resolved. "
                "Pass it in the request body, set DATASET_ID env var, "
                "or ensure pipeline_config.py exists in artifacts_dir/config/."
            ),
        )

    run_id = str(uuid.uuid4())
    run = _DeployRun(run_id=run_id, request=resolved)
    with _lock:
        _deploy_runs[run_id] = run

    background_tasks.add_task(_run_deploy, run_id)
    logger.info(
        "Deploy run %s started — project=%s dataset=%s env=%s",
        run_id, resolved.project_id, resolved.dataset_id, resolved.environment,
    )
    return {
        "run_id": run_id,
        "status": "pending",
        "environment": resolved.environment,
        "project_id": resolved.project_id,
        "dataset_id": resolved.dataset_id,
    }


@router.get("/deploy/{run_id}")
def get_deploy(run_id: str) -> dict:
    run = _deploy_runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Deploy run '{run_id}' not found")
    return {
        "run_id": run_id,
        "status": run.status.value,
        "result": run.result.model_dump() if run.result else None,
        "error": run.error,
    }


@router.get("/deploy")
def list_deploys() -> list[dict]:
    with _lock:
        runs = list(_deploy_runs.values())
    runs.sort(key=lambda r: r.created_at, reverse=True)
    return [
        {
            "run_id": r.run_id,
            "request_id": r.request.request_id,
            "status": r.status.value,
            "environment": r.request.environment,
            "project_id": r.request.project_id,
            "created_at": r.created_at.isoformat(),
        }
        for r in runs
    ]
