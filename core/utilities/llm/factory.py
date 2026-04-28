"""
LLM client factory — single entry point for all provider clients.

Swap providers by changing one argument — zero application code changes.

    llm = create_llm_client("anthropic",      api_key="sk-ant-...")   # Claude (direct API)  ← current default
    llm = create_llm_client("claude-code-sdk")                         # Claude Code Agent SDK
    llm = create_llm_client("openai",         api_key="sk-...")        # GPT-4
    llm = create_llm_client("gemini",         api_key="AI...")         # Gemini

The returned object is always a BaseLLMClient — agents and pipelines
never import provider-specific classes directly.

API key resolution order (recommended)
──────────────────────────────────────
1. Pass api_key= explicitly
2. Read from environment variable (see _ENV_KEYS below)
3. If neither is set, the client will raise ImportError or AuthError on use

Environment variables
─────────────────────
    ANTHROPIC_API_KEY   — Claude (Anthropic direct API)
    OPENAI_API_KEY      — GPT (OpenAI)
    GEMINI_API_KEY      — Gemini (Google)

Note: "claude-code-sdk" does NOT use an API key — it relies on the CLI
OAuth session established by running `claude login`.

Provider / model override via environment
─────────────────────────────────────────
Two env vars let you reconfigure the factory without changing any calling
code (useful when main.py hardcodes a default provider):

    LLM_PROVIDER   — overrides the provider argument passed to this function
    LLM_MODEL      — overrides the model argument passed to this function

Priority chain (highest → lowest):
    Provider: LLM_PROVIDER env var  >  provider argument  >  factory default
    Model:    LLM_MODEL env var     >  model argument      >  client DEFAULT_MODEL

Example (.env or shell):
    LLM_PROVIDER=anthropic
    LLM_MODEL=claude-sonnet-4-6        # or claude-haiku-4-5-20251001
    ANTHROPIC_API_KEY=sk-ant-...

To switch back to Agent SDK:
    LLM_PROVIDER=claude-code-sdk
"""
from __future__ import annotations
import os
from core.utilities.llm.base import BaseLLMClient

_SUPPORTED = ("anthropic", "claude-code-sdk", "claude-sdk", "openai", "gemini")

# Providers that authenticate via API key (claude-code-sdk uses CLI OAuth instead)
_ENV_KEYS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "gemini":    "GEMINI_API_KEY",
}


def create_llm_client(
    provider: str,
    api_key: str | None = None,
    model: str | None = None,
) -> BaseLLMClient:
    """
    Create and return a BaseLLMClient for the given provider.

    Priority chain
    ──────────────
    Provider: LLM_PROVIDER env var  >  provider argument  >  factory default
    Model:    LLM_MODEL env var     >  model argument      >  client DEFAULT_MODEL

    Args:
        provider : "anthropic" | "claude-code-sdk" | "openai" | "gemini".
                   Overridden by LLM_PROVIDER env var when set.
        api_key  : API key.  If None, falls back to the provider's standard
                   environment variable (ANTHROPIC_API_KEY, etc.)
        model    : Optional model override.  If None, falls back to LLM_MODEL
                   env var, then to the provider client's DEFAULT_MODEL.

    Returns:
        A BaseLLMClient instance ready for use.

    Raises:
        ValueError  : Unknown provider.
        ImportError : Required SDK not installed.
        RuntimeError: API key not found.
    """
    # ── Priority 1: LLM_PROVIDER / LLM_MODEL env vars override arguments ──────
    env_provider = os.environ.get("LLM_PROVIDER", "").strip()
    env_model    = os.environ.get("LLM_MODEL", "").strip()

    p = (env_provider or provider).lower().strip()
    if env_model:
        model = env_model

    if p not in _SUPPORTED:
        raise ValueError(
            f"Unknown LLM provider '{provider}'. "
            f"Supported: {', '.join(_SUPPORTED)}"
        )

    # claude-sdk is an alias for claude-code-sdk
    if p == "claude-sdk":
        p = "claude-code-sdk"

    # claude-code-sdk authenticates via CLI OAuth ('claude login') — no API key needed
    if p == "claude-code-sdk":
        from core.utilities.llm.claude_code_sdk_client import ClaudeCodeSDKClient
        kwargs: dict = {}
        if model:
            kwargs["model"] = model
        return ClaudeCodeSDKClient(**kwargs)

    # All other providers require an API key
    resolved_key = api_key or os.environ.get(_ENV_KEYS[p], "")
    if not resolved_key:
        raise RuntimeError(
            f"No API key for provider '{p}'. "
            f"Pass api_key= or set {_ENV_KEYS[p]} environment variable."
        )

    kwargs = {"api_key": resolved_key}
    if model:
        kwargs["model"] = model

    if p == "anthropic":
        from core.utilities.llm.anthropic_client import AnthropicLLMClient
        return AnthropicLLMClient(**kwargs)

    if p == "openai":
        from core.utilities.llm.openai_client import OpenAILLMClient
        return OpenAILLMClient(**kwargs)

    if p == "gemini":
        from core.utilities.llm.gemini_client import GeminiLLMClient
        return GeminiLLMClient(**kwargs)

    # Unreachable after the check above, but satisfies type checkers
    raise ValueError(f"Unhandled provider: {p}")
