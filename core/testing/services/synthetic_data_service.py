"""
services/synthetic_data_service.py
------------------------------------
Wraps the synthetic_data_generator_mapped_python to:
  1. Generate synthetic rows from an ICD mapping CSV (pure Python, no LLM)
  2. Create BQ tables from the ICD schema if they don't exist
  3. Execute the resulting SQL INSERT statements against BigQuery
"""

from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DEAH_ROOT, GCP_PROJECT_ID, GCP_DATASET_ID

_SYNTH_DIR    = DEAH_ROOT / "core/testing/agents/synthetic_data/synthetic_data_generator_mapped_python"
_SYNTH_SRC    = _SYNTH_DIR / "src"
_SYNTH_OUTPUT = _SYNTH_DIR / "output"


def _load_synth_main():
    if str(_SYNTH_SRC) not in sys.path:
        sys.path.insert(0, str(_SYNTH_SRC))
    spec = importlib.util.spec_from_file_location("synth_main", _SYNTH_SRC / "main.py")
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_mapping_loader():
    if str(_SYNTH_SRC) not in sys.path:
        sys.path.insert(0, str(_SYNTH_SRC))
    spec = importlib.util.spec_from_file_location("mapping_loader", _SYNTH_SRC / "mapping_loader.py")
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SYNTHETIC_SUFFIX = "_synthetic"

# Map common MySQL / generic SQL types → BigQuery types
_BQ_TYPE_MAP = {
    "VARCHAR": "STRING", "NVARCHAR": "STRING", "CHAR": "STRING",
    "TEXT": "STRING", "TINYTEXT": "STRING", "MEDIUMTEXT": "STRING", "LONGTEXT": "STRING",
    "JSON": "STRING",
    "INT": "INT64", "INTEGER": "INT64", "BIGINT": "INT64",
    "SMALLINT": "INT64", "TINYINT": "INT64", "BYTEINT": "INT64",
    "FLOAT": "FLOAT64", "DOUBLE": "FLOAT64", "REAL": "FLOAT64",
    "DECIMAL": "NUMERIC", "NUMBER": "NUMERIC",
    "BOOLEAN": "BOOL",
    "DATETIME": "DATETIME", "DATETIME2": "DATETIME",
    "BLOB": "BYTES", "BINARY": "BYTES", "VARBINARY": "BYTES",
}


def _normalize_bq_type(raw: str) -> str:
    """Convert any MySQL/generic SQL type to a valid BigQuery type."""
    base = raw.split("(")[0].strip().upper()   # strip precision, e.g. VARCHAR(255) → VARCHAR
    return _BQ_TYPE_MAP.get(base, base)        # unknown types passed through as-is


def _build_create_ddl(table_name: str, columns: list[dict]) -> str:
    """Build a BigQuery CREATE TABLE IF NOT EXISTS DDL from ICD column definitions."""
    col_defs      = []
    partition_col = None
    partition_type = None
    cluster_cols  = []

    for col in columns:
        name    = (col.get("target_column") or "").strip()
        raw_type = (col.get("target_data_type") or "STRING").strip()
        bq_type = _normalize_bq_type(raw_type)
        if not name:
            continue
        col_defs.append(f"  `{name}` {bq_type}")

        if col.get("is_partition_column"):
            partition_col  = name
            partition_type = bq_type
        if col.get("is_cluster_column"):
            cluster_cols.append(name)

    if not col_defs:
        raise ValueError(f"No valid columns found for table '{table_name}' in ICD mapping — check target_column/target_data_type fields")

    synthetic_name = table_name + SYNTHETIC_SUFFIX
    ddl = (
        f"CREATE TABLE IF NOT EXISTS `{GCP_PROJECT_ID}.{GCP_DATASET_ID}.{synthetic_name}` (\n"
        + ",\n".join(col_defs)
        + "\n)"
    )

    if partition_col:
        if partition_type in ("DATETIME", "TIMESTAMP"):
            ddl += f"\nPARTITION BY DATE({partition_col})"
        else:
            ddl += f"\nPARTITION BY {partition_col}"

    if cluster_cols:
        ddl += f"\nCLUSTER BY {', '.join(cluster_cols)}"

    return ddl + ";"


class SyntheticDataService:

    def generate(self, icd_csv_path: str, num_records: int = 100) -> dict:
        """
        Run the pure-Python synthetic data generator for the given ICD mapping CSV.
        Returns: {ok, sql_files, tables, output_dir, message}
        """
        icd_path = Path(icd_csv_path)
        if not icd_path.exists():
            return {"ok": False, "message": f"ICD file not found: {icd_csv_path}",
                    "sql_files": [], "tables": []}

        _SYNTH_OUTPUT.mkdir(parents=True, exist_ok=True)

        config = {
            "bq_project":       GCP_PROJECT_ID,
            "bq_dataset":       GCP_DATASET_ID,
            "num_records":      num_records,
            "date_window_days": 15,
            "output_dir":       str(_SYNTH_OUTPUT),
        }

        try:
            mod = _load_synth_main()
            mod.run(
                mapping_files_csv=str(icd_path),
                config=config,
                repo_root=str(DEAH_ROOT),
            )
        except SystemExit as e:
            if e.code and e.code != 0:
                return {"ok": False,
                        "message": "Synthetic generator exited with errors — check server logs.",
                        "sql_files": [], "tables": []}
        except Exception as e:
            return {"ok": False, "message": f"Synthetic generation failed: {e}",
                    "sql_files": [], "tables": []}

        sql_files = list(_SYNTH_OUTPUT.glob("*.sql"))
        if not sql_files:
            return {"ok": False, "message": "Generator ran but produced no SQL files.",
                    "sql_files": [], "tables": []}

        tables = [f.stem for f in sql_files]
        return {
            "ok":         True,
            "sql_files":  [str(f) for f in sql_files],
            "tables":     tables,
            "output_dir": str(_SYNTH_OUTPUT),
            "message":    f"Generated {len(tables)} table(s): {', '.join(tables)}",
        }

    def _ensure_tables_exist(self, icd_csv_path: str, client) -> list[dict]:
        """
        Read the ICD mapping CSV and CREATE TABLE IF NOT EXISTS for each target table.
        Returns list of {table, ok, action|error}.
        """
        try:
            mod    = _load_mapping_loader()
            tables = mod.load_mapping_file(icd_csv_path)
        except Exception as e:
            return [{"table": "unknown", "ok": False, "error": f"Failed to load mapping: {e}"}]

        results = []
        for table_name, columns in tables.items():
            try:
                ddl = _build_create_ddl(table_name, columns)
                print(f"[SyntheticDataService] Creating table if missing: {table_name}")
                job = client.query(ddl)
                job.result()
                results.append({"table": table_name, "ok": True, "action": "created or already exists"})
            except Exception as e:
                results.append({"table": table_name, "ok": False, "error": str(e)})

        return results

    def insert_into_bq(self, sql_files: list[str], client=None) -> dict:
        """
        Execute generated SQL INSERT statements against BigQuery.
        Returns: {ok, results, message}
        """
        if client is None:
            from services.bigquery_connector import create_bigquery_client
            try:
                client = create_bigquery_client()
            except Exception as e:
                return {"ok": False, "results": [], "message": f"BigQuery connection failed: {e}"}

        results = []
        for sql_path in sql_files:
            table          = Path(sql_path).stem
            synthetic_name = table + SYNTHETIC_SUFFIX
            try:
                sql = Path(sql_path).read_text(encoding="utf-8")
                # Redirect INSERT to the _synthetic table instead of the target table
                sql = sql.replace(
                    f"`{GCP_PROJECT_ID}.{GCP_DATASET_ID}.{table}`",
                    f"`{GCP_PROJECT_ID}.{GCP_DATASET_ID}.{synthetic_name}`",
                )
                job = client.query(sql)
                job.result()
                results.append({
                    "table":           table,
                    "synthetic_table": synthetic_name,
                    "ok":              True,
                })
            except Exception as e:
                results.append({"table": table, "synthetic_table": synthetic_name,
                                 "ok": False, "error": str(e)})

        failed = [r for r in results if not r["ok"]]
        ok     = len(failed) == 0 and len(results) > 0
        parts  = [f"✓ {r['table']}" for r in results if r["ok"]]
        parts += [f"✗ {r['table']}: {r.get('error','')}" for r in failed]
        return {
            "ok":      ok,
            "results": results,
            "message": f"Inserted {len(results)-len(failed)}/{len(results)} table(s). " + " | ".join(parts),
        }

    def generate_and_insert(self, icd_csv_path: str, num_records: int = 100) -> dict:
        """
        Full pipeline:
          1. Generate synthetic SQL from ICD mapping CSV
          2. Create BQ tables if they don't exist (schema from ICD)
          3. Insert synthetic rows into BQ
        """
        # Step 1 — generate SQL files
        gen = self.generate(icd_csv_path, num_records)
        if not gen["ok"]:
            return gen

        # Step 2 — get BQ client (shared across create + insert)
        from services.bigquery_connector import create_bigquery_client
        try:
            client = create_bigquery_client()
        except Exception as e:
            return {**gen, "ok": False, "message": f"BigQuery connection failed: {e}"}

        # Step 3 — create tables if missing
        table_results = self._ensure_tables_exist(icd_csv_path, client)
        failed_creates = [r for r in table_results if not r["ok"]]
        if failed_creates:
            errors = "; ".join(r.get("error", "") for r in failed_creates)
            return {**gen, "ok": False,
                    "message": f"Table creation failed: {errors}",
                    "tables_created": table_results}

        # Step 4 — insert synthetic data
        ins = self.insert_into_bq(gen["sql_files"], client)
        return {
            **gen,
            "tables_created": table_results,
            "bq_insert":      ins,
            "ok":             ins["ok"],
            "message":        gen["message"] + " → Tables ready. BQ: " + ins["message"],
        }
