"""
DEAH LLM Utility
================
Provider-agnostic wrapper over Claude (Anthropic), GPT (OpenAI), and
Gemini (Google).  All three expose the same BaseLLMClient interface so
application code never needs to know which provider is behind it.

Quick start
-----------
    from core.utilities.llm import create_llm_client

    llm = create_llm_client("anthropic", api_key="sk-ant-...")   # Claude  ← current default
    llm = create_llm_client("openai",    api_key="sk-...")        # GPT-4   ← future
    llm = create_llm_client("gemini",    api_key="AI...")         # Gemini  ← future

All clients implement:
    llm.complete(prompt, system=None)
    llm.chat(messages)
    llm.complete_with_context(context_blocks, task_prompt)  ← preferred for multi-agent pipelines

Prompt caching
--------------
AnthropicLLMClient marks ContextBlock(cacheable=True) blocks with
Anthropic's cache_control so they are stored server-side (~5 min TTL).
Subsequent agents that share the same static prefix (impl_md, mapping_csv,
plan) read it from cache — roughly 10× cheaper per cached token.

OpenAI and Gemini do not yet have the same block-level caching API;
complete_with_context() falls back to concatenation on those providers.
"""
from core.utilities.llm.base import (
    BaseLLMClient,
    ContextBlock,
    LLMMessage,
    LLMResponse,
)
from core.utilities.llm.factory import create_llm_client

__all__ = [
    "BaseLLMClient",
    "ContextBlock",
    "LLMMessage",
    "LLMResponse",
    "create_llm_client",
]
