"""
Tests for LLM_PROVIDER / LLM_MODEL environment variable priority chain in factory.py.

Priority contract under test:
    Provider: LLM_PROVIDER env var  >  provider argument  >  factory default
    Model:    LLM_MODEL env var     >  model argument      >  client DEFAULT_MODEL
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure DEAH root is on sys.path regardless of where pytest is invoked from
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))

from core.utilities.llm.factory import create_llm_client
from core.utilities.llm.base import BaseLLMClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_env(*keys: str):
    """Context manager: removes env vars before test, restores state after."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        saved = {k: os.environ.pop(k, None) for k in keys}
        try:
            yield
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)

    return _ctx()


# ---------------------------------------------------------------------------
# LLM_PROVIDER override tests
# ---------------------------------------------------------------------------

class TestProviderEnvOverride:
    """LLM_PROVIDER env var must take precedence over the provider argument."""

    def test_env_overrides_claude_code_sdk_with_anthropic(self):
        """
        When LLM_PROVIDER=anthropic and provider='claude-code-sdk' is passed,
        the factory must return an AnthropicLLMClient, not ClaudeCodeSDKClient.
        """
        with _clean_env("LLM_PROVIDER", "LLM_MODEL"):
            os.environ["LLM_PROVIDER"] = "anthropic"
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"

            with patch("anthropic.Anthropic"):
                client = create_llm_client("claude-code-sdk")

            from core.utilities.llm.anthropic_client import AnthropicLLMClient
            assert isinstance(client, AnthropicLLMClient), (
                f"Expected AnthropicLLMClient, got {type(client).__name__}. "
                "LLM_PROVIDER=anthropic should override provider='claude-code-sdk'."
            )

    def test_env_not_set_uses_argument(self):
        """
        When LLM_PROVIDER is not set, the provider argument is used as-is.
        """
        with _clean_env("LLM_PROVIDER", "LLM_MODEL"):
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"

            with patch("anthropic.Anthropic"):
                client = create_llm_client("anthropic")

            from core.utilities.llm.anthropic_client import AnthropicLLMClient
            assert isinstance(client, AnthropicLLMClient)

    def test_env_provider_takes_precedence_over_explicit_sdk_arg(self):
        """
        Even when caller explicitly passes provider='claude-code-sdk',
        LLM_PROVIDER=anthropic wins.
        """
        with _clean_env("LLM_PROVIDER", "LLM_MODEL"):
            os.environ["LLM_PROVIDER"] = "anthropic"
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"

            with patch("anthropic.Anthropic"):
                client = create_llm_client(provider="claude-code-sdk")

            from core.utilities.llm.anthropic_client import AnthropicLLMClient
            assert isinstance(client, AnthropicLLMClient)


# ---------------------------------------------------------------------------
# LLM_MODEL override tests
# ---------------------------------------------------------------------------

class TestModelEnvOverride:
    """LLM_MODEL env var must take precedence over the model argument."""

    def test_llm_model_env_sets_haiku(self):
        """
        When LLM_MODEL=claude-haiku-4-5-20251001, the client is initialised
        with that model even if model=None is passed.
        """
        with _clean_env("LLM_PROVIDER", "LLM_MODEL"):
            os.environ["LLM_MODEL"] = "claude-haiku-4-5-20251001"
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"

            with patch("anthropic.Anthropic"):
                client = create_llm_client("anthropic")

            assert client._model == "claude-haiku-4-5-20251001", (
                f"Expected haiku, got {client._model!r}. "
                "LLM_MODEL env var should set the model."
            )

    def test_llm_model_env_sets_sonnet(self):
        """LLM_MODEL=claude-sonnet-4-6 is passed through correctly."""
        with _clean_env("LLM_PROVIDER", "LLM_MODEL"):
            os.environ["LLM_MODEL"] = "claude-sonnet-4-6"
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"

            with patch("anthropic.Anthropic"):
                client = create_llm_client("anthropic")

            assert client._model == "claude-sonnet-4-6"

    def test_llm_model_env_overrides_model_argument(self):
        """
        When LLM_MODEL=claude-haiku-4-5-20251001 is set but model='claude-opus-4-6'
        is passed as argument, the env var wins.
        """
        with _clean_env("LLM_PROVIDER", "LLM_MODEL"):
            os.environ["LLM_MODEL"] = "claude-haiku-4-5-20251001"
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"

            with patch("anthropic.Anthropic"):
                client = create_llm_client("anthropic", model="claude-opus-4-6")

            assert client._model == "claude-haiku-4-5-20251001", (
                f"Expected haiku (env), got {client._model!r}. "
                "LLM_MODEL env var should beat the model argument."
            )

    def test_no_llm_model_env_uses_argument(self):
        """When LLM_MODEL is not set, the model argument is used."""
        with _clean_env("LLM_PROVIDER", "LLM_MODEL"):
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"

            with patch("anthropic.Anthropic"):
                client = create_llm_client("anthropic", model="claude-opus-4-6")

            assert client._model == "claude-opus-4-6"

    def test_no_env_no_argument_uses_default(self):
        """When neither LLM_MODEL nor model argument are set, client DEFAULT_MODEL is used."""
        with _clean_env("LLM_PROVIDER", "LLM_MODEL"):
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"

            with patch("anthropic.Anthropic"):
                client = create_llm_client("anthropic")

            from core.utilities.llm.anthropic_client import AnthropicLLMClient
            assert client._model == AnthropicLLMClient.DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Combined override tests
# ---------------------------------------------------------------------------

class TestCombinedOverride:
    """LLM_PROVIDER and LLM_MODEL both active at the same time."""

    def test_provider_and_model_both_overridden(self):
        """
        LLM_PROVIDER=anthropic overrides 'claude-code-sdk',
        LLM_MODEL=claude-haiku-4-5-20251001 sets the model — simultaneously.
        """
        with _clean_env("LLM_PROVIDER", "LLM_MODEL"):
            os.environ["LLM_PROVIDER"] = "anthropic"
            os.environ["LLM_MODEL"] = "claude-haiku-4-5-20251001"
            os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-key"

            with patch("anthropic.Anthropic"):
                client = create_llm_client("claude-code-sdk")

            from core.utilities.llm.anthropic_client import AnthropicLLMClient
            assert isinstance(client, AnthropicLLMClient)
            assert client._model == "claude-haiku-4-5-20251001"
