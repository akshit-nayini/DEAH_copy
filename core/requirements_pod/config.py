import json
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Reads exclusively from OS environment variables — no config.env file.
    # On GCP VM, export: JIRA_API_KEY, JIRA_EMAIL, GCS_CREDENTIALS_PATH
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )

    # App
    APP_NAME: str = "TaskFlow AI Agent"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8001

    # Storage — GCS client config (bucket, project, credentials) lives in
    # core/utilities/storage/gcs_provider.py and reads from os.environ directly.
    STORAGE_PROVIDER: str = "gcs"
    GCS_PREFIX: str = "requirements-pod"
    LOCAL_STORAGE_PATH: str = "./local_storage"

    # LLM
    LLM_PROVIDER: str = "claude-sdk"
    ANTHROPIC_API_KEY: str = ""
    LLM_MODEL: str = "claude-sonnet-4-6"
    LLM_MAX_TOKENS: int = 8192
    LLM_CHUNK_SIZE: int = 3000
    LLM_CHUNK_OVERLAP: int = 200

    # Jira — JIRA_API_KEY and JIRA_EMAIL must be set via OS environment export.
    JIRA_BASE_URL: str = "https://prodapt-deah.atlassian.net"
    JIRA_EMAIL: str = ""
    JIRA_API_KEY: str = ""
    JIRA_PROJECT_KEY: str = "SCRUM"
    JIRA_ISSUE_TYPE_MAP: str = '{"bug":"Bug","story":"Story","task":"Task","subtask":"Sub-task"}'
    JIRA_START_DATE_FIELD: str = "customfield_10015"

    # CORS — comma-separated list of allowed origins; use * for open dev access
    CORS_ORIGINS: str = "*"

    # Misc
    PROJECT_CONTEXT_FILE: str = "./docs/project_context.md"
    MAX_UPLOAD_SIZE_MB: int = 50
    ALLOWED_EXTENSIONS: str = "pdf,docx,txt,md,vtt,srt"

    def get_cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    def get_jira_issue_type_map(self) -> dict:
        try:
            return json.loads(self.JIRA_ISSUE_TYPE_MAP)
        except (json.JSONDecodeError, TypeError):
            return {"bug": "Bug", "story": "Story", "task": "Task", "subtask": "Sub-task"}

    def get_allowed_extensions(self) -> list[str]:
        return [ext.strip().lower() for ext in self.ALLOWED_EXTENSIONS.split(",")]


def get_settings() -> Settings:
    return Settings()
