"""
agents/validator/agent.py
--------------------------
ValidatorAgent: pure business logic.
Takes a list of test case dicts, runs each BQ query via BQService,
returns enriched list with actual_result and verdict.
"""

from __future__ import annotations
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import LLM_UTILITY_ROOT, LLM_PROVIDER, LLM_MODEL, LLM_MAX_TOKENS, VALIDATOR_OUTPUT_DIR, ICD_DIR
from services.bq_service import BQService
from services.audit_service import AuditService
from storage.local_storage import save_csv, save_excel, build_validator_stem

sys.path.insert(0, str(LLM_UTILITY_ROOT))
from core.utilities.llm import create_llm_client


class ValidatorAgent:

    def __init__(self):
        self._bq  = BQService()
        self._llm = create_llm_client(LLM_PROVIDER, model=LLM_MODEL or None)

    # ── ICD helpers ────────────────────────────────────────────────────────────

    def _load_icd_meta(self, icd_filename: str) -> dict:
        """Load ICD and return {table_name, pk_cols, icd_columns}."""
        try:
            from agents.generator.connectors import _datehr_key
            from services.icd_parser import ICDParserService
            import csv as _csv, io as _io

            candidates = sorted(ICD_DIR.glob("*.csv"), key=_datehr_key, reverse=True)
            if not candidates:
                return {}
            match    = next((f for f in candidates if f.name == icd_filename), None) if icd_filename else None
            icd_path = match or candidates[0]
            print(f"  [ValidatorAgent] Using ICD: {icd_path.name}")

            text        = icd_path.read_text(encoding="utf-8")
            meta        = ICDParserService(text).parse()
            reader      = _csv.DictReader(_io.StringIO(text))
            rows        = list(reader)
            meta["icd_columns"] = rows
            # Extract source table name (MySQL side) from first data row
            meta["source_table_name"] = (rows[0].get("source_table") or "") if rows else ""
            return meta
        except Exception as e:
            print(f"  [ValidatorAgent] ICD load failed: {e}")
            return {}

    # ── Programmatic checks ────────────────────────────────────────────────────

    def _check_schema(self, table_name: str, icd_columns: list) -> tuple[str, str]:
        """
        Compare BQ table column names + data types against ICD.
        Returns (actual_result, verdict).
        """
        result = self._bq.compare_schema(table_name, icd_columns)
        if "error" in result:
            return f"ERROR: {result['error']}", "FAIL"

        lines = []
        if result["missing"]:
            lines.append(f"Missing columns: {result['missing']}")
        if result["extra"]:
            lines.append(f"Extra columns not in ICD: {result['extra']}")
        if result["type_mismatches"]:
            lines.append(f"Type mismatches: {result['type_mismatches']}")

        if lines:
            return " | ".join(lines), "FAIL"

        return (
            f"{result['column_count']} columns — all names and types match ICD",
            "PASS",
        )

    def _check_enum(self, source_table: str, target_table: str,
                    col: str) -> tuple[str, str]:
        """
        Compare distinct values of col between source and target.
        PASS if both tables have the same set of distinct values.
        """
        if not col:
            return "No column specified", "SKIP"
        src_vals = self._bq.get_distinct_values(source_table, col)
        tgt_vals = self._bq.get_distinct_values(target_table, col)
        if isinstance(src_vals, str) or isinstance(tgt_vals, str):
            return f"ERROR fetching values: src={src_vals} tgt={tgt_vals}", "FAIL"
        missing = sorted(set(src_vals) - set(tgt_vals))
        extra   = sorted(set(tgt_vals) - set(src_vals))
        if missing or extra:
            actual = (f"{col}: source={sorted(src_vals)}, target={sorted(tgt_vals)}"
                      + (f" | missing in target: {missing}" if missing else "")
                      + (f" | extra in target: {extra}" if extra else ""))
            return actual, "FAIL"
        return f"{col}: both source and target have same values {sorted(src_vals)}", "PASS"

    # ── MySQL helpers (source_db mode) ─────────────────────────────────────────

    def _mysql_scalar(self, source_table: str, sql: str) -> str:
        """Run a scalar COUNT query against MySQL. Returns result as string."""
        try:
            from services.source_db_service import SourceDbService
            rows = SourceDbService().run_query(sql)
            return str(list(rows[0].values())[0]) if rows else "0"
        except Exception as e:
            return f"ERROR: {e}"

    def _mysql_distinct(self, source_table: str, col: str) -> list | str:
        """Get distinct non-null values of col from MySQL source table."""
        try:
            from services.source_db_service import SourceDbService
            rows = SourceDbService().run_query(
                f"SELECT DISTINCT `{col}` AS val FROM `{source_table}` "
                f"WHERE `{col}` IS NOT NULL ORDER BY val"
            )
            return [str(r.get("val", "")) for r in rows]
        except Exception as e:
            return f"ERROR: {e}"

    def _mysql_schema(self, source_table: str) -> dict | str:
        """Return {col_name: data_type} from MySQL INFORMATION_SCHEMA."""
        try:
            from services.source_db_service import SourceDbService
            svc      = SourceDbService()
            db_name  = svc.get_config().get("database", "")
            rows     = svc.run_query(
                f"SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
                f"WHERE TABLE_SCHEMA = '{db_name}' AND TABLE_NAME = '{source_table}' "
                f"ORDER BY ORDINAL_POSITION"
            )
            return {r["COLUMN_NAME"].upper(): r["DATA_TYPE"].upper() for r in rows}
        except Exception as e:
            return f"ERROR: {e}"

    def _count_nulls(self, table: str, col: str) -> str:
        """Return null count for a column in a table as a string."""
        from config import GCP_PROJECT_ID, GCP_DATASET_ID
        return self._bq.run_query(
            f"SELECT COUNT(*) AS n FROM `{GCP_PROJECT_ID}.{GCP_DATASET_ID}.{table}` "
            f"WHERE `{col}` IS NULL"
        )

    def _count_empty(self, table: str, col: str) -> str:
        """Return empty/whitespace count for a column in a table as a string."""
        from config import GCP_PROJECT_ID, GCP_DATASET_ID
        return self._bq.run_query(
            f"SELECT COUNT(*) AS n FROM `{GCP_PROJECT_ID}.{GCP_DATASET_ID}.{table}` "
            f"WHERE TRIM(CAST(`{col}` AS STRING)) = ''"
        )

    def _check_null(self, source_table: str, target_table: str,
                    col: str) -> tuple[str, str]:
        """
        Compare null count in source vs target for a column.
        PASS if both have 0 nulls.
        """
        if not col:
            return "No column specified", "SKIP"
        src = self._count_nulls(source_table, col)
        tgt = self._count_nulls(target_table, col)
        actual = f"{col}: source null_count={src}, target null_count={tgt}"
        verdict = "PASS" if src.strip() == "0" and tgt.strip() == "0" else "FAIL"
        return actual, verdict

    def _check_empty(self, source_table: str, target_table: str,
                     col: str) -> tuple[str, str]:
        """
        Compare empty/whitespace count in source vs target for a column.
        PASS if both have 0 empty values.
        """
        if not col:
            return "No column specified", "SKIP"
        src = self._count_empty(source_table, col)
        tgt = self._count_empty(target_table, col)
        actual = f"{col}: source empty_count={src}, target empty_count={tgt}"
        verdict = "PASS" if src.strip() == "0" and tgt.strip() == "0" else "FAIL"
        return actual, verdict

    def _check_partition_and_cluster(self, table_name: str) -> tuple[str, str]:
        """
        Compare partition column and cluster columns between
        {table}_synthetic (source) and {table} (target).
        Returns (actual_result, verdict).
        """
        synthetic = table_name + "_synthetic"
        target_info = self._bq.get_partition_info(table_name)
        source_info = self._bq.get_partition_info(synthetic)

        t_part = target_info.get("partition_column")
        s_part = source_info.get("partition_column")
        t_clus = target_info.get("cluster_columns", [])
        s_clus = source_info.get("cluster_columns", [])

        issues = []
        if t_part != s_part:
            issues.append(f"Partition column: source={s_part}, target={t_part}")
        if t_clus != s_clus:
            issues.append(f"Cluster columns: source={s_clus}, target={t_clus}")

        if issues:
            return " | ".join(issues), "FAIL"

        parts = []
        if t_part:
            parts.append(f"Both partitioned by {t_part}")
        if t_clus:
            parts.append(f"Both clustered by {t_clus}")
        if not parts:
            return "Neither table is partitioned or clustered", "SKIP"
        return " | ".join(parts) + " — match", "PASS"

    # ── Main run ───────────────────────────────────────────────────────────────

    def run(self, records: list[dict], source_filename: str | None = None,
            icd_filename: str | None = None, mode: str = "synthetic",
            mysql_config: dict | None = None) -> list[dict]:

        total   = len(records)
        results = []

        icd = self._load_icd_meta(icd_filename or "")
        table_name        = icd.get("table_name", "")
        pk_cols           = icd.get("pk_cols", [])
        icd_columns       = icd.get("icd_columns", [])
        source_table_name = icd.get("source_table_name", "")   # MySQL table name
        synthetic_table   = table_name + "_synthetic" if table_name else ""
        if table_name:
            print(f"  [ValidatorAgent] table={table_name} mode={mode} PKs={pk_cols}")

        for i, row in enumerate(records, 1):
            tc_id    = row.get("tc_id", f"TC-{i:03d}")
            category = (row.get("category") or "").strip().lower()
            query    = str(row.get("query", "") or "")
            expected = str(row.get("expected_result", "") or "")

            print(f"  [{i}/{total}] {tc_id} ({category}) ...", end=" ", flush=True)

            # ── Referential integrity checks — skip for synthetic mode ─────────
            _ref_keywords = ("orphan", "referential", "foreign key", "integrity",
                             "parent", "cross-table", "cross table")
            test_name_raw = (row.get("test_name") or "").strip().lower()
            if mode == "synthetic" and any(k in test_name_raw for k in _ref_keywords):
                actual         = "N/A (referential integrity check not applicable for synthetic data)"
                verdict        = "SKIP"
                resolved_query = query
                enriched = {**row, "resolved_query": resolved_query,
                            "actual_result": actual, "verdict": verdict}
                results.append(enriched)
                print(verdict)
                continue

            # ── Schema Validation ──────────────────────────────────────────────
            if "schema" in category and table_name:
                test_name = (row.get("test_name") or "").strip().lower()
                is_count  = any(k in test_name for k in ("count", "number of column"))

                if mode == "source_db" and source_table_name:
                    mysql_schema = self._mysql_schema(source_table_name)
                    bq_schema    = self._bq.compare_bq_schemas(table_name, table_name)
                    src_label    = f"MySQL:{source_table_name}"
                    if isinstance(mysql_schema, str):  # error string
                        actual, verdict = f"ERROR: {mysql_schema}", "FAIL"
                        result = {}
                    else:
                        bq_cols = set(self._bq.get_distinct_values.__func__ and [])  # unused
                        mysql_set = set(mysql_schema.keys())
                        bq_result = self._bq.compare_bq_schemas(table_name, table_name)
                        bq_cols_q = f"SELECT column_name FROM `{__import__('config').GCP_PROJECT_ID}.{__import__('config').GCP_DATASET_ID}`.INFORMATION_SCHEMA.COLUMNS WHERE table_name='{table_name}'"
                        bq_rows   = list(self._bq._client.query(bq_cols_q).result()) if self._bq._client else []
                        bq_set    = {r.column_name.upper() for r in bq_rows}
                        missing   = sorted(mysql_set - bq_set)
                        extra     = sorted(bq_set - mysql_set)
                        src_count = len(mysql_set)
                        tgt_count = len(bq_set)
                        if is_count:
                            if src_count == tgt_count:
                                actual  = f"column_count: {src_label}={src_count}, {table_name}={tgt_count} — match"
                                verdict = "PASS"
                            else:
                                actual  = f"column_count mismatch: {src_label}={src_count}, {table_name}={tgt_count}"
                                verdict = "FAIL"
                        else:
                            if missing or extra:
                                actual  = (f"Missing in BQ: {missing} | " if missing else "") + (f"Extra in BQ: {extra}" if extra else "")
                                verdict = "FAIL"
                            else:
                                actual  = f"All {tgt_count} columns match between {src_label} and {table_name}"
                                verdict = "PASS"
                        resolved_query = f"INFORMATION_SCHEMA.COLUMNS: {src_label} vs BQ:{table_name}"
                else:
                    source_name = synthetic_table
                    result = self._bq.compare_bq_schemas(source_name, table_name)
                    if is_count:
                        if "error" in result:
                            actual, verdict = f"ERROR: {result['error']}", "FAIL"
                        elif result["source_count"] == result["column_count"]:
                            actual  = (f"column_count: {source_name}={result['source_count']}, "
                                       f"{table_name}={result['column_count']} — match")
                            verdict = "PASS"
                        else:
                            actual  = (f"column_count mismatch: {source_name}={result['source_count']}, "
                                       f"{table_name}={result['column_count']}")
                            verdict = "FAIL"
                        resolved_query = f"COUNT(columns) INFORMATION_SCHEMA: {source_name} vs {table_name}"
                    else:
                        if "error" in result:
                            actual, verdict = f"ERROR: {result['error']}", "FAIL"
                        elif result["missing"] or result["extra"] or result["type_mismatches"]:
                            actual, verdict = result["summary"], "FAIL"
                        else:
                            actual  = f"All {result['column_count']} columns match — names and data types identical"
                            verdict = "PASS"
                        resolved_query = f"INFORMATION_SCHEMA.COLUMNS: {source_name} vs {table_name}"

            # ── Null / Empty check ─────────────────────────────────────────────
            elif any(k in category for k in ("null", "empty")) and table_name:
                test_name = (row.get("test_name") or "").strip().lower()
                is_empty  = any(k in test_name for k in ("empty", "whitespace", "blank"))
                col       = (row.get("column") or (pk_cols[0] if pk_cols else ""))

                if mode == "source_db" and source_table_name:
                    cond      = f"TRIM(CAST(`{col}` AS CHAR)) = ''" if is_empty else f"`{col}` IS NULL"
                    label     = "empty_count" if is_empty else "null_count"
                    src_val   = self._mysql_scalar(source_table_name, f"SELECT COUNT(*) AS n FROM `{source_table_name}` WHERE {cond}")
                    tgt_val   = self._count_empty(table_name, col) if is_empty else self._count_nulls(table_name, col)
                    actual    = f"{col}: MySQL:{source_table_name} {label}={src_val}, BQ:{table_name} {label}={tgt_val}"
                    verdict   = "PASS" if src_val.strip() == "0" and tgt_val.strip() == "0" else "FAIL"
                    resolved_query = f"COUNT(*) WHERE {cond} — MySQL:{source_table_name} vs BQ:{table_name}"
                else:
                    source_name = synthetic_table
                    if is_empty:
                        actual, verdict = self._check_empty(source_name, table_name, col)
                        resolved_query  = f"SELECT COUNT(*) WHERE TRIM(CAST(`{col}` AS STRING)) = '' — {source_name} vs {table_name}"
                    else:
                        actual, verdict = self._check_null(source_name, table_name, col)
                        resolved_query  = f"SELECT COUNT(*) WHERE `{col}` IS NULL — {source_name} vs {table_name}"

            # ── Partition + Cluster check ──────────────────────────────────────
            elif "partition" in category and table_name:
                if mode == "source_db":
                    actual, verdict = "N/A (partition check not applicable for source_db mode)", "SKIP"
                    resolved_query  = ""
                else:
                    actual, verdict = self._check_partition_and_cluster(table_name)
                    resolved_query  = (f"INFORMATION_SCHEMA — partition + cluster: "
                                       f"{synthetic_table} vs {table_name}")

            # ── Enumeration check ──────────────────────────────────────────────
            elif "enumeration" in category and table_name:
                col = (row.get("column") or "").strip()
                if mode == "source_db" and source_table_name:
                    src_vals = self._mysql_distinct(source_table_name, col)
                    tgt_vals = self._bq.get_distinct_values(table_name, col)
                    if isinstance(src_vals, str) or isinstance(tgt_vals, str):
                        actual, verdict = f"ERROR: src={src_vals} tgt={tgt_vals}", "FAIL"
                    else:
                        missing = sorted(set(src_vals) - set(tgt_vals))
                        extra   = sorted(set(tgt_vals) - set(src_vals))
                        if missing or extra:
                            actual  = (f"{col}: MySQL={sorted(src_vals)}, BQ={sorted(tgt_vals)}"
                                       + (f" | missing in BQ: {missing}" if missing else "")
                                       + (f" | extra in BQ: {extra}" if extra else ""))
                            verdict = "FAIL"
                        else:
                            actual  = f"{col}: MySQL and BQ both have {sorted(src_vals)}"
                            verdict = "PASS"
                    resolved_query = f"SELECT DISTINCT `{col}` — MySQL:{source_table_name} vs BQ:{table_name}"
                else:
                    actual, verdict = self._check_enum(synthetic_table, table_name, col)
                    resolved_query  = f"SELECT DISTINCT `{col}` — {synthetic_table} vs {table_name}"

            # ── All other categories — run LLM-generated query ─────────────────
            else:
                resolved_query = self._bq.resolve(query)
                actual         = self._bq.run_query(query)
                verdict        = BQService.determine_verdict(expected, actual)

            enriched = {**row, "resolved_query": resolved_query,
                        "actual_result": actual, "verdict": verdict}
            results.append(enriched)
            print(verdict)

        stem     = build_validator_stem(source_filename)
        csv_path = save_csv(results, VALIDATOR_OUTPUT_DIR, stem=stem)
        save_excel(results, VALIDATOR_OUTPUT_DIR, stem=stem,
                   sheet_name="Validation Results", verdict_col="verdict")
        print(f"=== Saved {len(results)} results to {csv_path} ===")

        try:
            AuditService().log_run(
                results,
                icd_filename=icd_filename or "",
                source_file=source_filename or "",
                mode=mode,
            )
        except Exception as _ae:
            print(f"  [AuditService] WARNING: failed to log run — {_ae}")

        return results
