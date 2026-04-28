import io
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from core.requirements_pod.database import repository


def test_upload_text_file(client: TestClient):
    content = b"This is a plain text requirements document.\nIt has several lines."
    resp = client.post(
        "/api/v1/files/upload",
        files={"file": ("requirements.txt", io.BytesIO(content), "text/plain")},
        data={"user_name": "testuser"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["filename"] == "requirements.txt"
    assert data["status"] == "uploaded"
    assert data["file_size"] == len(content)
    assert data["mime_type"] == "text/plain"
    assert "id" in data


def test_upload_disallowed_extension(client: TestClient):
    content = b"some binary data"
    resp = client.post(
        "/api/v1/files/upload",
        files={"file": ("malware.exe", io.BytesIO(content), "application/octet-stream")},
        data={"user_name": "testuser"},
    )
    assert resp.status_code == 422


def test_upload_and_get_status(client: TestClient, db: Session):
    content = b"Requirements content here."
    resp = client.post(
        "/api/v1/files/upload",
        files={"file": ("spec.txt", io.BytesIO(content), "text/plain")},
        data={"user_name": "alice"},
    )
    assert resp.status_code == 201
    file_id = resp.json()["id"]

    status_resp = client.get(f"/api/v1/files/{file_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["id"] == file_id
    assert status_resp.json()["status"] == "uploaded"


def test_parse_file_endpoint(client: TestClient, db: Session, mock_storage):
    content = b"Extract tasks from this document."
    resp = client.post(
        "/api/v1/files/upload",
        files={"file": ("tasks_doc.txt", io.BytesIO(content), "text/plain")},
        data={"user_name": "parseuser"},
    )
    assert resp.status_code == 201
    file_id = resp.json()["id"]

    # The mock storage in the test client may not have the file because the
    # upload endpoint uses the injected mock_storage via dependency override.
    # Manually write to mock_storage to simulate it.
    file_record = repository.get_source_file(db, file_id)
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        mock_storage.write(file_record.gcs_path, content)
    )

    parse_resp = client.post(f"/api/v1/files/{file_id}/parse")
    assert parse_resp.status_code == 200
    tasks = parse_resp.json()
    assert isinstance(tasks, list)
    assert len(tasks) == 3  # from mock fixture
    for task in tasks:
        assert task["status"] == "extracted"
        assert task["task_id"].startswith("SRC-")


def test_get_file_status_not_found(client: TestClient):
    resp = client.get("/api/v1/files/nonexistent-id/status")
    assert resp.status_code == 404
