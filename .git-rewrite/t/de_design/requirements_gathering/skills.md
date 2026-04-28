# Skills: Requirements Gathering Agent

## Purpose
Reads requirements from a Jira ticket or a local document, detects the request type, validates minimum required fields, and returns a structured `RequirementsOutput` with a `run_plan` telling the orchestrator which execution modules to invoke.

## Capabilities
- `detect_request_type`: determines whether the request is a bug, enhancement, or new development — from Jira issue type field first, then keywords in description/comments, rejects if neither is found
- `read_jira_ticket`: fetches issue body — summary, description, status, priority, assignee, issue type
- `read_jira_comments`: fetches all comments on a Jira issue
- `classify_requirements`: assigns two labels — `ingestion_type` (`batch`, `streaming`, `unknown`) and `output_type` (`pipeline`, `report`, `data_model`, `api_integration`, `migration`, `ml_feature`, `unknown`)
- `extract_requirements`: parses raw text into a structured requirements object, scoped to the fields required for the detected request type
- `build_run_plan`: determines which execution modules the orchestrator should invoke based on request type and whether the enhancement touches data structures
- `write_jira_summary`: posts an AI-generated summary comment back to Jira on success, or a rejection comment with the missing fields message on failure
- `read_document`: loads a local `.txt` or `.md` file as a requirements source

## Request Type and Module Activation

Request type detection priority:
1. Jira issue type field (if one of: bug, enhancement, new development)
2. Exact keyword in description or comments
3. Reject if not found in either

Module activation per request type — `validator` always runs last:
- bug: `impl_steps → validator`
- enhancement: `architecture → impl_steps → validator` (with `data_model` prepended if the enhancement modifies or adds entities, schemas, or relationships)
- new development: `data_model → architecture → tool_selector → impl_steps → validator`

## Invocation

```python
from gathering import RequirementsAgent

agent = RequirementsAgent(config)

# choose one
req = agent.run_from_jira("SCRUM-5")
# req = agent.run_from_document("output/requirements.md")

next_agent.run(req)
```

## Configuration
- `api_key`: Anthropic API key (required)
- `model`: Claude model string (default: `claude-sonnet-4-20250514`)
- `jira_base_url`: Jira instance base URL
- `jira_email`: Jira account email
- `jira_api_key`: Jira API token
- `write_back_to_jira`: bool, default `False`

## confidence
`RequirementsOutput.confidence` is a float 0–1 set by the extraction step reflecting how completely the source text covered the expected requirements fields for the detected request type. 0.0 means nearly nothing was extractable; 1.0 means all fields were populated with substantive content. Use it as the primary signal for whether to proceed downstream or request clarification.

When confidence is below `confidence_threshold` (default 0.6, configurable), `RequirementsOutput.low_confidence_warning` is populated with a contextual message explaining which fields are missing or thin and why providing them would improve the design. The agent still returns a full `RequirementsOutput` — the warning is a soft signal, not a block. The orchestrator should surface `low_confidence_warning` to the requester and allow them to proceed or provide more detail.

## When to use `write_back_to_jira`
Set to `True` when the ticket is the system of record and stakeholders track progress there. Do not use it when requirements came from a document source, when the ticket is read-only, or when confidence is below `confidence_threshold` — in that case flag the gap to the orchestrator instead.

## Error and Edge Case Behaviour
- Ticket not found: raises `requests.HTTPError` (404). Orchestrator should catch and prompt user for a valid ticket ID.
- Request type not found: raises `RequirementsRejected` with message "To design the right solution, I need to understand whether this is a bug, enhancement, or new development...".
- Insufficient requirements: raises `RequirementsRejected` if minimum required fields for the detected request type are missing. Minimum fields are: bug — `objective`, `functional_requirements`, `acceptance_criteria`; enhancement — `objective`, `functional_requirements`, `acceptance_criteria`, `constraints`; new development — `objective`, `data_requirements.source_systems`. Full detail in `implementation.md`.
- Empty document: extraction returns `confidence` of 0.0 and raises `RequirementsRejected`.
- Partial requirements (some fields `null`): agent still returns `RequirementsOutput` with available fields populated. Use `confidence` to decide whether to proceed or request clarification.
- Tool loop cap: Jira fetch is capped at 6 tool rounds. If exhausted, raises `RuntimeError`. Treat as a transient failure and retry once before escalating.
- Jira write-back failure: non-fatal. Logged and skipped. Does not affect the returned `RequirementsOutput` or raised `RequirementsRejected`.
