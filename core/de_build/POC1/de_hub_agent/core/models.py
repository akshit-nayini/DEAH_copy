"""
Core Pydantic models for the DE Hub Code Generator Agent.
Defines input schema (from Data Design POD), internal representations,
and output schemas for generated artifacts.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime
import uuid


# ─── Enums ───────────────────────────────────────────────────────────
class LayerType(str, Enum):
    STAGING = "stg"
    INTERMEDIATE = "int"
    FACT = "fct"
    DIMENSION = "dim"
    RAW = "raw"

class RefreshStrategy(str, Enum):
    FULL = "full_refresh"
    INCREMENTAL = "incremental_append"
    SCD1 = "scd_type_1"
    SCD2 = "scd_type_2"

class PartitionType(str, Enum):
    DAY = "DAY"
    MONTH = "MONTH"
    YEAR = "YEAR"
    HOUR = "HOUR"
    RANGE = "RANGE"
    NONE = "NONE"

class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"

class Verdict(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


# ─── Input Schema (from Data Design POD) ─────────────────────────────
class ColumnSpec(BaseModel):
    name: str
    data_type: str  # BigQuery-native: STRING, INT64, FLOAT64, BOOL, DATE, TIMESTAMP, etc.
    nullable: bool = True
    description: str = ""
    is_pii: bool = False
    default_value: Optional[str] = None

class PartitionConfig(BaseModel):
    column: str
    type: PartitionType = PartitionType.DAY

class TableSpec(BaseModel):
    name: str
    layer: LayerType
    description: str = ""
    columns: list[ColumnSpec]
    primary_key: list[str] = Field(default_factory=list)
    foreign_keys: list[ForeignKeySpec] = Field(default_factory=list)
    partition_config: Optional[PartitionConfig] = None
    cluster_columns: list[str] = Field(default_factory=list, max_length=4)
    refresh_strategy: RefreshStrategy = RefreshStrategy.FULL
    source_table: Optional[str] = None

class ForeignKeySpec(BaseModel):
    column: str
    references_table: str
    references_column: str

class Relationship(BaseModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    relationship_type: str = "many_to_one"

class PipelineArchitecture(BaseModel):
    pattern: str = "batch"  # batch, streaming, lakehouse
    source_systems: list[str] = Field(default_factory=list)
    data_flow: list[DataFlowStep] = Field(default_factory=list)

class DataFlowStep(BaseModel):
    source: str
    target: str
    transform_type: str = "direct"

class TechStackConfig(BaseModel):
    target_platform: str = "bigquery"
    orchestrator: str = "airflow"
    modeling_tool: str = "dbt"
    runtime: str = "python3.11"

class TransformationRule(BaseModel):
    rule_id: str
    source_columns: list[str]
    target_column: str
    logic: str  # SQL expression or natural language
    priority: int = 1

class ColumnMapping(BaseModel):
    source_table: str
    source_column: str
    target_column: str
    transform_logic: Optional[str] = None

class SchemaStatistics(BaseModel):
    table_name: str
    estimated_row_count: Optional[int] = None
    estimated_size_gb: Optional[float] = None

class GenerateRequest(BaseModel):
    """Top-level API request payload from Data Design POD."""
    version: str = "1.0"
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    data_model: DataModelSpec
    pipeline_architecture: PipelineArchitecture
    tech_stack: TechStackConfig = Field(default_factory=TechStackConfig)
    transformation_rules: list[TransformationRule] = Field(default_factory=list)
    column_mappings: list[ColumnMapping] = Field(default_factory=list)
    schema_statistics: list[SchemaStatistics] = Field(default_factory=list)

class DataModelSpec(BaseModel):
    tables: list[TableSpec]
    relationships: list[Relationship] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


# ─── Output Schemas ──────────────────────────────────────────────────
class DDLOutput(BaseModel):
    table_name: str
    file_name: str
    sql: str
    partition_type: str = "NONE"
    cluster_columns: list[str] = Field(default_factory=list)
    pii_columns: list[str] = Field(default_factory=list)

class DDLGenerationResult(BaseModel):
    ddl_files: list[DDLOutput]
    grant_statements: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

class DMLOutput(BaseModel):
    target_table: str
    file_name: str
    sql: str
    pattern: RefreshStrategy
    source_tables: list[str] = Field(default_factory=list)

class DMLGenerationResult(BaseModel):
    dml_files: list[DMLOutput]
    warnings: list[str] = Field(default_factory=list)

class ReviewFinding(BaseModel):
    check_name: str
    severity: Severity
    file_name: str
    line_reference: Optional[int] = None
    description: str
    suggested_fix: str = ""

class ReviewResult(BaseModel):
    review_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    reviewed_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    dimension: str
    verdict: Verdict
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)

class ManifestEntry(BaseModel):
    path: str
    purpose: str
    sha256: str
    dependencies: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class PipelineResult(BaseModel):
    request_id: str
    status: str  # completed, partial, failed
    ddl_result: Optional[DDLGenerationResult] = None
    dml_result: Optional[DMLGenerationResult] = None
    review_results: list[ReviewResult] = Field(default_factory=list)
    manifest: list[ManifestEntry] = Field(default_factory=list)
    quality_score: Optional[int] = None
    output_directory: str = ""


# Fix forward references
TableSpec.model_rebuild()
GenerateRequest.model_rebuild()
PipelineArchitecture.model_rebuild()
