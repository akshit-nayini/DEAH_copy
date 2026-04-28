"""
Google Gemini LLM client — FUTURE PROVIDER BLOCK.

Status: implemented and ready; not used in production yet.
        Switch via: create_llm_client("gemini", api_key="AI...")

Prompt caching
──────────────
Gemini supports context caching via google.generativeai.caching.CachedContent
(minimum 32,768 tokens, TTL configurable).  complete_with_context() currently
uses a simple concatenation fallback.

To enable Gemini native caching when needed:
  1. Replace the concatenation fallback below with CachedContent API calls
  2. Cache the static blocks (impl_md + mapping_csv + plan) once per session
  3. Reference the cached content name in subsequent generate_content() calls

Requirements
────────────
    pip install google-generativeai>=0.7

Models
──────
    gemini-1.5-pro      — best overall, 1M token context ← default
    gemini-1.5-flash    — faster, lower cost
    gemini-2.0-flash    — latest flash model
"""
from __future__ import annotations
import logging
from typing import Optional

from core.utilities.llm.base import BaseLLMClient, ContextBlock, LLMMessage, LLMResponse

logger = logging.getLogger("core.utilities.llm.gemini")


class GeminiLLMClient(BaseLLMClient):
    """
    Gemini client implementing the same BaseLLMClient interface as AnthropicLLMClient.

    Usage:
        from core.utilities.llm import create_llm_client
        llm = create_llm_client("gemini", api_key="AI...")
        response = llm.complete("Summarise this pipeline spec...")
    """

    DEFAULT_MODEL = "gemini-1.5-pro"

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self._genai = genai
        except ImportError:
            raise ImportError(
                "Gemini SDK not installed. Run: pip install google-generativeai>=0.7"
            )
        self._model_name = model
        logger.info("GeminiLLMClient initialised — model: %s", self._model_name)

    # ── Simple completion ──────────────────────────────────────────────────────

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> LLMResponse:
        model = self._genai.GenerativeModel(
            self._model_name,
            system_instruction=system,
            generation_config=self._genai.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            ),
        )
        resp = model.generate_content(prompt)
        usage = getattr(resp, "usage_metadata", None)
        return LLMResponse(
            content=resp.text,
            model=self._model_name,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        )

    # ── Multi-turn chat ────────────────────────────────────────────────────────

    def chat(
        self,
        messages: list[LLMMessage],
        system: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> LLMResponse:
        model = self._genai.GenerativeModel(
            self._model_name,
            system_instruction=system,
            generation_config=self._genai.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            ),
        )
        # All messages except the last become history; last is sent as the new turn
        history = [
            {"role": m.role, "parts": [m.content]}
            for m in messages[:-1]
        ]
        chat_session = model.start_chat(history=history)
        resp = chat_session.send_message(messages[-1].content)
        usage = getattr(resp, "usage_metadata", None)
        return LLMResponse(
            content=resp.text,
            model=self._model_name,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
        )

    # ── Cached context completion (fallback — concatenation for now) ───────────

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

        FUTURE: replace with Gemini CachedContent API for blocks > 32,768 tokens:
            cache = caching.CachedContent.create(
                model=self._model_name,
                contents=[block.text for block in context_blocks if block.cacheable],
                ttl=datetime.timedelta(minutes=5),
            )
            model = self._genai.GenerativeModel.from_cached_content(cache)
            resp = model.generate_content(task_prompt)

        Note: cacheable flag on ContextBlock is ignored here; it is only
        meaningful for AnthropicLLMClient.
        """
        full_prompt = "\n\n".join(b.text for b in context_blocks) + "\n\n" + task_prompt
        logger.debug(
            "Gemini complete_with_context: %d blocks concatenated (%d chars total)",
            len(context_blocks), len(full_prompt),
        )
        return self.complete(
            full_prompt, system=system, max_tokens=max_tokens, temperature=temperature
        )
