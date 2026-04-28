# data_model/prompts.py
"""
System prompt, user prompt, and tool definition for the Data Model Agent.
"""

from __future__ import annotations
import json


SYSTEM_PROMPT = """\
You are a senior data engineer specialising in cloud data warehouse design.
Given a source schema and requirements, design an optimal target schema for
the specified cloud platform.
Return a single JSON object only — no markdown fences, no explanation, no preamble.

Rules:
- Design target tables appropriate for the platform (e.g. BigQuery for GCP).
- Apply appropriate partitioning and clustering based on volume, frequency,
  and query patterns implied by the requirements.
- Infer relationships, cardinality, and key columns from the source schema.
- The mapping must contain ONLY columns that exist in the provided source
  schema. Never invent or assume source column names. If a column is not
  in the source schema it must not appear as source_column in the mapping.
- Do not add derived or audit columns (e.g. _ingested_at, _source_table,
  row_hash) to the target schema. Only map columns present in the source.
- Map every source column to a target column. Use the most precise type
  information available in the schema (e.g. decimal(10,0) over decimal,
  varchar(50) over varchar). For each mapping row populate:
    source_system: the database type from source_connections (e.g. MySQL, Oracle, Postgres)
    source_data_type: exact source type including precision/scale
    target_data_type: corresponding target platform type
    transformation_logic: exact cast or expression (e.g. CAST(col AS INT64))
    is_partition_column: true if this column is used for partitioning
    is_cluster_column: true if this column is used for clustering
    notes: any relevant notes about the mapping
- Generate a valid Mermaid erDiagram block covering all target tables and
  their relationships.
- Use snake_case for all target table and column names.
- Do not invent columns or relationships not present in or inferable from
  the source schema and requirements.
- Prefix target table names with the appropriate layer (e.g. stg_ for
  staging, dim_ for dimensions, fct_ for facts) based on the output_type
  in the requirements classification.
"""


def schema_design_prompt(requirements: dict, source_schema: list[dict]) -> str:
    return f"""\
Design the target schema based on the requirements and source schema below.

## Requirements
{json.dumps(requirements, indent=2)}

## Source Schema
{json.dumps(source_schema, indent=2)}

Return a JSON object with exactly these top-level keys:
  target_schema   (array of objects: table_name, layer, columns[name, data_type, nullable, primary_key, description])
  relationships   (array of objects: from_table, from_column, to_table, to_column, type)
  partitioning    (object keyed by table_name: type, column, granularity)
  clustering      (object keyed by table_name: array of column names)
  cardinality     (array of objects: from_table, to_table, type, notes)
  er_diagram      (string — valid Mermaid erDiagram block)
  mapping         (array of objects: source_system, source_table, source_column, source_data_type,
                   target_table, target_column, target_data_type, transformation_logic,
                   is_partition_column, is_cluster_column, notes)

Return JSON only — no markdown, no explanation.
"""


SCHEMA_DESIGN_TOOL = {
    "name": "design_target_schema",
    "description": "Store the designed target schema, ER diagram, and mapping.",
    "input_schema": {
        "type": "object",
        "required": ["target_schema", "er_diagram", "mapping"],
        "properties": {
            "target_schema": {
                "type": "array",
                "description": "List of target table definitions.",
                "items": {
                    "type": "object",
                    "properties": {
                        "table_name": {"type": "string"},
                        "layer": {
                            "type": "string",
                            "enum": ["staging", "dimension", "fact", "mart"]
                        },
                        "columns": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "data_type": {"type": "string"},
                                    "nullable": {"type": "boolean"},
                                    "primary_key": {"type": "boolean"},
                                    "description": {"type": "string"}
                                }
                            }
                        }
                    }
                }
            },
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from_table": {"type": "string"},
                        "from_column": {"type": "string"},
                        "to_table": {"type": "string"},
                        "to_column": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["one-to-one", "one-to-many", "many-to-one", "many-to-many"]
                        }
                    }
                }
            },
            "partitioning": {
                "type": "object",
                "description": "Partition config per target table name.",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["time", "range", "ingestion_time", "none"]
                        },
                        "column": {"type": "string"},
                        "granularity": {
                            "type": "string",
                            "enum": ["hour", "day", "month", "year"]
                        }
                    }
                }
            },
            "clustering": {
                "type": "object",
                "description": "Clustering columns per target table name.",
                "additionalProperties": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "cardinality": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from_table": {"type": "string"},
                        "to_table": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["one-to-one", "one-to-many", "many-to-one", "many-to-many"]
                        },
                        "notes": {"type": "string"}
                    }
                }
            },
            "er_diagram": {
                "type": "string",
                "description": "Valid Mermaid erDiagram block covering all target tables."
            },
            "mapping": {
                "type": "array",
                "description": "Source to target column mapping.",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_system": {"type": "string"},
                        "source_table": {"type": "string"},
                        "source_column": {"type": "string"},
                        "source_data_type": {"type": "string"},
                        "target_table": {"type": "string"},
                        "target_column": {"type": "string"},
                        "target_data_type": {"type": "string"},
                        "transformation_logic": {"type": "string"},
                        "is_partition_column": {"type": "boolean"},
                        "is_cluster_column": {"type": "boolean"},
                        "notes": {"type": "string"}
                    }
                }
            }
        }
    }
}
