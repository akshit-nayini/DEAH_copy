"""Pydantic models — unified input/output contracts for the Development Pod.

Data flow:
  Design Pod  →  PipelineInput
  PlannerAgent →  ExecutionPlan  ──┐
  (both stored in SessionContext)  │
                                   ↓
  GeneratorAgent uses SessionContext (cached) → list[GeneratedArtifact]
  OptimizerAgent uses SessionContext (cached) → list[GeneratedArtifact]
  ReviewerAgent  uses SessionContext (cached) → list[ReviewResult]
  Final          →  CodeGenOutput  →  Deploy Pod (DeployInput)
"""
from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Shared enums ───────────────────────────────────────────────────────────────

class CloudProvider(str, Enum):
    GCP = "gcp"
    AWS = "aws"
    AZURE = "azure"
    SNOWFLAKE = "snowflake"


class ArtifactType(str, Enum):
    DDL = "ddl"
    DML = "dml"
    SP = "sp"
    DAG = "dag"
    PIPELINE = "pipeline"
    CONFIG = "config"
    DOC = "doc"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class Verdict(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


# ── Plan spec sub-models ───────────────────────────────────────────────────────

class ServiceSpec(BaseModel):
    name: str
    connection: str = ""
    type: str = ""  # orchestration, warehouse, storage, streaming


class ConnectionDetailSpec(BaseModel):
    """Captures every explicit connection string, path, or URL in the requirements."""
    service: str              # e.g. "Cloud SQL", "GCS", "Pub/Sub"
    type: str = ""            # jdbc | gcs | pubsub | api | ftp | sftp | bq
    value: str = ""           # actual URL/path — masked secrets become <SECRET>
    env_var: str = ""         # name of the env-var that holds the secret at runtime


class LoggingSpec(BaseModel):
    """Describes a logging or monitoring mechanism explicitly mentioned in the doc."""
    type: str = ""            # CloudLogging | BigQuery | Stackdriver | Custom
    description: str = ""


class AlertingSpec(BaseModel):
    """Describes an alerting or notification mechanism explicitly mentioned in the doc."""
    type: str = ""            # CloudMonitoring | PagerDuty | Email | Slack | Custom
    description: str = ""


class TableSpec(BaseModel):
    name: str
    layer: str = ""   # staging, core, quarantine
    type: str = "CREATE"  # CREATE or ALTER


class ArtifactSpec(BaseModel):
    file_name: str
    type: str = ""    # DDL, DML, SP, DAG
    reason: str = ""


class AuditTableSpec(BaseModel):
    enabled: bool = False  # True only when audit logging is explicitly required by the requirements
    name: str = "audit_pipeline_runs"
    dataset: str = ""
    columns: list[str] = Field(default_factory=lambda: [
        "dag_name", "process_name", "source_table", "target_table",
        "source_count", "target_count", "insert_count", "upsert_count",
        "runtime_seconds", "status", "error_message", "run_timestamp",
    ])


class StoreProcSpec(BaseModel):
    name: str = "sp_log_audit"
    description: str = "Single reusable proc to log any pipeline run to audit_pipeline_runs"


class ManifestFile(BaseModel):
    file_path: str
    file_type: str
    change_type: str = "created"   # "created" or "modified"
    columns_affected: list[str] = []
    tc_ids: list[str] = []
    owner: str = "Development Agent"


# ── Code Gen Pod — Input (from Design Pod) ────────────────────────────────────

class PipelineInput(BaseModel):
    """Everything the Code Gen Pod needs from the Design Pod."""
    request_id: str
    implementation_md: str = Field(..., description="Raw content of Implementation.md")
    mapping_csv: str = Field(..., description="Raw content of mapping.csv")
    project_id: str = Field(default="", description="GCP project ID (or set PROJECT_ID env var)")
    dataset_id: str = Field(default="", description="BigQuery dataset ID (or set DATASET_ID env var)")
    environment: str = "dev"
    cloud_provider: CloudProvider = CloudProvider.GCP
    region: str = "us-central1"


# ── Session context — the shared cache across all code-gen agents ──────────────

class SessionContext(BaseModel):
    """
    Carries static documents + plan + human notes between pipeline stages.

    The implementation_md and mapping_csv are large and do not change across
    agent calls.  They are sent as ContextBlock(cacheable=True) objects so
    Anthropic caches them server-side.  Each subsequent agent call reads the
    same prefix from cache instead of re-encoding those tokens.

    human_notes accumulates any corrections or additional context the human
    provides at checkpoints.  These are appended to every downstream agent's
    task prompt so the LLM considers them without re-reading the full docs.
    """
    request_id: str
    implementation_md: str
    mapping_csv: str
    project_id: str
    dataset_id: str
    environment: str
    cloud_provider: str
    plan: Optional["ExecutionPlan"] = None
    human_notes: list[str] = []

    def human_notes_block(self) -> str:
        if not self.human_notes:
            return ""
        lines = "\n".join(f"  - {n}" for n in self.human_notes)
        return (
            "\n\n## Additional Context from Human Review\n"
            "Incorporate the following corrections/notes into your output:\n"
            f"{lines}"
        )

    def add_note(self, note: str) -> None:
        if note and note.strip():
            self.human_notes.append(note.strip())


# ── Code Gen Pod — Stage outputs ───────────────────────────────────────────────

class ExecutionPlan(BaseModel):
    """Structured plan produced by the Planner — human-approved before code gen."""
    request_id: str
    sprint: str = ""
    project: str = ""
    summary: str = ""
    services: list[ServiceSpec] = []
    tables: list[TableSpec] = []
    audit_table: AuditTableSpec = Field(default_factory=AuditTableSpec)
    store_proc: StoreProcSpec = Field(default_factory=StoreProcSpec)
    artifacts_to_generate: list[ArtifactSpec] = []
    patterns: list[str] = []
    pii_columns: list[str] = []
    open_blockers: list[str] = []
    clarifying_questions: list[str] = []
    # ── NEW: precise capture of connections, logging, alerting ────────────────
    connection_details: list[ConnectionDetailSpec] = []   # every URL / path / JDBC string
    logging_mechanisms: list[LoggingSpec] = []            # Cloud Logging, BQ audit, etc.
    alerting_mechanisms: list[AlertingSpec] = []          # Cloud Monitoring, PagerDuty, etc.
    raw_plan: str = ""  # JSON string of full plan (or markdown fallback)


class GeneratedArtifact(BaseModel):
    file_name: str
    artifact_type: ArtifactType
    content: str
    description: str = ""
    target_path: str = ""
    is_alter: bool = False  # True when this artifact ALTER-ed an existing table/proc/dag


class ReviewFinding(BaseModel):
    severity: Severity
    check_name: str
    file_name: str
    description: str
    suggested_fix: str


class ReviewResult(BaseModel):
    dimension: str
    verdict: Verdict
    summary: str
    findings: list[ReviewFinding] = []


class CodeGenOutput(BaseModel):
    request_id: str
    plan: ExecutionPlan
    artifacts: list[GeneratedArtifact]
    review_results: list[ReviewResult]
    quality_score: float
    output_directory: str
    approved_for_deploy: bool = False
    git_branch: str | None = None
    manifest_files: list[ManifestFile] = []


# Resolve forward reference
SessionContext.model_rebuild()


# ── Code Gen Pod — API request / response models ───────────────────────────────

class RunStatus(str, Enum):
    PENDING    = "pending"
    PLANNING   = "planning"
    CHECKPOINT = "checkpoint"
    GENERATING = "generating"
    OPTIMIZING = "optimizing"
    REVIEWING  = "reviewing"
    COMMITTING = "committing"
    DONE       = "done"
    ABORTED    = "aborted"
    FAILED     = "failed"


class StartRunRequest(BaseModel):
    """POST /api/v1/runs — start a new pipeline run."""
    implementation_md: str = Field(..., description="Raw content of Implementation.md")
    mapping_csv: str = Field(..., description="Raw content of mapping.csv")
    project_id: str = Field(default="", description="GCP project ID (falls back to PROJECT_ID env var)")
    dataset_id: str = Field(default="", description="BigQuery dataset ID (falls back to DATASET_ID env var)")
    environment: str = "dev"
    cloud_provider: CloudProvider = CloudProvider.GCP
    region: str = "us-central1"


class OptimizeReviewRequest(BaseModel):
    """POST /api/v1/optimize-review — optimize and review existing artifacts."""
    artifacts: list[GeneratedArtifact] = Field(
        ...,
        description=(
            "Existing code artifacts to optimize and review. "
            "Each must have file_name, artifact_type (ddl/dml/sp/dag/pipeline/config/doc), and content."
        ),
    )
    project_id: str = ""
    dataset_id: str = ""
    environment: str = "dev"
    cloud_provider: CloudProvider = CloudProvider.GCP
    human_notes: list[str] = []


class CheckpointDecision(str, Enum):
    APPROVE = "approve"
    REVISE  = "revise"
    ABORT   = "abort"
    DEPLOY  = "deploy"
    SKIP    = "skip"


class CheckpointRequest(BaseModel):
    """POST /api/v1/runs/{request_id}/checkpoint — submit human decision."""
    decision: CheckpointDecision
    notes: str = ""


class RunSummary(BaseModel):
    """Lightweight status returned by GET /api/v1/runs/{request_id}."""
    request_id: str
    status: RunStatus
    checkpoint_number: Optional[int] = None
    checkpoint_prompt: Optional[str] = None
    plan_summary: Optional[str] = None
    artifacts: list[dict] = []
    quality_score: Optional[float] = None
    git_branch: Optional[str] = None
    error: Optional[str] = None
    output_directory: Optional[str] = None
    current_task: Optional[str] = None
    log_messages: list[str] = []


# ── Deploy Pod — models ────────────────────────────────────────────────────────

class DeployTarget(str, Enum):
    GCP = "gcp"
    AWS = "aws"
    SNOWFLAKE = "snowflake"


class DeployStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED  = "failed"
    SKIPPED = "skipped"


class DeployInput(BaseModel):
    """Handed from the Code Gen Pod after human approval at Checkpoint 3."""
    request_id: str
    artifacts_dir: str
    project_id: str = ""
    dataset_id: str = ""
    region: str = "us-central1"
    environment: str = ""
    dag_bucket: str = ""
    composer_environment: str = ""
    target: DeployTarget = DeployTarget.GCP

    source_db_type: str = ""
    source_db_host: str = ""
    source_db_port: int = 0
    source_db_name: str = ""
    source_db_user: str = ""
    # Password always read from env var DB_PASSWORD — never stored here


class ValidationStatus(str, Enum):
    PASS    = "pass"
    FAIL    = "fail"
    SKIPPED = "skipped"


class ValidationResult(BaseModel):
    check: str
    status: ValidationStatus
    message: str = ""
    details: dict = {}


class DeployStepResult(BaseModel):
    step: str
    status: DeployStatus
    message: str = ""
    details: dict = {}


class DeployOutput(BaseModel):
    request_id: str
    target: DeployTarget
    validation: list[ValidationResult] = []
    steps: list[DeployStepResult] = []
    overall_status: DeployStatus
