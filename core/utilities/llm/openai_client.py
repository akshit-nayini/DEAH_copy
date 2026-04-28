"""
OpenAI (GPT) LLM client — FUTURE PROVIDER BLOCK.

Status: implemented and ready; not used in production yet.
        Switch via: create_llm_client("openai", api_key="sk-...")

Prompt caching
──────────────
OpenAI does not expose block-level cache_control.  complete_with_context()
falls back to concatenating all ContextBlocks into a single prompt string.
The output is identical to Anthropic; token efficiency differs.
OpenAI does have automatic prefix caching for prompts > 1,024 tokens —
this happens transparently on their side at no extra configuration.

Requirements
────────────
    pip install openai>=1.0.0

Models
──────
    gpt-4o          — best overall           ← default
    gpt-4o-mini     — faster, cheaper
    o1, o1-mini     — reasoning models (no system prompt support)
"""
from __future__ import annotations
import logging
from typing import Optional

from core.utilities.llm.base import BaseLLMClient, ContextBlock, LLMMessage, LLMResponse

logger = logging.getLogger("core.utilities.llm.openai")


class OpenAILLMClient(BaseLLMClient):
    """
    GPT client implementing the same BaseLLMClient interface as AnthropicLLMClient.

    Usage:
        from core.utilities.llm import create_llm_client
        llm = create_llm_client("openai", api_key="sk-...")
        response = llm.complete("Summarise this pipeline spec...")
    """

    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError(
                "OpenAI SDK not installed. Run: pip install openai>=1.0.0"
            )
        self._model = model
        logger.info("OpenAILLMClient initialised — model: %s", self._model)

    # ── Simple completion ──────────────────────────────────────────────────────

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> LLMResponse:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = resp.choices[0].message
        return LLMResponse(
            content=choice.content or "",
            model=self._model,
            input_tokens=resp.usage.prompt_tokens,
            output_tokens=resp.usage.completion_tokens,
        )

    # ── Multi-turn chat ────────────────────────────────────────────────────────

    def chat(
        self,
        messages: list[LLMMessage],
        system: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> LLMResponse:
        api_messages: list[dict] = []
        if system:
            api_messages.append({"role": "system", "content": system})
        api_messages.extend({"role": m.role, "content": m.content} for m in messages)

        resp = self._client.chat.completions.create(
            model=self._model,
            messages=api_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        choice = resp.choices[0].message
        return LLMResponse(
            content=choice.content or "",
            model=self._model,
            input_tokens=resp.usage.prompt_tokens,
            output_tokens=resp.usage.completion_tokens,
        )

    # ── Cached context completion (fallback — no block-level caching) ──────────

    def complete_with_context(
        self,
        context_blocks: list[ContextBlock],
        task_prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """
        Concatenates all context blocks + task_prompt into a single prompt.

        OpenAI automatic prefix caching kicks in transparently for prompts
        > 1,024 tokens — no extra configuration required.

        Note: cacheable flag on ContextBlock is ignored here; it is only
        meaningful for AnthropicLLMClient.
        """
        full_prompt = "\n\n".join(b.text for b in context_blocks) + "\n\n" + task_prompt
        logger.debug(
            "OpenAI complete_with_context: %d blocks concatenated (%d chars total)",
            len(context_blocks), len(full_prompt),
        )
        return self.complete(
            full_prompt, system=system, max_tokens=max_tokens, temperature=temperature
        )
