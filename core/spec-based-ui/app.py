import os
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from flask import (Flask, jsonify, redirect, render_template,
                   request, session, url_for)

load_dotenv()

BASE_DIR = Path(__file__).parent
COMMANDS_DIR = BASE_DIR.parent / "spec-based" / ".claude" / "commands"
SESSIONS_DIR = BASE_DIR / "sessions"
CLAUDE_TIMEOUT = 60

COMMAND_FILES = {
    "requirements": "de-requirements.md",
    "design": "de-design.md",
    "implement": "de-implement.md",
}

APPROVAL_MAP = {
    "requirements": [("specs/requirements.md", ".temp/requirements.md")],
    "design": [
        ("specs/design.md", ".temp/design.md"),
        ("specs/tasks.md", ".temp/tasks.md"),
    ],
    "implement": [("src", ".temp/src"), ("tests", ".temp/tests")],
}

CLI_MODE_FOOTER = """
---
IMPORTANT: You are running in non-interactive mode. Output ONLY the document
content as plain text. Do not reference file writing, tools, or approval steps.
Just output the content of the document itself.
"""

DESIGN_SEPARATOR_INSTRUCTION = """
Output the design document first, then output exactly this separator on its own line:
===TASKS===
Then output the tasks breakdown.
"""


def read_prompt(command: str, arguments: str = "") -> str:
    """Read command file, substitute $ARGUMENTS, append CLI mode footer."""
    cmd_file = COMMANDS_DIR / COMMAND_FILES[command]
    prompt = cmd_file.read_text()
    prompt = prompt.replace("$ARGUMENTS", arguments)
    if command == "design":
        prompt += DESIGN_SEPARATOR_INSTRUCTION
    prompt += CLI_MODE_FOOTER
    return prompt


def run_claude(prompt: str) -> dict:
    """Run claude -p with the given prompt. Returns dict with 'output' or 'error'."""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT,
        )
        if result.returncode != 0:
            return {"error": result.stderr or "Claude returned an error."}
        return {"output": result.stdout.strip(), "status": "ok"}
    except FileNotFoundError:
        return {"error": "claude CLI not found. Is it installed and on PATH?"}
    except subprocess.TimeoutExpired:
        return {"error": "Claude timed out — please try again."}


def check_deps(command: str, user_dir: Path) -> str | None:
    """Return error string if command dependencies aren't met, else None."""
    if command == "design":
        if not (user_dir / "specs" / "requirements.md").exists():
            return "Run Requirements first and approve it before running Design."
    elif command == "implement":
        if not (user_dir / "specs" / "design.md").exists():
            return "Run Design first and approve it before running Implement."
        if not (user_dir / "specs" / "tasks.md").exists():
            return "Run Design first and approve it before running Implement."
    return None


def _write_temp(user_dir: Path, command: str, output: str) -> None:
    """Write Claude output to .temp/ staging files."""
    temp_dir = user_dir / ".temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    if command == "requirements":
        (temp_dir / "requirements.md").write_text(output)

    elif command == "design":
        if "===TASKS===" in output:
            parts = output.split("===TASKS===", 1)
            (temp_dir / "design.md").write_text(parts[0].strip())
            (temp_dir / "tasks.md").write_text(parts[1].strip())
        else:
            (temp_dir / "design.md").write_text(output)
            (temp_dir / "tasks.md").write_text(output)

    elif command == "implement":
        _parse_and_write_code_files(temp_dir, output)


def _parse_and_write_code_files(temp_dir: Path, output: str) -> None:
    """Parse fenced code blocks with file path headers and write to .temp/."""
    import re
    pattern = re.compile(
        r"```(?:\w+)?\n# (?:FILE|file): (.+?)\n(.*?)```",
        re.DOTALL,
    )
    matches = pattern.findall(output)
    if matches:
        for file_path, content in matches:
            full_path = temp_dir / file_path.strip()
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
    else:
        (temp_dir / "implement_output.md").write_text(output)


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")
    app.config["ADMIN_PASSWORD"] = os.getenv("ADMIN_PASSWORD", "admin")

    if config:
        app.config.update(config)

    from functools import wraps

    def login_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("logged_in"):
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated

    @app.route("/")
    def index():
        if session.get("logged_in"):
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            if request.form.get("password") == app.config["ADMIN_PASSWORD"]:
                session["logged_in"] = True
                session["username"] = "admin"
                _ensure_user_dirs("admin")
                return redirect(url_for("dashboard"))
            error = "Invalid password."
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        username = session["username"]
        user_dir = SESSIONS_DIR / username
        requirements_done = (user_dir / "specs" / "requirements.md").exists()
        design_done = (user_dir / "specs" / "design.md").exists()
        last_output = session.get("last_output", "")
        last_command = session.get("last_command", "")
        return render_template(
            "index.html",
            requirements_done=requirements_done,
            design_done=design_done,
            last_output=last_output,
            last_command=last_command,
        )

    @app.route("/run/<command>", methods=["POST"])
    @login_required
    def run_command(command: str):
        if command not in COMMAND_FILES:
            return jsonify({"error": f"Unknown command: {command}"}), 400

        username = session["username"]
        user_dir = SESSIONS_DIR / username

        dep_error = check_deps(command, user_dir)
        if dep_error:
            return jsonify({"error": dep_error})

        data = request.get_json() or {}
        arguments = data.get("input", "").strip()

        if command == "requirements" and not arguments:
            return jsonify({"error": "Please enter a requirement in the input box."})

        prompt = read_prompt(command, arguments)
        result = run_claude(prompt)

        if "error" in result:
            return jsonify(result)

        output = result["output"]
        _write_temp(user_dir, command, output)

        session["last_output"] = output
        session["last_command"] = command
        session["last_prompt"] = prompt

        return jsonify({"output": output, "status": "ok"})

    @app.route("/approve/<command>", methods=["POST"])
    @login_required
    def approve_command(command: str):
        if command not in APPROVAL_MAP:
            return jsonify({"error": f"Unknown command: {command}"}), 400

        username = session["username"]
        user_dir = SESSIONS_DIR / username

        for final_rel, temp_rel in APPROVAL_MAP[command]:
            temp_path = user_dir / temp_rel
            final_path = user_dir / final_rel

            if not temp_path.exists():
                return jsonify({"error": "Nothing to approve — run the command first."})

            final_path.parent.mkdir(parents=True, exist_ok=True)
            if temp_path.is_dir():
                if final_path.exists():
                    shutil.rmtree(final_path)
                shutil.copytree(temp_path, final_path)
            else:
                shutil.copy2(temp_path, final_path)

        return jsonify({"status": "ok"})

    @app.route("/feedback/<command>", methods=["POST"])
    @login_required
    def feedback_command(command: str):
        if command not in COMMAND_FILES:
            return jsonify({"error": f"Unknown command: {command}"}), 400

        data = request.get_json() or {}
        feedback = data.get("feedback", "").strip()
        if not feedback:
            return jsonify({"error": "Please enter feedback before submitting."})

        username = session["username"]
        user_dir = SESSIONS_DIR / username
        last_prompt = session.get("last_prompt", "")
        last_output = session.get("last_output", "")

        if not last_prompt:
            return jsonify({"error": "Run a command first before submitting feedback."})

        # last_prompt already contains CLI_MODE_FOOTER — do not append again
        prompt = (
            f"{last_prompt}\n\n"
            f"Previous output:\n{last_output}\n\n"
            f"User feedback: {feedback}\n\n"
            f"Please regenerate the document incorporating this feedback."
        )

        result = run_claude(prompt)
        if "error" in result:
            return jsonify(result)

        output = result["output"]
        _write_temp(user_dir, command, output)
        session["last_output"] = output
        session["last_prompt"] = prompt

        return jsonify({"output": output, "status": "ok"})

    def _ensure_user_dirs(username: str) -> None:
        user_dir = SESSIONS_DIR / username
        for d in ["specs", "src", "tests", ".temp"]:
            (user_dir / d).mkdir(parents=True, exist_ok=True)

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="0.0.0.0", port=5000, debug=True)
