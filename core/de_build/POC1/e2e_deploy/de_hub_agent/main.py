"""
DE Hub Agent — Main Pipeline
Orchestrates: Input Parse → DDL Gen → DML Gen → Self-Review → Output
"""
import json
import hashlib
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))

from core.models import (
    PipelineResult, ManifestEntry, Verdict, ReviewResult,
)
from modules.input_parser.parser import InputParser
from modules.ddl_gen.generator import DDLGenerator
from modules.dml_gen.generator import DMLGenerator
from modules.self_review.reviewer import SelfReviewAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("de_hub_agent")


def run_pipeline(payload_path: str, output_dir: str = None) -> PipelineResult:
    """Run the full code generation pipeline on a sample payload."""

    logger.info("=" * 70)
    logger.info("DE HUB CODE GENERATOR & OPTIMIZER AGENT — POC Pipeline")
    logger.info("=" * 70)

    # ─── Stage 1: Parse Input ─────────────────────────────────────
    logger.info("[1/6] Parsing input payload...")
    parser = InputParser()
    request = parser.parse_file(payload_path)
    logger.info("  ✓ Parsed %d tables, %d rules, %d mappings",
                len(request.data_model.tables),
                len(request.transformation_rules),
                len(request.column_mappings))

    # ─── Stage 2: Generate DDL ────────────────────────────────────
    logger.info("[2/6] Generating BigQuery DDL...")
    ddl_gen = DDLGenerator(parser)
    ddl_result = ddl_gen.generate(request)
    logger.info("  ✓ Generated %d DDL files, %d grant statements",
                len(ddl_result.ddl_files), len(ddl_result.grant_statements))

    # ─── Stage 3: Generate DML ────────────────────────────────────
    logger.info("[3/6] Generating BigQuery DML / transformations...")
    dml_gen = DMLGenerator(parser)
    dml_result = dml_gen.generate(request)
    logger.info("  ✓ Generated %d DML files", len(dml_result.dml_files))
    for dml in dml_result.dml_files:
        logger.info("    - %s (%s)", dml.file_name, dml.pattern.value)

    # ─── Stage 4: Self-Review ─────────────────────────────────────
    logger.info("[4/6] Running self-review (correctness + security)...")
    reviewer = SelfReviewAgent(parser)
    review_results = reviewer.review_all(request, ddl_result, dml_result)
    for rr in review_results:
        logger.info("  %s review: %s (%d findings)",
                     rr.dimension.upper(), rr.verdict.value, len(rr.findings))
        for f in rr.findings:
            logger.info("    [%s] %s — %s: %s", f.severity.value, f.check_name, f.file_name, f.description)

    # ─── Stage 5: Write Output ────────────────────────────────────
    logger.info("[5/6] Writing output files...")
    if not output_dir:
        output_dir = str(Path(__file__).parent / "output" / request.request_id)
    out = Path(output_dir)
    (out / "ddl").mkdir(parents=True, exist_ok=True)
    (out / "dml").mkdir(parents=True, exist_ok=True)
    (out / "docs").mkdir(parents=True, exist_ok=True)

    manifest_entries = []

    for ddl in ddl_result.ddl_files:
        fpath = out / "ddl" / ddl.file_name
        fpath.write_text(ddl.sql)
        manifest_entries.append(ManifestEntry(
            path=f"ddl/{ddl.file_name}",
            purpose=f"DDL for {ddl.table_name}",
            sha256=hashlib.sha256(ddl.sql.encode()).hexdigest(),
            dependencies=[],
        ))

    for dml in dml_result.dml_files:
        fpath = out / "dml" / dml.file_name
        fpath.write_text(dml.sql)
        manifest_entries.append(ManifestEntry(
            path=f"dml/{dml.file_name}",
            purpose=f"DML ({dml.pattern.value}) for {dml.target_table}",
            sha256=hashlib.sha256(dml.sql.encode()).hexdigest(),
            dependencies=[f"ddl/{ddl.file_name}" for ddl in ddl_result.ddl_files if ddl.table_name.split('.')[-1] == dml.target_table],
        ))

    if ddl_result.grant_statements:
        grants_sql = "\n".join(ddl_result.grant_statements)
        (out / "ddl" / "_grants.sql").write_text(grants_sql)
        manifest_entries.append(ManifestEntry(
            path="ddl/_grants.sql", purpose="GRANT statements for PII tables",
            sha256=hashlib.sha256(grants_sql.encode()).hexdigest(),
        ))

    # Write review report
    review_json = [rr.model_dump() for rr in review_results]
    (out / "REVIEW_REPORT.json").write_text(json.dumps(review_json, indent=2))

    # Write human-readable review report
    md = _generate_review_markdown(review_results, request)
    (out / "REVIEW_REPORT.md").write_text(md)

    # Write manifest
    manifest_json = [m.model_dump() for m in manifest_entries]
    (out / "MANIFEST.json").write_text(json.dumps(manifest_json, indent=2))

    logger.info("  ✓ Output written to: %s", out)
    logger.info("  ✓ Files: %d DDL, %d DML, 1 MANIFEST, 1 REVIEW_REPORT", len(ddl_result.ddl_files), len(dml_result.dml_files))

    # ─── Stage 6: Compute Quality Score ───────────────────────────
    logger.info("[6/6] Computing quality score...")
    criticals = sum(1 for rr in review_results for f in rr.findings if f.severity.value == "CRITICAL")
    warnings = sum(1 for rr in review_results for f in rr.findings if f.severity.value == "WARNING")
    infos = sum(1 for rr in review_results for f in rr.findings if f.severity.value == "INFO")
    quality_score = max(0, 100 - (10 * criticals) - (3 * warnings) - (1 * infos))

    overall_verdict = Verdict.FAIL if criticals > 0 else (Verdict.CONDITIONAL_PASS if warnings > 0 else Verdict.PASS)

    logger.info("")
    logger.info("=" * 70)
    logger.info("PIPELINE COMPLETE")
    logger.info("  Overall Verdict: %s", overall_verdict.value)
    logger.info("  Quality Score: %d/100", quality_score)
    logger.info("  Findings: %d critical, %d warning, %d info", criticals, warnings, infos)
    logger.info("  Output: %s", out)
    logger.info("=" * 70)

    return PipelineResult(
        request_id=request.request_id,
        status="completed",
        ddl_result=ddl_result,
        dml_result=dml_result,
        review_results=review_results,
        manifest=manifest_entries,
        quality_score=quality_score,
        output_directory=str(out),
    )


def _generate_review_markdown(reviews: list[ReviewResult], request) -> str:
    lines = [
        "# Self-Review Report",
        f"**Request ID:** {request.request_id}",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"**Tables reviewed:** {len(request.data_model.tables)}",
        "",
    ]

    for rr in reviews:
        lines.append(f"## {rr.dimension.upper()} Review")
        lines.append(f"**Verdict:** {rr.verdict.value}")
        lines.append(f"**Summary:** {rr.summary}")
        lines.append("")

        if rr.findings:
            lines.append("| Severity | Check | File | Description | Fix |")
            lines.append("|----------|-------|------|-------------|-----|")
            for f in rr.findings:
                lines.append(f"| {f.severity.value} | {f.check_name} | {f.file_name} | {f.description} | {f.suggested_fix} |")
            lines.append("")
        else:
            lines.append("No findings. All checks passed.")
            lines.append("")

        if rr.stats:
            lines.append("**Stats:**")
            for k, v in rr.stats.items():
                lines.append(f"- {k}: {v}")
            lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    payload = sys.argv[1] if len(sys.argv) > 1 else "sample_payloads/ecommerce_medium.json"
    output = sys.argv[2] if len(sys.argv) > 2 else None
    result = run_pipeline(payload, output)
