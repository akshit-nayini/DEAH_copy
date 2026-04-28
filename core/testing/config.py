"""
config.py
---------
Central configuration for the Testing POD.
All paths, ports, and credentials live here.
"""

import os
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

# Load testing-specific .env first
load_dotenv(Path(__file__).resolve().parent / ".env")

# If any API key is still blank, pull it from the shared DEAH config.env (requirements_pod).
# This avoids duplicating keys across repos — one place to update.
_DEAH_ROOT_EARLY = Path(os.environ.get("DEAH_ROOT", str(Path(__file__).resolve().parents[2])))
_SHARED_ENV = _DEAH_ROOT_EARLY / "core/requirements_pod/config.env"
if _SHARED_ENV.exists():
    _shared = dotenv_values(_SHARED_ENV)
    for _key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        # Always prefer the key from the shared DEAH config — overrides stale OS env vars
        if _shared.get(_key):
            os.environ[_key] = _shared[_key]

# ── Repo roots ────────────────────────────────────────────────────────────────
# config.py lives at <DEAH_ROOT>/core/testing/config.py, so parents[2] = DEAH_ROOT.
# This works on any OS / machine — no hardcoded paths.
REPO_ROOT = Path(__file__).resolve().parent
DEAH_ROOT = Path(os.environ.get("DEAH_ROOT", str(Path(__file__).resolve().parents[2])))
RV_ROOT   = Path(os.environ.get("RV_ROOT",   str(DEAH_ROOT / "Result Validation")))

# ── Common module paths ───────────────────────────────────────────────────────
GIT_MANAGER_PATH = DEAH_ROOT / "core/utilities/versioning_tools/git_manager.py"
LLM_UTILITY_ROOT = DEAH_ROOT                           # add to sys.path to import core.utilities.llm
BQ_CONNECTOR_PATH = RV_ROOT / "bigquery_connector.py"
GCP_ENV_PATH      = RV_ROOT / "gcp.env"

# ── Source paths in DEAH repo ─────────────────────────────────────────────────
ICD_DIR              = DEAH_ROOT / "core/design/agents/data_model/output"
AC_DIR               = DEAH_ROOT / "core/design/agents/requirements_gathering/output"
TESTING_AGENTS_DIR   = DEAH_ROOT / "core/testing/agents"

# ── Output paths (local to this repo) ────────────────────────────────────────
GENERATOR_OUTPUT_DIR = REPO_ROOT / "agents/generator/output"
VALIDATOR_OUTPUT_DIR = REPO_ROOT / "agents/validator/output"

# ── Git ───────────────────────────────────────────────────────────────────────
GITHUB_PAT        = os.environ.get("GITHUB_PAT", "")
GITHUB_BRANCH_URL = "https://github.com/ahemadshaik/DEAH/tree/main"

# ── LLM ───────────────────────────────────────────────────────────────────────
# Switch provider by setting LLM_PROVIDER in .env — no code changes needed.
# Supported: "anthropic" | "gemini" | "openai"
# API keys are NOT handled here — the DEAH common LLM factory reads them
# directly from env vars (ANTHROPIC_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY).
LLM_PROVIDER   = os.environ.get("LLM_PROVIDER", "anthropic")
LLM_MODEL      = os.environ.get("LLM_MODEL", "")   # empty → factory uses provider default
LLM_MAX_TOKENS = 8000

# ── GCP / BigQuery ────────────────────────────────────────────────────────────
GCP_PROJECT_ID  = os.environ.get("GCP_PROJECT_ID",  "verizon-data")
GCP_DATASET_ID  = os.environ.get("GCP_DATASET_ID",  "deah_pod")
GCP_SA_KEY_PATH = os.environ.get("GCP_SA_KEY_PATH", "")   # path to service account JSON key

# ── Server ports & host ───────────────────────────────────────────────────────
GENERATOR_PORT = int(os.environ.get("GENERATOR_PORT", 9195))
VALIDATOR_PORT = int(os.environ.get("VALIDATOR_PORT", 9196))
SERVER_HOST    = os.environ.get("SERVER_HOST", "0.0.0.0")   # set in .env to pin display IP
