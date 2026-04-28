import json
import logging
import anthropic
from core.common.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)


class ClaudeProvider(BaseLLMProvider):
    """Uses the Anthropic SDK to call the Claude API for task extraction."""

    def __init__(self, api_key: str, model: str, max_tokens: int):
        self._api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def call_raw(self, system: str, user: str) -> str:
        """Make a direct Anthropic API call and return the raw response text."""
        message = await self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return message.content[0].text.strip()

    async def extract_tasks(self, text: str, system_prompt: str) -> list[dict]:
        user_message = (
            "Extract all tasks, requirements, action items, bugs, and user stories from the following text.\n"
            "Return ONLY a valid JSON array with NO markdown fences. Each item must have:\n"
            '- task_heading: string (short title)\n'
            '- description: string (full detail)\n'
            '- task_type: one of "bug", "story", "task", "subtask"\n'
            "- location: string (page number, section, or timestamp if available, else null)\n\n"
            f"Text:\n{text}"
        )

        message = await self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = message.content[0].text.strip()

        # Strip any accidental markdown fences
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            raw_text = "\n".join(lines).strip()

        try:
            result = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.error("Claude response was not valid JSON: %s", raw_text[:500])
            raise ValueError(f"Claude returned invalid JSON: {exc}") from exc

        if not isinstance(result, list):
            raise ValueError(f"Expected a JSON array from Claude, got: {type(result)}")

        return result
