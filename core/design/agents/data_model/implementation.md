# Implementation: Data Model Agent

## File Layout
- `test_data_model.py` — local test runner
- `data_model/__init__.py` — exposes `DataModelAgent`
- `data_model/agent.py` — `DataModelAgent` and `DataModelOutput`
- `data_model/connectors.py` — connector registry and `information_schema` queries
- `data_model/prompts.py` — system prompt, user prompt, and `SCHEMA_DESIGN_TOOL` definition

## Dependencies
- `anthropic`
- `sqlalchemy` — required for direct IP connections
- `pymysql` — MySQL direct
- `psycopg2` — Postgres direct
- `python-oracledb` — Oracle direct
- `pyodbc` — MSSQL direct

Only install the drivers relevant to your source systems.

## Constructor Parameters
- `api_key`: Anthropic API key (required)
- `model`: Claude model string (default: `claude-sonnet-4-20250514`)
- `output_root`: root directory for output files (default: `output`)

## Environment Variables
- `DB_PASSWORD` — source database password; required when no schema CSV is provided

## Input Schema
- `requirements: dict` — `RequirementsOutput.to_dict()`
- `schema_csv: str | Path | None` — path to source schema CSV; expected columns: `table_name`, `column_name`, `data_type`, `is_nullable`, `column_key` (optional), `extra` (optional), `column_type` (optional but preferred — includes precision and scale e.g. `decimal(10,0)`, `varchar(50)`). Headers are stripped of whitespace and lowercased on load. Missing optional columns default to empty string. When both `column_type` and `data_type` are present, `column_type` is used.

## Output Schema (`DataModelOutput`)
- `project_name: str`
- `source_tables: list[str]` — deduplicated list from `source_connections.source_tables`
- `target_schema: list[dict]` — each entry: `table_name: str`, `layer: str` (`staging|dimension|fact|mart`), `columns: list[dict]`; each column dict: `name: str`, `data_type: str`, `nullable: bool`, `primary_key: bool`, `description: str`
- `relationships: list[dict]` — each: `from_table`, `from_column`, `to_table`, `to_column`, `type` (`one-to-one|one-to-many|many-to-one|many-to-many`)
- `er_diagram: str` — Mermaid `erDiagram` block
- `partitioning: dict` — keyed by table name; each value: `type` (`time|range|ingestion_time|none`), `column`, `granularity` (`hour|day|month|year`)
- `clustering: dict` — keyed by table name; value is list of cluster column names
- `cardinality: list[dict]` — each: `from_table`, `to_table`, `type` (`one-to-one|one-to-many|many-to-one|many-to-many`), `notes`
- `mapping: list[dict]` — fields: `source_system`, `source_table`, `source_column`, `source_data_type`, `target_table`, `target_column`, `target_data_type`, `transformation_logic`, `is_partition_column` (bool), `is_cluster_column` (bool), `notes`
- `summary: dict` — subset written to `data_model_summary.json`; keys: `agent`, `project_name`, `request_type`, `source_tables`, `target_schema`, `relationships`, `partitioning`, `clustering`, `cardinality`
- `output_dir: Path`

`.write()` creates output directory and writes all three output files.

## Summary JSON Keys
Consumed by `architecture` and `implementation_steps` agents:
- `agent: str` — always `"data_model"`
- `project_name: str`
- `request_type: str`
- `source_tables: list[str]`
- `source_connections: list[dict]` — passed through from `RequirementsOutput.source_connections`; present even when schema was provided via CSV
- `target_schema: list[dict]` — same shape as `DataModelOutput.target_schema`
- `relationships: list[dict]`
- `partitioning: dict`
- `clustering: dict`
- `cardinality: list[dict]`

## Connector Registry (`connectors.py`)
`get_schema_from_source(source_connections, source_tables)` iterates over connections and always dispatches to `_query_direct` via SQLAlchemy. `instance_connection_name` is stored in `source_connections` for reference but not used for connecting — the direct IP path is always taken.

`INFORMATION_SCHEMA_QUERIES` holds per-dialect SQL. Each query filters by both `TABLE_SCHEMA` (using `database` from `source_connections`) and `TABLE_NAME`. Table names are validated against a strict allowlist (`^[A-Za-z0-9_]+# Implementation: Data Model Agent

## File Layout
- `test_data_model.py` — local test runner
- `data_model/__init__.py` — exposes `DataModelAgent`
- `data_model/agent.py` — `DataModelAgent` and `DataModelOutput`
- `data_model/connectors.py` — connector registry and `information_schema` queries
- `data_model/prompts.py` — system prompt, user prompt, and `SCHEMA_DESIGN_TOOL` definition

## Dependencies
- `anthropic`
- `sqlalchemy` — required for direct IP connections
- `pymysql` — MySQL direct
- `psycopg2` — Postgres direct
- `python-oracledb` — Oracle direct (replaces deprecated `cx_Oracle`)
- `pyodbc` — MSSQL direct
- `cloud-sql-python-connector[pymysql]` — Cloud SQL connections

Only install the drivers relevant to your source systems.

## Constructor Parameters
- `api_key`: Anthropic API key (required)
- `model`: Claude model string (default: `claude-sonnet-4-20250514`)
- `output_root`: root directory for output files (default: `output`)

## Environment Variables
- `DB_PASSWORD` — source database password; required when no schema CSV is provided

## Input Schema
- `requirements: dict` — `RequirementsOutput.to_dict()`
- `schema_csv: str | Path | None` — path to source schema CSV; expected columns: `table_name`, `column_name`, `data_type`, `is_nullable`, `column_key` (optional), `extra` (optional), `column_type` (optional but preferred — includes precision and scale e.g. `decimal(10,0)`, `varchar(50)`). Headers are stripped of whitespace and lowercased on load. Missing optional columns default to empty string. When both `column_type` and `data_type` are present, `column_type` is used.

## Output Schema (`DataModelOutput`)
- `project_name: str`
- `source_tables: list[str]` — deduplicated list from `source_connections.source_tables`
- `target_schema: list[dict]` — each entry: `table_name: str`, `layer: str` (`staging|dimension|fact|mart`), `columns: list[dict]`; each column dict: `name: str`, `data_type: str`, `nullable: bool`, `primary_key: bool`, `description: str`
- `relationships: list[dict]` — each: `from_table`, `from_column`, `to_table`, `to_column`, `type`
- `er_diagram: str` — Mermaid `erDiagram` block
- `partitioning: dict` — keyed by table name; each value: `type` (`time|range|ingestion_time|none`), `column`, `granularity` (`hour|day|month|year`)
- `clustering: dict` — keyed by table name; value is list of cluster column names
- `cardinality: list[dict]` — each: `from_table`, `to_table`, `type`, `notes`
- `mapping: list[dict]` — fields: `source_table`, `source_column`, `target_table`, `target_column`, `transformation`, `data_type_mapping`
- `summary: dict` — subset written to `data_model_summary.json`; keys: `agent`, `project_name`, `request_type`, `source_tables`, `target_schema`, `relationships`, `partitioning`, `clustering`, `cardinality`
- `output_dir: Path`

`.write()` creates output directory and writes all three output files.

## Summary JSON Keys
Consumed by `architecture` and `implementation_steps` agents:
- `agent: str` — always `"data_model"`
- `project_name: str`
- `request_type: str`
- `source_tables: list[str]`
- `target_schema: list[dict]` — same shape as `DataModelOutput.target_schema`
- `relationships: list[dict]`
- `partitioning: dict`
- `clustering: dict`
- `cardinality: list[dict]`

## Connector Registry (`connectors.py`)
`get_schema_from_source(source_connections, source_tables)` iterates over connections and dispatches:
- `instance_connection_name` present → `_query_cloud_sql` using `google.cloud.sql.connector`
- Otherwise → `_query_direct` using `sqlalchemy` + dialect driver

) before interpolation into SQL to prevent injection across the agent trust boundary. Any table name failing validation raises `ValueError` before a connection is opened. Missing `database` raises `ValueError` before any connection is opened.

Supported dialects and drivers (keyed by `db_type`):
- `mysql` → `pymysql`
- `postgres` → `psycopg2`
- `oracle` → `python-oracledb` (note: `cx_Oracle` is deprecated as of 2023; use `python-oracledb` in thin mode)
- `mssql` → `pyodbc`

To add a new dialect: add an entry to `INFORMATION_SCHEMA_QUERIES` and `_dialect_driver`.

## Schema Size Constraint
`_validate_schema_size` is called before the API call. Ceiling is 1,000 columns across all source tables. Raises `ValueError` with the actual column count if exceeded.

## Prompts (`data_model/prompts.py`)
`SYSTEM_PROMPT` instructs Claude to design target tables with layer prefixes (`stg_`, `dim_`, `fct_`), apply partitioning and clustering based on volume and frequency, infer relationships and cardinality from source schema, map every source column using `column_type` for precise type mapping, and produce a valid Mermaid `erDiagram`. The prompt explicitly prohibits inventing source column names — only columns present in the provided schema may appear as `source_column`; derived target columns must use `N/A`.

`schema_design_prompt(requirements, source_schema)` embeds requirements JSON and source schema JSON as labelled blocks.

`SCHEMA_DESIGN_TOOL` is a Claude tool definition enforcing the full output structure. Claude is forced to call it via `tool_choice: any`. All output facets (target schema, ER diagram, mapping, partitioning, clustering, cardinality) are produced in one structured response — not independent calls.

## Design Notes
- Single Claude call — no tool loop.
- Schema CSV is filtered to `source_tables` on load — unlisted tables never reach Claude.
- `source_tables` is deduplicated and order-preserved across multiple connections.
- `DB_PASSWORD` is never logged or included in any output file.
- `project_name` is slugified for the output path — spaces and slashes become underscores. Empty `project_name` raises `ValueError` before any API call.
- Claude API failures and missing `tool_use` blocks raise immediately. No automatic retry — caller handles retry logic.

## Running Tests

```bash
# With schema CSV
python test_data_model.py \
    --requirements output/requirement/requirements.json \
    --schema source_schema.csv

# Live connection (requires DB_PASSWORD)
export DB_PASSWORD=yourpassword
python test_data_model.py \
    --requirements output/requirement/requirements.json
```

Expected outputs on success:
- `output/{project_name}/data_model_summary.json` — non-empty; contains `target_schema` with at least one table
- `output/{project_name}/er_diagram.mmd` — starts with `erDiagram`
- `output/{project_name}/mapping.csv` — contains header row and at least one data row
