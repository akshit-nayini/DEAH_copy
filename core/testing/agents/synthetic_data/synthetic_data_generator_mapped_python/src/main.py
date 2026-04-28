"""
main.py
-------
Orchestrator for the Mapping-Based Synthetic Data Generator.

Called exclusively by trigger.py — never run directly.

Pipeline per mapping file:
  1. Load mapping CSV — group by target_table
  2. For each target_table:
      a. Build column profile from mapping (schema_builder)
      b. Compute date range from config
      c. Generate synthetic rows — pure Python (generator_agent)
      d. Write BQ INSERT SQL to output dir (sql_writer)

No LLM required — pure Python data generation.
"""

import os
import sys
import logging
from datetime import date, timedelta
from typing import Dict, List

import yaml

logger = logging.getLogger("main")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mapping_loader  import load_mapping_file, get_mapping_file_name
from schema_builder  import build_profile, print_profile
from generator_agent import generate_rows
from sql_writer      import write_sql, print_summary


def _compute_date_range(date_window_days):
    today     = date.today()
    from_date = today - timedelta(days=date_window_days)
    return str(from_date), str(today)


def _process_table(table_name, columns, config, output_dir, mapping_file_name):
    print("\n  " + "-" * 56)
    print("  Table    : " + table_name)
    print("  Columns  : " + str(len(columns)))
    print("  " + "-" * 56)

    try:
        print("  [1/3] Building column profile...")
        profile = build_profile(columns)
        print_profile(profile, table_name)

        from_date, to_date = _compute_date_range(config.get("date_window_days", 15))
        print("  [2/3] Date range : " + from_date + " -> " + to_date)

        num_records = config.get("num_records", 500)

        print("  [3/3] Generating " + str(num_records) + " rows...")
        synthetic_rows = generate_rows(
            profile     = profile,
            table_name  = table_name,
            num_records = num_records,
            from_date   = from_date,
            to_date     = to_date,
        )
        print("        Generated " + str(len(synthetic_rows)) + " rows")

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
            model             = "pure-python",
        )
        print_summary(output_file, len(synthetic_rows), table_name)
        return True

    except Exception as e:
        print("  Failed to process table " + table_name + ": " + str(e), file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False


def _process_mapping_file(file_path, config, output_dir):
    mapping_file_name = get_mapping_file_name(file_path)
    print("\n" + "=" * 60)
    print("  Mapping file : " + os.path.basename(file_path))
    print("=" * 60)

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
        )
        results[table_name] = success

    return results


def run(mapping_files_csv, config, repo_root):
    """
    Main pipeline entry point called by trigger.py.

    Parameters
    ----------
    mapping_files_csv : comma-separated absolute paths to mapping CSV files
    config            : loaded config.yaml dict
    repo_root         : absolute repo root path
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  [%(name)s]  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    print("\n" + "=" * 60)
    print("  Synthetic Data Generator")
    print("  Mode    : Pure Python (no LLM)")
    print("  BQ      : " + str(config.get("bq_project")) + "." + str(config.get("bq_dataset")))
    print("  Records : " + str(config.get("num_records", 500)) + " per table")
    print("=" * 60)

    output_dir_cfg = config.get("output_dir", "")
    if os.path.isabs(output_dir_cfg):
        output_dir = output_dir_cfg
    else:
        output_dir = os.path.join(repo_root, output_dir_cfg)
    os.makedirs(output_dir, exist_ok=True)
    print("\n  Output dir : " + output_dir)

    file_paths = [f.strip() for f in mapping_files_csv.split(",") if f.strip()]
    if not file_paths:
        print("  No mapping files to process.")
        sys.exit(1)

    print("  Files to process : " + str(len(file_paths)))

    all_results = {}
    for file_path in file_paths:
        results = _process_mapping_file(file_path, config, output_dir)
        all_results.update(results)

    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)

    passed = [t for t, ok in all_results.items() if ok]
    failed = [t for t, ok in all_results.items() if not ok]

    for t in passed:
        print("  OK    " + t + ".sql")
    for t in failed:
        print("  FAIL  " + t)

    print("\n  " + str(len(passed)) + " table(s) succeeded  |  " + str(len(failed)) + " failed")
    print("  Output : " + output_dir + "\n")

    if failed:
        sys.exit(1)
