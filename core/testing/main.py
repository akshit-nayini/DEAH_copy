"""
main.py
-------
Start one or both Testing POD agents.

Usage:
    python3 main.py                  # starts both generator + validator
    python3 main.py generator        # generator only  (port 9195)
    python3 main.py validator        # validator only  (port 9196)
"""

import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flask import Flask
from config import GENERATOR_PORT, VALIDATOR_PORT, SERVER_HOST
from routers.generator_router import generator_bp
from routers.validator_router import validator_bp


def git_pull():
    """Pull latest code from origin/<current branch> before starting."""
    repo_root = Path(__file__).resolve().parents[2]
    try:
        # Detect current branch
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=10,
        )
        branch = branch_result.stdout.strip() or "main"

        result = subprocess.run(
            ["git", "pull", "origin", branch],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            msg = result.stdout.strip() or "Already up to date."
            print(f"  [git] ({branch}) {msg}")
        else:
            print(f"  [git] Pull failed: {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        print("  [git] Pull timed out — starting with existing code.")
    except Exception as e:
        print(f"  [git] Pull skipped: {e}")


def make_generator_app() -> Flask:
    app = Flask("generator")
    app.register_blueprint(generator_bp)
    return app


def make_validator_app() -> Flask:
    app = Flask("validator")
    app.register_blueprint(validator_bp)
    return app


def run_app(app: Flask, port: int, name: str):
    display_ip = SERVER_HOST if SERVER_HOST != "0.0.0.0" else "localhost"
    print(f"  {name} -- http://{display_ip}:{port}")
    app.run(debug=False, port=port, host="0.0.0.0", use_reloader=False)


if __name__ == "__main__":
    print("\n  Pulling latest code from Git...")
    git_pull()

    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "both"

    if mode == "generator":
        run_app(make_generator_app(), GENERATOR_PORT, "Test Case Generator")

    elif mode == "validator":
        run_app(make_validator_app(), VALIDATOR_PORT, "Result Validator Agent")

    else:  # both
        print("\n  Starting both agents...")
        gen_thread = threading.Thread(
            target=run_app,
            args=(make_generator_app(), GENERATOR_PORT, "Test Case Generator"),
            daemon=True,
        )
        gen_thread.start()
        # Run validator on main thread (blocking)
        run_app(make_validator_app(), VALIDATOR_PORT, "Result Validator Agent")
