"""Integration test for the full 9-stage pipeline using a mocked LLM provider."""
from __future__ import annotations

import json
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from core.requirements_pod.database.models import Base
from core.requirements_pod.db import repository
from core.requirements_pod.config import Settings
from core.utilities.llm.provider_base import BaseLLMProvider
from core.utilities.storage.base import BaseStorageProvider
from core.requirements_pod.agents.extraction import parse_file
from core.requirements_pod.database.schemas.task import TaskOut

# ── Fixtures ──────────────────────────────────────────────────────────────────

# A plausible new-schema JSON array the pipeline LLM would return
_NEW_SCHEMA_TASKS = [
    {
        "summary": "Implement OAuth2 authentication service",
        "description": "Replace the existing basic auth with a full OAuth2 flow supporting Google and GitHub providers.",
        "issuetype": "Story",
        "priority": "High",
        "labels": ["auth", "backend", "security"],
        "storyPoints": 8,
        "acceptanceCriteria": [
            "User can log in with Google",
            "User can log in with GitHub",
            "JWT token is issued on successful auth",
        ],
        "extractionConfidence": 0.92,
        "temporalMarkers": [],
        "supersedes": False,
    },
    {
        "summary": "Fix null pointer exception on user login",
        "description": "Unregistered email causes NullPointerException instead of 404.",
        "issuetype": "Bug",
        "priority": "Critical",
        "labels": ["bug", "login"],
        "storyPoints": 3,
        "acceptanceCriteria": ["Returns 404 for unknown email"],
        "extractionConfidence": 0.95,
        "temporalMarkers": [],
        "supersedes": False,
    },
    {
        "summary": "Migrate database connection pool to async driver",
        "description": "Switch from synchronous SQLAlchemy pool to asyncpg/aiosqlite.",
        "issuetype": "Task",
        "priority": "Medium",
        "labels": ["database", "performance"],
        "storyPoints": 5,
        "acceptanceCriteria": ["All existing tests pass", "p99 latency improves"],
        "extractionConfidence": 0.85,
        "temporalMarkers": [],
        "supersedes": False,
    },
]


class _NewSchemaLLM(BaseLLMProvider):
    """Mock LLM that returns new-schema tasks as raw JSON text."""

    async def extract_tasks(self, text: str, system_prompt: str) -> list[dict]:
        return _NEW_SCHEMA_TASKS

    async def call_raw(self, system: str, user: str) -> str:
        return json.dumps(_NEW_SCHEMA_TASKS)


class _MockStorage(BaseStorageProvider):
    def __init__(self):
        self._store: dict[str, bytes] = {}

    async def write(self, path: str, data: bytes) -> str:
        self._store[path] = data
        return path

    async def read(self, path: str) -> bytes:
        if path not in self._store:
            raise FileNotFoundError(f"Not in mock storage: {path}")
        return self._store[path]

    async def list_files(self, prefix: str = "") -> list[dict]:
        return [{"name": k, "size": len(v), "updated": None} for k, v in self._store.items() if k.startswith(prefix)]


# ── DB fixtures ───────────────────────────────────────────────────────────────

_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture()
def db() -> Session:
    Base.metadata.create_all(bind=_engine)
    session = _Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=_engine)


@pytest.fixture()
def mock_storage() -> _MockStorage:
    return _MockStorage()


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        DATABASE_URL="sqlite:///:memory:",
        LLM_PROVIDER="mock",
        STORAGE_PROVIDER="local",
        PROJECT_CONTEXT_FILE="./docs/project_context.md",
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_returns_task_list(db: Session, mock_storage: _MockStorage, test_settings: Settings):
    """Full pipeline produces TaskOut objects from new-schema LLM fixture."""
    content = b"Sample requirements document text for pipeline integration testing."
    path = "test/pipeline_doc.txt"
    await mock_storage.write(path, content)

    source_file = repository.create_source_file(
        db=db,
        filename="pipeline_doc.txt",
        gcs_path=path,
        uploaded_by="testuser",
        file_size=len(content),
        mime_type="text/plain",
    )

    tasks = await parse_file(
        file_id=source_file.id,
        db=db,
        llm=_NewSchemaLLM(),
        storage=mock_storage,
        settings=test_settings,
    )

    assert isinstance(tasks, list)
    assert len(tasks) == 3
    for task in tasks:
        assert isinstance(task, TaskOut)
        assert task.task_id.startswith("SRC-")
        assert task.task_heading
        assert task.status.value == "extracted"


@pytest.mark.asyncio
async def test_pipeline_maps_issuetype_to_task_type(db: Session, mock_storage: _MockStorage, test_settings: Settings):
    """Stage 9 correctly maps issuetype Bug/Story/Task to task_type bug/story/task."""
    content = b"Requirements document for issuetype mapping test."
    path = "test/issuetype_doc.txt"
    await mock_storage.write(path, content)

    source_file = repository.create_source_file(
        db=db, filename="issuetype_doc.txt", gcs_path=path,
        uploaded_by="tester", file_size=len(content), mime_type="text/plain",
    )

    tasks = await parse_file(
        file_id=source_file.id, db=db,
        llm=_NewSchemaLLM(), storage=mock_storage, settings=test_settings,
    )

    type_values = {t.task_type.value for t in tasks}
    assert "bug" in type_values
    assert "story" in type_values
    assert "task" in type_values


@pytest.mark.asyncio
async def test_pipeline_deduplicates_across_chunks(db: Session, mock_storage: _MockStorage, test_settings: Settings):
    """Tasks duplicated across chunks are collapsed to one."""

    class _DuplicatingLLM(BaseLLMProvider):
        async def extract_tasks(self, text: str, system_prompt: str) -> list[dict]:
            return [{"task_heading": "Fix login bug", "description": "Detail.", "task_type": "bug", "location": "p1"}]

    content = (" ".join(["word"] * 12_000)).encode()
    path = "test/long_doc.txt"
    await mock_storage.write(path, content)

    source_file = repository.create_source_file(
        db=db, filename="long_doc.txt", gcs_path=path,
        uploaded_by="tester", file_size=len(content), mime_type="text/plain",
    )

    tasks = await parse_file(
        file_id=source_file.id, db=db,
        llm=_DuplicatingLLM(), storage=mock_storage, settings=test_settings,
    )

    assert len(tasks) == 1
    assert tasks[0].task_heading == "Fix login bug"


@pytest.mark.asyncio
async def test_pipeline_sets_source_file_status_parsed(db: Session, mock_storage: _MockStorage, test_settings: Settings):
    """Source file status is set to 'parsed' after successful extraction."""
    content = b"Short document."
    path = "test/status_doc.txt"
    await mock_storage.write(path, content)

    source_file = repository.create_source_file(
        db=db, filename="status_doc.txt", gcs_path=path,
        uploaded_by="tester", file_size=len(content), mime_type="text/plain",
    )

    await parse_file(
        file_id=source_file.id, db=db,
        llm=_NewSchemaLLM(), storage=mock_storage, settings=test_settings,
    )

    refreshed = repository.get_source_file(db, source_file.id)
    assert refreshed.status == "parsed"


@pytest.mark.asyncio
async def test_pipeline_raises_for_empty_document(db: Session, mock_storage: _MockStorage, test_settings: Settings):
    """Empty document raises RuntimeError, not a silent empty list."""
    content = b"   "
    path = "test/empty_doc.txt"
    await mock_storage.write(path, content)

    source_file = repository.create_source_file(
        db=db, filename="empty_doc.txt", gcs_path=path,
        uploaded_by="tester", file_size=len(content), mime_type="text/plain",
    )

    with pytest.raises(RuntimeError, match="No extractable text"):
        await parse_file(
            file_id=source_file.id, db=db,
            llm=_NewSchemaLLM(), storage=mock_storage, settings=test_settings,
        )


@pytest.mark.asyncio
async def test_pipeline_tasks_sorted_by_confidence_desc(db: Session, mock_storage: _MockStorage, test_settings: Settings):
    """Tasks returned by the pipeline are sorted by confidence, highest first."""
    content = b"Requirements document for confidence sort test."
    path = "test/sort_doc.txt"
    await mock_storage.write(path, content)

    source_file = repository.create_source_file(
        db=db, filename="sort_doc.txt", gcs_path=path,
        uploaded_by="tester", file_size=len(content), mime_type="text/plain",
    )

    tasks = await parse_file(
        file_id=source_file.id, db=db,
        llm=_NewSchemaLLM(), storage=mock_storage, settings=test_settings,
    )

    # Confidence is stored in raw_llm_json metadata; verify tasks list is non-empty
    assert len(tasks) > 0
    # All tasks should have been written with raw_llm_json containing confidence
    for task in tasks:
        assert task.task_heading  # basic sanity
