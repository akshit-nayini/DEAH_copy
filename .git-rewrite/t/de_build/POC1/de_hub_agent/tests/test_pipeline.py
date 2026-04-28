"""
Tests for DE Hub Agent POC Pipeline.
Run: cd de_hub_agent && python3 -m pytest tests/ -v
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import (
    GenerateRequest, RefreshStrategy, LayerType,
    Verdict, Severity,
)
from modules.input_parser.parser import InputParser
from modules.ddl_gen.generator import DDLGenerator
from modules.dml_gen.generator import DMLGenerator
from modules.self_review.reviewer import SelfReviewAgent


SAMPLE_PAYLOAD = Path(__file__).parent.parent / "sample_payloads" / "ecommerce_medium.json"


def load_request() -> GenerateRequest:
    parser = InputParser()
    return parser.parse_file(str(SAMPLE_PAYLOAD))


# ─── Input Parser Tests ─────────────────────────────────────────────

class TestInputParser:

    def test_parse_sample_payload(self):
        request = load_request()
        assert request.request_id == "poc-demo-001"
        assert len(request.data_model.tables) == 6

    def test_table_names_unique(self):
        request = load_request()
        names = [t.name for t in request.data_model.tables]
        assert len(names) == len(set(names))

    def test_layer_assignment(self):
        request = load_request()
        parser = InputParser()
        dim_tables = parser.get_tables_by_layer(request, LayerType.DIMENSION)
        fct_tables = parser.get_tables_by_layer(request, LayerType.FACT)
        stg_tables = parser.get_tables_by_layer(request, LayerType.STAGING)
        assert len(dim_tables) == 3  # customer, product, shipping_region
        assert len(fct_tables) == 2  # orders, daily_sales_summary
        assert len(stg_tables) == 1  # order_events

    def test_pii_detection(self):
        request = load_request()
        parser = InputParser()
        customer = next(t for t in request.data_model.tables if t.name == "customer")
        pii = parser.get_pii_columns(customer)
        assert "email" in pii
        assert "first_name" in pii
        assert "customer_id" not in pii

    def test_qualified_name_has_prefix(self):
        request = load_request()
        parser = InputParser()
        customer = next(t for t in request.data_model.tables if t.name == "customer")
        assert parser.get_qualified_name(customer) == "dim_customer"

    def test_rejects_unsupported_platform(self):
        data = json.loads(SAMPLE_PAYLOAD.read_text())
        data["tech_stack"]["target_platform"] = "snowflake"
        parser = InputParser()
        try:
            parser.parse_dict(data)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "snowflake" in str(e).lower()

    def test_rejects_duplicate_tables(self):
        data = json.loads(SAMPLE_PAYLOAD.read_text())
        data["data_model"]["tables"].append(data["data_model"]["tables"][0])
        parser = InputParser()
        try:
            parser.parse_dict(data)
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


# ─── DDL Generator Tests ────────────────────────────────────────────

class TestDDLGenerator:

    def test_generates_all_tables(self):
        request = load_request()
        parser = InputParser()
        gen = DDLGenerator(parser)
        result = gen.generate(request)
        assert len(result.ddl_files) == 6
        assert len(result.warnings) == 0

    def test_ddl_has_create_table(self):
        request = load_request()
        parser = InputParser()
        gen = DDLGenerator(parser)
        result = gen.generate(request)
        for ddl in result.ddl_files:
            assert "CREATE TABLE IF NOT EXISTS" in ddl.sql

    def test_ddl_uses_placeholders(self):
        request = load_request()
        parser = InputParser()
        gen = DDLGenerator(parser)
        result = gen.generate(request)
        for ddl in result.ddl_files:
            assert "${PROJECT_ID}" in ddl.sql
            assert "${DATASET}" in ddl.sql

    def test_scd2_table_has_tracking_columns(self):
        request = load_request()
        parser = InputParser()
        gen = DDLGenerator(parser)
        result = gen.generate(request)
        customer_ddl = next(d for d in result.ddl_files if "dim_customer" in d.file_name)
        assert "_surrogate_key" in customer_ddl.sql
        assert "_effective_from" in customer_ddl.sql
        assert "_effective_to" in customer_ddl.sql
        assert "_is_current" in customer_ddl.sql
        assert "_row_hash" in customer_ddl.sql

    def test_non_scd2_table_no_tracking_columns(self):
        request = load_request()
        parser = InputParser()
        gen = DDLGenerator(parser)
        result = gen.generate(request)
        product_ddl = next(d for d in result.ddl_files if "dim_product" in d.file_name)
        assert "_surrogate_key" not in product_ddl.sql
        assert "_effective_from" not in product_ddl.sql

    def test_partition_clause_present(self):
        request = load_request()
        parser = InputParser()
        gen = DDLGenerator(parser)
        result = gen.generate(request)
        orders_ddl = next(d for d in result.ddl_files if "fct_orders" in d.file_name)
        assert "PARTITION BY" in orders_ddl.sql

    def test_cluster_clause_present(self):
        request = load_request()
        parser = InputParser()
        gen = DDLGenerator(parser)
        result = gen.generate(request)
        orders_ddl = next(d for d in result.ddl_files if "fct_orders" in d.file_name)
        assert "CLUSTER BY" in orders_ddl.sql

    def test_pii_columns_annotated(self):
        request = load_request()
        parser = InputParser()
        gen = DDLGenerator(parser)
        result = gen.generate(request)
        customer_ddl = next(d for d in result.ddl_files if "dim_customer" in d.file_name)
        assert "PII: requires policy tag" in customer_ddl.sql
        assert len(customer_ddl.pii_columns) == 5

    def test_grant_statements_for_pii_tables(self):
        request = load_request()
        parser = InputParser()
        gen = DDLGenerator(parser)
        result = gen.generate(request)
        assert len(result.grant_statements) > 0
        assert any("dim_customer" in g for g in result.grant_statements)


# ─── DML Generator Tests ────────────────────────────────────────────

class TestDMLGenerator:

    def test_generates_all_tables(self):
        request = load_request()
        parser = InputParser()
        gen = DMLGenerator(parser)
        result = gen.generate(request)
        assert len(result.dml_files) == 6

    def test_scd2_pattern_for_customer(self):
        request = load_request()
        parser = InputParser()
        gen = DMLGenerator(parser)
        result = gen.generate(request)
        customer_dml = next(d for d in result.dml_files if "dim_customer" in d.target_table)
        assert customer_dml.pattern == RefreshStrategy.SCD2
        assert "MERGE INTO" in customer_dml.sql
        assert "FARM_FINGERPRINT" in customer_dml.sql
        assert "SHA256" in customer_dml.sql
        assert "_is_current" in customer_dml.sql

    def test_scd1_pattern_for_product(self):
        request = load_request()
        parser = InputParser()
        gen = DMLGenerator(parser)
        result = gen.generate(request)
        product_dml = next(d for d in result.dml_files if "dim_product" in d.target_table)
        assert product_dml.pattern == RefreshStrategy.SCD1
        assert "MERGE INTO" in product_dml.sql
        assert "WHEN MATCHED" in product_dml.sql
        assert "WHEN NOT MATCHED" in product_dml.sql

    def test_incremental_for_orders(self):
        request = load_request()
        parser = InputParser()
        gen = DMLGenerator(parser)
        result = gen.generate(request)
        orders_dml = next(d for d in result.dml_files if "fct_orders" in d.target_table)
        assert orders_dml.pattern == RefreshStrategy.INCREMENTAL
        assert "INSERT INTO" in orders_dml.sql
        assert "ROW_NUMBER()" in orders_dml.sql
        assert "_dedup_rank = 1" in orders_dml.sql

    def test_full_refresh_for_shipping(self):
        request = load_request()
        parser = InputParser()
        gen = DMLGenerator(parser)
        result = gen.generate(request)
        shipping_dml = next(d for d in result.dml_files if "shipping_region" in d.target_table)
        assert shipping_dml.pattern == RefreshStrategy.FULL
        assert "CREATE OR REPLACE TABLE" in shipping_dml.sql

    def test_dml_uses_placeholders(self):
        request = load_request()
        parser = InputParser()
        gen = DMLGenerator(parser)
        result = gen.generate(request)
        for dml in result.dml_files:
            assert "${PROJECT_ID}" in dml.sql


# ─── Self-Review Tests ──────────────────────────────────────────────

class TestSelfReview:

    def _run_pipeline(self):
        request = load_request()
        parser = InputParser()
        ddl = DDLGenerator(parser).generate(request)
        dml = DMLGenerator(parser).generate(request)
        reviewer = SelfReviewAgent(parser)
        return request, ddl, dml, reviewer

    def test_correctness_passes_on_valid_output(self):
        request, ddl, dml, reviewer = self._run_pipeline()
        result = reviewer.review_correctness(request, ddl, dml)
        assert result.verdict == Verdict.PASS
        assert result.stats["critical_count"] == 0

    def test_security_detects_pii_warnings(self):
        request, ddl, dml, reviewer = self._run_pipeline()
        result = reviewer.review_security(request, ddl, dml)
        assert result.verdict == Verdict.CONDITIONAL_PASS
        pii_findings = [f for f in result.findings if f.check_name == "PII_UNMASKED"]
        assert len(pii_findings) == 5  # 5 PII columns in dim_customer

    def test_no_secrets_in_generated_code(self):
        request, ddl, dml, reviewer = self._run_pipeline()
        result = reviewer.review_security(request, ddl, dml)
        secret_findings = [f for f in result.findings if f.check_name == "SECRET_DETECTED"]
        assert len(secret_findings) == 0

    def test_quality_score_calculation(self):
        request, ddl, dml, reviewer = self._run_pipeline()
        results = reviewer.review_all(request, ddl, dml)
        criticals = sum(1 for r in results for f in r.findings if f.severity == Severity.CRITICAL)
        warnings = sum(1 for r in results for f in r.findings if f.severity == Severity.WARNING)
        score = max(0, 100 - (10 * criticals) - (3 * warnings))
        assert score == 85  # 5 warnings × 3 = 15 deducted
