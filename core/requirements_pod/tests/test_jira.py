import pytest
import httpx
import respx
from datetime import datetime

from core.requirements_pod.config import Settings
from core.requirements_pod.database.schemas.task import TaskOut, TaskType, TaskStatus
from core.utilities.scrum_tools.jira import JiraService


def _make_task(
    task_type: str = "story",
    heading: str = "Implement login page",
    description: str = "Full description of the feature.",
) -> TaskOut:
    return TaskOut(
        id="test-uuid-1234",
        task_id="SRC-001",
        task_heading=heading,
        description=description,
        task_type=TaskType(task_type),
        user_name="testuser",
        location="Page 5",
        task_source="spec.txt",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        updated_at=datetime(2025, 1, 1, 12, 0, 0),
        status=TaskStatus.extracted,
        jira_id=None,
        jira_url=None,
    )


def _make_settings() -> Settings:
    return Settings(
        JIRA_BASE_URL="https://testorg.atlassian.net",
        JIRA_EMAIL="test@example.com",
        JIRA_API_TOKEN="test-token",
        JIRA_PROJECT_KEY="TEST",
        JIRA_ISSUE_TYPE_MAP='{"bug":"Bug","story":"Story","task":"Task","subtask":"Sub-task"}',
    )


@pytest.mark.asyncio
@respx.mock
async def test_push_task_success():
    """JiraService.push_task should POST to Jira and return jira_id and jira_url."""
    settings = _make_settings()
    task = _make_task(task_type="story")

    route = respx.post(f"{settings.JIRA_BASE_URL}/rest/api/3/issue").mock(
        return_value=httpx.Response(
            201,
            json={"id": "10001", "key": "TEST-42", "self": f"{settings.JIRA_BASE_URL}/rest/api/3/issue/10001"},
        )
    )

    service = JiraService()
    result = await service.push_task(task, settings)

    assert route.called
    assert result["jira_id"] == "TEST-42"
    assert result["jira_url"] == f"{settings.JIRA_BASE_URL}/browse/TEST-42"


@pytest.mark.asyncio
@respx.mock
async def test_push_task_maps_issue_type():
    """JiraService.push_task should map task_type to the correct Jira issue type name."""
    settings = _make_settings()
    task = _make_task(task_type="bug", heading="Fix crash on startup")

    captured_request = {}

    def capture(request: httpx.Request):
        import json
        captured_request["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "10002", "key": "TEST-43"})

    respx.post(f"{settings.JIRA_BASE_URL}/rest/api/3/issue").mock(side_effect=capture)

    service = JiraService()
    await service.push_task(task, settings)

    assert captured_request["body"]["fields"]["issuetype"]["name"] == "Bug"
    assert captured_request["body"]["fields"]["summary"] == "Fix crash on startup"
    assert captured_request["body"]["fields"]["project"]["key"] == "TEST"


@pytest.mark.asyncio
@respx.mock
async def test_push_task_raises_on_error():
    """JiraService.push_task should raise RuntimeError when Jira returns an error status."""
    settings = _make_settings()
    task = _make_task()

    respx.post(f"{settings.JIRA_BASE_URL}/rest/api/3/issue").mock(
        return_value=httpx.Response(403, json={"errorMessages": ["Forbidden"]})
    )

    service = JiraService()
    with pytest.raises(RuntimeError, match="403"):
        await service.push_task(task, settings)


@pytest.mark.asyncio
@respx.mock
async def test_push_task_adf_description_format():
    """JiraService.push_task should send description in Atlassian Document Format."""
    settings = _make_settings()
    task = _make_task(description="A detailed description of this story.")

    captured_request = {}

    def capture(request: httpx.Request):
        import json
        captured_request["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "10003", "key": "TEST-44"})

    respx.post(f"{settings.JIRA_BASE_URL}/rest/api/3/issue").mock(side_effect=capture)

    service = JiraService()
    await service.push_task(task, settings)

    desc = captured_request["body"]["fields"]["description"]
    assert desc["version"] == 1
    assert desc["type"] == "doc"
    assert desc["content"][0]["type"] == "paragraph"
    assert desc["content"][0]["content"][0]["text"] == "A detailed description of this story."
