"""
services/comparison_service.py
--------------------------------
Compares source data vs BQ target table to validate pipeline output.

Two modes:
  - synthetic : source = BQ {table}_synthetic  vs  target = BQ {table}
  - source_db : source = MySQL/other DB table   vs  target = BQ {table}
"""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DEAH_ROOT, GCP_PROJECT_ID, GCP_DATASET_ID

_SYNTH_SRC = DEAH_ROOT / "core/testing/agents/synthetic_data/synthetic_data_generator_mapped_python/src"
SYNTHETIC_SUFFIX = "_synthetic"


def _load_mapping(icd_csv_path: str) -> dict:
    """Load ICD mapping CSV → {table_name: [column_dicts]}."""
    if str(_SYNTH_SRC) not in sys.path:
        sys.path.insert(0, str(_SYNTH_SRC))
    import importlib.util
    spec = importlib.util.spec_from_file_location("mapping_loader", _SYNTH_SRC / "mapping_loader.py")
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_mapping_file(icd_csv_path)


def _compare_bq_tables(client, source_fq: str, target_fq: str,
                        columns: list[dict]) -> dict:
    """
    Run statistical comparison between two fully-qualified BQ tables.
    Returns: {ok, checks: [{name, source_val, target_val, passed}], summary}
    """
    col_names = [c["target_column"] for c in columns if c.get("target_column")]
    checks    = []

    # 1 — Row count
    try:
        src_count = list(client.query(f"SELECT COUNT(*) AS n FROM `{source_fq}`").result())[0].n
        tgt_count = list(client.query(f"SELECT COUNT(*) AS n FROM `{target_fq}`").result())[0].n
        checks.append({
            "name":       "Row count",
            "source_val": src_count,
            "target_val": tgt_count,
            "passed":     src_count == tgt_count,
        })
    except Exception as e:
        checks.append({"name": "Row count", "source_val": "error",
                       "target_val": str(e), "passed": False})

    # 2 — Per-column null rate and (for numerics) SUM comparison
    for col in columns:
        name    = col.get("target_column", "")
        bq_type = (col.get("target_data_type") or "").upper()
        if not name:
            continue

        # Null rate check
        try:
            src_nulls = list(client.query(
                f"SELECT COUNTIF(`{name}` IS NULL) AS n FROM `{source_fq}`").result())[0].n
            tgt_nulls = list(client.query(
                f"SELECT COUNTIF(`{name}` IS NULL) AS n FROM `{target_fq}`").result())[0].n
            checks.append({
                "name":       f"{name} — null count",
                "source_val": src_nulls,
                "target_val": tgt_nulls,
                "passed":     src_nulls == tgt_nulls,
            })
        except Exception:
            pass

        # SUM for numeric columns
        if any(t in bq_type for t in ("INT", "FLOAT", "NUMERIC", "BIGNUMERIC")):
            try:
                src_sum = list(client.query(
                    f"SELECT SUM(`{name}`) AS s FROM `{source_fq}`").result())[0].s
                tgt_sum = list(client.query(
                    f"SELECT SUM(`{name}`) AS s FROM `{target_fq}`").result())[0].s
                # Allow 1% tolerance for floats
                passed = abs((src_sum or 0) - (tgt_sum or 0)) <= max(abs(src_sum or 0) * 0.01, 1)
                checks.append({
                    "name":       f"{name} — SUM",
                    "source_val": src_sum,
                    "target_val": tgt_sum,
                    "passed":     passed,
                })
            except Exception:
                pass

    passed_n = sum(1 for c in checks if c["passed"])
    return {
        "ok":      all(c["passed"] for c in checks),
        "checks":  checks,
        "summary": f"{passed_n}/{len(checks)} checks passed",
    }


def _compare_mysql_to_bq(mysql_config: dict, source_table: str,
                          target_fq: str, columns: list[dict],
                          bq_client) -> dict:
    """
    Compare MySQL source table vs BQ target table.
    Uses SQLAlchemy for MySQL queries.
    """
    from sqlalchemy import create_engine, text as sqla_text

    db_type  = mysql_config.get("db_type", "mysql")
    host     = mysql_config.get("host", "")
    port     = mysql_config.get("port", 3306)
    user     = mysql_config.get("user") or mysql_config.get("username", "")
    password = mysql_config.get("password", "")
    database = mysql_config.get("database", "")

    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
    engine = create_engine(url)

    col_names = [c.get("source_column") or c.get("target_column")
                 for c in columns if c.get("target_column")]
    checks = []

    # Row count
    try:
        with engine.connect() as conn:
            src_count = conn.execute(
                sqla_text(f"SELECT COUNT(*) FROM `{source_table}`")).scalar()
        tgt_count = list(bq_client.query(
            f"SELECT COUNT(*) AS n FROM `{target_fq}`").result())[0].n
        checks.append({
            "name":       "Row count",
            "source_val": src_count,
            "target_val": tgt_count,
            "passed":     src_count == tgt_count,
        })
    except Exception as e:
        checks.append({"name": "Row count", "source_val": "error",
                       "target_val": str(e), "passed": False})

    # Numeric SUM comparison per column
    for col in columns:
        src_col = col.get("source_column") or ""
        tgt_col = col.get("target_column") or ""
        bq_type = (col.get("target_data_type") or "").upper()
        if not src_col or not tgt_col:
            continue
        if not any(t in bq_type for t in ("INT", "FLOAT", "NUMERIC", "BIGNUMERIC")):
            continue
        try:
            with engine.connect() as conn:
                src_sum = conn.execute(
                    sqla_text(f"SELECT SUM(`{src_col}`) FROM `{source_table}`")).scalar()
            tgt_sum = list(bq_client.query(
                f"SELECT SUM(`{tgt_col}`) AS s FROM `{target_fq}`").result())[0].s
            passed = abs((src_sum or 0) - (tgt_sum or 0)) <= max(abs(src_sum or 0) * 0.01, 1)
            checks.append({
                "name":       f"{tgt_col} — SUM",
                "source_val": src_sum,
                "target_val": tgt_sum,
                "passed":     passed,
            })
        except Exception:
            pass

    passed_n = sum(1 for c in checks if c["passed"])
    return {
        "ok":      all(c["passed"] for c in checks),
        "checks":  checks,
        "summary": f"{passed_n}/{len(checks)} checks passed",
    }


class ComparisonService:

    def compare(self, icd_csv_path: str, mode: str,
                mysql_config: dict | None = None) -> dict:
        """
        Compare source vs BQ target for all tables in the ICD mapping.

        Parameters
        ----------
        icd_csv_path  : path to the ICD mapping CSV
        mode          : 'synthetic' | 'source_db'
        mysql_config  : required when mode='source_db'

        Returns
        -------
        dict with keys:
            ok           : bool
            table_results: list[{table, source, target, ok, checks, summary}]
            message      : str
        """
        from services.bigquery_connector import create_bigquery_client
        try:
            bq_client = create_bigquery_client()
        except Exception as e:
            return {"ok": False, "table_results": [],
                    "message": f"BigQuery connection failed: {e}"}

        try:
            tables = _load_mapping(icd_csv_path)
        except Exception as e:
            return {"ok": False, "table_results": [],
                    "message": f"Failed to load ICD mapping: {e}"}

        table_results = []
        for table_name, columns in tables.items():
            target_fq = f"{GCP_PROJECT_ID}.{GCP_DATASET_ID}.{table_name}"

            if mode == "synthetic":
                source_fq = f"{GCP_PROJECT_ID}.{GCP_DATASET_ID}.{table_name}{SYNTHETIC_SUFFIX}"
                try:
                    result = _compare_bq_tables(bq_client, source_fq, target_fq, columns)
                    table_results.append({
                        "table":  table_name,
                        "source": source_fq,
                        "target": target_fq,
                        **result,
                    })
                except Exception as e:
                    table_results.append({"table": table_name, "source": source_fq,
                                          "target": target_fq, "ok": False,
                                          "checks": [], "summary": str(e)})

            elif mode == "source_db":
                if not mysql_config:
                    return {"ok": False, "table_results": [],
                            "message": "mysql_config required for source_db mode"}
                src_table = col["source_table"] if (col := next(
                    (c for c in columns if c.get("source_table")), None)) else table_name
                try:
                    result = _compare_mysql_to_bq(
                        mysql_config, src_table, target_fq, columns, bq_client)
                    table_results.append({
                        "table":  table_name,
                        "source": f"mysql://{mysql_config.get('host')}/{src_table}",
                        "target": target_fq,
                        **result,
                    })
                except Exception as e:
                    table_results.append({"table": table_name, "ok": False,
                                          "checks": [], "summary": str(e)})

        all_ok = all(r["ok"] for r in table_results) if table_results else False
        passed = sum(1 for r in table_results if r["ok"])
        return {
            "ok":           all_ok,
            "table_results": table_results,
            "message":      f"{passed}/{len(table_results)} table(s) passed validation",
        }
