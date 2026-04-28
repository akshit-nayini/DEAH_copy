"""Code Gen Pod — FastAPI routes.

Endpoint surface
────────────────
  POST   /api/v1/runs                          — start a pipeline run
  GET    /api/v1/runs/{request_id}             — get run status / summary
  POST   /api/v1/runs/{request_id}/checkpoint  — submit a checkpoint decision
  GET    /api/v1/runs                          — list all runs (latest first)
  POST   /api/v1/optimize-review               — optimize and review existing artifacts

Human-in-the-loop via API
──────────────────────────
The pipeline runs in a background thread and pauses at each checkpoint.
When paused, status = "checkpoint" and checkpoint_prompt describes the decision.
The UI sends POST .../checkpoint with {"decision": "approve"|"revise"|"abort", "notes": "..."}.
The background thread unblocks and continues (or re-runs the stage on revise).
"""
from __future__ import annotations
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

_DEFAULT_OUTPUT_ROOT = os.environ.get("OUTPUT_ROOT", "/mnt/data/development")

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.models import (
    CheckpointDecision,
    CheckpointRequest,
    OptimizeReviewRequest,
    RunStatus,
    RunSummary,
    StartRunRequest,
)

logger = logging.getLogger("api.routes.code_gen")

router = APIRouter(prefix="/api/v1", tags=["code-gen-pod"])


class _RunState:
    """Mutable state for a single pipeline run — shared with the pipeline thread."""

    _LOG_CAP = 100  # keep last N log lines

    def __init__(self, request_id: str, output_dir: str) -> None:
        self.request_id = request_id
        self.output_dir = output_dir
        self.status: RunStatus = RunStatus.PENDING
        self.checkpoint_number: Optional[int] = None
        self.checkpoint_prompt: Optional[str] = None
        self.plan_summary: Optional[str] = None
        self.artifacts: list[dict] = []
        self.quality_score: Optional[float] = None
        self.git_branch: Optional[str] = None
        self.error: Optional[str] = None
        self.created_at: datetime = datetime.now(timezone.utc)
        self.current_task: Optional[str] = None
        self.log_messages: list[str] = []
        self._log_lock = threading.Lock()

        self._checkpoint_event = threading.Event()
        self._checkpoint_decision: Optional[CheckpointRequest] = None

    def push_log(self, msg: str) -> None:
        """Append a timestamped log line (thread-safe). Caps at _LOG_CAP entries."""
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        with self._log_lock:
            self.log_messages.append(entry)
            if len(self.log_messages) > self._LOG_CAP:
                self.log_messages = self.log_messages[-self._LOG_CAP:]
        self.current_task = msg

    def pause_at_checkpoint(self, number: int, prompt: str) -> CheckpointRequest:
        self.status = RunStatus.CHECKPOINT
        self.checkpoint_number = number
        self.checkpoint_prompt = prompt
        self._checkpoint_event.clear()
        self._checkpoint_event.wait()
        return self._checkpoint_decision  # type: ignore[return-value]

    def submit_decision(self, decision: CheckpointRequest) -> None:
        self._checkpoint_decision = decision
        self._checkpoint_event.set()

    def to_summary(self) -> RunSummary:
        with self._log_lock:
            logs = list(self.log_messages)
        return RunSummary(
            request_id=self.request_id,
            status=self.status,
            checkpoint_number=self.checkpoint_number,
            checkpoint_prompt=self.checkpoint_prompt,
            plan_summary=self.plan_summary,
            artifacts=self.artifacts,
            quality_score=self.quality_score,
            git_branch=self.git_branch,
            error=self.error,
            output_directory=self.output_dir,
            current_task=self.current_task,
            log_messages=logs,
        )


_runs: dict[str, _RunState] = {}
_runs_lock = threading.Lock()


def _run_pipeline(request_id: str, req: StartRunRequest, output_root: str) -> None:
    state = _runs[request_id]
    try:
        import os
        from core.utilities.llm import create_llm_client
        from api.models import PipelineInput
        from agents.orchestration.orchestrator import CodeGenPipeline

        provider = os.environ.get("LLM_PROVIDER", "claude-code-sdk")
        llm = create_llm_client(provider)

        # project_id / dataset_id / environment: request body > env var
        project_id  = req.project_id  or os.environ.get("PROJECT_ID",  "")
        dataset_id  = req.dataset_id  or os.environ.get("DATASET_ID",  "")
        environment = req.environment or os.environ.get("ENV", "dev")

        pipeline_input = PipelineInput(
            request_id=request_id,
            implementation_md=req.implementation_md,
            mapping_csv=req.mapping_csv,
            project_id=project_id,
            dataset_id=dataset_id,
            environment=environment,
            cloud_provider=req.cloud_provider,
            region=req.region,
        )

        git_repo_url = os.environ.get("GIT_REPO_URL")
        git_pat = os.environ.get("GIT_PAT", "")
        git_local_path = os.environ.get("GIT_LOCAL_PATH")
        push_remote = os.environ.get("GIT_PUSH_REMOTE", "").lower() == "true"

        pipeline = CodeGenPipeline(
            llm=llm,
            output_root=output_root,
            git_repo_url=git_repo_url,
            git_pat=git_pat or None,
            git_local_path=git_local_path,
            push_to_remote=push_remote,
            run_state=state,
        )
        output = pipeline.run(pipeline_input)

        state.artifacts = [
            {"file_name": a.file_name, "artifact_type": a.artifact_type.value}
            for a in output.artifacts
        ]
        state.quality_score = output.quality_score
        state.status = RunStatus.DONE if output.approved_for_deploy else RunStatus.ABORTED

    except Exception as exc:
        logger.exception("Pipeline run %s failed: %s", request_id, exc)
        state.error = str(exc)
        state.status = RunStatus.FAILED


@router.post("/runs", response_model=RunSummary, status_code=202)
def start_run(
    req: StartRunRequest,
    background_tasks: BackgroundTasks,
    output_root: str = _DEFAULT_OUTPUT_ROOT,
) -> RunSummary:
    """Start a new code generation pipeline run."""
    request_id = str(uuid.uuid4())
    output_dir = f"{output_root}/{request_id}"
    state = _RunState(request_id=request_id, output_dir=output_dir)

    with _runs_lock:
        _runs[request_id] = state

    background_tasks.add_task(_run_pipeline, request_id, req, output_root)
    logger.info("Started pipeline run %s", request_id)
    return state.to_summary()


@router.get("/runs/{request_id}", response_model=RunSummary)
def get_run(request_id: str) -> RunSummary:
    state = _runs.get(request_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Run '{request_id}' not found")
    return state.to_summary()


@router.post("/runs/{request_id}/checkpoint", response_model=RunSummary)
def submit_checkpoint(request_id: str, decision: CheckpointRequest) -> RunSummary:
    state = _runs.get(request_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Run '{request_id}' not found")

    if state.status != RunStatus.CHECKPOINT:
        raise HTTPException(
            status_code=409,
            detail=f"Run is not at a checkpoint (current status: {state.status})",
        )

    if decision.decision == CheckpointDecision.REVISE and not decision.notes.strip():
        raise HTTPException(
            status_code=422,
            detail="'notes' is required when decision is 'revise'",
        )

    state.submit_decision(decision)
    logger.info(
        "Checkpoint %s decision for run %s: %s",
        state.checkpoint_number, request_id, decision.decision,
    )
    return state.to_summary()


@router.get("/runs", response_model=list[RunSummary])
def list_runs() -> list[RunSummary]:
    with _runs_lock:
        runs = list(_runs.values())
    runs.sort(key=lambda r: r.created_at, reverse=True)
    return [r.to_summary() for r in runs]


def _run_optimize_review(request_id: str, req: OptimizeReviewRequest, output_root: str) -> None:
    state = _runs[request_id]
    try:
        import os
        from core.utilities.llm import create_llm_client
        from agents.orchestration.orchestrator import CodeGenPipeline

        provider = os.environ.get("LLM_PROVIDER", "claude-code-sdk")
        llm = create_llm_client(provider)

        pipeline = CodeGenPipeline(
            llm=llm,
            output_root=output_root,
            run_state=state,
        )
        result = pipeline.optimize_and_review(
            artifacts=req.artifacts,
            project_id=req.project_id,
            dataset_id=req.dataset_id,
            environment=req.environment,
            cloud_provider=req.cloud_provider.value,
            human_notes=req.human_notes,
            request_id=request_id,
        )

        state.artifacts = [
            {"file_name": a.file_name, "artifact_type": a.artifact_type.value}
            for a in result["artifacts"]
        ]
        state.quality_score = result["quality_score"]
        state.status = RunStatus.DONE

    except Exception as exc:
        logger.exception("Optimize-review run %s failed: %s", request_id, exc)
        state.error = str(exc)
        state.status = RunStatus.FAILED


@router.post("/optimize-review", response_model=RunSummary, status_code=202)
def start_optimize_review(
    req: OptimizeReviewRequest,
    background_tasks: BackgroundTasks,
    output_root: str = _DEFAULT_OUTPUT_ROOT,
) -> RunSummary:
    """Optimize and review existing code artifacts without running the planner or generator."""
    request_id = str(uuid.uuid4())
    output_dir = f"{output_root}/{request_id}"
    state = _RunState(request_id=request_id, output_dir=output_dir)

    with _runs_lock:
        _runs[request_id] = state

    background_tasks.add_task(_run_optimize_review, request_id, req, output_root)
    logger.info("Started optimize-review run %s", request_id)
    return state.to_summary()
