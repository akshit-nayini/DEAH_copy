# DEAH LLM Utility — `core/utilities/llm`

Provider-agnostic wrapper over **Claude (Anthropic)**, **GPT-4 (OpenAI)**, and
**Gemini (Google)**.

All three providers expose the same `BaseLLMClient` interface.  Switching
providers is a single argument change — no application code changes required.

---

## Contents

```
core/utilities/llm/
├── __init__.py          — public API surface
├── base.py              — BaseLLMClient interface + data classes
├── factory.py           — create_llm_client() — single entry point
├── anthropic_client.py  — Claude with native prompt-caching  ← current default
├── openai_client.py     — GPT-4 (auto prefix caching)
├── gemini_client.py     — Gemini (CachedContent upgrade path noted inline)
├── test_connection.py   — quick Claude connectivity test
└── README.md            — this file
```

---

## Install

```bash
# Claude (Anthropic) — current production provider
pip install anthropic>=0.39.0

# GPT-4 (OpenAI) — when switching
pip install openai>=1.0.0

# Gemini (Google) — when switching
pip install google-generativeai>=0.7
```

---

## Set API Keys

```bash
# Windows
setx ANTHROPIC_API_KEY "sk-ant-..."
setx OPENAI_API_KEY    "sk-..."
setx GEMINI_API_KEY    "AI..."

# Mac / Linux
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
export GEMINI_API_KEY="AI..."
```

---

## Provider & Model Override via Environment Variables

Two env vars let you control which provider and model the factory uses
**without changing any calling code**. This is the recommended way to
configure agents when the entry-point (`main.py`) hardcodes a default.

| Variable | Purpose | Example values |
|----------|---------|----------------|
| `LLM_PROVIDER` | Overrides the `provider` argument | `anthropic`, `claude-code-sdk`, `openai`, `gemini` |
| `LLM_MODEL` | Overrides the `model` argument | `claude-sonnet-4-6`, `claude-haiku-4-5-20251001` |

**Priority chain (highest → lowest):**
```
Provider: LLM_PROVIDER env var  >  provider argument  >  factory default
Model:    LLM_MODEL env var     >  model argument      >  client DEFAULT_MODEL
```

### Use Anthropic API key (recommended for production)

```bash
# .env or shell — overrides the claude-code-sdk default in main.py
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6          # or claude-haiku-4-5-20251001
ANTHROPIC_API_KEY=sk-ant-...
```

### Switch back to Claude Agent SDK

```bash
LLM_PROVIDER=claude-code-sdk
# LLM_MODEL is ignored by ClaudeCodeSDKClient
```

No code changes needed in any agent or pipeline file — just update the env vars.

---

## Quick Start

```python
from core.utilities.llm import create_llm_client

# Claude — current provider (reads ANTHROPIC_API_KEY from env)
llm = create_llm_client("anthropic")

# Or pass the key explicitly
llm = create_llm_client("anthropic", api_key="sk-ant-...")

# Swap to GPT-4 — zero other changes
llm = create_llm_client("openai", api_key="sk-...")

# Swap to Gemini — zero other changes
llm = create_llm_client("gemini", api_key="AI...")
```

---

## Three API Methods

All providers implement the same three methods.

### 1 · `complete()` — single-turn

```python
response = llm.complete(
    prompt="List the BigQuery best practices for partitioned tables.",
    system="You are a GCP data engineering expert.",
    max_tokens=2048,
    temperature=0.2,
)

print(response.content)
print(f"Tokens: {response.input_tokens} in / {response.output_tokens} out")
```

### 2 · `chat()` — multi-turn conversation

```python
from core.utilities.llm import LLMMessage

messages = [
    LLMMessage(role="user",      content="What is SCD Type 1?"),
    LLMMessage(role="assistant", content="SCD Type 1 overwrites old column values..."),
    LLMMessage(role="user",      content="How does it differ from Type 2?"),
]
response = llm.chat(messages, system="You are a data warehousing expert.")
print(response.content)
```

### 3 · `complete_with_context()` — preferred for multi-agent pipelines

Splits the call into **large cacheable context** + **small task prompt**.
On Claude, Anthropic caches the context blocks server-side (~5 min) so
subsequent agents sharing the same prefix pay ~10× less for those tokens.

```python
from core.utilities.llm import ContextBlock

context_blocks = [
    ContextBlock(
        text="## Pipeline Spec\n...(3,000 tokens)...",
        label="implementation_md",
        cacheable=True,    # Claude stores this server-side
    ),
    ContextBlock(
        text="## Column Mapping\n...(1,000 tokens)...",
        label="mapping_csv",
        cacheable=True,
    ),
    ContextBlock(
        text=f"## Reviewer Notes\n{human_notes}",
        label="human_notes",
        cacheable=False,   # changes each revision — never cache
    ),
]

response = llm.complete_with_context(
    context_blocks=context_blocks,
    task_prompt="Generate BigQuery DDL for all staging tables in the plan.",
    system="You are a BigQuery SQL expert following GCP best practices.",
    max_tokens=8192,
)

print(response.content)
print(f"Cache written : {response.cache_creation_tokens} tokens")
print(f"Cache read    : {response.cache_read_tokens} tokens")
print(f"Cache hit rate: {response.cache_hit_rate:.0%}")
```

---

## Response Object

```python
response.content                # str   — model output text
response.model                  # str   — model name that answered
response.input_tokens           # int   — tokens sent (excludes cache reads)
response.output_tokens          # int   — tokens generated
response.total_tokens           # int   — input + output
response.cache_creation_tokens  # int   — tokens written to cache  (Anthropic only)
response.cache_read_tokens      # int   — tokens read from cache   (Anthropic only)
response.cache_hit_rate         # float — 0.0–1.0, fraction served from cache
```

---

## Prompt Caching — Why It Matters

In a pipeline where 4 agents (Planner, Generator, Optimizer, Reviewer)
all read the same large documents, caching those documents pays off quickly:

| Without cache | With cache (Anthropic) |
|---|---|
| Agent 1: 4,000 input tokens | Agent 1: 4,000 tokens — writes to cache |
| Agent 2: 4,000 input tokens | Agent 2: ~200 fresh + 3,800 from cache |
| Agent 3: 4,000 input tokens | Agent 3: ~200 fresh + 3,800 from cache |
| Agent 4: 4,000 input tokens | Agent 4: ~200 fresh + 3,800 from cache |
| **Total: 16,000 tokens billed** | **Total: ~4,600 tokens billed** |

Rules:
- Set `cacheable=True` on blocks that **don't change between agent calls** (spec, mapping, plan)
- Set `cacheable=False` on anything **dynamic** (human notes, timestamps, run IDs)
- Cache TTL is ~5 minutes — all 4 agents should complete within one session

---

## Available Models

### Claude (Anthropic)
| Model | Use case |
|-------|----------|
| `claude-opus-4-6` | Most capable — complex reasoning, long outputs |
| `claude-sonnet-4-6` | Best balance for pipeline work **← default** |
| `claude-haiku-4-5-20251001` | Fastest / cheapest — lighter classification tasks |

```python
llm = create_llm_client("anthropic", model="claude-opus-4-6")
```

### GPT (OpenAI)
| Model | Use case |
|-------|----------|
| `gpt-4o` | Best overall **← default** |
| `gpt-4o-mini` | Faster, lower cost |

### Gemini (Google)
| Model | Use case |
|-------|----------|
| `gemini-1.5-pro` | Best overall, 1M token context **← default** |
| `gemini-1.5-flash` | Faster, lower cost |

---

## How Other Pods Should Use This

Every pod that needs LLM access should:

1. Import `create_llm_client` from this package
2. Accept `llm: BaseLLMClient` as a constructor argument in their agents
3. Never import a specific client class — always use the factory

```python
# In your agent class
from core.utilities.llm import BaseLLMClient, ContextBlock, create_llm_client

class MyAgent:
    def __init__(self, llm: BaseLLMClient) -> None:
        self._llm = llm   # injected — works with any provider

    def run(self, doc: str) -> str:
        response = self._llm.complete(f"Summarise: {doc}")
        return response.content

# In your entry point / main.py
llm   = create_llm_client("anthropic")   # or "openai" / "gemini"
agent = MyAgent(llm=llm)
```

---

## Adding a New Provider

1. Create `core/utilities/llm/<name>_client.py`
2. Subclass `BaseLLMClient` and implement `complete()`, `chat()`, `complete_with_context()`
3. Add a branch in `factory.py`
4. No changes needed in any agent or pipeline code

---

## Test Claude Connection

```bash
# From DEAH root
python core/utilities/llm/test_connection.py

# With an explicit key
python core/utilities/llm/test_connection.py --api-key sk-ant-...

# Against a different model
python core/utilities/llm/test_connection.py --model claude-opus-4-6
```
