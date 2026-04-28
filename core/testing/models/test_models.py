"""
models/test_models.py
---------------------
Shared data models for test cases and validation results.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict


@dataclass
class TestCase:
    # Required (no default)
    tc_id:           str
    category:        str
    test_name:       str
    # Optional (with defaults) — order matters for dataclass
    column:          str = "ALL"    # specific column under test, or ALL
    description:     str = ""
    precondition:    str = ""       # data state / setup required before the test
    input_data:      str = ""       # concrete test value (NULL, boundary int, regex, etc.)
    steps:           str = ""       # numbered steps "1. ... 2. ... 3. ..."
    query:           str = ""       # executable BQ SQL; empty for Airflow Job
    sql_hint:        str = ""       # human-readable SQL fragment (documentation only)
    expected_result: str = ""
    priority:        str = "Medium"
    linked_ac:       str = "N/A"
    change_reason:   str = ""       # CR mode: reason for this change request

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TestCase":
        return cls(
            tc_id=d.get("tc_id", ""),
            category=d.get("category", ""),
            test_name=d.get("test_name", ""),
            column=d.get("column", "ALL"),
            description=d.get("description", ""),
            precondition=d.get("precondition", ""),
            input_data=d.get("input_data", ""),
            steps=d.get("steps", ""),
            query=d.get("query", ""),
            sql_hint=d.get("sql_hint", ""),
            expected_result=d.get("expected_result", ""),
            priority=d.get("priority", "Medium"),
            linked_ac=d.get("linked_ac", "N/A"),
            change_reason=d.get("change_reason", ""),
        )


@dataclass
class ValidationResult:
    tc_id:           str
    category:        str
    test_name:       str
    description:     str
    query:           str
    expected_result: str
    actual_result:   str
    verdict:         str          # PASS | FAIL | SKIP
    priority:        str
    linked_ac:       str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_test_case(cls, tc: TestCase, actual: str, verdict: str) -> "ValidationResult":
        return cls(
            tc_id=tc.tc_id,
            category=tc.category,
            test_name=tc.test_name,
            description=tc.description,
            query=tc.query,
            expected_result=tc.expected_result,
            actual_result=actual,
            verdict=verdict,
            priority=tc.priority,
            linked_ac=tc.linked_ac,
        )