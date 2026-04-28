# Extraction Pipeline Refactor — Claude Code Spec

## Scope & Constraints

**Touch only the LLM extraction pipeline layer.**
Do not modify: UI components, database models/migrations, storage adapters, Jira integration, authentication, API routes (except internal signatures if unavoidable), configuration files unrelated to the extraction pipeline, or any test files outside the extraction module.

If the existing code has a module/service boundary for the agent/extraction layer (e.g. `extraction/`, `agent/`, `pipeline/`, `services/extraction*`), all changes stay inside that boundary. If no such boundary exists, create one — move the relevant logic into `extraction/` without changing its callers' interfaces.

---

## What to Replace

Locate the current extraction logic. It will look like one or more of:
- A function that takes a document/text and calls an LLM once to get tasks
- A simple prompt → parse → return pattern with no chunking
- Possibly a single `extract_tasks(text)` or `run_agent(document)` call

Replace that logic entirely with the 9-stage pipeline described below. The replacement must expose the **exact same interface** as whatever it currently replaces — same function/method signature, same return type, same error contract — so that the rest of the application requires zero changes.

---

## 9-Stage Pipeline — Implementation Spec

### Stage 1 — Input Normalisation

Accept the existing input type (string, file path, file object, or document model — match whatever the caller currently passes).

Produce a plain UTF-8 string. If the input is a file, read it. If it is a structured document model, extract its text content. Strip null bytes and normalise line endings.

Also accept an optional `project_context: str` parameter (empty string if not provided). This is forwarded to every LLM call.

```python
def normalise_input(source) -> tuple[str, str]:
    """Returns (full_text, project_context)."""
```

---

### Stage 2 — Token-aware Chunker

Split the full text into overlapping windows. Do **not** split mid-sentence.

**Parameters** (all should be configurable via environment variables or a config object, with these defaults):

| Parameter | Default | Env var |
|---|---|---|
| `chunk_size_tokens` | 2000 | `EXTRACT_CHUNK_SIZE` |
| `overlap_tokens` | 200 | `EXTRACT_OVERLAP` |
| `words_per_token` | 1.3 | `EXTRACT_WORDS_PER_TOKEN` |

**Algorithm:**
1. Split text into sentences using regex `r'[^.!?\n]+[.!?\n]+|[^.!?\n]+'`.
2. Accumulate sentences until `word_count >= chunk_size_tokens * words_per_token`.
3. When a chunk is full, emit it, then seed the next chunk with the last `overlap_tokens * words_per_token` words from the current chunk (overlap window).
4. Drop any chunk shorter than 20 characters.

```python
@dataclass
class Chunk:
    text: str
    file_index: int   # index of the source document (0-based)
    chunk_index: int  # position within the document

def chunk_text(text: str, file_index: int, config: ChunkConfig) -> list[Chunk]:
    ...
```

---

### Stage 3 — Parallel Extraction with Retry

For each chunk, call the Anthropic Claude API and parse the returned JSON array of raw tasks.

**Concurrency:** Use `asyncio` + `asyncio.Semaphore` to cap concurrent API calls.

| Parameter | Default | Env var |
|---|---|---|
| `max_concurrent` | 5 | `EXTRACT_MAX_CONCURRENT` |
| `retry_attempts` | 3 | `EXTRACT_RETRY_ATTEMPTS` |
| `retry_base_ms` | 1200 | `EXTRACT_RETRY_BASE_MS` |

**Retry:** Exponential backoff. Wait `retry_base_ms * 2^attempt` milliseconds between attempts. Catch `anthropic.APIError`, `anthropic.RateLimitError`, and network errors. On final failure, log the error and return an empty list for that chunk (do not raise — one bad chunk must not abort the pipeline).

**System prompt** — use exactly this, do not paraphrase or shorten:

```
You are a precise Jira task extraction expert. Extract every actionable task from the text.
Return ONLY a valid JSON array with no markdown fences, no preamble, no explanation.
Each element must have exactly these fields:
- "summary": string ≤80 chars, starts with imperative verb (Build/Fix/Create/Add/Implement/Update/Remove/Design/Write/Test/Configure/Migrate/Refactor/Integrate)
- "description": string with specific details
- "issuetype": "Story"|"Task"|"Bug"|"Epic"|"Sub-task"
- "priority": "Critical"|"High"|"Medium"|"Low"
- "labels": string[] ≤5 items, no spaces (use hyphens)
- "storyPoints": Fibonacci integer (1,2,3,5,8,13,21)
- "acceptanceCriteria": string[] of specific testable criteria
- "extractionConfidence": float 0.0–1.0
- "temporalMarkers": string[] of temporal language found in the text
- "supersedes": boolean, true if this task clearly overrides a prior statement
If project context is provided, use it to expand acronyms, assign labels, calibrate priority.
Return [] if no tasks found. Never return null.
```

**User message format:**
```
PROJECT CONTEXT:
{project_context}

---
EXTRACT TASKS FROM:
{chunk.text}
```
(Omit the PROJECT CONTEXT block if `project_context` is empty.)

**Model:** Use the model already configured in the application (read from its existing config key). If no model is configured, default to `claude-sonnet-4-20250514`. Do not hardcode the model string anywhere other than that single default.

**Response parsing:** Strip markdown fences if present (```` ```json ... ``` ````), then `json.loads`. If parsing fails, log a warning and return `[]` for that chunk.

```python
@dataclass
class RawTask:
    summary: str
    description: str
    issuetype: str
    priority: str
    labels: list[str]
    story_points: int
    acceptance_criteria: list[str]
    extraction_confidence: float
    temporal_markers: list[str]
    supersedes: bool
    file_index: int
    chunk_index: int
    source_indices: list[int]   # starts as [file_index]

async def extract_chunk(chunk: Chunk, project_context: str, config: ExtractConfig) -> list[RawTask]:
    ...

async def extract_all(chunks: list[Chunk], project_context: str, config: ExtractConfig) -> list[RawTask]:
    """Fan out all chunks with semaphore, collect results."""
    ...
```

---

### Stage 4 — Local Deduplication (per document)

Before merging across documents, deduplicate tasks extracted from the same document.

**Jaccard similarity** over word tokens (lowercase, length > 2):

```python
def jaccard(a: str, b: str) -> float:
    sa = {w for w in a.lower().split() if len(w) > 2}
    sb = {w for w in b.lower().split() if len(w) > 2}
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

def task_key(task: RawTask) -> str:
    return f"{task.summary} {task.description}"
```

For each document (grouped by `file_index`), iterate tasks in order. Keep a task only if no already-kept task has `jaccard(task_key(a), task_key(b)) >= local_dedup_threshold`.

| Parameter | Default | Env var |
|---|---|---|
| `local_dedup_threshold` | 0.75 | `EXTRACT_LOCAL_DEDUP_THRESHOLD` |

```python
def local_dedup(tasks: list[RawTask], threshold: float) -> list[RawTask]:
    ...
```

---

### Stage 5 — Global Task Pool

Flatten all per-document deduplicated task lists into a single list.

```python
def build_global_pool(tasks_by_file: dict[int, list[RawTask]]) -> list[RawTask]:
    return [t for tasks in tasks_by_file.values() for t in tasks]
```

---

### Stage 6 — Graph Similarity Merge (Union-Find)

Find clusters of similar tasks across all documents and merge each cluster into one canonical task.

**Union-Find with path compression:**

```python
class UnionFind:
    def __init__(self, n: int): ...
    def find(self, x: int) -> int: ...   # path compression
    def union(self, x: int, y: int): ... # union by rank
```

**Clustering:** For every pair `(i, j)` where `i < j`, if `jaccard(task_key(tasks[i]), task_key(tasks[j])) >= global_merge_threshold`, call `union(i, j)`.

| Parameter | Default | Env var |
|---|---|---|
| `global_merge_threshold` | 0.55 | `EXTRACT_GLOBAL_MERGE_THRESHOLD` |

**Merging a cluster** (all tasks in the same connected component):
- `summary`, `description` — from the task with the highest `extraction_confidence`
- `priority` — highest priority in the cluster (`Critical > High > Medium > Low`)
- `labels` — union of all labels, deduplicated, capped at 5
- `story_points` — max across the cluster
- `acceptance_criteria` — union, deduplicated
- `temporal_markers` — union, deduplicated
- `cluster_size` — number of tasks merged (new field)
- `source_indices` — union of all `source_indices` across the cluster
- `file_index`, `chunk_index` — minimum values (earliest position in document order)

```python
@dataclass
class MergedTask(RawTask):
    cluster_size: int = 1

def graph_merge(tasks: list[RawTask], threshold: float) -> list[MergedTask]:
    ...
```

---

### Stage 7 — Temporal Reasoning

Some documents contain revision history, meeting notes, or iterative drafts where later statements override earlier ones. This stage removes tasks that have been superseded.

Sort tasks by `(file_index, chunk_index)` ascending — this is document order.

**Override keywords** (check if any appear in `task_key(task).lower()` or in `task.temporal_markers`):
```python
OVERRIDE_MARKERS = [
    "updated", "revised", "changed to", "now should", "instead",
    "replaced by", "no longer", "remove", "deprecated", "superseded",
    "as of now", "currently requires", "should now"
]
```

**Initial/draft keywords:**
```python
INITIAL_MARKERS = [
    "initially", "originally", "first draft", "preliminary",
    "tentatively", "proposed", "tbd", "placeholder", "to be determined"
]
```

**Rules:**
1. For each task `later` (in document order), if it has an override marker OR `later.supersedes is True`:
   - Scan all earlier tasks. For any earlier task where `jaccard(earlier.summary, later.summary) > 0.35`, mark `earlier` as dead. Increment `later.overrode_count`.
2. For each task with an initial marker:
   - Scan all later tasks. If any later task has `jaccard(later.summary, this.summary) > 0.40`, mark this task as dead.
3. Return only tasks where `dead is False`.

```python
@dataclass
class TemporalTask(MergedTask):
    overrode_count: int = 0

def apply_temporal_reasoning(tasks: list[MergedTask]) -> list[TemporalTask]:
    ...
```

---

### Stage 8 — Confidence Scoring

Assign a final `confidence` score (0.0–1.0) to each task.

```python
def score_confidence(task: TemporalTask) -> float:
    extraction  = max(0.0, min(1.0, task.extraction_confidence or 0.5))
    density     = min(0.12, (task.cluster_size - 1) * 0.04)
    cross_source= 0.10 if len(task.source_indices) > 1 else 0.0
    ac_richness = min(0.06, len(task.acceptance_criteria) * 0.02)
    return min(1.0, extraction + density + cross_source + ac_richness)
```

Add `confidence: float` to the task. Sort the final list by `confidence` descending.

---

### Stage 9 — Output Normalisation

Convert each scored task into the output format that the existing application expects from the extraction layer.

**This is the most important integration point.** Look at what the current extraction function returns — it will be one of:
- A list of dicts with keys like `summary`, `description`, `issuetype`, etc.
- A list of Pydantic models or dataclasses
- A list of ORM model instances ready to be saved

Match that exact structure. Map fields as follows:

| Pipeline field | Output field (match existing) |
|---|---|
| `summary` | `summary` |
| `description` | `description` |
| `issuetype` | `issue_type` or `issuetype` — match existing |
| `priority` | `priority` |
| `labels` | `labels` |
| `story_points` | `story_points` or `storyPoints` — match existing |
| `acceptance_criteria` | `acceptance_criteria` or `acceptanceCriteria` — match existing |
| `confidence` | add as new field if model allows; otherwise store in `metadata` |
| `cluster_size` | store in `metadata` if available |
| `source_indices` | store in `metadata` if available |
| `overrode_count` | store in `metadata` if available |

If the existing output type has a `metadata: dict` or `extra: dict` field, put pipeline-specific fields there. If it doesn't, add a `metadata: dict` field — this is safe because it is additive and callers that ignore unknown fields will not break.

---

## Public Interface

The pipeline must be callable as a single function matching the existing interface. Example — adapt names/signatures to match what already exists:

```python
async def run_extraction_pipeline(
    source,                          # whatever type the caller already passes
    project_context: str = "",       # new optional param — safe to add
    config: ExtractionConfig | None = None,
) -> list[<existing_return_type>]:
    """
    Drop-in replacement for the existing extraction function.
    Internally runs all 9 stages. Externally identical interface.
    """
    config = config or ExtractionConfig.from_env()

    # Stage 1
    text, ctx = normalise_input(source, project_context)

    # Stage 2
    chunks = chunk_text(text, file_index=0, config=config)

    # Stage 3
    raw = await extract_all(chunks, ctx, config)

    # Stage 4
    by_file = group_by_file(raw)
    deduped = {fi: local_dedup(tasks, config.local_dedup_threshold)
               for fi, tasks in by_file.items()}

    # Stage 5
    pool = build_global_pool(deduped)

    # Stage 6
    merged = graph_merge(pool, config.global_merge_threshold)

    # Stage 7
    temporal = apply_temporal_reasoning(merged)

    # Stage 8
    for task in temporal:
        task.confidence = score_confidence(task)
    temporal.sort(key=lambda t: t.confidence, reverse=True)

    # Stage 9
    return [to_output_format(t) for t in temporal]
```

For multi-document extraction (if the existing system passes multiple documents at once), assign each document a unique `file_index` (0, 1, 2 …) before chunking, then run stages 2–9 across all of them together.

---

## Configuration Object

```python
@dataclass
class ExtractionConfig:
    chunk_size_tokens: int    = 2000
    overlap_tokens: int       = 200
    words_per_token: float    = 1.3
    max_concurrent: int       = 5
    retry_attempts: int       = 3
    retry_base_ms: int        = 1200
    local_dedup_threshold: float  = 0.75
    global_merge_threshold: float = 0.55
    model: str                = "claude-sonnet-4-20250514"

    @classmethod
    def from_env(cls) -> "ExtractionConfig":
        """Read overrides from environment variables. Fall back to defaults."""
        ...
```

---

## File Structure to Create

Create these files inside the existing extraction module boundary. If the module is named differently, adapt the path but keep the same internal structure:

```
extraction/
├── __init__.py          # re-export run_extraction_pipeline
├── config.py            # ExtractionConfig dataclass + from_env()
├── chunker.py           # Stage 2 — chunk_text()
├── llm.py               # Stage 3 — extractChunk(), extract_all(), system prompt
├── dedup.py             # Stages 4+5 — jaccard, local_dedup, build_global_pool
├── merge.py             # Stage 6 — UnionFind, graph_merge()
├── temporal.py          # Stage 7 — apply_temporal_reasoning()
├── scoring.py           # Stage 8 — score_confidence()
├── output.py            # Stage 9 — to_output_format() mapped to existing types
└── pipeline.py          # run_extraction_pipeline() — orchestrates all stages
```

---

## Tests to Add

Add unit tests alongside the module. Do not modify any existing test files.

```
extraction/tests/
├── test_chunker.py      # Test overlap, sentence boundaries, min length filter
├── test_dedup.py        # Test jaccard values, dedup threshold behaviour
├── test_merge.py        # Test Union-Find correctness, merge field rules
├── test_temporal.py     # Test override detection, initial-marker detection
├── test_scoring.py      # Test formula bounds, bonus caps
└── test_pipeline.py     # Integration test with a mocked Anthropic client
```

For `test_pipeline.py`, mock the Anthropic client so no real API calls are made. Use a fixture that returns a plausible JSON task array.

---

## Do Not Change

- Database models or migrations
- Storage adapters (S3, GCS, local, etc.)
- Jira client or Jira field mapping (the `to_output_format()` in Stage 9 must feed into whatever the Jira layer already expects)
- Authentication or authorisation logic
- API route handlers (only their internal call to the extraction function is updated to use the new `run_extraction_pipeline`)
- UI components or frontend code
- CI/CD configuration
- Dependency files — only add `anthropic` if it is not already present; do not change or remove existing dependencies
- Logging configuration — use the existing logger, do not introduce a new one
- Any existing extraction tests — they should still pass if the output format is preserved correctly

---

## Clarification Protocol for Claude Code

Before writing any code, do the following in order:

1. **Find the existing extraction entry point** — search for the function or class that currently calls the LLM to extract tasks. Print its name, file path, and signature.
2. **Find the existing return type** — identify exactly what that function returns (dict, Pydantic model, ORM object). Print the type definition.
3. **Find the Anthropic client setup** — identify how the existing code constructs or imports the Anthropic client and where the API key comes from.
4. **Find the existing model config** — identify the config key or env var used to select the model, if any.
5. **Confirm the module boundary** — identify where the extraction module currently lives and confirm that all new files will be created there.

Only after completing those five steps, proceed with implementation.

If any of the above cannot be determined from the codebase alone (e.g. the extraction logic is embedded in a route handler with no clear boundary), stop and ask rather than guess.

Finally, update claude md as needed and review to ensure the logic is working error free.

