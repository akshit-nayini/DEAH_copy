# Skills: Implementation Steps Agent

## Purpose
Receives summaries from upstream agents and produces a structured Markdown implementation plan for consumption by a downstream development agent.

## Capabilities
- `generate_implementation_plan`: produces a phased, ordered implementation plan from input summaries; assumes infrastructure is already provisioned; includes a connectivity check step if source and destination systems differ; testing phase contains concrete derived test cases; always ends with a handover phase covering runbook updates
- `surface_risks`: presents risks and mitigations from the architecture summary as reference warnings — not as steps
- `surface_blockers`: lists open blockers prominently so the development agent knows what must be resolved before proceeding

## Input Combinations by Request Type
- bug: `requirements_summary` only
- enhancement: `architecture_summary` only
- new development: `architecture_summary` + `data_model_summary`

## Output
A Markdown file written to `output/{project_name}/implementation_steps.md`. The document is structured as:
- Open blockers section (omitted if none)
- Risks and mitigations section (reference only)
- Implementation phases with ordered, actionable steps (infrastructure assumed provisioned; connectivity check included as first step if source and destination systems differ)
- Testing phase with concrete test cases derived from inputs
- Handover phase (always present) with runbook update steps

## Invocation

```python
from implementation_steps import ImplStepsAgent

agent = ImplStepsAgent(config)

output = agent.run(
    request_type="new development",
    project_name="Customer 360 Data Platform",
    architecture_summary=arch_dict,
    data_model_summary=dm_dict,
)
```

## Configuration
- `api_key`: Anthropic API key (required)
- `model`: Claude model string (default: `claude-sonnet-4-20250514`)
- `output_root`: root directory for output files (default: `output`)

## Error and Edge Case Behaviour
- Missing required summary for request type: raises `ValueError` before any API call with a clear message stating which summary is missing
- Output directory created automatically if it does not exist
- Project name is slugified for the output path — spaces and slashes become underscores
