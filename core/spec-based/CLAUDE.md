# Spec-Driven Data Engineering Assistant

A Claude Code project that guides you through a structured data engineering
workflow using three slash commands. Works entirely inside Claude Code CLI —
no SDK, no API keys needed beyond your `claude` session.

---

## What This Does

Takes a natural language requirement and produces:
1. A structured requirements doc
2. A scored design with 3 options
3. A task breakdown
4. Pipeline + infra code with mocked tests

Every artifact is staged in `.temp/` for your review before being saved to
its final location.

---

## Getting Started

```bash
git clone <repo-url>
cd spec-based
claude
```

Then run slash commands in order:

```
/de-requirements "build a pipeline that ingests Kafka events into BigQuery"
/de-design
/de-implement
```

---

## Workflow & Stage Dependencies

```
/de-requirements
  └─ writes → specs/requirements.md

/de-design        (reads specs/requirements.md — run /de-requirements first)
  └─ writes → specs/design.md
  └─ writes → specs/tasks.md

/de-implement     (reads specs/design.md + specs/tasks.md — run /de-design first)
  └─ writes → src/
  └─ writes → tests/
```

---

## Approval Loop

Every command stages output in `.temp/` before writing to the final location:

1. Content is generated and saved to `.temp/<file>`
2. You are shown the file path to review
3. You are asked: **"Approve to save? (yes / feedback)"**
   - `yes` → file is moved to its final location
   - anything else → treated as feedback, content is regenerated

---

## File Locations

| Artifact | Staging (temp) | Final location |
|----------|---------------|----------------|
| Requirements | `.temp/requirements.md` | `specs/requirements.md` |
| Design | `.temp/design.md` | `specs/design.md` |
| Tasks | `.temp/tasks.md` | `specs/tasks.md` |
| Pipeline/infra code | `.temp/src/` | `src/` |
| Mocked tests | `.temp/tests/` | `tests/` |

---

## Code Conventions (for /de-implement output)

- **Language:** Python 3.12
- **Pipeline frameworks:** PySpark, dbt, Airflow (per design choice)
- **Infra/config:** Terraform, YAML, Spark configs (per design choice)
- **Tests:** `unittest.mock` — no real DB/API connections in tests
- **Structure:** `src/<concern>.py` ↔ `tests/test_<concern>.py`
- **Style:** type hints on all function signatures, docstrings on public functions

---

## Design Scoring Rubric (used by /de-design)

| Criterion | Weight |
|-----------|--------|
| Complexity | 30% |
| Maintainability | 35% |
| Scalability | 35% |

Weighted score = (complexity × 0.30) + (maintainability × 0.35) + (scalability × 0.35).
Option with the highest weighted score is recommended.

---

## Confidence Score (used by /de-implement)

After generating code, Claude counts how many requirements were explicit vs.
assumed and reports a score (0–100%) plus a numbered assumptions list.

Example: "8 of 10 requirements were explicitly specified → **80% confidence**"
