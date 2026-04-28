"""
main.py
-------
Orchestrator for the GitHub Actions Synthetic Data Generator.

Called by the workflow with:
    python src/main.py --files "path/to/file1.csv,path/to/file2.csv"

For each file it:
  1. Loads the source table
  2. Analyzes columns
  3. Computes from_date / to_date from config + today's date
  4. Generates synthetic rows
  5. Writes BigQuery INSERT SQL to output/

Working directory when called from workflow:
    core/testing/agents/synthetic_data/synthetic_data_generator_python/
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

# ── Path setup ─────────────────────────────────────────────────────────────────
HERE     = os.path.dirname(os.path.abspath(__file__))          # src/
BASE_DIR = os.path.dirname(HERE)                                # synthetic_data_generator_python/
REPO_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "..", "..", ".."))

sys.path.insert(0, HERE)

from scanner          import resolve_files, get_table_name
from data_loader      import load_file
from column_analyzer  import analyze_columns, print_profile
from data_generator   import generate_rows
from sql_writer       import write_sql, print_summary


# ── Paths ──────────────────────────────────────────────────────────────────────
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
OUTPUT_DIR  = os.path.join(BASE_DIR, "output")


# ── Load config ────────────────────────────────────────────────────────────────

def load_config() -> dict:
    if not os.path.isfile(CONFIG_FILE):
        raise FileNotFoundError(f"config.json not found at: {CONFIG_FILE}")
    with open(CONFIG_FILE, encoding="utf-8") as f:
        cfg = json.load(f)

    required = {"bq_project", "bq_dataset", "num_records", "date_window_days"}
    missing  = required - set(cfg.keys())
    if missing:
        raise ValueError(f"config.json is missing required keys: {missing}")

    return cfg


# ── Date range ─────────────────────────────────────────────────────────────────

def compute_date_range(date_window_days: int):
    """
    to_date   = today
    from_date = today minus date_window_days

    Both returned as YYYY-MM-DD strings.
    date_window_days is read from config.json and is fully editable.
    """
    today     = date.today()
    from_date = today - timedelta(days=date_window_days)
    return str(from_date), str(today)


# ── Per-file pipeline ──────────────────────────────────────────────────────────

def process_file(file_path: str, config: dict) -> bool:
    """
    Full pipeline for one source file.
    Returns True on success, False on failure.
    """
    table_name = get_table_name(file_path)
    print(f"\n{'─'*60}")
    print(f"  Processing : {os.path.basename(file_path)}")
    print(f"  Table name : {table_name}")
    print(f"{'─'*60}")

    try:
        # ── 1. Load ─────────────────────────────────────────────────────────
        print(f"  Loading source file...")
        rows, fmt = load_file(file_path, max_rows=1000)
        print(f"  Loaded {len(rows)} rows × {len(rows[0])} columns  [{fmt.upper()}]")

        # ── 2. Analyze ──────────────────────────────────────────────────────
        print(f"  Analyzing columns...")
        profile = analyze_columns(rows)
        print_profile(profile)

        # ── 3. Date range ───────────────────────────────────────────────────
        from_date, to_date = compute_date_range(config["date_window_days"])
        print(f"  Date range : {from_date} → {to_date}  ({config['date_window_days']} days)")

        # ── 4. Generate ─────────────────────────────────────────────────────
        num_records = config["num_records"]
        print(f"  Generating {num_records:,} synthetic rows...")
        synthetic_rows = generate_rows(profile, num_records, from_date, to_date)
        print(f"  Generated  {len(synthetic_rows)} rows ✓")

        # ── 5. Write SQL ────────────────────────────────────────────────────
        print(f"  Writing SQL...")
        output_file = write_sql(
            rows        = synthetic_rows,
            profile     = profile,
            table_name  = table_name,
            output_dir  = OUTPUT_DIR,
            bq_project  = config["bq_project"],
            bq_dataset  = config["bq_dataset"],
            from_date   = from_date,
            to_date     = to_date,
            num_records = num_records,
        )
        print_summary(output_file, len(synthetic_rows), table_name)
        return True

    except Exception as e:
        print(f"\n  ❌  Failed to process {table_name}: {e}", file=sys.stderr)
        return False


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Synthetic Data Generator — GitHub Actions orchestrator"
    )
    parser.add_argument(
        "--files", "-f",
        required=True,
        help="Comma-separated repo-relative paths to changed source files."
    )
    args = parser.parse_args()

    print("\n" + "="*60)
    print("  Synthetic Data Generator")
    print("  Trigger: GitHub Actions — push to main")
    print("="*60)

    # ── Load config ────────────────────────────────────────────────────────
    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"\n❌  Config error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n  Config loaded:")
    print(f"    BQ target      : {config['bq_project']}.{config['bq_dataset']}")
    print(f"    Records        : {config['num_records']:,}")
    print(f"    Date window    : last {config['date_window_days']} days")

    # ── Resolve files ──────────────────────────────────────────────────────
    print(f"\n  Scanning changed files...")
    files = resolve_files(args.files, REPO_ROOT)

    if not files:
        print("\n  No valid source files to process. Exiting.")
        sys.exit(0)

    print(f"  Found {len(files)} file(s) to process.")

    # ── Process each file ──────────────────────────────────────────────────
    results = {}
    for file_path in files:
        success = process_file(file_path, config)
        results[os.path.basename(file_path)] = success

    # ── Final summary ──────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    passed = [f for f, ok in results.items() if ok]
    failed = [f for f, ok in results.items() if not ok]

    for f in passed:
        print(f"  ✅  {f}")
    for f in failed:
        print(f"  ❌  {f}")

    print(f"\n  {len(passed)} succeeded  |  {len(failed)} failed")
    print(f"  Output folder: {OUTPUT_DIR}\n")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
