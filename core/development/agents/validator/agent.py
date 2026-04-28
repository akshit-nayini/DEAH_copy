"""Pre-deploy validator agent.

Runs connectivity and service availability checks before any artifacts
are applied to GCP.  All checks run unconditionally — the deployer
reads the full result list and aborts if ANY check is FAIL.
"""
from __future__ import annotations
import logging

from api.models import DeployInput, ValidationResult, ValidationStatus

logger = logging.getLogger("development.validator")


class PreDeployValidator:
    def validate(self, request: DeployInput) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        results.append(self._check_bigquery(request))
        results.append(self._check_gcs_dag_bucket(request))
        results.append(self._check_composer_env(request))
        results.append(self._check_dataflow_api(request))
        results.append(self._check_secret_manager(request))
        results.append(self._check_source_db(request))
        return results

    def _check_bigquery(self, req: DeployInput) -> ValidationResult:
        try:
            from common.cloud.gcp.bigquery_client import BigQueryClient
            bq = BigQueryClient(project_id=req.project_id, location=req.region)
            bq.test_connection()
            return ValidationResult(
                check="bigquery",
                status=ValidationStatus.PASS,
                message=f"BigQuery accessible: {req.project_id}.{req.dataset_id}",
            )
        except Exception as exc:
            logger.error("BigQuery check failed: %s", exc)
            return ValidationResult(
                check="bigquery",
                status=ValidationStatus.FAIL,
                message=str(exc),
            )

    def _check_gcs_dag_bucket(self, req: DeployInput) -> ValidationResult:
        if not req.dag_bucket:
            return ValidationResult(
                check="gcs_dag_bucket",
                status=ValidationStatus.SKIPPED,
                message="dag_bucket not set — DAG upload step will be skipped",
            )
        try:
            from common.cloud.gcp.storage_client import GCSStorageClient
            gcs = GCSStorageClient(project_id=req.project_id)
            gcs.test_bucket_access(req.dag_bucket)
            return ValidationResult(
                check="gcs_dag_bucket",
                status=ValidationStatus.PASS,
                message=f"GCS bucket accessible: gs://{req.dag_bucket}",
            )
        except Exception as exc:
            logger.error("GCS bucket check failed: %s", exc)
            return ValidationResult(
                check="gcs_dag_bucket",
                status=ValidationStatus.FAIL,
                message=str(exc),
            )

    def _check_composer_env(self, req: DeployInput) -> ValidationResult:
        if not req.composer_environment:
            return ValidationResult(
                check="composer_env",
                status=ValidationStatus.SKIPPED,
                message="composer_environment not set — DAG deploy step will be skipped",
            )
        try:
            from common.cloud.gcp.composer_client import ComposerClient
            composer = ComposerClient(
                project_id=req.project_id,
                region=req.region,
                environment_name=req.composer_environment,
                dag_bucket=req.dag_bucket,
            )
            composer.test_connection()
            return ValidationResult(
                check="composer_env",
                status=ValidationStatus.PASS,
                message=f"Composer environment accessible: {req.composer_environment}",
            )
        except Exception as exc:
            logger.error("Composer check failed: %s", exc)
            return ValidationResult(
                check="composer_env",
                status=ValidationStatus.FAIL,
                message=str(exc),
            )

    def _check_dataflow_api(self, req: DeployInput) -> ValidationResult:
        try:
            import subprocess
            result = subprocess.run(
                ["gcloud", "services", "list", "--enabled",
                 f"--project={req.project_id}", "--filter=dataflow.googleapis.com"],
                capture_output=True, text=True, timeout=15,
            )
            if "dataflow" in result.stdout.lower():
                return ValidationResult(
                    check="dataflow_api",
                    status=ValidationStatus.PASS,
                    message="Dataflow API is enabled",
                )
            return ValidationResult(
                check="dataflow_api",
                status=ValidationStatus.SKIPPED,
                message="Dataflow API not detected — Flex Template step will be skipped",
            )
        except Exception as exc:
            logger.warning("Dataflow API check skipped: %s", exc)
            return ValidationResult(
                check="dataflow_api",
                status=ValidationStatus.SKIPPED,
                message=f"Could not verify Dataflow API: {exc}",
            )

    def _check_secret_manager(self, req: DeployInput) -> ValidationResult:
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            parent = f"projects/{req.project_id}"
            list(client.list_secrets(request={"parent": parent, "page_size": 1}))
            return ValidationResult(
                check="secret_manager",
                status=ValidationStatus.PASS,
                message="Secret Manager API accessible",
            )
        except Exception as exc:
            logger.warning("Secret Manager check failed: %s", exc)
            return ValidationResult(
                check="secret_manager",
                status=ValidationStatus.SKIPPED,
                message=f"Secret Manager not verified (optional): {exc}",
            )

    def _check_source_db(self, req: DeployInput) -> ValidationResult:
        if not req.source_db_type or not req.source_db_host:
            return ValidationResult(
                check="source_db",
                status=ValidationStatus.SKIPPED,
                message="source_db_type / source_db_host not set — source DB check skipped",
            )
        import os
        password = os.environ.get("DB_PASSWORD", "")
        if not password:
            return ValidationResult(
                check="source_db",
                status=ValidationStatus.SKIPPED,
                message="DB_PASSWORD env var not set — source DB connectivity check skipped",
            )
        try:
            import socket
            sock = socket.create_connection(
                (req.source_db_host, req.source_db_port or 3306), timeout=5
            )
            sock.close()
            return ValidationResult(
                check="source_db",
                status=ValidationStatus.PASS,
                message=f"TCP reachable: {req.source_db_host}:{req.source_db_port}",
            )
        except Exception as exc:
            logger.error("Source DB TCP check failed: %s", exc)
            return ValidationResult(
                check="source_db",
                status=ValidationStatus.FAIL,
                message=str(exc),
            )
