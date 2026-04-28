"""
agents/generator/prompts.py
----------------------------
Prompt templates for the Test Case Generator agent.
Supports per-category prompts enriched with ICD metadata from ICDParserService.
"""

ALL_CATEGORIES = [
    "Schema Validation",
    "Null/Empty",
    "Boundary Values",
    "Format/Pattern",
    "Length/Size",
    "Duplicates",
    "Special Characters",
    "Enumeration",
    "PII",
    "Data Quality",
    "Partition Validation",
    "Airflow Job",
]

EDGE_CASE_CATEGORIES = ["Boundary Values", "Null/Empty", "Special Characters"]

SYSTEM_PROMPT = """You are a senior data quality engineer for a BigQuery migration Testing POD.
Generate test cases for a SINGLE validation category.

Return ONLY a valid JSON array. Each object must have exactly these fields:
- tc_id          : TC-001 etc. (use the start ID provided)
- category       : exact category string as provided
- test_name      : max 6 words
- column         : specific column name from the ICD, or ALL
- description    : one sentence — what is being validated
- precondition   : one sentence — required data state or setup before the test
- input_data     : concrete test value (e.g. NULL, empty string, -1, "abc@!", "2099-01-01")
- steps          : numbered steps e.g. "1. run query  2. check result  3. verify expected"
- query          : executable BigQuery SQL SELECT statement; use <project>.<dataset> as placeholders; empty string for Airflow Job only
- sql_hint       : human-readable SQL fragment for documentation (may differ from query)
- expected_result: exact expected value or condition (under 15 words)
- priority       : High | Medium | Low
- linked_ac      : AC reference or N/A

Rules:
- Use REAL column names from the ICD schema provided.
- query must reference <project>.<dataset>.<table_name>.
- For Airflow Job: query must be an empty string "".
- Do NOT include actual_result or verdict.
- Return ONLY the JSON array. No markdown fences. No extra text."""


def build_category_prompt(
    category: str,
    icd_meta: dict,
    ac: str,
    start_tc_num: int,
    tc_count: int = 2,
) -> str:
    """Build a per-category prompt enriched with ICD metadata."""
    table  = icd_meta.get('table_name', 'target_table')
    pii    = ', '.join(icd_meta.get('pii_cols',  [])) or 'none identified'
    pk     = ', '.join(icd_meta.get('pk_cols',   [])) or 'see schema'
    enums  = '; '.join(icd_meta.get('enum_cols', []))
    cols   = icd_meta.get('col_count', 0)
    schema = icd_meta.get('schema_text', '')
    guid   = _category_guidance(category, table, pii, pk, enums, cols)

    lines = [
        f'Generate exactly {tc_count} test case(s) for category: "{category}"',
        f'Start TC IDs from TC-{start_tc_num:03d}.',
        '',
        f'=== TABLE: {table} ({cols} columns) ===',
        f'{"column":<20}| {"data_type":<13}| {"nullable":<9}| constraint',
        schema,
        '',
        f'=== ACCEPTANCE CRITERIA ===',
        ac,
        '',
        f'PK columns : {pk}',
        f'PII columns: {pii}',
    ]
    if enums:
        lines.append(f'Enum cols  : {enums}')
    if guid:
        lines += ['', guid]
    lines += [
        '',
        f'Use REAL column names from the schema. '
        f'SQL must reference <project>.<dataset>.{table}.',
    ]
    return '\n'.join(lines)


def _category_guidance(cat: str, table: str, pii: str, pk: str, enums: str, cols: int) -> str:
    _pii_auto = (
        "No PII columns are tagged in the ICD — identify them by column name from the schema above: "
        "look for any column whose name contains 'email', 'phone', 'phone_number', 'address', "
        "'first_name', 'last_name', 'ssn', 'dob', 'date_of_birth'. "
        if pii == "none identified" else ""
    )
    guidance = {
        "Schema Validation":
            f"ICD has {cols} columns. "
            f"TC1: SELECT COUNT(*) AS column_count FROM INFORMATION_SCHEMA.COLUMNS WHERE table_name='<table_name>' AND table_schema='<dataset>'; "
            f"expected_result = 'column_count = {cols}'. "
            f"TC2: SELECT COUNT(*) AS mismatch_count FROM INFORMATION_SCHEMA.COLUMNS WHERE table_name='<table_name>' AND table_schema='<dataset>' "
            f"AND column_name NOT IN (<comma-separated list of ICD column names>); "
            f"expected_result = 'mismatch_count = 0'. "
            f"Use INFORMATION_SCHEMA directly — no backtick-quoted project prefix on INFORMATION_SCHEMA.",

        "Null/Empty":
            f"NOT NULL columns include: {pk}. "
            "TC1=null check on a NOT NULL column  TC2=empty string / whitespace-only check.",

        "Boundary Values":
            "TC1=check no values fall BELOW the minimum allowed (expected: below_min_count = 0). "
            "TC2=check no values exceed the MAXIMUM allowed (expected: above_max_count = 0). "
            "Use range queries, NOT existence checks: "
            "  TC1 example: SELECT COUNT(*) AS below_min_count FROM <project>.<dataset>.{table} WHERE SALARY < 0.01 "
            "  TC2 example: SELECT COUNT(*) AS above_max_count FROM <project>.<dataset>.{table} WHERE SALARY > 999999.99 "
            "CRITICAL — match SQL literal type to column data type: "
            "INT64/NUMERIC/FLOAT64 → bare numeric literal (WHERE salary < 0.01); "
            "STRING → use LENGTH/CHAR_LENGTH for size limits; "
            "DATE → DATE literal (WHERE hire_date < DATE '2000-01-01'). "
            "NEVER look for a specific exact value (e.g. WHERE SALARY = 0.01) — check the RANGE instead.",

        "Format/Pattern":
            "TC1=valid format passes  TC2=invalid format fails (e.g. wrong date separator, malformed email). "
            "CRITICAL — REGEXP_CONTAINS only accepts STRING: for DATE/TIMESTAMP columns always CAST first: "
            "REGEXP_CONTAINS(CAST(date_col AS STRING), r'pattern'). "
            "Do NOT use REGEXP_CONTAINS(date_col, ...) directly — DATE is not STRING.",

        "Length/Size":
            "TC1=check that all values are within the max allowed length (expected: violation_count = 0)  "
            "TC2=verify specific column length constraints (e.g. LENGTH(first_name) <= 50). "
            "Use LENGTH() or CHAR_LENGTH() on STRING columns only.",

        "Duplicates":
            f"PK columns: {pk}. "
            f"TC1=duplicate primary key check  TC2=COUNT(*) vs COUNT(DISTINCT {pk}).",

        "Special Characters":
            "TC1=verify no rows have SQL special characters that would break queries: "
            "  SELECT COUNT(*) AS injection_risk_count FROM <project>.<dataset>.{table} "
            "  WHERE REGEXP_CONTAINS(FIRST_NAME, r\"[';\\\\-]{2,}\"); expected = 'injection_risk_count = 0'. "
            "TC2=verify STRING columns support multi-byte characters (BYTE_LENGTH >= CHAR_LENGTH for any row): "
            "  SELECT COUNT(*) AS multibyte_count FROM <project>.<dataset>.{table} "
            "  WHERE BYTE_LENGTH(FIRST_NAME) > CHAR_LENGTH(FIRST_NAME); expected = 'multibyte_count >= 0'. "
            "NEVER search for a specific hardcoded string value — the synthetic data won't have it. "
            "CRITICAL: use STRING columns only (FIRST_NAME, EMAIL, JOB_ID), NOT INT64 PKs.",

        "Enumeration":
            f"Enum cols: {enums or 'see schema'}. "
            f"TC1: SELECT COUNT(*) AS invalid_status_count FROM <project>.<dataset>.{table} "
            f"WHERE STATUS NOT IN (<ALL valid values from enum_cols above exactly as listed>); "
            f"expected_result = 'invalid_status_count = 0'. "
            f"CRITICAL: the NOT IN list MUST include EVERY value listed in the enum definition — do not omit any. "
            f"TC2: SELECT COUNT(*) AS valid_count FROM <project>.<dataset>.{table} "
            f"WHERE STATUS IN (<ALL valid values from enum_cols above>); "
            f"expected_result = 'valid_count > 0' (at least one valid status value exists). "
            f"Do NOT treat any value listed in the enum definition as invalid.",

        "PII":
            f"ICD-tagged PII columns: {pii}. {_pii_auto}"
            f"TC1: Data completeness — verify the PII column has no missing values: "
            f"SELECT COUNT(*) AS pii_null_count FROM <project>.<dataset>.{table} "
            f"WHERE <pii_column> IS NULL; expected_result = 'pii_null_count = 0'. "
            f"TC2: Format validation — verify the PII column contains valid formatted values: "
            f"For email columns: SELECT COUNT(*) AS invalid_email_count FROM <project>.<dataset>.{table} "
            f"WHERE NOT REGEXP_CONTAINS(CAST(email AS STRING), r'@[a-zA-Z0-9.-]+\\.[a-zA-Z]{{2,}}'); "
            f"expected_result = 'invalid_email_count = 0'. "
            f"For phone columns: SELECT COUNT(*) AS invalid_phone_count FROM <project>.<dataset>.{table} "
            f"WHERE phone_number IS NOT NULL AND LENGTH(phone_number) NOT BETWEEN 7 AND 15; "
            f"expected_result = 'invalid_phone_count = 0'. "
            f"CRITICAL: Generate DATA COMPLETENESS (null check) and FORMAT checks ONLY. "
            f"Do NOT generate masking, anonymization, or 'exposure' checks — the ICD has no masking requirement. "
            f"TC1 must use IS NULL (missing data = FAIL). Do NOT use IS NOT NULL to count 'exposed' data. "
            f"Do NOT query INFORMATION_SCHEMA or policy_tags.",

        "Data Quality":
            "TC1=row count is not zero (table is populated). "
            "TC2=referential integrity / orphan records check. "
            "IMPORTANT: TC2 only applies to source_db validation mode, not synthetic data. "
            "The test_name for TC2 MUST contain the word 'orphan' or 'referential' "
            "so the validator can skip it automatically in synthetic mode.",

        "Partition Validation":
            f"TC1: SELECT COUNT(*) AS null_partition_count FROM <project>.<dataset>.{table} WHERE <partition_column> IS NULL; "
            f"expected_result = 'null_partition_count = 0'. "
            f"TC2: SELECT COUNT(*) AS mismatched_row_count FROM <project>.<dataset>.{table} WHERE DATE(<partition_column>) != CURRENT_DATE(); "
            f"expected_result = 'mismatched_row_count = 0'. "
            f"Use the actual partition column name from the ICD schema — do NOT use _PARTITIONDATE or _PARTITIONTIME pseudo-columns.",

        "Airflow Job":
            "TC1=DAG completes without error status  "
            "TC2=pipeline schedule/interval is configured as expected. "
            "IMPORTANT: query must be empty string \"\" for both TCs.",
    }
    return guidance.get(cat, "")


# ── Legacy single-call prompts (kept for backward compatibility) ──────────────

def build_user_prompt(icd: str, ac: str) -> str:
    return f"ICD DOCUMENT:\n{icd}\n\nACCEPTANCE CRITERIA:\n{ac}"


def build_incremental_prompt(delta_icd: str, ac: str, start_tc_num: int) -> str:
    return (
        f"NEW COLUMNS DELTA — ICD DOCUMENT (new columns only):\n{delta_icd}\n\n"
        f"ACCEPTANCE CRITERIA:\n{ac}\n\n"
        f"IMPORTANT: Start TC IDs from TC-{start_tc_num:03d}. "
        f"Generate test cases ONLY for the columns listed in the delta ICD above. "
        f"Do NOT re-generate test cases for columns already covered."
    )