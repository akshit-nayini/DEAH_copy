import json
from abc import ABC, abstractmethod


class BaseLLMProvider(ABC):
    @abstractmethod
    async def extract_tasks(self, text: str, system_prompt: str) -> list[dict]:
        """Extract tasks from text using the LLM.

        Args:
            text: The text chunk to process.
            system_prompt: The system-level instructions for the LLM.

        Returns:
            A list of task dictionaries parsed from the LLM response.
        """
        raise NotImplementedError

    async def call_raw(self, system: str, user: str) -> str:
        """Call the LLM and return the raw text response.

        Default implementation serialises extract_tasks() output back to JSON so
        that MockLLMProvider and legacy test subclasses work without changes.
        Override in real providers for direct API control.
        """
        result = await self.extract_tasks(user, system)
        return json.dumps(result)
