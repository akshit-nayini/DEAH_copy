# gathering/prompts.py
"""
System and user prompts for the Requirements Gathering Agent.
"""

from __future__ import annotations
from typing import Optional


# ── System prompts ────────────────────────────────────────────────────────────

SYSTEM_PROMPT_FETCH = """\
You are a Jira data fetcher. Use the available tools to fetch the requested
Jira ticket and all its comments. Return the raw content — do not summarise,
interpret, or add commentary. Read both the ticket body and all comments
before finishing.
"""

SYSTEM_PROMPT_EXTRACT = """\
You are a senior data engineer and business analyst assistant.
Extract structured requirements from raw source text.
Return a single JSON object only — no markdown fences, no explanation, no preamble.

Rules:
- Never invent information not present in the source; use null for missing fields.
- Classification is two-axis:
    ingestion_type: batch | streaming | unknown
    output_type: pipeline | report | data_model | api_integration | migration | ml_feature | unknown
- Request type detection priority:
    1. Jira issue type field (if one of: bug, enhancement, new development)
    2. Exact keyword in description or comments
    3. If not found, return status: rejected
- Reject ONLY if:
    1. objective is missing for any request type, OR
    2. data_requirements.source_systems is missing for new development, OR
    3. existing_architecture is missing for enhancement, OR
    4. For new development: source_connections is empty, OR every entry has
       all of host, instance_connection_name, database, and source_tables
       null or empty — meaning the ticket names a source but provides zero
       usable connection details (e.g. db_type present but everything else null).
       When rejecting for this reason, list ALL null or empty fields in
       missing_fields (host, instance_connection_name, database, source_tables,
       port, username) so the author sees everything missing at once.
  These are the ONLY rejection conditions. Any other missing field must be
  derived or left to inferred_assumptions — never a reason to reject.
- functional_requirements, business_context, acceptance_criteria, and
  expected_outputs must always be populated: derive them from objective,
  data_requirements, technology, or non_functional if not stated directly.
- For enhancement, set data_model_required: true only if the change modifies
  or adds entities, schemas, or relationships.
- For technology.preferred_tools: extract any specific tools, services, or
  frameworks mentioned alongside the stack (e.g. "GCP, Airflow Composer" →
  preferred_tools: ["Airflow Composer"]). Empty list if none mentioned.
- For source_connections: extract connection details for SOURCE (input) systems
  only — systems that data is read FROM. Do NOT include target or destination
  systems (e.g. BigQuery, Redshift, GCS as write targets) even if they appear
  in the Interfaces / Connections section.
  Map fields as follows:
    db_type: database engine type lowercased (e.g. mysql, postgres, oracle, mssql)
    database: actual database or schema name to connect to (e.g. agentichub,
      sales_db) — this is distinct from db_type; look for it in the connection
      string, TABLE_SCHEMA, or any mention of a schema or database name
    instance_connection_name: GCP Cloud SQL instance connection name if present
      (format: project:region:instance, e.g. verizon-data:us-central1:mysql-instance)
    host: IP address or hostname (e.g. 34.70.79.163)
    port: port number as a string (e.g. "3306")
    username: source username
    source_tables: list of source tables mentioned
  Connection strings like "instance-name, ip, port" should be split
  accordingly — the first part is instance_connection_name, second is host,
  third is port. Populate one entry per source system. Do not include
  section labels or field names (e.g. "Connection Details", "Databases",
  "APIs") as source table entries — source_tables must only contain
  actual table or dataset names.
  always attempt to populate from source. Never add to inferred_assumptions.
- inferred_assumptions are only for design-critical fields
  (technology.stack, technology.cloud_or_onprem, technology.environment,
  non_functional.latency, data_requirements.data_types) whose values come
  from outside the provided requirements. Never restate extracted or derived
  values as inferred assumptions.
- Set status: rejected ONLY when objective is missing, or source_systems is
  missing for new development, or existing_architecture is missing for
  enhancement, or source_connections has all null/empty detail fields for
  new development. In all other cases set status: ok.
  message must start with "To design the right solution, I need to understand"
  and explain what is missing and why it matters.
"""


# ── Extraction tool definition ────────────────────────────────────────────────

EXTRACTION_TOOL = {
    "name": "extract_requirements",
    "description": "Store the structured requirements extracted from the source text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["ok", "rejected"]
            },
            "missing_fields": {
                "type": "array",
                "items": {"type": "string"}
            },
            "message": {"type": "string"},
            "request_type": {
                "type": "string",
                "enum": ["bug", "enhancement", "new development"]
            },
            "data_model_required": {"type": "boolean"},
            "project_name": {"type": "string"},
            "objective": {"type": "string"},
            "business_context": {"type": "string"},
            "functional_requirements": {
                "type": "array",
                "items": {"type": "string"}
            },
            "data_requirements": {
                "type": "object",
                "properties": {
                    "source_systems": {"type": "array", "items": {"type": "string"}},
                    "data_types": {"type": "string"},
                    "volume": {"type": "string"},
                    "frequency": {"type": "string"}
                }
            },
            "technology": {
                "type": "object",
                "properties": {
                    "stack": {"type": "string"},
                    "environment": {"type": "string"},
                    "cloud_or_onprem": {"type": "string"},
                    "preferred_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific tools or services mentioned e.g. Airflow, Composer, dbt, Spark"
                    }
                }
            },
            "non_functional": {
                "type": "object",
                "properties": {
                    "performance": {"type": "string"},
                    "scalability": {"type": "string"},
                    "latency": {"type": "string"},
                    "sla": {"type": "string"}
                }
            },
            "security": {
                "type": "object",
                "properties": {
                    "data_sensitivity": {"type": "string"},
                    "access_controls": {"type": "string"},
                    "compliance": {"type": "string"}
                }
            },
            "constraints": {
                "type": "object",
                "properties": {
                    "budget": {"type": "string"},
                    "timeline": {"type": "string"},
                    "technical_limitations": {"type": "string"}
                }
            },
            "source_connections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "db_type": {
                            "type": "string",
                            "description": "Database engine type e.g. mysql, postgres, oracle, mssql"
                        },
                        "database": {
                            "type": "string",
                            "description": "Database or schema name to connect to e.g. agentichub, sales_db"
                        },
                        "instance_connection_name": {"type": "string"},
                        "host": {"type": "string"},
                        "port": {"type": "string"},
                        "username": {"type": "string"},
                        "source_tables": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    }
                }
            },
            "assumptions": {
                "type": "array",
                "items": {"type": "string"}
            },
            "inferred_assumptions": {
                "type": "array",
                "items": {"type": "string"}
            },
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string"}
            },
            "expected_outputs": {
                "type": "array",
                "items": {"type": "string"}
            },
            "classification": {
                "type": "object",
                "properties": {
                    "ingestion_type": {
                        "type": "string",
                        "enum": ["batch", "streaming", "unknown"]
                    },
                    "output_type": {
                        "type": "string",
                        "enum": ["pipeline", "report", "data_model", "api_integration", "migration", "ml_feature", "unknown"]
                    }
                }
            },
            "confidence": {"type": "number"},
            "low_confidence_warning": {"type": "string"}
        },
        "required": ["status"]
    }
}


# ── User prompts ──────────────────────────────────────────────────────────────

def extraction_prompt(raw_text: str, jira_issue_type: Optional[str] = None, confidence_threshold: float = 0.6) -> str:
    issue_type_line = (
        f"Jira issue type field value: {jira_issue_type}"
        if jira_issue_type
        else "Jira issue type field value: not provided"
    )
    return f"""\
Extract requirements from the source text below and return a JSON object.

{issue_type_line}
Confidence threshold: {confidence_threshold}

--- SOURCE TEXT ---
{raw_text}
--- END ---

Return a JSON object with exactly these top-level keys:
  status                  ("ok" or "rejected")
  missing_fields          (array of strings, empty if status is ok)
  message                 (string, only set if status is rejected)
  request_type            ("bug", "enhancement", or "new development")
  data_model_required     (boolean)
  project_name            (string)
  objective               (string)
  business_context        (string)
  functional_requirements (array of strings)
  data_requirements       (object: source_systems, data_types, volume, frequency)
  technology              (object: stack, environment, cloud_or_onprem, preferred_tools)
  non_functional          (object: performance, scalability, latency, sla)
  security                (object: data_sensitivity, access_controls, compliance)
  constraints             (object: budget, timeline, technical_limitations)
  existing_architecture   (string or null)
  source_connections      (array of objects: db_type, database, instance_connection_name, host, port, username, source_tables)
  assumptions             (array of strings)
  inferred_assumptions    (array of strings)
  acceptance_criteria     (array of strings)
  expected_outputs        (array of strings)
  classification          (object: ingestion_type, output_type)
  confidence              (number 0-1)
  low_confidence_warning  (string or null)

Return JSON only — no markdown, no explanation.
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
