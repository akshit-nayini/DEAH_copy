# Implementation: Requirements Gathering Agent

## File Layout
- `jira_rw.py` — Jira HTTP client, single source of truth for all Jira I/O
- `test_requirements.py` — local test runner
- `requirements_template.txt` — example document source
- `gathering/__init__.py` — exposes `RequirementsAgent`
- `gathering/agent.py` — `RequirementsAgent`, `RequirementsOutput`, `RequirementsRejected`, `RUN_PLAN`
- `gathering/prompts.py` — system prompt and extraction prompt
- `gathering/tools.py` — tool definitions and handlers

## Dependencies
- `anthropic`
- `requests`

## Environment Variables
- `ANTHROPIC_API_KEY` (required)
- `CLAUDE_MODEL` — model override, default `claude-sonnet-4-20250514`
- `JIRA_BASE_URL` — required if using Jira source
- `JIRA_EMAIL` — required if using Jira source
- `JIRA_API_KEY` — required if using Jira source
- `confidence_threshold` — float, default `0.6`; controls when `low_confidence_warning` is populated

## Minimum Required Fields by Request Type
Validated before returning `RequirementsOutput`. Missing fields trigger `RequirementsRejected`.

- bug: `objective`, `functional_requirements`, `acceptance_criteria`
- enhancement: `objective`, `functional_requirements`, `acceptance_criteria`, `constraints`
- new development: `objective`, `data_requirements.source_systems`

If `request_type` itself cannot be determined, that is treated as a missing field and triggers rejection immediately.

`RequirementsRejected` carries:
- `missing_fields: list[str]` — names of fields that could not be populated
- `message: str` — starts with "To design the right solution, I need to understand..." and explains what is missing and why it matters

```python
from gathering import RequirementsAgent
from gathering.agent import RequirementsRejected

try:
    req = agent.run_from_jira("SCRUM-5")
except RequirementsRejected as e:
    print(e.message)          # surface to requester
    print(e.missing_fields)   # programmatic access for the orchestrator
```

## Output Schema (`RequirementsOutput`)
All fields are `str | None` unless noted. `None` means the field was absent or not extractable from the source.

- `source: str` — `"jira"` or `"document"`
- `ticket_id: str | None` — Jira key, or `None` if document source
- `request_type: str` — `"bug"`, `"enhancement"`, or `"new development"`
- `run_plan: list[str]` — ordered list of execution modules for the orchestrator to invoke; valid values are `"data_model"`, `"architecture"`, `"tool_selector"`, `"impl_steps"`, `"validator"`
- `project_name: str | None`
- `objective: str | None`
- `business_context: str | None`
- `functional_requirements: list[str]` — empty list if none found
- `data_requirements: dict` — keys: `source_systems: list[str] | None`, `data_types: str | None`, `volume: str | None`, `frequency: str | None`
- `technology: dict` — keys: `stack: str | None`, `environment: str | None`, `cloud_or_onprem: str | None`
- `non_functional: dict` — keys: `performance: str | None`, `scalability: str | None`, `latency: str | None`, `sla: str | None`
- `security: dict` — keys: `data_sensitivity: str | None`, `access_controls: str | None`, `compliance: str | None`
- `constraints: dict` — keys: `budget: str | None`, `timeline: str | None`, `technical_limitations: str | None`
- `assumptions: list[str]` — empty list if none found
- `acceptance_criteria: list[str]` — empty list if none found
- `expected_outputs: list[str]` — empty list if none found
- `classification: dict` — two keys: `ingestion_type: "batch" | "streaming" | "unknown"`, `output_type: "pipeline" | "report" | "data_model" | "api_integration" | "migration" | "ml_feature" | "unknown"`
- `confidence: float` — see `skills.md` for definition and usage
- `low_confidence_warning: str | None` — populated by Claude when confidence is below `confidence_threshold`; explains which fields are missing or thin and why providing them would improve the design. `null` when confidence is at or above the threshold.
- `raw_text: str` — original source text as ingested

Serialisation methods on the dataclass:
- `.to_markdown()` — human-readable report
- `.to_dict()` — JSON-serialisable dict

## Run Plan Logic
Defined in `RUN_PLAN` constant in `agent.py`. Built by `_build_run_plan()`. `validator` is always appended last.

- bug: `impl_steps → validator`
- enhancement: `architecture → impl_steps → validator`, with `data_model` prepended if `data_model_required` is `True`
- new development: `data_model → architecture → tool_selector → impl_steps → validator`

`data_model_required` is inferred by Claude during extraction — set to `True` only if the enhancement modifies or adds entities, schemas, or relationships.

## Tool Definitions
Defined in `gathering/tools.py`, backed by `jira_rw.py`. `tools.py` patches `jira_rw` credentials at runtime from `JiraContext`.

- `jira_get_ticket` — input: `ticket_id: str`, output: `{ ticket_id, issue_type, summary, status, priority, assignee, created, updated, description }`
- `jira_get_comments` — input: `ticket_id: str`, output: `{ comments: [ { author, created, body } ] }`
- `jira_add_comment` — input: `ticket_id: str, text: str`, output: `{ status, comment_id }`

`issue_type` is returned lowercased from the Jira `issuetype.name` field and passed directly to `extraction_prompt` as the first signal for request type detection.

## Prompts (`gathering/prompts.py`)
Two prompts are defined:

`SYSTEM_PROMPT` instructs Claude to act as a senior data engineer and business analyst. It defines the two-axis classification schema, the request type detection priority order, the minimum required fields per request type, the `data_model_required` inference rule for enhancements, and the `low_confidence_warning` population rule.

`extraction_prompt(raw_text, jira_issue_type, confidence_threshold)` embeds the raw source text, the Jira issue type field value, and the confidence threshold. It instructs Claude to follow a three-step process: detect request type, validate minimum fields, then extract. Returns either `{"status": "ok", ...}` or `{"status": "rejected", ...}` as a bare JSON object with no preamble. If extraction quality is low or parse failures occur, check whether the source text is complete and whether the model returned wrapped JSON.

## Design Notes
- The Jira fetch and extraction are two separate Claude calls. The fetch call runs the tool loop and captures `issue_type` from the `jira_get_ticket` result. The extraction call receives the assembled text plus `issue_type` and `confidence_threshold` and returns structured JSON.
- Jira tool loop is capped at `MAX_TOOL_ROUNDS = 6` in `agent.py`.
- When `write_back_to_jira` is `True` and extraction raises `RequirementsRejected`, the agent posts a rejection comment to the Jira ticket before re-raising — so the ticket author sees exactly what's missing without any engineer needing to relay it manually.
- Jira write-back failure is non-fatal — logged and skipped, does not affect the returned `RequirementsOutput` or raised `RequirementsRejected`.

## Running Tests
Default output is printed to stdout as both Markdown and JSON. If `--out` is specified, Markdown is saved to that path; no file is written otherwise.

```bash
# From Jira
python test_requirements.py --source jira --ticket SCRUM-5

# From Jira + write summary comment back
python test_requirements.py --source jira --ticket SCRUM-5 --write-back

# From local document
python test_requirements.py --source document --file requirements_template.txt

# Save Markdown output to file
python test_requirements.py --source jira --ticket SCRUM-5 --out output/requirements.md

# Print JSON only
python test_requirements.py --source document --file requirements_template.txt --format json
```
