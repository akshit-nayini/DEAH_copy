# DEAH v1 — Design Specification
**Data Engineering Agent Hub — Version 1**
**Date:** 2026-04-05
**Author:** Ahemad Ali Shaik (via Claude Code)

---

## 1. Purpose

DEAH v1 is a multi-agent CLI system that acts as a **Data Architect**. It accepts data engineering requirements (from Markdown files or Jira tickets), validates them, routes them to the appropriate agents, and produces **design blueprints only** — no pipeline code, DAGs, or implementation code. Its output is consumed by a Data Engineering Pod.

---

## 2. Inputs

| Source | Format |
|---|---|
| Markdown file | Path to `.md` file |
| Jira Ticket | Ticket ID (e.g. `DE-123`) — system fetches description + comments via API |

---

## 3. Requirement Model — `RequirementDoc` (Pydantic v2)

### Core Fields (MANDATORY — fail-fast if missing)
| Field | Type | Values |
|---|---|---|
| `activity_type` | Enum | `new_dev`, `enhancement`, `bug` |
| `use_case` | str | Description of the use case |
| `acceptance_criteria` | list[str] | At least one criterion |

### Optional Fields
| Field | Type | Notes |
|---|---|---|
| `title` | str | Human-readable title |
| `technology` | dict | cloud, warehouse, orchestration, transform |
| `environment` | Enum | DEV, QA, PROD |
| `connections` | dict | source + target systems |
| `business_context` | str | |
| `constraints` | list[str] | |
| `assumptions` | list[str] | |
| `non_functional_requirements` | list[str] | |
| `data_volume` | str | |
| `latency_requirements` | str | |

**Validation rule:** If ANY core field is missing → STOP, display `"Missing required core fields: <field_names>"`, do NOT proceed to agents.

---

## 4. Jira Integration

- Input: Ticket ID string (e.g. `DE-123`)
- Fetches description + all comments via Jira REST API (`/rest/api/3/issue/{id}`)
- Auth: `.env` vars `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` (Basic auth)
- Parses response into `RequirementDoc` fields
- **Fallback:** If any Jira credential is missing → use static mock Jira response automatically (no flag needed)
- Log at startup: `[JIRA: REAL]` or `[JIRA: MOCK]`

---

## 5. LLM Provider Design

- Configured via `.env`: `LLM_PROVIDER = anthropic | gemini | mock`
- `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `MODEL_NAME`
- **Fallback rule:** If API key missing for configured provider → auto-switch to mock
- No manual flags — purely `.env`-driven
- Log at startup: `[LLM: CLAUDE]`, `[LLM: GEMINI]`, or `[LLM: MOCK]`

---

## 6. Routing Logic

| `activity_type` | Agents Run |
|---|---|
| `new_dev` | Architecture + Data Model + Impl Spec |
| `enhancement` | Data Model + Impl Spec |
| `bug` | Impl Spec only |

**Override:** If schema/data impact is detected in any input (regardless of `activity_type`), force-include Architecture and Data Model agents.

---

## 7. Agents

### 7.1 Architecture Agent (2-Stage)

**Stage 1** — Generate 2–3 full architecture options. Each option includes:
- Pattern name (batch lakehouse / streaming / warehouse-centric / cloud-native)
- Full tech stack (tool · version · managed vs self-hosted per component)
- IaC tooling
- Pros / cons

**Stage 2** — Score all options using configurable weighted dimensions (`config.yaml`):
```yaml
scoring_weights:
  cost: 0.30
  scalability: 0.25
  complexity: 0.20
  latency: 0.15
  operability: 0.10
```
Stage 2 receives Stage 1 output as context. Returns:
- All options with full stacks
- Side-by-side scoring table
- Recommended option + reasoning + trade-offs accepted

### 7.2 Data Model Agent
Generates:
- Logical model
- Physical schema (SQL DDL)
- Partitioning + clustering strategy
- SCD type decisions

### 7.3 Implementation Spec Agent (design blueprint, no code)
Generates:
- Ordered task breakdown
- Env deployment order (DEV → QA → PROD)
- Rollback strategy
- Error handling patterns
- Orchestration recommendations

---

## 8. Cross-Artifact Validator

- Validates ALL artifacts together after agents complete
- Returns: issues list, severity (High / Medium / Low), confidence score (0.0–1.0)

---

## 9. Auto-Fix Loop

- Identifies which agent produced failing artifact
- Re-runs ONLY that agent with validation feedback as context
- Retries up to `MAX_RETRIES` (from `.env`, default 3)
- Stores fix history per attempt

---

## 10. Human-in-the-Loop (CLI)

**Checkpoint 1** — before agent execution:
- Display `RequirementDoc` summary
- Prompt: `[A]pprove / [E]dit / [Ab]ort`
- Edit → re-parse and re-validate

**Checkpoint 2** — after validation:
- Triggered if `confidence < CONFIDENCE_THRESHOLD` OR validation failed
- Display validation summary
- Prompt: `[A]pprove / [R]etry / [Ab]ort`

---

## 11. Output Files (`/output/`)

| File | Contents |
|---|---|
| `architecture_options.md` | All options + full stacks + scores + recommendation |
| `model.sql` | Physical schema DDL |
| `impl_spec.md` | Implementation spec blueprint |
| `validation_report.md` | Full validation report (see below) |
| `metadata.json` | Run metadata (see below) |

**`metadata.json` fields:**
`request_type`, `confidence`, `retries`, `validation_status`, `llm_provider`, `jira_mode`, `timestamp`, `agents_run`

**`validation_report.md` sections:**
- Request summary, LLM provider, Jira mode
- Validation status (PASS/FAIL), confidence score, retry count
- Issues grouped by severity
- Fix history (attempt-wise)
- Final assessment + human review section

---

## 12. Logging

- Structured logging + Rich for console output
- Log: LLM mode, Jira mode, each stage execution, retry attempts
- Startup banner showing provider modes

---

## 13. Configuration (`config.yaml`)

- Scoring weights (configurable)
- Default model names per provider
- Agent prompt templates (parameterised, not hardcoded strings)

---

## 14. Environment Variables (`.env`)

```
LLM_PROVIDER=anthropic|gemini|mock
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
MODEL_NAME=
MAX_RETRIES=3
CONFIDENCE_THRESHOLD=0.75
JIRA_BASE_URL=
JIRA_EMAIL=
JIRA_API_TOKEN=
```

---

## 15. Project Layout (`v1/`)

```
v1/
├── VERSION
├── cli.py                          # Entry point
├── pyproject.toml
├── config.yaml
├── .env.example
├── input_samples/
│   └── sample.md
├── deah/
│   ├── __init__.py
│   ├── models/
│   │   └── requirement_doc.py      # Pydantic v2 RequirementDoc
│   ├── llm/
│   │   ├── provider.py             # LLM provider factory
│   │   ├── anthropic_client.py
│   │   ├── gemini_client.py
│   │   └── mock_client.py
│   ├── jira/
│   │   ├── client.py               # Real + mock Jira client
│   │   └── parser.py               # Jira → RequirementDoc
│   ├── agents/
│   │   ├── architecture.py         # 2-stage architecture agent
│   │   ├── data_model.py
│   │   └── impl_spec.py
│   ├── prompts/
│   │   ├── architecture_stage1.py
│   │   ├── architecture_stage2.py
│   │   ├── data_model.py
│   │   └── impl_spec.py
│   ├── routing.py                  # Request type → agent routing
│   ├── validator.py                # Cross-artifact validator
│   ├── autofix.py                  # Auto-fix retry loop
│   ├── orchestrator.py             # Main run orchestrator
│   ├── output.py                   # Output file writers
│   └── config.py                   # Config loader
└── output/                         # Generated artifacts
```

---

## 16. Self-Validation Requirements

Before completion, the system must pass:
1. All 3 activity types (`new_dev`, `enhancement`, `bug`) with `sample.md`
2. `new_dev` with mock Jira input
3. Missing core field → confirm fail-fast (no agent execution)
4. No API keys → confirm mock LLM runs cleanly
5. All 5 output files generated per run

---

## 17. HOW_TO_USE.md (Required)

Must cover:
1. Setup steps
2. `.env` configuration
3. Jira integration setup
4. CLI commands and examples
5. How to add a new agent
6. How to add a new validation rule
7. How to modify scoring weights
8. How to switch LLM providers
9. How to debug failures
10. Example runs with expected output
