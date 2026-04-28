# Implementation: Architecture Agent

## File Layout
- `test_architecture.py` — local test runner
- `architecture/__init__.py` — exposes `ArchitectureAgent` and `get_agent(config)`
- `architecture/agent.py` — `ArchitectureAgent`, `AgentResult`, manifest validation
- `architecture/skills.py` — deterministic pre-computation: cloud resolution, pattern inference, volume tier, latency tier
- `architecture/prompts.py` — system prompt and architecture design prompt

## Dependencies
- `anthropic`

## Environment Variables
- `ANTHROPIC_API_KEY` (required)
- `CLAUDE_MODEL` — model override, default `claude-sonnet-4-20250514`

## Configuration
Passed as a `config` dict to `get_agent(config)` or `ArchitectureAgent(config)`:

```python
config = {
    "model": {
        "model_id":   "claude-sonnet-4-20250514",
        "max_tokens": 16000,
        "temperature": 0.0,
    },
    "confidence_threshold": 0.7,   # float 0–1; default 0.7
    "paths": {
        "output_dir": "outputs/",
    },
}
```

## Pre-computation Skills
Run deterministically in `skills.py` before the LLM is called. Results are embedded in the prompt as hard constraints.

### Cloud Platform Resolution
Maps `technology.cloud_or_onprem` (checked first) then `technology.stack` (fallback) to a target cloud.

| Input keyword (case-insensitive) | Resolved platform |
|---|---|
| gcp, google | GCP |
| aws, amazon | AWS |
| azure, microsoft | Azure |
| (unrecognised / missing) | GCP (default) — open question seeded |

### Pattern Type Inference

```
IF ingestion_type = streaming          → streaming
IF output_type ∈ {report, ml_feature} → lakehouse
IF latency contains real-time keywords → hybrid
DEFAULT                                → batch
```

Real-time keywords scanned in `non_functional.latency`:
`real-time, realtime, real time, < 1, <1, seconds, minutes`

The inferred pattern is passed to the LLM as a constraint — it must justify any deviation in writing.

### Data Volume Tier

| Volume string contains | Tier |
|---|---|
| billion, tb, pb, 100m, 500m, large, high | high |
| million, gb, 10m, 50m, medium | medium |
| (unrecognised / missing) | low |

High volume seeds an open question if managed autoscaling is not confirmed.

### Latency Tier

| Latency string contains | Tier |
|---|---|
| real-time, realtime, real time, < 1 min, seconds | real-time |
| minutes, near real, near-real, < 15, < 5 | near-real-time |
| (T+1, daily, hourly, unrecognised / missing) | batch |

Latency tier constrains which services are valid for the processing component of each option.

### Open Questions Seeded (always, independent of confidence)

| Missing field | Open question seeded |
|---|---|
| `data_requirements.volume` | "Data volume not specified — cannot determine processing tier or cost estimate." |
| `data_requirements.frequency` | "Ingestion frequency not specified — cannot confirm batch vs streaming decision." |
| `non_functional.latency` | "Latency SLA not specified — pattern type may be suboptimal." |
| `technology.cloud_or_onprem` | "Cloud/on-prem not specified — defaulting to GCP." |
| `non_functional.scalability` | "Scalability requirements not specified — cannot assess managed service sizing." |

## Input Schema
- `requirements: dict` — `RequirementsOutput.to_dict()`; must contain `request_type`, `classification`, `technology`, `non_functional`, `data_requirements`
- `run_plan: list[str]` — from `RequirementsOutput.run_plan`; if `"architecture"` is absent the agent returns `skipped=True` without calling the LLM

## Output Schema (`AgentResult`)
- `success: bool` — `True` if the LLM call completed and the manifest parsed successfully
- `skipped: bool` — `True` when `"architecture"` is not in `run_plan`
- `skip_reason: str | None` — explanation when `skipped=True`; `None` otherwise
- `manifest: dict | None` — full architecture manifest (see below); `None` when `skipped=True` or `success=False`
- `handoff_summary: dict | None` — slim subset of manifest passed to `implementation_steps`; `None` when skipped or failed
- `validation_warnings: list[str]` — non-blocking issues found during post-LLM manifest validation; empty list if none
- `error: str | None` — error message when `success=False`; `None` otherwise
- `run_id: str` — UUID assigned at invocation time
- `output_dir: Path` — directory where output files were written

## Architecture Manifest Schema (`AgentResult.manifest`)
- `options: list[dict]` — 2–3 scored architecture options; each entry:
  - `name: str`
  - `tech_stack: dict` — keys: `ingestion`, `processing`, `storage`, `orchestration`, `monitoring`, `iac`; each value: `tool: str`, `managed: bool`, `justification: str`
  - `scores: dict` — keys: `cost`, `scalability`, `complexity`, `latency`, `operability` (each float 0–10), `weighted_score: float`
  - `pros: list[str]`
  - `cons: list[str]`
  - `risks: list[str]`
- `recommendation: dict` — keys: `selected_option: str`, `rationale: str`
- `scoring_table: list[dict]` — one row per option; mirrors `options[].scores` in tabular form
- `open_questions: list[str]` — gaps or missing inputs seeded by pre-computation skills
- `global_risks: list[dict]` — each: `risk: str`, `mitigation: str`
- `traceability: list[dict]` — links each architecture decision back to a requirements field

### Scoring Weights (prompt-enforced)

| Dimension | Weight |
|---|---|
| Cost | 0.30 |
| Scalability | 0.25 |
| Complexity | 0.20 |
| Latency | 0.15 |
| Operability | 0.10 |

`weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

Post-LLM validation checks that all score fields are present but does not re-compute them.

## Invocation

```python
from architecture import get_agent

config = {
    "model": {
        "model_id": "claude-sonnet-4-20250514",
        "max_tokens": 16000,
        "temperature": 0.0,
    },
    "confidence_threshold": 0.7,
    "paths": {"output_dir": "outputs/"},
}

agent = get_agent(config)
result = agent.run(requirements_output.to_dict())

if result.skipped:
    print(f"Skipped: {result.skip_reason}")
elif result.success:
    manifest = result.manifest
    print(manifest["recommendation"]["selected_option"])
    for option in manifest["options"]:
        print(f"  {option['name']}: weighted_score={option['scores']['weighted_score']}")
else:
    print(f"Failed: {result.error}")

if result.validation_warnings:
    for w in result.validation_warnings:
        print(f"Warning: {w}")
```

## Output Files
Written to `paths.output_dir` per run, keyed by `run_id`:

| File | Contents |
|---|---|
| `{run_id}_architecture_manifest.json` | Parsed architecture manifest |
| `{run_id}_architecture_raw_response.txt` | Raw LLM text for debugging |

## Post-LLM Manifest Validation
Runs deterministically after parsing the LLM response. All checks are non-blocking — failures become entries in `validation_warnings`, not exceptions.

| Check | Warning raised if |
|---|---|
| Options count | fewer than 2 options returned |
| Tech stack completeness (per option) | any of `ingestion / processing / storage / orchestration / monitoring / iac` missing `tool` |
| Scores completeness (per option) | any of `cost / scalability / complexity / latency / operability / weighted_score` missing |
| Pros / cons / risks (per option) | any are empty lists |
| Recommendation present | `selected_option` missing |
| Scoring table row count | does not match number of options |
| Global risks present | empty list |
| Traceability present | empty list |

## Prompts (`architecture/prompts.py`)
`SYSTEM_PROMPT` contains fixed rules: default to GCP unless another cloud is specified; produce exactly 2–3 scored options; apply the fixed scoring weights; include global risks and traceability; justify any deviation from the inferred pattern type in writing.

`architecture_prompt(requirements, resolved_cloud, pattern_type, volume_tier, latency_tier, open_questions)` embeds the requirements JSON and all pre-computed skill results as labelled blocks. Structural rules are not repeated in the user turn — they are in `SYSTEM_PROMPT` only.

## Design Notes
- Single Claude call — no tool loop.
- Temperature is `0.0` — scoring and tech stack selection must be deterministic across runs.
- Pre-computed `cloud_platform`, `pattern_type`, `volume_tier`, and `latency_tier` are passed as constraints in the prompt. The LLM must justify any deviation.
- Three JSON extraction methods are attempted on parse failure before returning `success=False`. Raw response is always written to disk for debugging regardless of parse outcome.
- Rate limit and server errors are retried up to 3 times with exponential backoff before raising.
- No automatic retry on other API errors — caller (orchestrator) handles retry logic.
- Low confidence input proceeds with `open_questions` seeded — it does not block execution.
- `api_key` is never written to output files or included in logged prompts.

## Running Tests

```bash
# Run from a requirements JSON
python test_architecture.py \
    --requirements output/requirement/requirements.json

# Run and write output to a specific directory
python test_architecture.py \
    --requirements output/requirement/requirements.json \
    --output-dir output/architecture/

# Print JSON manifest only
python test_architecture.py \
    --requirements output/requirement/requirements.json \
    --format json
```

Expected outputs on success:
- `result.success == True` and `result.skipped == False`
- `result.manifest["options"]` contains 2–3 entries
- `result.manifest["recommendation"]["selected_option"]` matches one of the option names
- `result.manifest["scoring_table"]` has one row per option
- `{run_id}_architecture_manifest.json` and `{run_id}_architecture_raw_response.txt` written to `output_dir`
