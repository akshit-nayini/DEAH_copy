import pytest
from sqlalchemy.orm import Session

from core.requirements_pod.config import Settings
from core.requirements_pod.database import repository
from core.requirements_pod.database.schemas.task import TaskOut
from core.utilities.llm.provider_base import BaseLLMProvider
from core.requirements_pod.agents.extraction import parse_file


@pytest.mark.asyncio
async def test_parse_file_returns_task_list(db: Session, mock_llm, mock_storage, test_settings: Settings):
    """parse_file should return a list of TaskOut objects from mock LLM fixture data."""
    content = b"Sample requirements document text for testing."
    storage_path = "testuser/2025-01-01/test-file-id_sample.txt"
    await mock_storage.write(storage_path, content)

    source_file = repository.create_source_file(
        db=db,
        filename="sample.txt",
        gcs_path=storage_path,
        uploaded_by="testuser",
        file_size=len(content),
        mime_type="text/plain",
    )

    tasks = await parse_file(
        file_id=source_file.id,
        db=db,
        llm=mock_llm,
        storage=mock_storage,
        settings=test_settings,
    )

    assert isinstance(tasks, list)
    assert len(tasks) == 3

    task_types = {t.task_type.value for t in tasks}
    assert "bug" in task_types
    assert "story" in task_types
    assert "task" in task_types

    for task in tasks:
        assert isinstance(task, TaskOut)
        assert task.task_id.startswith("SRC-")
        assert task.task_heading
        assert task.status.value == "extracted"
        assert task.source_file_id == source_file.id


@pytest.mark.asyncio
async def test_parse_file_updates_source_status(db: Session, mock_llm, mock_storage, test_settings: Settings):
    """parse_file should set source_file status to 'parsed' after success."""
    content = b"Another document."
    storage_path = "user/2025-01-01/abc_doc.txt"
    await mock_storage.write(storage_path, content)

    source_file = repository.create_source_file(
        db=db,
        filename="doc.txt",
        gcs_path=storage_path,
        uploaded_by="user",
        file_size=len(content),
        mime_type="text/plain",
    )
    assert source_file.status == "uploaded"

    await parse_file(
        file_id=source_file.id,
        db=db,
        llm=mock_llm,
        storage=mock_storage,
        settings=test_settings,
    )

    refreshed = repository.get_source_file(db, source_file.id)
    assert refreshed.status == "parsed"


class _DuplicatingLLM(BaseLLMProvider):
    """Always returns the same single task — triggers deduplication logic."""

    async def extract_tasks(self, text: str, system_prompt: str) -> list[dict]:
        return [
            {
                "task_heading": "Fix login bug",
                "description": "Detailed description.",
                "task_type": "bug",
                "location": "Page 1",
            }
        ]


@pytest.mark.asyncio
async def test_parse_file_deduplicates(db: Session, mock_storage, test_settings: Settings):
    """parse_file should deduplicate identical tasks returned across multiple chunks."""
    # Long enough to create multiple chunks (chunk_size=3000 words by default)
    content = (" ".join(["word"] * 10000)).encode("utf-8")
    storage_path = "user/2025-01-01/long.txt"
    await mock_storage.write(storage_path, content)

    source_file = repository.create_source_file(
        db=db,
        filename="long.txt",
        gcs_path=storage_path,
        uploaded_by="user",
        file_size=len(content),
        mime_type="text/plain",
    )

    tasks = await parse_file(
        file_id=source_file.id,
        db=db,
        llm=_DuplicatingLLM(),
        storage=mock_storage,
        settings=test_settings,
    )

    # Should have exactly 1 task despite multiple chunks all returning the same task
    assert len(tasks) == 1
    assert tasks[0].task_heading == "Fix login bug"
