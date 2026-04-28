# Spec-Driven Data Engineering Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code project with three slash commands (`/de-requirements`, `/de-design`, `/de-implement`) that guide users through a structured data engineering workflow with staged approval before writing any final output.

**Architecture:** Flat commands — each stage is a standalone `.md` file in `.claude/commands/`. Each command file is a self-contained prompt containing all instructions, clarifying logic, `.temp/` staging, and the approval loop. Commands have soft dependencies (design reads requirements, implement reads design+tasks) but are otherwise independent.

**Tech Stack:** Claude Code CLI, Markdown command files (`.claude/commands/`), CLAUDE.md project context, no external dependencies.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `CLAUDE.md` | Create | Project context, conventions, workflow overview, getting started |
| `.claude/commands/de-requirements.md` | Create | `/de-requirements` slash command prompt |
| `.claude/commands/de-design.md` | Create | `/de-design` slash command prompt |
| `.claude/commands/de-implement.md` | Create | `/de-implement` slash command prompt |
| `.gitignore` | Create | Ignore `.temp/`, `__pycache__`, `.pyc`, output dirs |
| `specs/.gitkeep` | Create | Ensure specs/ directory is tracked |
| `src/.gitkeep` | Create | Ensure src/ directory is tracked |
| `tests/.gitkeep` | Create | Ensure tests/ directory is tracked |
| `.temp/.gitkeep` | Create | Ensure .temp/ exists locally (gitignored content, not dir) |

---

## Task 1: Scaffold Project Structure

**Files:**
- Create: `.gitignore`
- Create: `specs/.gitkeep`
- Create: `src/.gitkeep`
- Create: `tests/.gitkeep`
- Create: `.temp/.gitkeep`

- [ ] **Step 1: Create `.gitignore`**

```
# Staging area — contents are temporary
.temp/*
!.temp/.gitkeep

# Python
__pycache__/
*.pyc
*.pyo
*.egg-info/

# OS
.DS_Store
```

Write this to `.gitignore` in `spec-based/`.

- [ ] **Step 2: Create placeholder files for tracked directories**

Create the following empty files (touch or Write with empty content):
- `specs/.gitkeep`
- `src/.gitkeep`
- `tests/.gitkeep`
- `.temp/.gitkeep`

- [ ] **Step 3: Verify structure**

Run:
```bash
find . -not -path './.git/*' | sort
```
Expected output includes:
```
./.gitignore
./.temp/.gitkeep
./specs/.gitkeep
./src/.gitkeep
./tests/.gitkeep
./docs/superpowers/plans/...
./docs/superpowers/specs/...
```

- [ ] **Step 4: Commit**

```bash
git add .gitignore specs/.gitkeep src/.gitkeep tests/.gitkeep .temp/.gitkeep
git commit -m "scaffold: add project folder structure and gitignore"
```

---

## Task 2: Write CLAUDE.md

**Files:**
- Create: `CLAUDE.md`

- [ ] **Step 1: Write `CLAUDE.md`**

```markdown
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
```

- [ ] **Step 2: Verify CLAUDE.md renders cleanly**

Run:
```bash
wc -l CLAUDE.md
```
Expected: > 80 lines with no truncation errors.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md with project context and workflow overview"
```

---

## Task 3: Write `/de-requirements` Command

**Files:**
- Create: `.claude/commands/de-requirements.md`

- [ ] **Step 1: Create `.claude/commands/` directory**

```bash
mkdir -p .claude/commands
```

- [ ] **Step 2: Write `.claude/commands/de-requirements.md`**

```markdown
You are a data engineering requirements analyst. Your job is to turn a
natural language requirement into a clear, structured requirements document.

## Input

The user's requirement is: $ARGUMENTS

If $ARGUMENTS is empty, ask: "Please describe the data engineering requirement
you'd like to work on."

---

## Step 1 — Assess Clarity

Before generating anything, analyze the input for ambiguity. A requirement is
ambiguous if ANY of the following are unclear:

- What data is being moved, transformed, or served
- Where data comes from (source systems, formats)
- Where data goes (destination, consumers)
- Volume/frequency expectations
- Success criteria or SLAs

If the requirement is sufficiently detailed (you can infer reasonable answers
to all 5 points above), skip to Step 2.

If ambiguous, ask clarifying questions — ONE AT A TIME, maximum 3 questions.
Wait for each answer before asking the next. After 3 questions (or if the user
says "skip"), proceed to Step 2 with whatever you have.

Good clarifying questions (use these patterns):
- "What is the data source — a database, message queue, API, or file system?"
- "How often should this pipeline run — real-time, hourly, daily?"
- "What format is the input data — JSON, CSV, Avro, Parquet?"
- "Who consumes the output — a dashboard, another pipeline, an analytics DB?"
- "Are there SLA requirements — e.g. data must be available within 1 hour?"

---

## Step 2 — Generate Requirements Document

Write a requirements document with these exact sections:

```
# Requirements: [short descriptive title]

**Date:** [today's date]
**Status:** Draft

---

## Goal
[One paragraph: what this pipeline/system does and why it exists]

## Inputs
[Bullet list: data sources, formats, schemas if known, frequency]

## Outputs
[Bullet list: destinations, formats, downstream consumers]

## Data Sources
[Table or bullets: system name, type, connection method, owner/team if known]

## SLAs & Performance
[Bullet list: latency requirements, throughput, availability, data freshness]

## Constraints
[Bullet list: tech stack restrictions, compliance/security requirements,
budget/infra limits, existing systems to integrate with]

## Assumptions
[Numbered list: everything you assumed that was not explicitly stated]
```

Fill every section. If a section has no known information, write
"Not specified — assumed [your assumption]" and add it to Assumptions.

---

## Step 3 — Stage and Request Approval

1. Write the requirements document to `.temp/requirements.md` using the
   Write tool.

2. Print exactly:
   ```
   Requirements document saved to `.temp/requirements.md`
   Please open the file and review it.

   Approve to save? (yes / feedback)
   ```

3. Wait for the user's response:
   - If the response is exactly `yes` (case-insensitive): copy the file from
     `.temp/requirements.md` to `specs/requirements.md`. Print:
     "Saved to `specs/requirements.md`. Run `/de-design` when ready."
   - If the response is anything else: treat it as feedback. Regenerate the
     requirements document incorporating the feedback. Go back to step 1 of
     Step 3 (re-stage, re-ask).
```

- [ ] **Step 3: Verify the file exists and is non-empty**

```bash
wc -l .claude/commands/de-requirements.md
```
Expected: > 60 lines.

- [ ] **Step 4: Commit**

```bash
git add .claude/commands/de-requirements.md
git commit -m "feat: add /de-requirements slash command"
```

---

## Task 4: Write `/de-design` Command

**Files:**
- Create: `.claude/commands/de-design.md`

- [ ] **Step 1: Write `.claude/commands/de-design.md`**

```markdown
You are a senior data engineering architect. Your job is to produce a scored
design document with 3 options and a task breakdown based on an approved
requirements document.

---

## Step 1 — Load Requirements

Read the file `specs/requirements.md` using the Read tool.

If the file does not exist, stop and print:
```
Error: `specs/requirements.md` not found.
Please run `/de-requirements` first to generate and approve a requirements doc.
```

---

## Step 2 — Clarifying Questions (Conditional)

Review the requirements. If ANY of the following are unclear, ask about them
ONE AT A TIME (max 2 questions). If all are clear, skip to Step 3.

- Preferred orchestration tool (Airflow, Prefect, dbt Cloud, cron, etc.)
- Preferred compute (Spark, Pandas, dbt, SQL, serverless, etc.)
- Approximate data volume (MB/day vs TB/day changes the design significantly)
- Cloud provider (AWS, GCP, Azure, on-prem)

Wait for each answer before asking the next.

---

## Step 3 — Generate 3 Design Options

For each option, provide:

```
### Option [N]: [Short Name]

**Description:** [2-3 sentences explaining the approach]

**Components:**
- [component 1: tool/service and its role]
- [component 2: tool/service and its role]
- (etc.)

**Data Flow:**
[source] → [step 1] → [step 2] → [destination]

**Scoring:**
| Criterion | Score (1-10) | Rationale |
|-----------|-------------|-----------|
| Complexity | X | [why] |
| Maintainability | X | [why] |
| Scalability | X | [why] |

**Weighted Score:** (complexity × 0.30) + (maintainability × 0.35) + (scalability × 0.35) = **X.XX**
```

After all 3 options, add:

```
### Recommendation

Option [N] — [Name] is recommended with a weighted score of X.XX.
[2-3 sentences explaining why this option best fits the requirements.]
```

The 3 options should represent genuinely different approaches. Examples:
- Simple batch vs streaming vs micro-batch
- SQL-first vs Python-first vs config-driven
- Managed service vs self-hosted vs serverless

---

## Step 4 — Generate Task Breakdown

Based on the recommended option (or whichever option the user prefers —
if they haven't indicated, use the recommended one), generate `tasks.md`:

```
# Tasks: [short title matching requirements doc]

**Based on:** Design Option [N] — [Name]
**Date:** [today's date]

---

## Phase 1: Infrastructure & Setup
1. [task]
2. [task]

## Phase 2: Pipeline Implementation
3. [task]
4. [task]

## Phase 3: Testing & Validation
5. [task]
6. [task]

## Phase 4: Documentation & Handoff
7. [task]
8. [task]
```

Each task should be a single unit of work (1-4 hours). Be specific:
"Set up Airflow DAG skeleton with correct schedule and connection IDs"
not "Set up Airflow".

---

## Step 5 — Stage and Request Approval

1. Write the design document to `.temp/design.md`.
2. Write the task breakdown to `.temp/tasks.md`.
3. Print:
   ```
   Design document saved to `.temp/design.md`
   Task breakdown saved to `.temp/tasks.md`
   Please review both files.

   Approve design to save? (yes / feedback)
   ```
4. Wait for response on the design:
   - `yes` → copy `.temp/design.md` to `specs/design.md`. Print "Design saved."
   - feedback → regenerate design incorporating feedback, re-stage, re-ask.
5. Once design is approved, ask:
   ```
   Approve tasks to save? (yes / feedback)
   ```
6. Wait for response on tasks:
   - `yes` → copy `.temp/tasks.md` to `specs/tasks.md`. Print:
     "Tasks saved to `specs/tasks.md`. Run `/de-implement` when ready."
   - feedback → regenerate tasks incorporating feedback, re-stage, re-ask.
```

- [ ] **Step 2: Verify the file exists and is non-empty**

```bash
wc -l .claude/commands/de-design.md
```
Expected: > 80 lines.

- [ ] **Step 3: Commit**

```bash
git add .claude/commands/de-design.md
git commit -m "feat: add /de-design slash command"
```

---

## Task 5: Write `/de-implement` Command

**Files:**
- Create: `.claude/commands/de-implement.md`

- [ ] **Step 1: Write `.claude/commands/de-implement.md`**

```markdown
You are a senior data engineer. Your job is to generate production-quality
pipeline code, infrastructure config, and mocked tests based on an approved
design and task breakdown.

---

## Step 1 — Load Design and Tasks

Read `specs/design.md` and `specs/tasks.md` using the Read tool.

If either file is missing, stop and print:
```
Error: Missing required files.
- `specs/design.md` found: [yes/no]
- `specs/tasks.md` found: [yes/no]

Please run `/de-design` to generate and approve both files first.
```

---

## Step 2 — Clarifying Question (Conditional)

Review the design. If the technology stack is still underspecified (e.g.,
"use Python" without knowing if it's PySpark, Pandas, or dbt), ask ONE
clarifying question to resolve it. If the stack is clear, skip this step.

Example: "The design mentions Python processing — should I use PySpark for
distributed processing or Pandas for single-node? Expected data volume from
requirements suggests [X]."

---

## Step 3 — Track Assumptions

As you plan the implementation, maintain a numbered list of anything you are
assuming that was not explicitly stated in the requirements or design.
Examples:
1. Assumed BigQuery dataset name: `raw_events`
2. Assumed Kafka topic name: `user_events`
3. Assumed Airflow connection ID: `bigquery_default`

You will output this list at the end.

---

## Step 4 — Generate Code

### Pipeline Code (`src/`)

Generate one Python file per concern. Follow these conventions:
- Python 3.12, type hints on all function signatures
- Docstrings on all public functions
- One class or set of related functions per file
- No hardcoded credentials — use environment variables or Airflow connections
- File naming: `src/<concern>.py` (e.g., `src/extractor.py`, `src/transformer.py`, `src/loader.py`)

### Infrastructure / Config (`src/`)

Generate infra and config files alongside code:
- Airflow DAG: `src/<pipeline_name>_dag.py`
- dbt models: `src/models/<model_name>.sql` + `src/dbt_project.yml`
- Terraform: `src/infra/main.tf`, `src/infra/variables.tf`
- YAML configs: `src/config/<name>.yml`

Generate whichever apply based on the design. Skip types not relevant to
the chosen design option.

### Mocked Tests (`tests/`)

For each `src/<concern>.py`, generate `tests/test_<concern>.py`.

Test conventions:
- Use `unittest.mock.patch` and `MagicMock` — NO real database or API calls
- Each test function tests one behavior
- Use `unittest.TestCase` as the base class
- Mock at the boundary (patch the external call, not the internal logic)
- Test: happy path, one error/edge case per function

Example test structure:
```python
import unittest
from unittest.mock import patch, MagicMock
from src.loader import load_to_bigquery

class TestLoader(unittest.TestCase):
    @patch("src.loader.bigquery.Client")
    def test_load_to_bigquery_success(self, mock_client):
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        mock_instance.load_table_from_dataframe.return_value.result.return_value = None

        load_to_bigquery(dataframe=MagicMock(), table_id="project.dataset.table")

        mock_instance.load_table_from_dataframe.assert_called_once()

    @patch("src.loader.bigquery.Client")
    def test_load_to_bigquery_raises_on_failure(self, mock_client):
        mock_client.return_value.load_table_from_dataframe.side_effect = Exception("BQ error")

        with self.assertRaises(Exception, msg="BQ error"):
            load_to_bigquery(dataframe=MagicMock(), table_id="project.dataset.table")
```

---

## Step 5 — Compute Confidence Score

Count:
- **Explicit requirements:** requirements that were clearly stated in `specs/requirements.md`
- **Assumed requirements:** things in your assumptions list that weren't stated

Confidence score = explicit / (explicit + assumed) × 100, rounded to nearest 5%.

---

## Step 6 — Stage and Request Approval

1. Write all generated files under `.temp/`:
   - `.temp/src/<filename>` for each src file
   - `.temp/tests/<filename>` for each test file
2. Print:
   ```
   Implementation staged in `.temp/`:

   Source files:
   - .temp/src/<file1>
   - .temp/src/<file2>
   (etc.)

   Test files:
   - .temp/tests/<file1>
   (etc.)

   ---
   Confidence Score: XX%
   
   Assumptions:
   1. [assumption]
   2. [assumption]
   (etc.)

   Please review the staged files.

   Approve to save? (yes / feedback)
   ```
3. Wait for response:
   - `yes` → copy all `.temp/src/*` to `src/` and `.temp/tests/*` to `tests/`.
     Print: "Implementation saved to `src/` and `tests/`."
   - feedback → regenerate incorporating feedback, re-stage all files, re-ask.
```

- [ ] **Step 2: Verify the file exists and is non-empty**

```bash
wc -l .claude/commands/de-implement.md
```
Expected: > 100 lines.

- [ ] **Step 3: Commit**

```bash
git add .claude/commands/de-implement.md
git commit -m "feat: add /de-implement slash command"
```

---

## Task 6: End-to-End Smoke Test

Verify all three commands work with a sample requirement.

- [ ] **Step 1: Open Claude Code in the project**

```bash
cd spec-based
claude
```

- [ ] **Step 2: Run `/de-requirements` with a sample**

In Claude Code:
```
/de-requirements build a daily batch pipeline that reads CSV files from S3, applies basic transformations, and loads the result into a PostgreSQL table
```

Expected: Claude asks 0-3 clarifying questions, generates `.temp/requirements.md`, prints the path, asks for approval.

- [ ] **Step 3: Approve requirements**

Type `yes` in Claude Code.

Expected: `specs/requirements.md` is created.

- [ ] **Step 4: Run `/de-design`**

```
/de-design
```

Expected: Claude reads `specs/requirements.md`, asks 0-2 questions, presents 3 scored options, stages `.temp/design.md` and `.temp/tasks.md`.

- [ ] **Step 5: Approve design and tasks**

Type `yes` twice.

Expected: `specs/design.md` and `specs/tasks.md` are created.

- [ ] **Step 6: Run `/de-implement`**

```
/de-implement
```

Expected: Claude reads both spec files, generates `src/` and `tests/` files under `.temp/`, prints confidence score and assumptions list, asks for approval.

- [ ] **Step 7: Approve implementation**

Type `yes`.

Expected: Files appear in `src/` and `tests/`.

- [ ] **Step 8: Verify final state**

```bash
find specs/ src/ tests/ -type f | sort
```
Expected: requirements.md, design.md, tasks.md in specs/; Python files in src/ and tests/.

- [ ] **Step 9: Clean up test artifacts and commit**

```bash
rm -f specs/requirements.md specs/design.md specs/tasks.md
find src/ tests/ -name "*.py" -delete
find .temp/ -not -name ".gitkeep" -delete
git add -A
git commit -m "test: verify end-to-end smoke test, clean up sample artifacts"
```

---

## Task 7: Final Commit & README

- [ ] **Step 1: Verify `.temp/` contents are gitignored**

```bash
git status
```
Expected: `.temp/` contents do not appear as untracked files (only `.temp/.gitkeep` is tracked).

- [ ] **Step 2: Final commit with all files**

```bash
git add .
git status  # verify nothing unexpected is staged
git commit -m "chore: finalize project structure"
```
