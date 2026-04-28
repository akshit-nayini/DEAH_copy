import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from core.requirements_pod.database import repository
from core.requirements_pod.database.schemas.task import TaskUpdate


def _create_test_task(db: Session, heading: str = "Test task", task_type: str = "task") -> str:
    task = repository.create_task(
        db=db,
        task_heading=heading,
        description="Test description",
        task_type=task_type,
        user_name="testuser",
        task_source="test_source.txt",
        source_file_id=None,
        location="Page 1",
    )
    return task.task_id


def test_list_tasks_empty(client: TestClient):
    resp = client.get("/api/v1/tasks")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_tasks_returns_created(client: TestClient, db: Session):
    _create_test_task(db, "First task")
    _create_test_task(db, "Second task")

    resp = client.get("/api/v1/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    headings = {t["task_heading"] for t in data}
    assert "First task" in headings
    assert "Second task" in headings


def test_get_task_found(client: TestClient, db: Session):
    task_id = _create_test_task(db, "Single task")
    resp = client.get(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == task_id
    assert data["task_heading"] == "Single task"


def test_get_task_not_found(client: TestClient):
    resp = client.get("/api/v1/tasks/SRC-999")
    assert resp.status_code == 404


def test_update_task(client: TestClient, db: Session):
    task_id = _create_test_task(db, "Original heading")
    payload = {"task_heading": "Updated heading", "task_type": "bug"}
    resp = client.patch(f"/api/v1/tasks/{task_id}", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_heading"] == "Updated heading"
    assert data["task_type"] == "bug"
    assert data["status"] == "modified"


def test_delete_task_soft(client: TestClient, db: Session):
    task_id = _create_test_task(db, "Task to delete")

    # Delete
    resp = client.delete(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    # Should not appear in default list
    resp_list = client.get("/api/v1/tasks")
    assert resp_list.status_code == 200
    task_ids = [t["task_id"] for t in resp_list.json()]
    assert task_id not in task_ids

    # Should appear when filtering by status=deleted
    resp_deleted = client.get("/api/v1/tasks?status=deleted")
    assert resp_deleted.status_code == 200
    task_ids_deleted = [t["task_id"] for t in resp_deleted.json()]
    assert task_id in task_ids_deleted


def test_export_tasks_json(client: TestClient, db: Session):
    task_id = _create_test_task(db, "Export me")
    resp = client.post("/api/v1/tasks/export", json={"task_ids": [task_id], "format": "json"})
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["task_id"] == task_id


def test_export_tasks_csv(client: TestClient, db: Session):
    task_id = _create_test_task(db, "CSV task")
    resp = client.post("/api/v1/tasks/export", json={"task_ids": [task_id], "format": "csv"})
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    text = resp.text
    assert "task_id" in text
    assert task_id in text


def test_export_tasks_md(client: TestClient, db: Session):
    task_id = _create_test_task(db, "Markdown task")
    resp = client.post("/api/v1/tasks/export", json={"task_ids": [task_id], "format": "md"})
    assert resp.status_code == 200
    assert task_id in resp.text


def test_filter_tasks_by_user(client: TestClient, db: Session):
    repository.create_task(
        db=db,
        task_heading="Alice task",
        description="desc",
        task_type="task",
        user_name="alice",
        task_source=None,
        source_file_id=None,
        location=None,
    )
    repository.create_task(
        db=db,
        task_heading="Bob task",
        description="desc",
        task_type="task",
        user_name="bob",
        task_source=None,
        source_file_id=None,
        location=None,
    )

    resp = client.get("/api/v1/tasks?user_name=alice")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["user_name"] == "alice"
