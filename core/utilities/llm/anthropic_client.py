"""
Anthropic (Claude) LLM client — CURRENT DEFAULT PROVIDER.

Prompt caching
──────────────
Each ContextBlock with cacheable=True is sent with:
    "cache_control": {"type": "ephemeral"}

Anthropic caches the token prefix up to (and including) that block for
~5 minutes.  Cache behaviour:

  First call   →  usage.cache_creation_input_tokens > 0
                  (blocks are written to cache; slightly higher cost than normal)

  Subsequent   →  usage.cache_read_input_tokens > 0
                  (blocks are served from cache — ~10× cheaper per cached token)

The system message is also marked cacheable so it is stored once and
reused across all agent calls in a pipeline session.

Requirements
────────────
    pip install anthropic>=0.39.0

Models (as of 2026)
────────────────────
    claude-opus-4-6           — most capable, highest cost
    claude-sonnet-4-6         — best balance for pipeline work  ← default
    claude-haiku-4-5-20251001 — fastest, cheapest, lighter tasks
"""
from __future__ import annotations
import logging
from typing import Optional

from core.utilities.llm.base import BaseLLMClient, ContextBlock, LLMMessage, LLMResponse

logger = logging.getLogger("core.utilities.llm.anthropic")


class AnthropicLLMClient(BaseLLMClient):
    """
    Claude client with native Anthropic prompt-caching support.

    Usage:
        from core.utilities.llm import create_llm_client
        llm = create_llm_client("anthropic", api_key="sk-ant-...")
        response = llm.complete("Summarise this pipeline spec...")
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError(
                "Anthropic SDK not installed. Run: pip install anthropic>=0.39.0"
            )
        self._model = model
        logger.info("AnthropicLLMClient initialised — model: %s", self._model)

    # ── Simple completion ──────────────────────────────────────────────────────

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> LLMResponse:
        kwargs: dict = dict(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system
        msg = self._client.messages.create(**kwargs)
        return LLMResponse(
            content=msg.content[0].text,
            model=self._model,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
        )

    # ── Multi-turn chat ────────────────────────────────────────────────────────

    def chat(
        self,
        messages: list[LLMMessage],
        system: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> LLMResponse:
        api_messages = [{"role": m.role, "content": m.content} for m in messages]
        kwargs: dict = dict(
            model=self._model,
            max_tokens=max_tokens,
            messages=api_messages,
        )
        if system:
            kwargs["system"] = system
        msg = self._client.messages.create(**kwargs)
        return LLMResponse(
            content=msg.content[0].text,
            model=self._model,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
        )

    # ── Cached context completion (preferred for pipeline agents) ──────────────

    def complete_with_context(
        self,
        context_blocks: list[ContextBlock],
        task_prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """
        Build a structured message where cacheable blocks carry cache_control
        so Anthropic stores them server-side.

        Message layout sent to Anthropic:
            system  : [cached — GCP rules + agent role description]
            user    : [cached: impl_md block]
                      [cached: mapping_csv block]
                      [cached: plan block (from PlannerAgent)]
                      [NOT cached: human checkpoint notes (changes each revision)]
                      [NOT cached: task_prompt (different per agent call)]
        """
        # ── Build user content list ────────────────────────────────────────────
        content: list[dict] = []
        for block in context_blocks:
            entry: dict = {"type": "text", "text": block.text}
            if block.cacheable:
                entry["cache_control"] = {"type": "ephemeral"}
            content.append(entry)

        # Task prompt is NEVER cached — it is call-specific
        content.append({"type": "text", "text": task_prompt})

        # ── System prompt with cache_control ───────────────────────────────────
        system_param: list[dict] | None = None
        if system:
            system_param = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]

        kwargs: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        if system_param:
            kwargs["system"] = system_param

        msg = self._client.messages.create(**kwargs)

        # Cache usage attributes are present only when caching is active
        cache_creation = getattr(msg.usage, "cache_creation_input_tokens", 0) or 0
        cache_read     = getattr(msg.usage, "cache_read_input_tokens", 0) or 0

        if cache_creation:
            logger.debug("Cache written: %d tokens stored for reuse", cache_creation)
        if cache_read:
            pct = cache_read / max(1, msg.usage.input_tokens + cache_read) * 100
            logger.debug(
                "Cache hit: %d tokens read from cache (saved ~%.1f%% of input cost)",
                cache_read, pct,
            )

        return LLMResponse(
            content=msg.content[0].text,
            model=self._model,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            cache_creation_tokens=cache_creation,
            cache_read_tokens=cache_read,
        )
