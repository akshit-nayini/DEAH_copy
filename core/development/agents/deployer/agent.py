"""Deployer agent.

Applies code-gen artifacts to GCP (BigQuery DDL, Composer DAGs, Dataflow template).
Currently GCP-only. To target AWS/Snowflake:
  1. Implement BaseDataWarehouse / BaseOrchestrator for the new cloud
  2. Add a branch in DeployerAgent.deploy() based on request.target
  3. Pass --target aws or --target snowflake — nothing else changes
"""
from __future__ import annotations
import logging
from pathlib import Path

from api.models import (
    DeployInput, DeployOutput, DeployStatus, DeployStepResult, ValidationStatus,
)

logger = logging.getLogger("development.deployer")


class DeployerAgent:
    def deploy(self, request: DeployInput) -> DeployOutput:
        """
        Run pre-deploy validation then all deploy steps.

        Flow:
          1. PreDeployValidator runs ALL connectivity checks (BQ, GCS, Composer,
             Dataflow API, Secret Manager, source DB)
          2. If ANY check returns FAIL → deploy is aborted immediately; no
             artifacts are applied to GCP
          3. Only when all checks PASS (or SKIPPED) do the deploy steps run
        """
        from agents.validator.agent import PreDeployValidator

        logger.info("Deploy: running pre-deploy connectivity checks...")
        validation = PreDeployValidator().validate(request)

        failed_checks = [v for v in validation if v.status == ValidationStatus.FAIL]
        if failed_checks:
            logger.error(
                "Deploy ABORTED — %d connectivity check(s) failed:", len(failed_checks)
            )
            for v in failed_checks:
                logger.error("  [FAIL] %s: %s", v.check, v.message)
            return DeployOutput(
                request_id=request.request_id,
                target=request.target,
                validation=validation,
                steps=[],
                overall_status=DeployStatus.FAILED,
            )

        passed = sum(1 for v in validation if v.status == ValidationStatus.PASS)
        skipped = sum(1 for v in validation if v.status == ValidationStatus.SKIPPED)
        logger.info(
            "Deploy: pre-deploy validation complete — %d passed, %d skipped. Proceeding.",
            passed, skipped,
        )

        steps: list[DeployStepResult] = []
        artifacts_dir = Path(request.artifacts_dir)

        if request.target.value == "gcp":
            steps.append(self._create_audit_table(request))
            steps.append(self._apply_bq_ddl(artifacts_dir, request))
            steps.append(self._apply_sp(artifacts_dir, request))
            steps.append(self._upload_dags(artifacts_dir, request))
            steps.append(self._register_dataflow_template(artifacts_dir, request))
        else:
            steps.append(DeployStepResult(
                step="deploy",
                status=DeployStatus.SKIPPED,
                message=f"Target '{request.target.value}' not yet implemented. Add a cloud client.",
            ))

        succeeded = all(
            s.status in (DeployStatus.SUCCESS, DeployStatus.SKIPPED) for s in steps
        )
        return DeployOutput(
            request_id=request.request_id,
            target=request.target,
            validation=validation,
            steps=steps,
            overall_status=DeployStatus.SUCCESS if succeeded else DeployStatus.FAILED,
        )

    def _create_audit_table(self, req: DeployInput) -> DeployStepResult:
        try:
            from common.cloud.gcp.bigquery_client import BigQueryClient
            from common.audit.ddl import generate_audit_ddl
            bq = BigQueryClient(project_id=req.project_id, location=req.region)
            ddl = generate_audit_ddl(req.project_id, req.dataset_id)
            bq.execute_ddl(ddl)
            logger.info("Audit table: pipeline_audit_log created/verified in %s.%s",
                        req.project_id, req.dataset_id)
            return DeployStepResult(
                step="create_audit_table",
                status=DeployStatus.SUCCESS,
                message=f"pipeline_audit_log ready in {req.project_id}.{req.dataset_id}",
            )
        except Exception as exc:
            logger.error("Audit table creation failed: %s", exc)
            return DeployStepResult(
                step="create_audit_table",
                status=DeployStatus.FAILED,
                message=str(exc),
            )

    def _apply_bq_ddl(self, artifacts_dir: Path, req: DeployInput) -> DeployStepResult:
        ddl_dir = artifacts_dir / "ddl"
        if not ddl_dir.exists():
            return DeployStepResult(
                step="apply_bq_ddl",
                status=DeployStatus.SKIPPED,
                message="No ddl/ directory in artifacts",
            )
        try:
            from common.cloud.gcp.bigquery_client import BigQueryClient
            bq = BigQueryClient(project_id=req.project_id, location=req.region)
            applied = []
            for sql_file in sorted(ddl_dir.glob("*.sql")):
                sql = sql_file.read_text(encoding="utf-8")
                bq.execute_ddl(sql)
                applied.append(sql_file.name)
                logger.info("DDL applied: %s", sql_file.name)
            return DeployStepResult(
                step="apply_bq_ddl",
                status=DeployStatus.SUCCESS,
                message=f"Applied {len(applied)} DDL file(s)",
                details={"files": applied},
            )
        except Exception as exc:
            logger.error("DDL apply failed: %s", exc)
            return DeployStepResult(
                step="apply_bq_ddl",
                status=DeployStatus.FAILED,
                message=str(exc),
            )

    def _apply_sp(self, artifacts_dir: Path, req: DeployInput) -> DeployStepResult:
        sp_dir = artifacts_dir / "sp"
        if not sp_dir.exists():
            return DeployStepResult(
                step="apply_sp",
                status=DeployStatus.SKIPPED,
                message="No sp/ directory in artifacts",
            )
        try:
            from common.cloud.gcp.bigquery_client import BigQueryClient
            bq = BigQueryClient(project_id=req.project_id, location=req.region)
            applied = []
            for sql_file in sorted(sp_dir.glob("*.sql")):
                sql = sql_file.read_text(encoding="utf-8")
                bq.execute_ddl(sql)
                applied.append(sql_file.name)
                logger.info("SP applied: %s", sql_file.name)
            return DeployStepResult(
                step="apply_sp",
                status=DeployStatus.SUCCESS,
                message=f"Applied {len(applied)} stored procedure(s)",
                details={"files": applied},
            )
        except Exception as exc:
            logger.error("SP apply failed: %s", exc)
            return DeployStepResult(
                step="apply_sp",
                status=DeployStatus.FAILED,
                message=str(exc),
            )

    def _upload_dags(self, artifacts_dir: Path, req: DeployInput) -> DeployStepResult:
        dag_dir = artifacts_dir / "dag"
        if not dag_dir.exists():
            return DeployStepResult(
                step="upload_dags",
                status=DeployStatus.SKIPPED,
                message="No dag/ directory in artifacts",
            )
        try:
            from common.cloud.gcp.composer_client import ComposerClient
            composer = ComposerClient(
                project_id=req.project_id,
                region=req.region,
                environment_name=req.composer_environment,
                dag_bucket=req.dag_bucket,
            )
            uploaded = []
            for dag_file in dag_dir.glob("*.py"):
                blob = composer.deploy_dag(str(dag_file), req.dag_bucket)
                uploaded.append(blob)
                logger.info("DAG uploaded: %s → %s", dag_file.name, blob)
            return DeployStepResult(
                step="upload_dags",
                status=DeployStatus.SUCCESS,
                message=f"Uploaded {len(uploaded)} DAG file(s)",
                details={"blobs": uploaded},
            )
        except Exception as exc:
            logger.error("DAG upload failed: %s", exc)
            return DeployStepResult(
                step="upload_dags",
                status=DeployStatus.FAILED,
                message=str(exc),
            )

    def _register_dataflow_template(self, artifacts_dir: Path, req: DeployInput) -> DeployStepResult:
        pipeline_dir = artifacts_dir / "pipeline"
        if not pipeline_dir.exists():
            return DeployStepResult(
                step="register_dataflow_template",
                status=DeployStatus.SKIPPED,
                message="No pipeline/ directory — Flex Template registration skipped (manual step required)",
            )
        return DeployStepResult(
            step="register_dataflow_template",
            status=DeployStatus.SUCCESS,
            message="Flex Template spec found — registration: see RUNBOOK.md for manual steps",
        )
