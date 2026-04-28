# Spec-Driven Data Engineering Assistant — Design

**Date:** 2026-04-12
**Status:** Approved

---

## Overview

A Claude Code project that guides users through a structured data engineering workflow using multi-step slash commands. Users clone the repo, open it with the `claude` CLI, and interact through Claude Code's conversation loop. No SDK or API calls — Claude Code itself is the runtime.

The assistant converts natural language requirements into approved requirements docs, scored design options, task breakdowns, pipeline/infra code, and mocked tests. Every artifact is staged for approval before being written to its final location.

---

## Folder Structure

```
spec-based/
  .claude/
    commands/
      de-requirements.md    ← /de-requirements slash command
      de-design.md          ← /de-design slash command
      de-implement.md       ← /de-implement slash command
  CLAUDE.md                 ← project context, conventions, stage dependencies
  specs/
    requirements.md         ← approved requirements doc
    design.md               ← approved design doc (with scored options)
    tasks.md                ← approved task breakdown
  src/                      ← approved generated pipeline + infra code
  tests/                    ← approved mocked tests
  .temp/                    ← staging area (gitignored)
  docs/
    superpowers/
      specs/                ← design docs
      plans/                ← implementation plans
```

---

## Architecture

**Option A (chosen): Flat Commands**

Each stage is a standalone `.md` file in `.claude/commands/`. Each command file contains all instructions, clarifying logic, `.temp/` staging, and the approval loop. No shared agents directory — logic lives close to where it's used.

Commands are independent but have soft dependencies:
- `/de-design` requires `specs/requirements.md` to exist
- `/de-implement` requires `specs/design.md` and `specs/tasks.md` to exist

---

## Command Behavior

### `/de-requirements`

1. Accept natural language requirement inline or prompt the user for it
2. Analyze input — if ambiguous, ask up to 3 targeted clarifying questions one at a time
3. Generate `requirements.md` covering: goal, inputs/outputs, data sources, SLAs, constraints, assumptions
4. Save to `.temp/requirements.md`, print the file path
5. Approval loop:
   - `yes` → move to `specs/requirements.md`
   - feedback → regenerate from feedback, repeat from step 4

### `/de-design`

1. Read `specs/requirements.md` — error with clear message if not found (run `/de-requirements` first)
2. Ask 1-2 clarifying questions about tech preferences (stack, orchestrator, expected scale)
3. Generate 3 design options, each scored on complexity, maintainability, scalability (1-10 each, weighted)
4. Generate `tasks.md` with numbered task breakdown derived from chosen/recommended option
5. Save each to `.temp/design.md` and `.temp/tasks.md`, print paths
6. Approval loop on each file separately (design first, then tasks)

### `/de-implement`

1. Read `specs/design.md` and `specs/tasks.md` — error if either is missing
2. Ask 1 clarifying question if stack details remain ambiguous
3. Generate:
   - Pipeline code in `src/` (PySpark, dbt, Airflow DAG, etc. per design)
   - Infrastructure/config files in `src/` (Terraform, YAML, etc. per design)
   - Mocked tests in `tests/` mirroring `src/` structure
4. Output includes a confidence score and numbered assumptions list
5. Stage all generated files under `.temp/src/` and `.temp/tests/`, print paths
6. Approval loop: `yes` → move to `src/` and `tests/` | feedback → regenerate

---

## Approval Loop (All Commands)

Every command follows this pattern before writing to final locations:

```
1. Generate content
2. Write to .temp/<filename>
3. Print: "Saved to .temp/<filename> — review it, then:"
4. Ask: "Approve to save? (yes / feedback)"
5a. yes      → move .temp/<filename> → <final-location>/<filename>
5b. feedback → regenerate incorporating feedback, repeat from step 2
```

---

## CLAUDE.md Contents

- Project description and intended audience (data engineers, cloned and run locally)
- Workflow overview: 3-stage pipeline with stage dependencies
- File location map
- Code conventions:
  - Python 3.12, type hints required, docstrings on public functions
  - One file per concern in `src/`
  - Mocked tests use `unittest.mock`, no real connections, test file mirrors `src/` file
- Approval loop protocol: always stage in `.temp/`, always ask before final write
- Getting started: `git clone` → `cd spec-based` → `claude` → `/de-requirements`

---

## Scoring Rubric (used in `/de-design`)

| Criterion       | Weight |
|----------------|--------|
| Complexity      | 30%    |
| Maintainability | 35%    |
| Scalability     | 35%    |

Each option receives a raw score (1-10) per criterion. Weighted score = sum of (score × weight). The option with the highest weighted score is recommended, with reasoning.

---

## Confidence Score (used in `/de-implement`)

Narrative self-assessment. Claude counts how many requirements were explicitly stated vs. had to be assumed, and reports:

- Score: 0–100%
- Example: "8 of 10 requirements were explicitly specified → 80% confidence"
- Numbered assumptions list accompanies every implementation output

---

## Conventions for Generated Code

- **Language:** Python 3.12
- **Pipeline frameworks:** PySpark, dbt, Airflow (per design choice)
- **Infra/config:** Terraform, YAML pipeline configs, Spark job configs (per design choice)
- **Tests:** `unittest.mock` only — no real database/API connections in tests
- **Structure:** `src/<concern>.py`, `tests/test_<concern>.py`
- **Style:** type hints on all function signatures, docstrings on public functions

---

## Getting Started (for new users)

```bash
git clone <repo>
cd spec-based
claude          # opens Claude Code CLI
/de-requirements "build a pipeline that ingests Kafka events into BigQuery"
```
