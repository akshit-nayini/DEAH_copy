"""
package.py — Interactive wrapper for GitHub repo tools.

Run with:  python package.py
"""

import os
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).parent

SCRIPTS = {
    1: _HERE / "github_repo_tree.py",
    2: _HERE / "github_repo_analyzer.py",
    3: _HERE / "github_create_release_notes.py",
}

OPTION_LABELS = {
    1: "Generate Tree",
    2: "Generate Summary",
    3: "Create Release Notes",
}

DEFAULT_OUTPUTS = {
    1: "tree.txt",
    2: "analysis.txt",
    3: "release_note.txt",
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def prompt(message: str, required: bool = True) -> str:
    """Print a prompt and return stripped input. Exits if required and empty."""
    while True:
        value = input(message).strip()
        if value:
            return value
        if not required:
            return ""
        print("    ⚠  This field is required. Please enter a value.\n")


def divider(char: str = "─", width: int = 60) -> None:
    print(char * width)


def parse_folder_from_input(raw: str) -> str:
    """
    Accept either a full GitHub folder URL or a plain path.

    Full URL  : https://github.com/owner/repo/tree/main/src/components
                → returns  src/components
    Plain path: src/components  (or  /src/components)
                → returns  src/components
    """
    raw = raw.strip().rstrip("/")
    # Match: .../{owner}/{repo}/tree/{branch}/{folder/path}
    m = re.match(
        r"https?://github\.com/[^/]+/[^/]+/tree/[^/]+/(.+)",
        raw,
    )
    if m:
        return m.group(1).strip("/")
    # Not a URL — treat as a direct relative folder path
    return raw.strip("/")


def verify_scripts(choice: int) -> None:
    script = SCRIPTS[choice]
    if not script.exists():
        print(f"\n❌  Script not found: {script}")
        print("    Make sure all three .py files are in the same folder as package.py.")
        sys.exit(1)


def run(script: Path, args: list[str], env: dict | None = None) -> None:
    cmd         = [sys.executable, str(script)] + args
    merged_env  = {**os.environ, **(env or {})}   # inherit + override
    divider()
    print(f"▶  Starting: {script.name}\n")
    result = subprocess.run(cmd, env=merged_env)
    divider()
    if result.returncode == 0:
        print("✅  Done.")
    else:
        print(f"❌  Script exited with code {result.returncode}.")
    sys.exit(result.returncode)


# ── Main interactive flow ─────────────────────────────────────────────────────
def main() -> None:
    print()
    divider("═")
    print("  GitHub Repo Tools — Interactive Launcher")
    divider("═")
    print()

    # Step 1: choose task
    print("  What would you like to do?\n")
    for num, label in OPTION_LABELS.items():
        print(f"    [{num}] {label}")
    print()

    while True:
        raw = prompt("  Enter option (1 / 2 / 3): ")
        if raw in ("1", "2", "3"):
            choice = int(raw)
            break
        print(f"    ⚠  Please enter 1, 2, or 3.\n")

    print(f"\n  Selected: [{choice}] {OPTION_LABELS[choice]}")
    divider()

    # Step 2: repo URL and PAT
    print()
    repo_url      = prompt("  Repository URL (HTTPS or SSH)\n  > ")
    pat           = prompt("\n  Personal Access Token (PAT)\n  > ")

    # Step 3: extra inputs
    commit_sha    = ""
    output_file   = ""
    anthropic_key = ""
    folder_path   = ""

    # ── Option 2: whole repo or sub-folder? ───────────────────────────────────
    if choice == 2:
        print()
        print("  Analyse the whole repository?")
        while True:
            scope = prompt("  (y / n): ", required=False).lower()
            if scope in ("y", "n", ""):
                break
            print("    ⚠  Please enter y or n.\n")

        if scope == "n":
            print()
            print("  Enter the folder URL or path to analyse")
            print("  Examples:")
            print("    https://github.com/owner/repo/tree/main/src/components")
            print("    src/components")
            raw_folder  = prompt("  > ")
            folder_path = parse_folder_from_input(raw_folder)
            print(f"    ℹ  Analysing folder: {folder_path}/")
        else:
            print("    ℹ  Analysing the entire repository.")

    # ── Options 2 & 3: Claude AI key ─────────────────────────────────────────
    if choice in (2, 3):
        print()
        # Strip surrounding quotes that Windows cmd sometimes adds to env vars
        # e.g.  set ANTHROPIC_API_KEY="sk-ant-xxx"  →  value includes the quotes
        existing_key = os.environ.get("ANTHROPIC_API_KEY", "").strip().strip('"').strip("'")
        if existing_key:
            masked = existing_key[:8] + "..." + existing_key[-4:]
            print(f"  Anthropic API Key detected in environment: {masked}")
            print("  Press Enter to use it, or type a new key to override")
            entered = prompt("  > ", required=False).strip().strip('"').strip("'")
            anthropic_key = entered if entered else existing_key
        else:
            print("  Anthropic API Key  (required for AI features — starts with sk-ant-)")
            anthropic_key = prompt("  > ").strip().strip('"').strip("'")

        if not anthropic_key.startswith("sk-ant-"):
            print("  ⚠  Warning: key does not start with 'sk-ant-' — double-check it.")
        else:
            masked = anthropic_key[:8] + "..." + anthropic_key[-4:]
            print(f"    ✓  Using API key: {masked}")

    # ── Option 3: commit SHA ──────────────────────────────────────────────────
    if choice == 3:
        print()
        print("  Commit SHA (leave blank to use the latest commit)")
        commit_sha = prompt("  > ", required=False)
        if not commit_sha:
            print("    ℹ  No commit SHA provided — will use the latest commit.")

    # ── Output file ───────────────────────────────────────────────────────────
    print()
    print(f"  Output file (leave blank for default: {DEFAULT_OUTPUTS[choice]})")
    output_file = prompt("  > ", required=False) or DEFAULT_OUTPUTS[choice]
    print(f"    ℹ  Output will be saved to: {output_file}")

    # Step 4: verify and execute
    print()
    divider()
    verify_scripts(choice)

    script_args = ["--url", repo_url, "--token", pat, "--output", output_file]

    if choice == 2 and folder_path:
        script_args += ["--folder", folder_path]

    if choice == 3 and commit_sha:
        script_args += ["--commit", commit_sha]

    # Pass the Anthropic key as an environment variable to the subprocess
    extra_env = {"ANTHROPIC_API_KEY": anthropic_key} if anthropic_key else {}

    print()
    run(SCRIPTS[choice], script_args, env=extra_env)


if __name__ == "__main__":
    main()
