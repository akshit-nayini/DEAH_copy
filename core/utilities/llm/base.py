"""
LLM abstraction layer — interface definitions.

Every provider client must subclass BaseLLMClient and implement all three
abstract methods.  Application code (agents, pipelines) imports only from
this module — never from a specific provider client directly.

Key design decisions
────────────────────
ContextBlock
    Wraps a large, static text block.  When cacheable=True the Anthropic
    implementation sends cache_control: {type: ephemeral} so Anthropic
    stores the block server-side for ~5 minutes.  Other providers that
    don't support block-level caching silently concatenate the blocks —
    same result, different token efficiency.

complete_with_context()
    Preferred method for multi-stage pipelines (e.g. Planner → Generator
    → Optimizer → Reviewer).  Keeps large static documents (impl_md,
    mapping_csv, plan) as cached blocks; only the small task-specific
    prompt varies per call.  Subsequent agent calls re-use the cached
    prefix and pay only for the fresh task tokens.

complete() / chat()
    Kept for single-turn or simple calls where the caching benefit is
    not needed.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ContextBlock:
    """
    One unit of cacheable context sent to the LLM.

    Args:
        text      : Full text content of the block.
        label     : Human-readable name (used for logging / debugging).
        cacheable : If True, Anthropic caches this block server-side.
                    Set False for dynamic content that changes every call
                    (e.g. human checkpoint notes, per-run timestamps).
    """
    text: str
    label: str = ""
    cacheable: bool = True


@dataclass
class LLMMessage:
    """Single message in a multi-turn conversation."""
    role: str       # "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    """Unified response object returned by every provider client."""
    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    # Populated only by AnthropicLLMClient when prompt caching is active
    cache_creation_tokens: int = 0   # tokens written to cache on first call
    cache_read_tokens: int = 0       # tokens read from cache on subsequent calls

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of input tokens served from cache (0.0 – 1.0)."""
        denom = self.input_tokens + self.cache_read_tokens
        return self.cache_read_tokens / denom if denom else 0.0


class BaseLLMClient(ABC):
    """
    Provider-agnostic LLM interface.  One concrete implementation per provider.

    To add a new provider:
      1. Subclass BaseLLMClient
      2. Implement complete(), chat(), complete_with_context()
      3. Register in factory.create_llm_client()
    """

    @abstractmethod
    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Single-turn completion from a plain string prompt."""
        ...

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        system: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Multi-turn chat completion."""
        ...

    @abstractmethod
    def complete_with_context(
        self,
        context_blocks: list[ContextBlock],
        task_prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """
        Preferred method for pipeline agents.

        context_blocks  — large, static content (implementation docs, plan,
                          best-practice rules).  Anthropic caches these
                          blocks; subsequent calls read them from cache
                          instead of re-encoding them.
        task_prompt     — small, call-specific instruction.  Never cached
                          because it differs between calls.

        Providers without block-level caching (OpenAI, Gemini) fall back to
        concatenating all blocks + task_prompt into a single string.
        """
        ...
