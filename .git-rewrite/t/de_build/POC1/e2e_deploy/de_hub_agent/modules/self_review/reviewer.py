"""
Self-Review Module
Performs read-only validation of generated code:
- Correctness: DDL completeness, DML mapping coverage
- Security: secret detection, PII masking validation
"""
import re
import logging
from core.models import (
    GenerateRequest, DDLGenerationResult, DMLGenerationResult,
    ReviewResult, ReviewFinding, Severity, Verdict,
)
from modules.input_parser.parser import InputParser

logger = logging.getLogger(__name__)

SECRET_PATTERNS = [
    (r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?[A-Za-z0-9!@#$%^&*]{8,}', "Hardcoded password"),
    (r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?[A-Za-z0-9_\-]{20,}', "Hardcoded API key"),
    (r'(?i)(secret|token)\s*[=:]\s*["\']?[A-Za-z0-9_\-]{16,}', "Hardcoded secret/token"),
    (r'(?i)private_key', "Private key reference"),
    (r'(?i)(jdbc|postgresql|mysql|bigquery)://[^\s]+:[^\s]+@', "Connection string with credentials"),
    (r'AKIA[0-9A-Z]{16}', "AWS Access Key ID"),
    (r'(?i)client_email.*\.iam\.gserviceaccount\.com', "GCP service account"),
]


class SelfReviewAgent:
    """Performs automated code review on generated artifacts."""

    def __init__(self, parser: InputParser):
        self.parser = parser

    def review_all(
        self,
        request: GenerateRequest,
        ddl_result: DDLGenerationResult,
        dml_result: DMLGenerationResult,
    ) -> list[ReviewResult]:
        results = []
        results.append(self.review_correctness(request, ddl_result, dml_result))
        results.append(self.review_security(request, ddl_result, dml_result))
        return results

    def review_correctness(
        self,
        request: GenerateRequest,
        ddl_result: DDLGenerationResult,
        dml_result: DMLGenerationResult,
    ) -> ReviewResult:
        findings = []

        # Check 1: DDL completeness — all model tables have DDL
        ddl_tables = {d.table_name.split(".")[-1] for d in ddl_result.ddl_files}
        for table in request.data_model.tables:
            qname = self.parser.get_qualified_name(table)
            if qname not in ddl_tables:
                findings.append(ReviewFinding(
                    check_name="DDL_COMPLETENESS",
                    severity=Severity.CRITICAL,
                    file_name="(missing)",
                    description=f"Table '{qname}' defined in data model but no DDL file generated",
                    suggested_fix=f"Run DDL generator for table '{table.name}' with layer={table.layer.value}",
                ))

        # Check 2: Column completeness — all model columns present in DDL
        for table in request.data_model.tables:
            qname = self.parser.get_qualified_name(table)
            ddl_match = next((d for d in ddl_result.ddl_files if d.table_name.split(".")[-1] == qname), None)
            if not ddl_match:
                continue
            for col in table.columns:
                if col.name not in ddl_match.sql:
                    findings.append(ReviewFinding(
                        check_name="COLUMN_COMPLETENESS",
                        severity=Severity.CRITICAL,
                        file_name=ddl_match.file_name,
                        description=f"Column '{col.name}' missing from DDL for table '{qname}'",
                        suggested_fix=f"Add column: {col.name} {col.data_type}",
                    ))

        # Check 3: DML exists for every table
        dml_targets = {d.target_table for d in dml_result.dml_files}
        for table in request.data_model.tables:
            qname = self.parser.get_qualified_name(table)
            if qname not in dml_targets:
                findings.append(ReviewFinding(
                    check_name="DML_COVERAGE",
                    severity=Severity.WARNING,
                    file_name="(missing)",
                    description=f"No DML/transformation generated for table '{qname}'",
                    suggested_fix=f"Generate DML for '{table.name}' with strategy={table.refresh_strategy.value}",
                ))

        # Check 4: Primary key columns referenced in DML
        for table in request.data_model.tables:
            qname = self.parser.get_qualified_name(table)
            dml_match = next((d for d in dml_result.dml_files if d.target_table == qname), None)
            if not dml_match:
                continue
            for pk in table.primary_key:
                if pk not in dml_match.sql:
                    findings.append(ReviewFinding(
                        check_name="PK_IN_DML",
                        severity=Severity.WARNING,
                        file_name=dml_match.file_name,
                        description=f"Primary key column '{pk}' not found in DML for '{qname}'",
                        suggested_fix=f"Ensure '{pk}' is included in SELECT and JOIN/PARTITION BY clauses",
                    ))

        # Check 5: Partition column filter in DML
        for table in request.data_model.tables:
            if not table.partition_config:
                continue
            qname = self.parser.get_qualified_name(table)
            dml_match = next((d for d in dml_result.dml_files if d.target_table == qname), None)
            if not dml_match:
                continue
            part_col = table.partition_config.column
            if part_col not in dml_match.sql:
                findings.append(ReviewFinding(
                    check_name="PARTITION_ALIGNMENT",
                    severity=Severity.WARNING,
                    file_name=dml_match.file_name,
                    description=f"Partition column '{part_col}' not referenced in DML for '{qname}' — full table scan risk",
                    suggested_fix=f"Add WHERE {part_col} > ... or include {part_col} in SELECT",
                ))

        # Determine verdict
        criticals = [f for f in findings if f.severity == Severity.CRITICAL]
        warnings = [f for f in findings if f.severity == Severity.WARNING]
        if criticals:
            verdict = Verdict.FAIL
        elif warnings:
            verdict = Verdict.CONDITIONAL_PASS
        else:
            verdict = Verdict.PASS

        return ReviewResult(
            dimension="correctness",
            verdict=verdict,
            summary=f"Correctness review: {len(criticals)} critical, {len(warnings)} warning, {len(findings) - len(criticals) - len(warnings)} info findings",
            findings=findings,
            stats={
                "tables_checked": len(request.data_model.tables),
                "ddl_files_found": len(ddl_result.ddl_files),
                "dml_files_found": len(dml_result.dml_files),
                "critical_count": len(criticals),
                "warning_count": len(warnings),
            },
        )

    def review_security(
        self,
        request: GenerateRequest,
        ddl_result: DDLGenerationResult,
        dml_result: DMLGenerationResult,
    ) -> ReviewResult:
        findings = []

        # Scan all generated SQL for secrets
        all_files = [(d.file_name, d.sql) for d in ddl_result.ddl_files] + \
                    [(d.file_name, d.sql) for d in dml_result.dml_files]

        for fname, sql in all_files:
            for pattern, desc in SECRET_PATTERNS:
                matches = re.findall(pattern, sql)
                if matches:
                    findings.append(ReviewFinding(
                        check_name="SECRET_DETECTED",
                        severity=Severity.CRITICAL,
                        file_name=fname,
                        description=f"{desc} detected in generated SQL",
                        suggested_fix="Replace with environment variable reference: ${VARIABLE_NAME}",
                    ))

        # Check PII masking in DML output
        for table in request.data_model.tables:
            pii_cols = self.parser.get_pii_columns(table)
            if not pii_cols:
                continue
            qname = self.parser.get_qualified_name(table)
            dml_match = next((d for d in dml_result.dml_files if d.target_table == qname), None)
            if not dml_match:
                continue
            for pii_col in pii_cols:
                # Check if PII column appears in SELECT without masking
                if pii_col in dml_match.sql:
                    has_masking = any(mask in dml_match.sql for mask in [
                        f"SHA256({pii_col})", f"SHA256(CAST({pii_col}",
                        f"REGEXP_REPLACE({pii_col}", f"TO_HEX(SHA256",
                        f"'MASKED'", f"'***'"
                    ])
                    if not has_masking and table.layer.value != "stg":
                        findings.append(ReviewFinding(
                            check_name="PII_UNMASKED",
                            severity=Severity.WARNING,
                            file_name=dml_match.file_name,
                            description=f"PII column '{pii_col}' appears unmasked in DML for non-staging table '{qname}'",
                            suggested_fix=f"Apply masking: SHA256(CAST({pii_col} AS BYTES)) or use BigQuery column-level policy tags",
                        ))

        # Check for placeholder credential patterns (${} is OK)
        for fname, sql in all_files:
            if re.search(r'(?i)(password|secret|key)\s*=\s*["\'][^$][^{]', sql):
                findings.append(ReviewFinding(
                    check_name="HARDCODED_CREDENTIAL",
                    severity=Severity.CRITICAL,
                    file_name=fname,
                    description="Possible hardcoded credential (non-placeholder value)",
                    suggested_fix="Use ${VARIABLE_NAME} placeholders for all credentials",
                ))

        criticals = [f for f in findings if f.severity == Severity.CRITICAL]
        warnings = [f for f in findings if f.severity == Severity.WARNING]
        if criticals:
            verdict = Verdict.FAIL
        elif warnings:
            verdict = Verdict.CONDITIONAL_PASS
        else:
            verdict = Verdict.PASS

        return ReviewResult(
            dimension="security",
            verdict=verdict,
            summary=f"Security review: {len(criticals)} critical, {len(warnings)} warning findings",
            findings=findings,
            stats={
                "files_scanned": len(all_files),
                "secret_patterns_checked": len(SECRET_PATTERNS),
                "pii_columns_checked": sum(len(self.parser.get_pii_columns(t)) for t in request.data_model.tables),
                "critical_count": len(criticals),
                "warning_count": len(warnings),
            },
        )
