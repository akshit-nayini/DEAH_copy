# LLM Utility — core/utilities/llm

Provider-agnostic wrapper over Claude, GPT-4, and Gemini.  All three
expose the same interface — swap providers by changing one argument.

---

## Install

```bash
# Claude (Anthropic) — current default
pip install anthropic>=0.39.0

# GPT-4 (OpenAI) — future
pip install openai>=1.0.0

# Gemini (Google) — future
pip install google-generativeai>=0.7
```

---

## Quick Start

```python
from core.utilities.llm import create_llm_client

# Claude — current provider
llm = create_llm_client("anthropic", api_key="sk-ant-...")

# GPT-4 — future
llm = create_llm_client("openai", api_key="sk-...")

# Gemini — future
llm = create_llm_client("gemini", api_key="AI...")

# Or use environment variables (recommended)
# Set ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY
llm = create_llm_client("anthropic")
```

---

## API

### `llm.complete(prompt, system=None)`

Single-turn completion.

```python
response = llm.complete(
    prompt="List the BigQuery best practices for partitioned tables.",
    system="You are a GCP data engineering expert.",
)
print(response.content)
print(f"Tokens: {response.input_tokens} in / {response.output_tokens} out")
```

### `llm.chat(messages)`

Multi-turn conversation.

```python
from core.utilities.llm import LLMMessage

messages = [
    LLMMessage(role="user",      content="What is SCD Type 1?"),
    LLMMessage(role="assistant", content="SCD Type 1 overwrites old values..."),
    LLMMessage(role="user",      content="How does it differ from Type 2?"),
]
response = llm.chat(messages)
```

### `llm.complete_with_context(context_blocks, task_prompt)` ← preferred for pipelines

Sends large, static documents as cacheable blocks and a small task prompt
as the fresh instruction.  On Anthropic, the blocks are stored server-side
for ~5 minutes — subsequent agents sharing the same prefix read from cache
(~10× cheaper per cached token).

```python
from core.utilities.llm import ContextBlock

context_blocks = [
    ContextBlock(
        text="## Implementation Document\n...",
        label="implementation_md",
        cacheable=True,   # Anthropic caches this server-side
    ),
    ContextBlock(
        text="## Column Mapping\n...",
        label="mapping_csv",
        cacheable=True,
    ),
    ContextBlock(
        text=f"## Human Notes\n{notes}",
        label="human_notes",
        cacheable=False,  # Changes each revision — never cache
    ),
]

response = llm.complete_with_context(
    context_blocks=context_blocks,
    task_prompt="Generate the DDL for all staging tables listed in the plan.",
    system="You are a BigQuery SQL expert...",
    max_tokens=8192,
)

print(f"Cache written : {response.cache_creation_tokens} tokens")
print(f"Cache read    : {response.cache_read_tokens} tokens")
print(f"Cache hit rate: {response.cache_hit_rate:.0%}")
```

---

## Response object

```python
response.content               # str — model output
response.model                 # str — model name used
response.input_tokens          # int — tokens sent (excludes cache hits)
response.output_tokens         # int — tokens generated
response.cache_creation_tokens # int — tokens written to cache (Anthropic only)
response.cache_read_tokens     # int — tokens read from cache  (Anthropic only)
response.total_tokens          # int — input + output
response.cache_hit_rate        # float — 0.0–1.0 fraction served from cache
```

---

## Environment Variables

| Provider  | Variable            |
|-----------|---------------------|
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI    | `OPENAI_API_KEY`    |
| Gemini    | `GEMINI_API_KEY`    |

---

## Prompt caching (Anthropic — current provider)

Anthropic charges ~10× less for tokens read from cache.  In the DEAH
pipeline, four agents (Planner, Generator, Optimizer, Reviewer) share
the same large `impl_md + mapping_csv + plan` prefix.  With caching:

- **First agent call**: blocks written to cache (slight overhead)
- **Agents 2–4**: blocks served from cache → significant cost reduction

The `cacheable=True` flag on `ContextBlock` activates this automatically.
Set `cacheable=False` for anything that changes between calls (human notes,
timestamps, per-run values).

---

## Adding a new provider

1. Create `core/utilities/llm/<provider>_client.py`
2. Subclass `BaseLLMClient` and implement `complete()`, `chat()`, `complete_with_context()`
3. Add a branch in `factory.py`
4. No changes needed in any application code
