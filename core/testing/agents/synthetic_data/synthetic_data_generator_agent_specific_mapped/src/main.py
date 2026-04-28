"""
main.py
-------
Orchestrator for the Mapping-Based Synthetic Data Generator Agent.

Called exclusively by trigger.py — never run directly by upstream team.

Pipeline per mapping file:
  1. Load mapping CSV — group by target_table
  2. For each target_table:
      a. Build column profile from mapping (schema_builder)
      b. Compute date range from config
      c. Generate synthetic rows via Claude (generator_agent)
      d. Write BQ INSERT SQL to output dir (sql_writer)

Uses core/utilities/llm factory with claude-code-sdk provider.
No API key needed — authenticates via claude login CLI session.
"""

import os
import sys
import logging
from datetime import date, timedelta
from typing import Any, Dict, List

import yaml

logger = logging.getLogger("main")

# ── Resolve src/ on path ───────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mapping_loader  import load_mapping_file, get_mapping_file_name
from schema_builder  import build_profile, print_profile
from generator_agent import generate_rows
from sql_writer      import write_sql, print_summary


# ── Date range ─────────────────────────────────────────────────────────────────

def _compute_date_range(date_window_days: int):
    """to_date = today, from_date = today minus date_window_days."""
    today     = date.today()
    from_date = today - timedelta(days=date_window_days)
    return str(from_date), str(today)


# ── Per-table pipeline ─────────────────────────────────────────────────────────

def _process_table(
    table_name,
    columns,
    config,
    output_dir,
    mapping_file_name,
    llm,
):
    """Full pipeline for one target_table. Returns True on success."""
    sep = "-" * 56
    print("\n  " + sep)
    print("  Table    : " + table_name)
    print("  Columns  : " + str(len(columns)))
    print("  " + sep)

    try:
        # 1. Build column profile
        print("  [1/3] Building column profile from mapping...")
        profile = build_profile(columns)
        print_profile(profile, table_name)

        # 2. Date range
        from_date, to_date = _compute_date_range(config.get("date_window_days", 15))
        print("  [2/3] Date range : " + from_date + " -> " + to_date)

        # 3. Generate rows
        num_records = config.get("num_records", 500)
        model       = config.get("model", "claude-sonnet-4-6")
        batch_size  = config.get("batch_size", 50)

        print("  [3/3] Generating " + str(num_records) + " rows via Claude Agent...")
        synthetic_rows = generate_rows(
            profile     = profile,
            table_name  = table_name,
            num_records = num_records,
            from_date   = from_date,
            to_date     = to_date,
            llm         = llm,
            batch_size  = batch_size,
        )
        print("        Generated " + str(len(synthetic_rows)) + " rows")

        # 4. Write SQL
        print("  Writing SQL file...")
        output_file = write_sql(
            rows              = synthetic_rows,
            profile           = profile,
            table_name        = table_name,
            output_dir        = output_dir,
            bq_project        = config.get("bq_project", "your-gcp-project"),
            bq_dataset        = config.get("bq_dataset", "your_dataset"),
            from_date         = from_date,
            to_date           = to_date,
            num_records       = len(synthetic_rows),
            mapping_file_name = mapping_file_name,
            model             = model,
        )
        print_summary(output_file, len(synthetic_rows), table_name)
        return True

    except Exception as e:
        print("  Failed to process table '" + table_name + "': " + str(e), file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


# ── Per-mapping-file pipeline ──────────────────────────────────────────────────

def _process_mapping_file(file_path, config, output_dir, llm):
    """
    Process one mapping CSV file.
    May produce multiple SQL files (one per target_table).
    Returns dict: { table_name: success_bool }
    """
    mapping_file_name = get_mapping_file_name(file_path)
    sep = "=" * 60
    print("\n" + sep)
    print("  Mapping file : " + os.path.basename(file_path))
    print(sep)

    try:
        tables = load_mapping_file(file_path)
    except (FileNotFoundError, ValueError) as e:
        print("  Cannot load mapping file: " + str(e), file=sys.stderr)
        return {}

    results = {}
    for table_name, columns in tables.items():
        success = _process_table(
            table_name        = table_name,
            columns           = columns,
            config            = config,
            output_dir        = output_dir,
            mapping_file_name = mapping_file_name,
            llm               = llm,
        )
        results[table_name] = success

    return results


# ── Main entry point (called by trigger.py) ────────────────────────────────────

def run(
    mapping_files_csv,
    config,
    repo_root,
):
    """
    Main pipeline entry point called by trigger.py.

    Parameters
    ----------
    mapping_files_csv : comma-separated absolute paths to mapping CSV files
    config            : loaded config.yaml dict (our team's config)
    repo_root         : absolute repo root path
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  [%(name)s]  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sep = "=" * 60
    print("\n" + sep)
    print("  Synthetic Data Generator Agent")
    print("  Mode    : Mapping-based (design team output)")
    print("  Model   : " + str(config.get("model", "claude-sonnet-4-6")))
    print("  BQ      : " + str(config.get("bq_project")) + "." + str(config.get("bq_dataset")))
    print("  Records : " + str(config.get("num_records", 500)) + " per table")
    print(sep)

    # Resolve output directory
    output_dir_cfg = config.get("output_dir", "")
    if os.path.isabs(output_dir_cfg):
        output_dir = output_dir_cfg
    else:
        output_dir = os.path.join(repo_root, output_dir_cfg)
    os.makedirs(output_dir, exist_ok=True)
    print("\n  Output dir  : " + output_dir)

    # Create LLM client via claude-code-sdk — no API key needed
    # Authenticates via 'claude login' CLI OAuth session
    print("  Initialising LLM client (claude-code-sdk)...")
    try:
        from core.utilities.llm.factory import create_llm_client
        llm = create_llm_client(
            provider = "claude-code-sdk",
            model    = config.get("model", "claude-sonnet-4-6"),
        )
        print("  LLM client ready")
    except Exception as e:
        print("  Failed to create LLM client: " + str(e), file=sys.stderr)
        sys.exit(1)

    # Process each mapping file
    file_paths = [f.strip() for f in mapping_files_csv.split(",") if f.strip()]

    if not file_paths:
        print("  No mapping files to process.")
        sys.exit(1)

    print("\n  Mapping files to process: " + str(len(file_paths)))

    all_results = {}
    for file_path in file_paths:
        results = _process_mapping_file(file_path, config, output_dir, llm)
        all_results.update(results)

    # Final summary
    print("\n" + sep)
    print("  SUMMARY")
    print(sep)

    passed = [t for t, ok in all_results.items() if ok]
    failed = [t for t, ok in all_results.items() if not ok]

    for t in passed:
        print("  OK    " + t + ".sql")
    for t in failed:
        print("  FAIL  " + t)

    print("\n  " + str(len(passed)) + " table(s) succeeded  |  " + str(len(failed)) + " failed")
    print("  Output: " + output_dir + "\n")

    if failed:
        sys.exit(1)
