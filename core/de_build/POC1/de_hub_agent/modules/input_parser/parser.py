"""
Input Parser Module
Consumes the API payload from Data Design POD, validates schema,
and hydrates internal representations for downstream code generation.
"""
import json
import logging
from pathlib import Path
from core.models import GenerateRequest, TableSpec, LayerType

logger = logging.getLogger(__name__)


class InputParser:
    """Parses and validates Data Design POD payloads."""

    def __init__(self):
        self.layer_prefixes = {
            LayerType.STAGING: "stg_",
            LayerType.INTERMEDIATE: "int_",
            LayerType.FACT: "fct_",
            LayerType.DIMENSION: "dim_",
            LayerType.RAW: "raw_",
        }

    def parse_file(self, path: str | Path) -> GenerateRequest:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Payload file not found: {path}")
        with open(path) as f:
            raw = json.load(f)
        return self.parse_dict(raw)

    def parse_dict(self, data: dict) -> GenerateRequest:
        request = GenerateRequest(**data)
        self._validate_request(request)
        self._enrich_table_names(request)
        logger.info(
            "Parsed request %s: %d tables, %d transformation rules, %d column mappings",
            request.request_id,
            len(request.data_model.tables),
            len(request.transformation_rules),
            len(request.column_mappings),
        )
        return request

    def _validate_request(self, request: GenerateRequest):
        if request.version != "1.0":
            raise ValueError(f"Unsupported schema version: {request.version}. Expected 1.0")
        if not request.data_model.tables:
            raise ValueError("Data model must contain at least one table")
        if request.tech_stack.target_platform != "bigquery":
            raise ValueError(f"Unsupported platform: {request.tech_stack.target_platform}. MVP supports bigquery only")
        table_names = [t.name for t in request.data_model.tables]
        dupes = [n for n in table_names if table_names.count(n) > 1]
        if dupes:
            raise ValueError(f"Duplicate table names: {set(dupes)}")
        for table in request.data_model.tables:
            self._validate_table(table)

    def _validate_table(self, table: TableSpec):
        col_names = [c.name for c in table.columns]
        dupes = [n for n in col_names if col_names.count(n) > 1]
        if dupes:
            raise ValueError(f"Table {table.name}: duplicate column names: {set(dupes)}")
        for pk in table.primary_key:
            if pk not in col_names:
                raise ValueError(f"Table {table.name}: primary key column '{pk}' not found in columns")
        if table.partition_config and table.partition_config.column not in col_names:
            raise ValueError(f"Table {table.name}: partition column '{table.partition_config.column}' not found")
        for cc in table.cluster_columns:
            if cc not in col_names:
                raise ValueError(f"Table {table.name}: cluster column '{cc}' not found")
        if len(table.cluster_columns) > 4:
            raise ValueError(f"Table {table.name}: BigQuery supports max 4 clustering columns, got {len(table.cluster_columns)}")

    def _enrich_table_names(self, request: GenerateRequest):
        for table in request.data_model.tables:
            prefix = self.layer_prefixes.get(table.layer, "")
            if not table.name.startswith(prefix):
                table._qualified_name = f"{prefix}{table.name}"
            else:
                table._qualified_name = table.name

    def get_qualified_name(self, table: TableSpec) -> str:
        return getattr(table, '_qualified_name', f"{self.layer_prefixes.get(table.layer, '')}{table.name}")

    def get_pii_columns(self, table: TableSpec) -> list[str]:
        return [c.name for c in table.columns if c.is_pii]

    def get_tables_by_layer(self, request: GenerateRequest, layer: LayerType) -> list[TableSpec]:
        return [t for t in request.data_model.tables if t.layer == layer]

    def get_tables_by_strategy(self, request: GenerateRequest, strategy) -> list[TableSpec]:
        return [t for t in request.data_model.tables if t.refresh_strategy == strategy]
