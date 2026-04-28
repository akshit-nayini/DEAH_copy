# Skills: Data Model Agent

## Purpose
Reads source schema (from CSV or live database), designs a target schema for the specified cloud platform, and produces a summary JSON, a Mermaid ER diagram, and a CSV mapping document for downstream agents.

## Capabilities
- `fetch_schema_from_csv`: loads source schema from a provided CSV file, filtered to tables listed in `source_connections.source_tables`
- `get_schema_from_source`: connects to the source database via the connector registry, queries `information_schema`, and returns column metadata for the specified tables
- `design_target_schema`: single Claude inference pass that produces all output facets together — target tables with layer prefixes, partitioning, clustering, relationships, cardinality, Mermaid ER diagram, and source-to-target column mapping. Only columns present in the provided source schema may appear as `source_column` in the mapping — derived target columns use `N/A`. These are not independent calls; they are sections of one structured response via `SCHEMA_DESIGN_TOOL`.

## Connector Registry
Source connection always uses SQLAlchemy direct IP regardless of whether `instance_connection_name` is present. `instance_connection_name` is stored in `source_connections` for reference but not used for connecting.

Supported database types (`db_type`): `mysql`, `postgres`, `oracle` (via `python-oracledb`), `mssql`

Password is read from the `DB_PASSWORD` environment variable.

## Inputs
- `requirements: dict` — `RequirementsOutput.to_dict()`; must contain `source_connections` with `source_tables`
- `schema_csv: str | Path | None` — optional path to source schema CSV; if omitted the agent connects to the source directly. When `column_type` is present alongside `data_type`, `column_type` is preferred (e.g. `decimal(10,0)` over `decimal`).

## Summary JSON Schema
`data_model_summary.json` contains the following keys consumed by downstream agents:

- `agent: str` — always `"data_model"`
- `project_name: str`
- `request_type: str`
- `source_tables: list[str]`
- `source_connections: list[dict]` — passed through from `RequirementsOutput.source_connections`; present even when schema was provided via CSV
- `target_schema: list[dict]` — each entry: `table_name: str`, `layer: str`, `columns: list[dict]`; each column: `name: str`, `data_type: str`, `nullable: bool`, `primary_key: bool`, `description: str`
- `relationships: list[dict]` — each: `from_table`, `from_column`, `to_table`, `to_column`, `type` (`one-to-one|one-to-many|many-to-one|many-to-many`)
- `partitioning: dict` — keyed by table name; each value: `type`, `column`, `granularity`
- `clustering: dict` — keyed by table name; value is list of column names
- `cardinality: list[dict]` — each: `from_table`, `to_table`, `type`, `notes`

## Output
Three files written to `output/{project_name}/`, where `project_name` is slugified (spaces and slashes replaced with underscores; empty name raises `ValueError` before any API call):
- `data_model_summary.json` — see Summary JSON Schema above
- `er_diagram.mmd` — Mermaid ER diagram
- `mapping.csv` — columns: `source_system`, `source_table`, `source_column`, `source_data_type`, `target_table`, `target_column`, `target_data_type`, `transformation_logic`, `is_partition_column`, `is_cluster_column`, `notes`

## Schema Size Constraint
Ceiling is 1,000 columns across all filtered source tables. Raises `ValueError` with actual column count before any API call if exceeded. Reduce scope by listing fewer tables in `source_connections.source_tables`.

## Invocation

```python
from data_model import DataModelAgent

agent = DataModelAgent(config)

# with CSV
output = agent.run(requirements=req_dict, schema_csv="source_schema.csv")

# live connection
output = agent.run(requirements=req_dict)
```

## Constructor Parameters
- `api_key`: Anthropic API key (required)
- `model`: Claude model string (default: `claude-sonnet-4-20250514`)
- `output_root`: root directory for output files (default: `output`)

## Environment Variables
- `DB_PASSWORD`: source database password; required when no schema CSV is provided

## Error and Edge Case Behaviour
- No `source_connections` in requirements and no CSV provided: raises `ValueError` before any API or DB call
- `DB_PASSWORD` not set when live connection needed: raises `EnvironmentError`
- Unsupported database type: raises `ValueError` with supported types listed
- Schema exceeds 1,000 column ceiling: raises `ValueError` with actual column count before API call
- Empty or missing `project_name`: raises `ValueError` before any API call
- Schema CSV filtered to `source_tables` only — rows for unlisted tables are silently dropped
- CSV headers are stripped of whitespace and lowercased on load; missing optional columns (`column_key`, `extra`) default to empty string
- Empty source schema after filtering: raises `ValueError` before any API call — indicates table names don't match or the database connection is scoped to the wrong schema
- Missing `database` (schema name) in a `source_connections` entry: raises `ValueError` before any connection is opened — check that the requirements agent extracted the schema name correctly
- Claude API failures and missing `tool_use` blocks raise immediately; no automatic retry — caller is responsible for retry logic
