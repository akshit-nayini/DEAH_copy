# Design: LLM Environment Variable Provider Override

**Date:** 2026-04-15  
**Status:** Approved  
**Scope:** `core/utilities/llm/` only — zero changes to `core/development/`

---

## Problem

`core/development/main.py` defaults to `--provider claude-code-sdk`, which requires the
Claude CLI OAuth session (`claude login`). Agents need to run against the Anthropic API
directly (using `ANTHROPIC_API_KEY`) with haiku or sonnet models — but `main.py` cannot
be modified.

---

## Solution

Add an **environment-variable priority chain** to `create_llm_client()` in `factory.py`.
When `LLM_PROVIDER` is set in the environment it takes explicit precedence over the
`provider` argument. The same applies to `LLM_MODEL`. The priority is a **documented
contract** in the docstring — not a hidden side-effect.

---

## Priority Chain

### Provider resolution (highest → lowest)

| Priority | Source | Example value |
|----------|--------|---------------|
| 1 | `LLM_PROVIDER` env var | `anthropic` |
| 2 | `provider` argument to `create_llm_client()` | `claude-code-sdk` (from main.py) |
| 3 | Factory hardcoded fallback | `anthropic` |

### Model resolution (highest → lowest)

| Priority | Source | Example value |
|----------|--------|---------------|
| 1 | `LLM_MODEL` env var | `claude-sonnet-4-6` |
| 2 | `model` argument to `create_llm_client()` | `None` (from main.py) |
| 3 | `AnthropicLLMClient.DEFAULT_MODEL` | `claude-sonnet-4-6` |

---

## Supported Models (Anthropic)

| Model ID | Use case |
|----------|----------|
| `claude-sonnet-4-6` | Best balance for pipeline work **← default** |
| `claude-haiku-4-5-20251001` | Fastest / cheapest — lighter tasks |
| `claude-opus-4-6` | Most capable — complex reasoning |

---

## Configuration

Set these in shell or a `.env` file loaded before the process starts:

```bash
# Use Anthropic API key (overrides claude-code-sdk default in main.py)
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6          # or claude-haiku-4-5-20251001
ANTHROPIC_API_KEY=sk-ant-...
```

To switch back to Agent SDK:

```bash
LLM_PROVIDER=claude-code-sdk
# LLM_MODEL is ignored by ClaudeCodeSDKClient
```

---

## Files Changed

| File | Change |
|------|--------|
| `core/utilities/llm/factory.py` | Add `LLM_PROVIDER` / `LLM_MODEL` env-var priority chain with documented contract |
| `core/utilities/llm/README.md` | Add env-var configuration section |

## Files NOT Changed

- `core/utilities/llm/base.py` — interface unchanged
- `core/utilities/llm/anthropic_client.py` — already supports model selection
- `core/utilities/llm/claude_code_sdk_client.py` — unchanged, stays as Agent SDK path
- `core/development/**` — zero changes; agents receive `BaseLLMClient` and are provider-agnostic

---

## Compatibility

- **Claude Agent SDK**: Switch back at any time via `LLM_PROVIDER=claude-code-sdk`
- **OpenAI / Gemini**: Also configurable via `LLM_PROVIDER=openai` / `LLM_PROVIDER=gemini`
- **Existing callers** that pass `provider="anthropic"` explicitly are unaffected — env var
  matches the argument so resolution is identical
- **`--model` CLI flag** in `main.py` still works when `LLM_MODEL` is not set

---

## Non-Goals

- No changes to agent logic, orchestrator, or pipeline code
- No new provider implementations
- No changes to `BaseLLMClient` interface
