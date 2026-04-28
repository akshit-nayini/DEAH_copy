# Architecture Agent — Skills

## Purpose

Reads `RequirementsOutput` from the Requirements Agent, applies deterministic pre-computation skills, and produces an Architecture Decision Document with 2–3 scored options, a weighted recommendation, risk analysis, and full traceability to requirements. Defaults to GCP managed services unless another cloud is explicitly specified.

---

## Skill 1 — Cloud Platform Resolution

Determines the target cloud from `technology.cloud_or_onprem` and `technology.stack`.

| Input keyword (case-insensitive) | Resolved platform |
|----------------------------------|-------------------|
| gcp, google                      | GCP               |
| aws, amazon                      | AWS               |
| azure, microsoft                 | Azure             |
| (unrecognised / missing)         | GCP (default)     |

Resolution checks `cloud_or_onprem` first, then falls back to `stack`. If neither contains a recognisable keyword, GCP is assumed and an open question is seeded.

---

## Skill 2 — Pattern Type Inference

Determines the primary architecture pattern before the LLM is called.

```
IF ingestion_type = streaming          → streaming
IF output_type ∈ {report, ml_feature} → lakehouse
IF latency contains real-time keywords → hybrid
DEFAULT                                → batch
```

Real-time keywords scanned in `non_functional.latency`:
`real-time, realtime, real time, < 1, <1, seconds, minutes`

The inferred pattern type is passed to the LLM as a constraint — the LLM must justify any deviation.

---

## Skill 3 — Data Volume Tier

Classifies `data_requirements.volume` as a tier used in tech stack and scoring decisions.

| Volume string contains             | Tier   |
|------------------------------------|--------|
| billion, tb, pb, 100m, 500m, large, high | high   |
| million, gb, 10m, 50m, medium      | medium |
| (unrecognised / missing)           | low    |

High volume → seeds open question if managed autoscaling is not confirmed.

---

## Skill 4 — Latency Tier Classification

Maps `non_functional.latency` to a processing tier constraint.

| Latency string contains                              | Tier           |
|------------------------------------------------------|----------------|
| real-time, realtime, real time, < 1 min, seconds     | real-time      |
| minutes, near real, near-real, < 15, < 5             | near-real-time |
| (T+1, daily, hourly, unrecognised / missing)         | batch          |

Latency tier directly constrains which GCP services are valid for the Processing component of each option.

---

## Skill 5 — Confidence Scoring & Gating

The `confidence` float (0.0–1.0) from the Requirements Agent reflects how complete the source text is.

### Threshold

Default threshold: **0.7** (configurable).

### Behaviour

| Condition              | Action                                                                                         |
|------------------------|------------------------------------------------------------------------------------------------|
| confidence ≥ threshold | Proceed normally. `confidence_note: null`.                                                     |
| confidence < threshold | Echo `low_confidence_warning` in prompt. Seed open questions with specific architecture gaps.  |

### Architecture-Specific Gap Detection (always runs)

Even when confidence ≥ threshold, seed `open_questions` if any of these are missing:

| Missing field                    | Open question seeded                                                        |
|----------------------------------|-----------------------------------------------------------------------------|
| `data_requirements.volume`       | "Data volume not specified — cannot determine processing tier or cost estimate." |
| `data_requirements.frequency`    | "Ingestion frequency not specified — cannot confirm batch vs streaming decision." |
| `non_functional.latency`         | "Latency SLA not specified — pattern type may be suboptimal."               |
| `technology.cloud_or_onprem`     | "Cloud/on-prem not specified — defaulting to GCP."                         |
| `non_functional.scalability`     | "Scalability requirements not specified — cannot assess managed service sizing." |

---

## Skill 6 — Skip Gate

The architecture agent respects the orchestrator's `run_plan`.

```
IF run_plan is not empty AND "architecture" not in run_plan
→ return AgentResult(skipped=True, skip_reason=...)
```

Bug requests with `architecture` in run_plan trigger a validation warning — unusual unless a systemic redesign is needed.

---

## Skill 7 — Manifest Validation (Post-LLM)

After LLM response is parsed, these checks run deterministically:

| Check                                           | Warning raised if failing                                          |
|-------------------------------------------------|--------------------------------------------------------------------|
| Options count                                   | fewer than 2 options generated                                     |
| Tech stack completeness (per option)            | any of ingestion / processing / storage / orchestration / monitoring / iac missing `tool` |
| Scores completeness (per option)                | any of cost / scalability / complexity / latency / operability / weighted_score missing |
| Pros / cons / risks present (per option)        | any are empty                                                      |
| Recommendation selected_option present          | missing                                                            |
| Scoring table row count matches options count   | mismatch                                                           |
| Global risks present                            | empty list                                                         |
| Traceability present                            | empty list                                                         |

Warnings are non-blocking — the agent returns success with the manifest and attaches warnings to `AgentResult.validation_warnings`.

---

## Skill 8 — Scoring Weights (enforced in prompt)

The LLM is instructed to apply fixed weights. The manifest validation does NOT re-compute scores — it only checks the fields are present.

| Dimension   | Weight |
|-------------|--------|
| Cost        | 0.30   |
| Scalability | 0.25   |
| Complexity  | 0.20   |
| Latency     | 0.15   |
| Operability | 0.10   |

Formula enforced: `weighted_score = (cost × 0.30) + (scalability × 0.25) + (complexity × 0.20) + (latency × 0.15) + (operability × 0.10)`

---

## Invocation

```python
from architecture.init import get_agent

agent = get_agent(config)
result = agent.run(requirements_output.to_dict())

if result.success and not result.skipped:
    manifest = result.manifest
    # manifest["recommendation"]["selected_option"]
    # manifest["options"]
    # manifest["scoring_table"]
```

## Configuration

- `model.model_id`: Claude model string (default: `claude-sonnet-4-20250514`)
- `model.max_tokens`: max output tokens (default: `16000`)
- `model.temperature`: sampling temperature (default: `0.0` — deterministic)
- `confidence_threshold`: float 0–1 (default: `0.7`)
- `paths.output_dir`: directory to write manifest JSON and raw LLM response (default: `outputs/`)

## Output Files (per run)

| File pattern                                | Contents                         |
|---------------------------------------------|----------------------------------|
| `{run_id}_architecture_manifest.json`       | Parsed architecture manifest     |
| `{run_id}_architecture_raw_response.txt`    | Raw LLM text for debugging       |

## Error and Edge Case Behaviour

- `architecture` not in `run_plan`: returns `AgentResult(skipped=True)` — not an error.
- Input validation failure (missing required fields): returns `AgentResult(success=False, error=...)`.
- LLM response not parseable as JSON: returns `AgentResult(success=False, error=...)` — 3 extraction methods attempted before failing.
- Rate limit / server errors: retried up to 3 times with exponential backoff before raising.
- Low confidence input: proceeds with warnings seeded in `open_questions` — does not block.
