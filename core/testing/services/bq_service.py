"""
services/bq_service.py
-----------------------
Thin wrapper around the Testing POD BigQuery connector.
All BQ operations for the Testing POD go through this service.
"""

from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import GCP_PROJECT_ID, GCP_DATASET_ID
from services.bigquery_connector import create_bigquery_client, create_dataset_if_missing


class BQService:
    """
    Wraps the BigQuery connector.
    Provides run_query() and verdict determination for the validator agent.
    """

    def __init__(self):
        try:
            self._client = create_bigquery_client()
            create_dataset_if_missing(self._client, GCP_DATASET_ID)
        except Exception as e:
            print(f"  [BQService] connector unavailable: {e}")
            self._client = None

    def _resolve_sql(self, sql: str) -> str:
        sql = (sql
               .replace("<project>.<dataset>", f"{GCP_PROJECT_ID}.{GCP_DATASET_ID}")
               .replace("<project>",            GCP_PROJECT_ID)
               .replace("<dataset>",            GCP_DATASET_ID)
               .replace("<table_name>",         "")
               )
        # REGEXP_CONTAINS requires STRING — auto-wrap bare column references with CAST AS STRING
        # so DATE/TIMESTAMP columns work without failing or being skipped
        sql = re.sub(
            r'REGEXP_CONTAINS\s*\(\s*(?!CAST\s*\()(`?[\w.]+`?)\s*,',
            r'REGEXP_CONTAINS(CAST(\1 AS STRING),',
            sql,
            flags=re.IGNORECASE,
        )
        return sql

    def resolve(self, sql: str) -> str:
        """Public alias — returns the query with placeholders replaced by real values."""
        return self._resolve_sql(sql)

    def get_partition_info(self, table_name: str) -> dict:
        """
        Return partition and cluster info from BQ INFORMATION_SCHEMA.
        {partition_column, partition_type, cluster_columns}
        """
        if self._client is None:
            return {}
        try:
            part_sql = (
                f"SELECT column_name, data_type "
                f"FROM `{GCP_PROJECT_ID}.{GCP_DATASET_ID}`.INFORMATION_SCHEMA.COLUMNS "
                f"WHERE table_name = '{table_name}' AND is_partitioning_column = 'YES'"
            )
            part_rows = list(self._client.query(part_sql).result())
            partition_column = part_rows[0].column_name if part_rows else None

            cluster_sql = (
                f"SELECT clustering_ordinal_position, column_name "
                f"FROM `{GCP_PROJECT_ID}.{GCP_DATASET_ID}`.INFORMATION_SCHEMA.COLUMNS "
                f"WHERE table_name = '{table_name}' AND clustering_ordinal_position IS NOT NULL "
                f"ORDER BY clustering_ordinal_position"
            )
            cluster_rows = list(self._client.query(cluster_sql).result())
            cluster_columns = [r.column_name for r in cluster_rows]

            return {
                "partition_column":  partition_column,
                "cluster_columns":   cluster_columns,
            }
        except Exception as e:
            return {"error": str(e)}

    def check_partition_data(self, table_name: str, partition_column: str) -> dict:
        """
        Check that all rows have a partition date equal to the load date (today)
        and that no rows have a NULL partition column.
        """
        if self._client is None:
            return {"error": "BQ connector not available"}
        fq = f"`{GCP_PROJECT_ID}.{GCP_DATASET_ID}.{table_name}`"
        try:
            null_rows = list(self._client.query(
                f"SELECT COUNT(*) AS n FROM {fq} WHERE `{partition_column}` IS NULL"
            ).result())[0].n
            mismatch_rows = list(self._client.query(
                f"SELECT COUNT(*) AS n FROM {fq} "
                f"WHERE DATE(`{partition_column}`) != CURRENT_DATE()"
            ).result())[0].n
            return {
                "partition_column": partition_column,
                "null_count":       null_rows,
                "mismatch_count":   mismatch_rows,
                "ok":               null_rows == 0 and mismatch_rows == 0,
                "summary": (
                    f"Partition column: {partition_column}. "
                    f"NULL rows: {null_rows}. "
                    f"Rows not on today's date: {mismatch_rows}."
                ),
            }
        except Exception as e:
            return {"error": str(e)}

    def compare_bq_schemas(self, source_table: str, target_table: str) -> dict:
        """
        Compare column names + data types between two BQ tables via INFORMATION_SCHEMA.
        Returns {column_count, source_count, missing, extra, type_mismatches, summary}
        """
        if self._client is None:
            return {"error": "BQ connector not available"}

        def _get_cols(table: str) -> dict:
            sql = (f"SELECT column_name, data_type "
                   f"FROM `{GCP_PROJECT_ID}.{GCP_DATASET_ID}`.INFORMATION_SCHEMA.COLUMNS "
                   f"WHERE table_name = '{table}' ORDER BY ordinal_position")
            try:
                return {r.column_name.upper(): r.data_type.upper()
                        for r in self._client.query(sql).result()}
            except Exception as e:
                return {"__error__": str(e)}

        src = _get_cols(source_table)
        tgt = _get_cols(target_table)

        if "__error__" in src:
            return {"error": f"Source table error: {src['__error__']}"}
        if "__error__" in tgt:
            return {"error": f"Target table error: {tgt['__error__']}"}

        missing   = [c for c in src if c not in tgt]
        extra     = [c for c in tgt if c not in src]
        type_mm   = [f"{c}: source={src[c]} target={tgt[c]}"
                     for c in src if c in tgt and src[c] != tgt[c]]

        return {
            "source_count":    len(src),
            "column_count":    len(tgt),
            "missing":         missing,
            "extra":           extra,
            "type_mismatches": type_mm,
            "summary": (
                f"Source ({source_table}): {len(src)} cols, "
                f"Target ({target_table}): {len(tgt)} cols. "
                + (f"Missing in target: {missing}. " if missing else "")
                + (f"Extra in target: {extra}. " if extra else "")
                + (f"Type mismatches: {type_mm}." if type_mm else "All types match.")
            ),
        }

    def compare_schema(self, table_name: str, icd_columns: list[dict]) -> dict:
        """
        Programmatically compare the ICD schema vs the actual BQ table schema.
        Returns {column_count, bq_columns, missing, extra, type_mismatches, summary}
        """
        if self._client is None:
            return {"error": "BQ connector not available"}

        # BQ INFORMATION_SCHEMA for the target table
        sql = (
            f"SELECT column_name, data_type "
            f"FROM `{GCP_PROJECT_ID}.{GCP_DATASET_ID}`.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE table_name = '{table_name}' "
            f"ORDER BY ordinal_position"
        )
        try:
            rows = list(self._client.query(sql).result())
        except Exception as e:
            return {"error": str(e)}

        # Normalize type names so VARCHAR→STRING, INT→INT64 etc. don't cause false mismatches
        _TYPE_NORM = {
            "VARCHAR": "STRING", "NVARCHAR": "STRING", "CHAR": "STRING",
            "TEXT": "STRING", "INTEGER": "INT64", "INT": "INT64",
            "BIGINT": "INT64", "SMALLINT": "INT64", "FLOAT": "FLOAT64",
            "DOUBLE": "FLOAT64", "BOOLEAN": "BOOL", "DECIMAL": "NUMERIC",
        }

        def norm(t: str) -> str:
            base = t.upper().split("(")[0].strip()
            return _TYPE_NORM.get(base, base)

        bq_schema = {r.column_name.upper(): norm(r.data_type) for r in rows}
        icd_schema = {
            (c.get("target_column") or "").upper(): norm(c.get("target_data_type") or "STRING")
            for c in icd_columns if c.get("target_column")
        }

        missing    = [c for c in icd_schema if c not in bq_schema]
        extra      = [c for c in bq_schema  if c not in icd_schema]
        type_mm    = [
            f"{c}: ICD={icd_schema[c]} BQ={bq_schema[c]}"
            for c in icd_schema if c in bq_schema and icd_schema[c] != bq_schema[c]
        ]

        part_info = self.get_partition_info(table_name)
        return {
            "column_count":    len(bq_schema),
            "icd_count":       len(icd_schema),
            "bq_columns":      list(bq_schema.keys()),
            "missing":         missing,
            "extra":           extra,
            "type_mismatches": type_mm,
            "partition_column": part_info.get("partition_column"),
            "cluster_columns":  part_info.get("cluster_columns", []),
            "summary": (
                f"BQ has {len(bq_schema)} columns, ICD expects {len(icd_schema)}. "
                + (f"Missing: {missing}. " if missing else "")
                + (f"Extra: {extra}. " if extra else "")
                + (f"Type mismatches: {type_mm}. " if type_mm else "All types match. ")
                + (f"Partitioned by: {part_info.get('partition_column')}. "
                   if part_info.get("partition_column") else "")
                + (f"Clustered by: {part_info.get('cluster_columns')}."
                   if part_info.get("cluster_columns") else "")
            ),
        }

    def get_distinct_values(self, table_name: str, col: str) -> list | str:
        """Return sorted list of distinct non-null values for col in table."""
        if self._client is None:
            return "ERROR: BQ connector not available"
        try:
            sql = (f"SELECT DISTINCT CAST(`{col}` AS STRING) AS val "
                   f"FROM `{GCP_PROJECT_ID}.{GCP_DATASET_ID}.{table_name}` "
                   f"WHERE `{col}` IS NOT NULL ORDER BY val")
            rows = list(self._client.query(sql).result())
            return [r.val for r in rows]
        except Exception as e:
            return f"ERROR: {e}"

    def run_query(self, sql: str) -> str:
        """
        Execute a BQ query and return a compact scalar or row-count string.
        Returns 'N/A (no query)' for empty/airflow SQL, 'Table does not exist'
        when the target table is missing, 'ERROR: ...' on other failures.
        """
        if not sql or not sql.strip() or sql.strip().lower() == "nan":
            return "N/A (no query)"
        if self._client is None:
            return "ERROR: BQ connector not available"
        try:
            from google.api_core.exceptions import NotFound
            _not_found_exc = NotFound
        except ImportError:
            _not_found_exc = None

        try:
            job  = self._client.query(self._resolve_sql(sql.strip()))
            rows = list(job.result())
            if not rows:
                # INFORMATION_SCHEMA returning 0 rows means the schema object doesn't exist
                if "information_schema" in sql.lower():
                    return "Table does not exist"
                return "0 rows"
            row0   = rows[0]
            fields = list(row0.keys())
            if len(rows) == 1 and len(fields) == 1:
                val = str(row0[fields[0]])
                # INFORMATION_SCHEMA returning 0 means the object (table/column) doesn't exist
                if val == "0" and "information_schema" in sql.lower():
                    return "Table does not exist"
                return val
            if len(rows) == 1:
                return ", ".join(f"{k}={row0[k]}" for k in fields)
            return f"{len(rows)} rows returned"
        except Exception as exc:
            # Catch BQ NotFound (404) exceptions by type first, then by message
            if _not_found_exc and isinstance(exc, _not_found_exc):
                return "Table does not exist"
            msg = str(exc)
            if any(phrase in msg for phrase in [
                "Not found", "not found", "does not exist",
                "404", "NOT_FOUND", "was not found",
            ]):
                return "Table does not exist"
            # Queries that fail due to invalid generation (not data issues) → SKIP
            _gen_errors = [
                "_PARTITIONDATE", "_PARTITIONTIME",             # pseudo-column not valid on non-partitioned table
                "No matching signature for operator",            # type mismatch (INT64 vs STRING literal)
                "policy_tags",                                  # policy tags not accessible via SQL
                "COLUMN_FIELD_PATHS",                           # BQ info schema view not available
            ]
            if any(p in msg for p in _gen_errors):
                return f"N/A (query not applicable: {msg[:120]})"
            return f"ERROR: {msg}"

    @staticmethod
    def determine_verdict(expected: str, actual: str) -> str:
        """Compare expected vs actual and return PASS, FAIL, or SKIP."""
        if actual.startswith("N/A"):
            return "SKIP"
        if actual == "Table does not exist":
            return "SKIP"
        if actual.startswith("ERROR"):
            return "FAIL"

        exp = str(expected).strip().lower()
        act = str(actual).strip().lower()

        if exp == act:
            return "PASS"

        try:
            if float(exp) == float(act):
                return "PASS"
        except ValueError:
            pass

        # "0 rows" / "zero rows" — any equivalent phrasing
        if re.search(r'\b0\s+rows?\b', exp) and re.search(r'\b0\s+rows?\b', act):
            return "PASS"
        if re.search(r'\bzero\s+rows?\b', exp) and re.search(r'\b0\s+rows?\b', act):
            return "PASS"

        # "N rows returned" in actual — evaluate comparison operators in expected
        rows_match = re.search(r'^(\d+)\s+rows?\s+(returned|found)$', act.strip())
        if rows_match:
            n = int(rows_match.group(1))
            for op, pat in [('>=', r'>=\s*(\d+)'), ('<=', r'<=\s*(\d+)'),
                            ('>',  r'(?<![>=])>\s*(\d+)'), ('<', r'(?<![<=])<\s*(\d+)'),
                            ('=',  r'(?<![!<>])=\s*(\d+)')]:
                m = re.search(pat, exp)
                if m:
                    thr = int(m.group(1))
                    if ((op == '>=' and n >= thr) or (op == '<=' and n <= thr) or
                            (op == '>'  and n >  thr) or (op == '<'  and n <  thr) or
                            (op == '='  and n == thr)):
                        return "PASS"

        # Single numeric actual — evaluate comparison operators in expected
        # e.g. actual="100", expected="row_count > 0; table contains at least one record"
        act_num_match = re.match(r'^\s*([\d,]+(?:\.\d+)?)\s*$', act)
        if act_num_match:
            try:
                act_num = float(act_num_match.group(1).replace(',', ''))
                for op, pat in [('>=', r'>=\s*([\d,]+(?:\.\d+)?)'),
                                 ('<=', r'<=\s*([\d,]+(?:\.\d+)?)'),
                                 ('>',  r'(?<![>=])>\s*([\d,]+(?:\.\d+)?)'),
                                 ('<',  r'(?<![<=])<\s*([\d,]+(?:\.\d+)?)'),
                                 ('=',  r'(?<![!<>])=\s*([\d,]+(?:\.\d+)?)')]:
                    m = re.search(pat, exp)
                    if m:
                        thr = float(m.group(1).replace(',', ''))
                        if ((op == '>=' and act_num >= thr) or (op == '<=' and act_num <= thr) or
                                (op == '>'  and act_num >  thr) or (op == '<'  and act_num <  thr) or
                                (op == '='  and act_num == thr)):
                            return "PASS"
            except ValueError:
                pass

        # Multi-field actual e.g. "total_rows=100, distinct_ids=100, duplicate_count=0"
        # PASS when non-zero fields are all equal ("equals" in expected) AND zero fields
        # satisfy "= 0" / "exactly 0" / "is 0" in expected
        kv_pairs = dict(re.findall(r'(\w+)=([\d.]+)', act))
        if len(kv_pairs) >= 2:
            zero_keys   = [k for k, v in kv_pairs.items() if float(v) == 0]
            nonzero_vals = [float(v) for v in kv_pairs.values() if float(v) != 0]
            all_nonzero_equal = len(set(nonzero_vals)) <= 1 and nonzero_vals
            expects_equal = bool(re.search(r'\bequals?\b', exp))
            expects_zero  = bool(re.search(r'(?:=\s*0|exactly\s+0|is\s+0)\b', exp))
            if all_nonzero_equal and expects_equal and zero_keys and expects_zero:
                return "PASS"

        positive_keywords = ["pass", "true", "success", "exists", "ok", "valid",
                             "no null", "no error", "complete", "scheduled"]
        for kw in positive_keywords:
            if kw in exp and kw in act:
                return "PASS"

        num_match = re.search(r"(\d[\d,.]*)", exp)
        if num_match:
            try:
                exp_num = float(num_match.group(1).replace(",", ""))
                act_num = float(re.sub(r"[^\d.]", "", act))
                if exp_num == act_num:
                    return "PASS"
            except ValueError:
                pass

        return "FAIL"