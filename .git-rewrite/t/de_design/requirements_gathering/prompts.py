# gathering/prompts.py
"""
System and user prompts for the Requirements Gathering Agent.
"""

SYSTEM_PROMPT = """\
You are a senior data engineer and business analyst assistant.
Your job is to read raw requirements text (from Jira tickets, call transcripts,
or requirement documents) and produce clean, structured JSON that downstream
data-design agents can consume without further interpretation.

Rules:
- Always respond with valid, parseable JSON when asked to extract requirements.
- Never invent information that isn't present; use null for missing fields.
- Classification is two-axis:
    ingestion_type: batch | streaming | unknown
    output_type: pipeline | report | data_model | api_integration | migration | ml_feature | unknown
  Return both as a dict: {"ingestion_type": "...", "output_type": "..."}
- Confidence is a float 0.0-1.0 reflecting how complete the source text is.
- If confidence is below the threshold passed in the prompt, populate
  low_confidence_warning with a single sentence explaining which fields are
  missing or thin and why providing them would improve the design.
  If confidence is at or above the threshold, set low_confidence_warning to null.
- When using Jira tools, read BOTH the ticket body and all comments before
  declaring you have enough information.
- Request type detection follows this priority order:
    1. Jira issue type field (if present and one of: bug, enhancement, new development)
    2. Explicit keyword in description or comments (look for: bug, enhancement, new development)
    3. If not found in either, reject with a clear message asking for the request type
- Required fields vary by request type:
    bug:             objective, functional_requirements, acceptance_criteria
    enhancement:     objective, functional_requirements, acceptance_criteria, constraints
    new development: objective, data_requirements.source_systems
- For enhancement, infer whether the change touches data structures. Set
  data_model_required: true only if the enhancement modifies or adds entities,
  schemas, or relationships. Otherwise set it to false.
- Before returning, validate that the minimum required fields for the detected
  request type are present. If any are missing, return a rejection object
  specifying exactly which fields are missing and what information is needed
  to populate them.
"""


def extraction_prompt(raw_text: str, jira_issue_type: str | None = None, confidence_threshold: float = 0.6) -> str:
    issue_type_line = (
        f"Jira issue type field value: {jira_issue_type}"
        if jira_issue_type
        else "Jira issue type field value: not provided"
    )
    return f"""\
Extract structured requirements from the text below.

{issue_type_line}
Confidence threshold: {confidence_threshold}

Step 1 — Determine request_type:
  - If the Jira issue type field is one of: bug, enhancement, new development — use it.
  - Else look for those exact keywords in the source text.
  - If not found in either, reject immediately with the message format below.

Step 2 — Validate minimum required fields for the detected request_type:
  bug:             objective, functional_requirements, acceptance_criteria
  enhancement:     objective, functional_requirements, acceptance_criteria, constraints
  new development: objective, data_requirements.source_systems

Step 3 — If all minimum fields are present, return ONLY this JSON object
(no markdown preamble, no explanation):

{{
  "status": "ok",
  "request_type": "bug | enhancement | new development",
  "data_model_required": true | false,
  "project_name": "string",
  "objective": "string",
  "business_context": "string",
  "functional_requirements": ["string", ...],
  "data_requirements": {{
    "source_systems": ["string", ...],
    "data_types": "string",
    "volume": "string",
    "frequency": "string"
  }},
  "technology": {{
    "stack": "string",
    "environment": "string",
    "cloud_or_onprem": "string"
  }},
  "non_functional": {{
    "performance": "string",
    "scalability": "string",
    "latency": "string",
    "sla": "string"
  }},
  "security": {{
    "data_sensitivity": "string",
    "access_controls": "string",
    "compliance": "string"
  }},
  "constraints": {{
    "budget": "string",
    "timeline": "string",
    "technical_limitations": "string"
  }},
  "assumptions": ["string", ...],
  "acceptance_criteria": ["string", ...],
  "expected_outputs": ["string", ...],
  "classification": {{
    "ingestion_type": "batch | streaming | unknown",
    "output_type": "pipeline | report | data_model | api_integration | migration | ml_feature | unknown"
  }},
  "confidence": 0.0,
  "low_confidence_warning": "string | null"
}}

If minimum fields are missing OR request_type cannot be determined, return ONLY
this rejection object (no markdown preamble, no explanation):

{{
  "status": "rejected",
  "missing_fields": ["field_name", ...],
  "message": "To design the right solution, I need to understand <what is missing and why it matters for the design>."
}}

The message must be a single coherent sentence starting with
"To design the right solution, I need to understand" and must explain
not just what is missing but why it is needed to proceed.

--- SOURCE TEXT ---
{raw_text}
--- END ---
"""


def classification_prompt(summary: str) -> str:
    """Standalone classification prompt (used by orchestrator if needed)."""
    return f"""\
Classify the following requirements summary on two axes:
  ingestion_type: batch | streaming | unknown
  output_type: pipeline | report | data_model | api_integration | migration | ml_feature | unknown

Return JSON only (no markdown preamble, no explanation):
{{
  "classification": {{
    "ingestion_type": "...",
    "output_type": "..."
  }},
  "confidence": 0.0,
  "reason": "..."
}}

Summary:
{summary}
"""
