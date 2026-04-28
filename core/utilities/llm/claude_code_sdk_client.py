"""
Claude Agent SDK LLM client.

Routes completion requests through claude_agent_sdk.query().
No API key or authentication setup required.

Requirements
────────────
    pip install claude-agent-sdk

Caching
───────
The Agent SDK does not expose Anthropic's block-level cache_control API.
complete_with_context() concatenates all ContextBlock texts into a single
prompt — same fallback behaviour as OpenAILLMClient and GeminiLLMClient.
"""
from __future__ import annotations

import logging
from typing import Optional

from core.utilities.llm.base import BaseLLMClient, ContextBlock, LLMMessage, LLMResponse

logger = logging.getLogger("core.utilities.llm.claude_agent_sdk")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class ClaudeCodeSDKClient(BaseLLMClient):
    """
    LLM client backed by the Claude Agent SDK.

    Uses claude_agent_sdk.query() — no API key or authentication required.

    Usage:
        from core.utilities.llm import create_llm_client
        llm = create_llm_client("claude-code-sdk")
        response = llm.complete("Generate a Python function that sorts a list")
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        try:
            from claude_agent_sdk import query as _query
            import anyio as _anyio
            self._query = _query
            self._anyio = _anyio
        except ImportError:
            raise ImportError(
                "Claude Agent SDK not installed. Run: pip install claude-agent-sdk"
            )
        self._model = model
        logger.info("ClaudeCodeSDKClient initialised — model: %s", self._model)

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _query_async(self, prompt: str) -> LLMResponse:
        """Collect the result from a single SDK query."""
        result_text = ""
        async for message in self._query(prompt=prompt):
            if hasattr(message, "result"):
                result_text = message.result
                break

        return LLMResponse(
            content=result_text,
            model=self._model,
        )

    def _run(self, prompt: str) -> LLMResponse:
        """Bridge async query to sync using anyio.

        Temporarily clears ANTHROPIC_API_KEY from the environment so the
        claude CLI uses its OAuth session instead of a potentially stale key
        that the parent process may have injected.
        """
        import os
        stale_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            async def _wrapper():
                return await self._query_async(prompt)
            return self._anyio.run(_wrapper)
        finally:
            if stale_key:
                os.environ["ANTHROPIC_API_KEY"] = stale_key

    # ── BaseLLMClient interface ────────────────────────────────────────────────

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Single-turn completion via the Claude Agent SDK."""
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        return self._run(full_prompt)

    def chat(
        self,
        messages: list[LLMMessage],
        system: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """
        Multi-turn chat via the Claude Agent SDK.

        Prior turns are embedded as labelled sections in the prompt since
        query() operates as a single-turn call.
        """
        parts: list[str] = []
        if system:
            parts.append(system)
        for m in messages:
            label = "User" if m.role == "user" else "Assistant"
            parts.append(f"[{label}]: {m.content}")
        return self._run("\n\n".join(parts))

    def complete_with_context(
        self,
        context_blocks: list[ContextBlock],
        task_prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """
        Context-rich completion via the Claude Agent SDK.

        ContextBlock.cacheable flags are ignored — the SDK does not expose
        Anthropic's block-level cache_control API.  All blocks are
        concatenated before the task prompt.
        """
        parts: list[str] = []
        if system:
            parts.append(system)
        for block in context_blocks:
            header = f"# {block.label}\n" if block.label else ""
            parts.append(f"{header}{block.text}")
        parts.append(task_prompt)
        return self._run("\n\n".join(parts))
