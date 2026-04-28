"""
preflight.py — Mandatory startup checks for the Development Agent.

Called as the very first step in main.py (before any other local imports).

What it does
────────────
1. Verifies every required package is importable.
2. pip-installs any that are missing (user-install, no sudo needed).
3. Re-imports newly installed packages so the rest of the process works
   without requiring a restart.
4. Prints a concise status table and exits with code 1 if any install fails.

Design rules
────────────
- Uses only stdlib modules (sys, subprocess, importlib) — no third-party
  imports — so it can safely run before anything is installed.
- Never silently swallows errors; every failure is logged and surfaced.
- Idempotent: already-installed packages produce one "OK" line and move on.
"""
from __future__ import annotations

import importlib
import subprocess
import sys


# ── Package manifest ──────────────────────────────────────────────────────────
# Maps:  import_name  →  (pip_package_spec,  human_label)
#
# import_name   : the name used in `import <name>` (dots OK for subpackages)
# pip_package   : the exact string passed to `pip install`
# label         : short description shown in the status table
#
_REQUIRED: list[tuple[str, str, str]] = [
    # Core framework
    ("pydantic",        "pydantic>=2.7",            "Pydantic v2 (data models)"),
    ("dotenv",          "python-dotenv>=1.0",        "python-dotenv (env vars)"),
    ("fastapi",         "fastapi>=0.111.0",          "FastAPI (REST layer)"),
    ("uvicorn",         "uvicorn[standard]>=0.29.0", "Uvicorn (ASGI server)"),
    ("anyio",           "anyio>=4.0",               "AnyIO (async runtime)"),

    # LLM providers
    ("anthropic",       "anthropic>=0.39.0",         "Anthropic SDK"),
    ("claude_agent_sdk","claude-agent-sdk>=0.1.0",   "Claude Agent SDK (default provider)"),

    # Database
    ("sqlalchemy",      "sqlalchemy>=2.0",           "SQLAlchemy (ORM)"),
    ("pymysql",         "pymysql>=1.1.0",            "PyMySQL (metadata DB driver)"),
    ("google.cloud.sql.connector", "cloud-sql-python-connector[pymysql]>=1.9.0",
                                                     "Cloud SQL Connector (GCP MySQL)"),

    # Code quality
    ("ruff",            "ruff>=0.4.0",               "Ruff (Python linter / formatter)"),
]

# ── Colours (suppressed on non-TTY / Windows without ANSI) ───────────────────
def _c(code: str, text: str) -> str:
    if sys.stdout.isatty() and sys.platform != "win32":
        return f"\033[{code}m{text}\033[0m"
    return text

_GREEN  = lambda t: _c("32", t)
_YELLOW = lambda t: _c("33", t)
_RED    = lambda t: _c("31", t)
_BOLD   = lambda t: _c("1",  t)


def _pip_install(pip_spec: str) -> bool:
    """Run `pip install <spec>` in a subprocess. Returns True on success."""
    cmd = [sys.executable, "-m", "pip", "install", pip_spec, "--quiet"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def run() -> None:
    """
    Check and install all required packages.

    Prints a status table, then either continues (all OK) or exits(1).
    Called before any other local imports in main.py.
    """
    print()
    print(_BOLD("  Development Agent — Pre-flight Package Check"))
    print("  " + "─" * 56)
    print(f"  {'Package':<38} {'Status':>12}")
    print("  " + "─" * 56)

    installed_now: list[str] = []
    failed:        list[str] = []

    for import_name, pip_spec, label in _REQUIRED:
        try:
            importlib.import_module(import_name)
            print(f"  {label:<38} {_GREEN('OK'):>12}")
        except ModuleNotFoundError:
            print(f"  {label:<38} {_YELLOW('installing...'):>12}", end="", flush=True)
            ok = _pip_install(pip_spec)
            if ok:
                # Re-import so the module is available in this process
                try:
                    importlib.import_module(import_name)
                    print(f"\r  {label:<38} {_GREEN('installed'):>12}")
                    installed_now.append(pip_spec)
                except ModuleNotFoundError:
                    # Installed but still not importable (rare edge case)
                    print(f"\r  {label:<38} {_RED('import failed'):>12}")
                    failed.append(pip_spec)
            else:
                print(f"\r  {label:<38} {_RED('pip failed'):>12}")
                failed.append(pip_spec)

    print("  " + "─" * 56)

    if installed_now:
        pkgs = ", ".join(installed_now)
        print(f"\n  Newly installed: {pkgs}")

    if failed:
        print(f"\n  {_RED('ERROR')} — {len(failed)} package(s) could not be installed:")
        for pkg in failed:
            print(f"    • {pkg}")
        print("\n  Fix the above, then re-run the agent.\n")
        sys.exit(1)

    if not installed_now:
        print(f"\n  {_GREEN('All packages present.')} Continuing...\n")
    else:
        print(f"\n  {_GREEN('All packages ready.')} Continuing...\n")

    # Flush stdout so preflight output appears before any logging (stderr) output
    sys.stdout.flush()
