import json
import os
from core.common.llm.base import BaseLLMProvider

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "tests", "fixtures", "mock_llm_response.json"
)


class MockLLMProvider(BaseLLMProvider):
    """Returns fixture data without making any API call. Used in development and testing."""

    async def extract_tasks(self, text: str, system_prompt: str) -> list[dict]:
        fixture_path = os.path.abspath(FIXTURE_PATH)
        with open(fixture_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data
