# Skills: Requirements Gathering Agent

## Purpose
Reads requirements from a Jira ticket or a local document, detects the request type, validates minimum required fields, and returns a structured `RequirementsOutput` with a `run_plan` telling the orchestrator which execution modules to invoke.

## Capabilities
- `detect_request_type`: determines whether the request is a bug, enhancement, or new development — from Jira issue type field first, then keywords in description/comments, rejects if neither is found
- `read_jira_ticket`: fetches issue body — summary, description, status, priority, assignee, issue type
- `read_jira_comments`: fetches all comments on a Jira issue
- `classify_requirements`: assigns two labels — `ingestion_type` (`batch`, `streaming`, `unknown`) and `output_type` (`pipeline`, `report`, `data_model`, `api_integration`, `migration`, `ml_feature`, `unknown`)
- `extract_requirements`: parses raw text into a structured requirements object, scoped to the fields required for the detected request type; extracts specific tools mentioned alongside the stack into `technology.preferred_tools`
- `build_run_plan`: determines which execution modules the orchestrator should invoke based on request type and whether the enhancement touches data structures
- `write_jira_summary`: posts an AI-generated summary comment back to Jira on success, or a rejection comment with the missing fields message on failure
- `read_document`: loads a local `.txt` or `.md` file as a requirements source

## Request Type and Module Activation

Request type detection priority:
1. Jira issue type field (if one of: bug, enhancement, new development)
2. Exact keyword in description or comments
3. Reject if not found in either

Module activation per request type:
- bug: `implementation_steps`
- enhancement: `implementation_steps` (with `data_model` prepended if the enhancement modifies or adds entities, schemas, or relationships)
- new development: `data_model → architecture → implementation_steps`

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

When confidence is below `confidence_threshold` (default 0.6, configurable), the agent infers values only for design-critical fields that are absent and cannot be derived from the source — specifically `technology.stack`, `technology.cloud_or_onprem`, `technology.environment`, `non_functional.latency`, and `data_requirements.data_types` — using external context such as industry norms or technology conventions. Fields that can be derived from explicit source values are populated directly without an `inferred_assumptions` entry. Non-design fields such as `business_context` are populated where possible but never added to `inferred_assumptions`. Each genuinely external inference is recorded in `inferred_assumptions` using the format `"<field>: assumed <value> because <reason>"`. `low_confidence_warning` summarises which fields were inferred from external context and invites the requester to confirm or correct them. Both are included in the Jira write-back comment. When confidence is at or above the threshold, `low_confidence_warning` is null and `inferred_assumptions` is empty.

## When to use `write_back_to_jira`
Set to `True` when the ticket is the system of record and stakeholders track progress there. Especially recommended when confidence is below `confidence_threshold` — that is when the inferred assumptions comment is most valuable, as it gives the ticket author a concrete list to confirm or correct directly on the ticket. Do not use it when requirements came from a document source or when the ticket is read-only.

## Error and Edge Case Behaviour
- Ticket not found: raises `requests.HTTPError` (404). Orchestrator should catch and prompt user for a valid ticket ID.
- Request type not found: raises `RequirementsRejected` with message "To design the right solution, I need to understand whether this is a bug, enhancement, or new development...".
- Insufficient requirements: raises `RequirementsRejected` if minimum required fields for the detected request type are missing. Minimum fields are: bug — `objective`, `functional_requirements`, `acceptance_criteria`; enhancement — `objective`, `functional_requirements`, `acceptance_criteria`, `constraints`, `existing_architecture`; new development — `objective`, `data_requirements.source_systems`. Full detail in `implementation.md`.
- `source_connections` is populated when connection details are present in the source. Each entry has `db_type` (engine e.g. `mysql`), `database` (schema/database name e.g. `agentichub`), `host`, `port`, `username`, `instance_connection_name` (Cloud SQL only), `source_tables`. Empty list if not provided. No passwords are stored.
- Empty document: extraction returns `confidence` of 0.0 and raises `RequirementsRejected`.
- Partial requirements (some fields `null`): agent still returns `RequirementsOutput` with available fields populated. Use `confidence` to decide whether to proceed or request clarification.
- Tool loop cap: Jira fetch is capped at 6 tool rounds. If exhausted, raises `RuntimeError`. Treat as a transient failure and retry once before escalating.
- Jira write-back failure: non-fatal. Logged and skipped. Does not affect the returned `RequirementsOutput` or raised `RequirementsRejected`.
