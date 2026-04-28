# Implementation: Implementation Steps Agent

## File Layout
- `test_implementation_steps.py` — local test runner
- `implementation_steps/__init__.py` — exposes `ImplStepsAgent`
- `implementation_steps/agent.py` — `ImplStepsAgent` and `ImplStepsOutput`
- `implementation_steps/prompts.py` — system prompt and generation prompt

## Dependencies
- `anthropic`

## Environment Variables
- `ANTHROPIC_API_KEY` (required)
- `CLAUDE_MODEL` — model override, default `claude-sonnet-4-20250514`

## Input Schema
All inputs are plain dicts loaded from JSON. Caller passes only the summaries relevant to the request type.

- `request_type: str` — `"bug"`, `"enhancement"`, or `"new development"`
- `project_name: str` — used in the document header and output path
- `requirements_summary: dict | None` — required for bug, omitted otherwise
- `architecture_summary: dict | None` — required for enhancement and new development
- `data_model_summary: dict | None` — required for new development only

## Output Schema (`ImplStepsOutput`)
- `project_name: str`
- `request_type: str`
- `output_path: Path` — resolved path where the Markdown file was written
- `markdown: str` — full Markdown content of the implementation plan

`.write()` creates parent directories and writes `markdown` to `output_path`.

## Output Document Structure
Claude generates the Markdown in this order:

- `# Implementation Plan: {project_name}` — document header
- `## ⚠️ Open Blockers` — omitted entirely if no blockers present; lists items that must be resolved before or during implementation
- `## ⚠️ Risks & Mitigations` — reference warnings only; not implementation steps
- `## Phase N: <Phase Name>` — one or more implementation phases in natural build sequence; infrastructure is assumed provisioned; if source and destination systems differ, first step of the first phase is a connectivity check
- `## Phase N: Testing` — concrete test cases derived from inputs; each test case states what is being tested, the input condition, and the expected outcome
- `## Phase N: Handover` — always present; steps to update the runbook covering pipeline design summary, operational procedures, known risks, escalation paths, and sign-off confirmation

## Prompts (`implementation_steps/prompts.py`)
`SYSTEM_PROMPT` contains all fixed rules and the document structure template — phase format, connectivity check rule, testing rule, handover rule, risk and blocker handling. Kept in the system prompt so these instructions are not repeated in the user turn on every call.

`generation_prompt(...)` embeds only the variable data — project name, request type, and the provided summary JSON blocks. No structural instructions. This minimises user-turn token cost per call.

## Design Notes
- Single Claude call — no tool loop, no agentic iteration.
- Input validation happens before the API call — `ValueError` is raised immediately if required summaries are missing for the request type.
- `max_tokens` is set to 8096 to accommodate detailed multi-phase plans.
- Output path is derived from `project_name` via `_slugify` — spaces and slashes become underscores.

## Running Tests

```bash
# New development
python test_implementation_steps.py --type "new development" \
    --architecture sample_handoff.json \
    --data-model sample_data_model.json \
    --project "Customer 360 Data Platform"

# Enhancement
python test_implementation_steps.py --type enhancement \
    --architecture sample_handoff.json \
    --project "Customer 360 Data Platform"

# Bug
python test_implementation_steps.py --type bug \
    --requirements sample_requirements.json \
    --project "Customer 360 Data Platform"
```
