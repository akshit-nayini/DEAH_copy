"""Unit tests for BigQuery schema check helpers in orchestrator.py."""
from __future__ import annotations
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.orchestration.orchestrator import _parse_mapping_schema, _normalize_bq_type


_SAMPLE_CSV = """\
source_table,source_column,source_data_type,target_table,target_column,target_data_type,nullable,is_pk,is_pii,transformation,notes
EMPLOYEES,EMP_ID,NUMBER,stg_employees,emp_id,INT64,false,true,false,,
EMPLOYEES,FIRST_NAME,VARCHAR2,stg_employees,first_name,STRING,true,false,false,,
EMPLOYEES,HIRE_DATE,DATE,stg_employees,hire_date,DATE,true,false,false,,
DEPARTMENTS,DEPT_ID,NUMBER,stg_departments,dept_id,INT64,false,true,false,,
DEPARTMENTS,DEPT_NAME,VARCHAR2,stg_departments,dept_name,STRING,true,false,false,,
"""


def test_parse_mapping_schema_groups_by_target_table():
    schema = _parse_mapping_schema(_SAMPLE_CSV)
    assert set(schema.keys()) == {"stg_employees", "stg_departments"}


def test_parse_mapping_schema_correct_columns():
    schema = _parse_mapping_schema(_SAMPLE_CSV)
    emp_cols = schema["stg_employees"]
    assert ("emp_id", "INT64") in emp_cols
    assert ("first_name", "STRING") in emp_cols
    assert ("hire_date", "DATE") in emp_cols


def test_normalize_bq_type_aliases():
    assert _normalize_bq_type("INTEGER") == "INT64"
    assert _normalize_bq_type("FLOAT") == "FLOAT64"
    assert _normalize_bq_type("BOOLEAN") == "BOOL"


def test_normalize_bq_type_passthrough():
    assert _normalize_bq_type("STRING") == "STRING"
    assert _normalize_bq_type("NUMERIC") == "NUMERIC"
    assert _normalize_bq_type("TIMESTAMP") == "TIMESTAMP"


def test_normalize_bq_type_case_insensitive():
    assert _normalize_bq_type("integer") == "INT64"
    assert _normalize_bq_type("Float") == "FLOAT64"
