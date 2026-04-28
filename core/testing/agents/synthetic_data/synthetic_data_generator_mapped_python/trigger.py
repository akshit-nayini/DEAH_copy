"""
trigger.py
----------
UPSTREAM TEAM — integrate this file into your process.

This is the ONLY entry point the upstream team needs to call.
It reads trigger_config.yaml (which your UI updates) and our
config.yaml (which our team owns), then fires the main pipeline.

Integration options for upstream team:
    Option A — Run directly from terminal / shell script:
        python trigger.py

    Option B — Call from your Python process / UI backend:
        from trigger import run_trigger
        run_trigger()

    Option C — Shell command from any language:
        subprocess.run(["python", "trigger.py"])

The upstream UI flow:
    1. User enters mapping file name in UI field
    2. UI writes the filename into trigger_config.yaml
    3. UI calls this trigger (any of the options above)
    4. SQL files appear in the output folder defined in config.yaml

OUR TEAM makes zero changes to this file.
Upstream team makes zero changes to src/ or config.yaml.
Clean boundary. No conflicts.
"""

import os
import sys
import logging
from datetime import datetime

import yaml

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [TRIGGER]  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("trigger")

# ── Paths ──────────────────────────────────────────────────────────────────────
HERE              = os.path.dirname(os.path.abspath(__file__))
TRIGGER_CFG_PATH  = os.path.join(HERE, "trigger_config.yaml")
OUR_CFG_PATH      = os.path.join(HERE, "config.yaml")
MAIN_SCRIPT       = os.path.join(HERE, "src", "main.py")


# ── Load YAML helper ───────────────────────────────────────────────────────────

def _load_yaml(path: str) -> dict:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ── Main trigger function ──────────────────────────────────────────────────────

def run_trigger() -> None:
    """
    Entry point called by upstream team.

    Reads trigger_config.yaml → validates mapping files →
    reads config.yaml → calls main.py pipeline.
    """
    logger.info("=" * 60)
    logger.info("  Synthetic Data Generator — Trigger")
    logger.info("  Started at: %s", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    logger.info("=" * 60)

    # ── Load trigger config (upstream team's file) ─────────────────────────────
    logger.info("Loading trigger_config.yaml...")
    try:
        trigger_cfg = _load_yaml(TRIGGER_CFG_PATH)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)

    mapping_files = trigger_cfg.get("mapping_files", [])
    if not mapping_files:
        logger.error(
            "No mapping_files specified in trigger_config.yaml. "
            "Please add at least one mapping file name."
        )
        sys.exit(1)

    logger.info("Mapping files to process: %d", len(mapping_files))
    for f in mapping_files:
        logger.info("  → %s", f)

    # ── Load our config ────────────────────────────────────────────────────────
    logger.info("Loading config.yaml...")
    try:
        our_cfg = _load_yaml(OUR_CFG_PATH)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)

    mapping_source_dir = our_cfg.get("mapping_source_dir", "")
    if not mapping_source_dir:
        logger.error("mapping_source_dir not set in config.yaml")
        sys.exit(1)

    # ── Resolve full paths and validate files exist ────────────────────────────
    # Resolve relative to repo root (two levels up from HERE)
    repo_root = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
    resolved_paths = []

    for fname in mapping_files:
        # Support both filename-only and full relative paths
        if os.path.isabs(fname):
            full_path = fname
        else:
            # Try as filename inside mapping_source_dir first
            candidate = os.path.join(repo_root, mapping_source_dir, fname)
            if os.path.isfile(candidate):
                full_path = candidate
            else:
                # Try as repo-relative path
                candidate2 = os.path.join(repo_root, fname)
                if os.path.isfile(candidate2):
                    full_path = candidate2
                else:
                    logger.error(
                        "Mapping file not found: '%s'\n"
                        "  Tried: %s\n"
                        "  Tried: %s",
                        fname, candidate, candidate2,
                    )
                    sys.exit(1)

        resolved_paths.append(full_path)
        logger.info("  Resolved: %s", full_path)

    # ── Build comma-separated file list for main.py ────────────────────────────
    files_arg = ",".join(resolved_paths)

    # ── Call main pipeline ─────────────────────────────────────────────────────
    logger.info("")
    logger.info("Handing off to main pipeline...")
    logger.info("=" * 60)

    # Add src/ to path so main.py can be imported
    src_dir = os.path.join(HERE, "src")
    sys.path.insert(0, src_dir)
    sys.path.insert(0, HERE)

    try:
        from src.main import run
        run(
            mapping_files_csv = files_arg,
            config            = our_cfg,
            repo_root         = repo_root,
        )
    except Exception as e:
        logger.error("Pipeline failed: %s", str(e))
        import traceback
        traceback.print_exc()
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("  Trigger complete.")
    logger.info("=" * 60)


# ── Allow direct execution ─────────────────────────────────────────────────────
if __name__ == "__main__":
    run_trigger()
