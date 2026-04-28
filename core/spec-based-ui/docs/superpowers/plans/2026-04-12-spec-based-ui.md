# Spec-Based UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Flask web UI that lets users run the three-stage DE workflow (requirements → design → implement) through a browser with approve/feedback loops, backed by `claude -p` subprocess calls.

**Architecture:** Single `app.py` with all routes. Flask reads command prompts from `../spec-based/.claude/commands/`, appends a CLI-mode instruction (so Claude outputs text instead of calling tools), runs `claude -p` as a subprocess, writes output to per-user `.temp/` staging, and moves files to final locations on approval.

**Tech Stack:** Python 3.12, Flask, python-dotenv, pytest, plain HTML/JS (no npm).

---

## Important: How CLI Mode Works

The original `.claude/commands/` prompts instruct Claude to "use the Write tool" to save files. In `claude -p` subprocess mode, Claude has no tools — it only outputs text. Flask appends this footer to every prompt before calling Claude:

```
---
IMPORTANT: You are running in non-interactive mode. Output ONLY the document
content as plain text. Do not reference file writing, tools, or approval steps.
Just output the content of the document itself.
```

Flask then writes the output text to the appropriate `.temp/` file.

**Design command special case:** The design prompt asks Claude to produce both a design doc and a tasks breakdown. Flask appends a separator instruction so it can split the output:

```
Output the design document, then output exactly this separator on its own line:
===TASKS===
Then output the tasks breakdown.
```

Flask splits on `===TASKS===` and writes two files: `.temp/design.md` and `.temp/tasks.md`.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `spec-based-ui/app.py` | Create | All Flask routes + helper functions |
| `spec-based-ui/templates/login.html` | Create | Login form |
| `spec-based-ui/templates/index.html` | Create | Main UI (sidebar + output panel) |
| `spec-based-ui/requirements.txt` | Create | flask, python-dotenv |
| `spec-based-ui/.env` | Create | ADMIN_PASSWORD, SECRET_KEY (gitignored) |
| `spec-based-ui/.gitignore` | Create | .env, sessions/, __pycache__, .venv |
| `spec-based-ui/tests/__init__.py` | Create | Empty |
| `spec-based-ui/tests/test_app.py` | Create | Pytest test suite |
| `spec-based-ui/sessions/admin/{specs,src,tests,.temp}/` | Create | User workspace dirs |

---

## Task 1: Scaffold Project Structure

**Files:**
- Create: `spec-based-ui/requirements.txt`
- Create: `spec-based-ui/.env`
- Create: `spec-based-ui/.gitignore`
- Create: `spec-based-ui/sessions/admin/` subdirectories

- [ ] **Step 1: Create `requirements.txt`**

```
flask==3.1.0
python-dotenv==1.0.1
pytest==8.3.5
```

Write to `spec-based-ui/requirements.txt`.

- [ ] **Step 2: Create `.env`**

```
SECRET_KEY=change-this-in-production
ADMIN_PASSWORD=admin
```

Write to `spec-based-ui/.env`.

- [ ] **Step 3: Create `.gitignore`**

```
.env
sessions/*/specs/
sessions/*/src/
sessions/*/tests/
sessions/*/.temp/
__pycache__/
*.pyc
.venv/
venv/
.pytest_cache/
```

Write to `spec-based-ui/.gitignore`.

- [ ] **Step 4: Create session workspace directories and `conftest.py`**

Run from `spec-based-ui/`:
```bash
mkdir -p sessions/admin/specs
mkdir -p sessions/admin/src
mkdir -p sessions/admin/tests
mkdir -p sessions/admin/.temp
touch sessions/admin/specs/.gitkeep
touch sessions/admin/src/.gitkeep
touch sessions/admin/tests/.gitkeep
touch sessions/admin/.temp/.gitkeep
mkdir -p tests
touch tests/__init__.py
```

Write to `spec-based-ui/tests/conftest.py`:

```python
import sys
from pathlib import Path

# Add spec-based-ui/ to path so `from app import ...` works in all tests
sys.path.insert(0, str(Path(__file__).parent.parent))
```

- [ ] **Step 5: Install dependencies**

```bash
cd spec-based-ui
pip install -r requirements.txt --break-system-packages
```

Expected: flask, python-dotenv, pytest installed.

- [ ] **Step 6: Verify structure**

```bash
find spec-based-ui -not -path '*/.git/*' | sort
```

Expected includes: `app.py` (not yet), `requirements.txt`, `.env`, `.gitignore`, `sessions/admin/specs/.gitkeep`, `tests/__init__.py`.

- [ ] **Step 7: Commit**

```bash
git add spec-based-ui/requirements.txt spec-based-ui/.gitignore spec-based-ui/tests/__init__.py spec-based-ui/sessions/
git commit -m "scaffold: add spec-based-ui project structure"
```

Note: do NOT commit `.env`.

---

## Task 2: Flask App — Setup + Auth

**Files:**
- Create: `spec-based-ui/app.py`
- Create: `spec-based-ui/tests/test_app.py`

- [ ] **Step 1: Write failing auth tests**

Write to `spec-based-ui/tests/test_app.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def app():
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from app import create_app
    application = create_app({"TESTING": True, "SECRET_KEY": "test", "ADMIN_PASSWORD": "admin"})
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


def test_root_redirects_to_login_when_not_logged_in(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_page_loads(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"login" in response.data.lower()


def test_login_with_correct_credentials(client):
    response = client.post("/login", data={"password": "admin"}, follow_redirects=False)
    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]


def test_login_with_wrong_password(client):
    response = client.post("/login", data={"password": "wrong"}, follow_redirects=False)
    assert response.status_code == 200
    assert b"invalid" in response.data.lower()


def test_dashboard_requires_login(client):
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_dashboard_accessible_when_logged_in(client):
    client.post("/login", data={"password": "admin"})
    response = client.get("/dashboard")
    assert response.status_code == 200


def test_logout_clears_session(client):
    client.post("/login", data={"password": "admin"})
    client.get("/logout")
    response = client.get("/dashboard")
    assert response.status_code == 302
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd spec-based-ui
python -m pytest tests/test_app.py -v 2>&1 | head -30
```

Expected: ImportError or ModuleNotFoundError (app.py doesn't exist yet).

- [ ] **Step 3: Write `app.py` — setup + auth only**

```python
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


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")
    app.config["ADMIN_PASSWORD"] = os.getenv("ADMIN_PASSWORD", "admin")

    if config:
        app.config.update(config)

    def login_required(f):
        from functools import wraps
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

    def _ensure_user_dirs(username: str) -> None:
        user_dir = SESSIONS_DIR / username
        for d in ["specs", "src", "tests", ".temp"]:
            (user_dir / d).mkdir(parents=True, exist_ok=True)

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="0.0.0.0", port=5000, debug=True)
```

- [ ] **Step 4: Run auth tests — verify they pass**

```bash
cd spec-based-ui
python -m pytest tests/test_app.py -v
```

Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add spec-based-ui/app.py spec-based-ui/tests/test_app.py
git commit -m "feat: add Flask app with auth routes"
```

---

## Task 3: Helper Functions — Prompt Loading + Subprocess

**Files:**
- Modify: `spec-based-ui/app.py` (add helper functions inside `create_app`)
- Modify: `spec-based-ui/tests/test_app.py` (add helper tests)

- [ ] **Step 1: Add helper function tests to `test_app.py`**

Append to `spec-based-ui/tests/test_app.py`:

```python
def test_read_prompt_substitutes_arguments(tmp_path, monkeypatch):
    cmd_dir = tmp_path / "commands"
    cmd_dir.mkdir()
    (cmd_dir / "de-requirements.md").write_text("Your requirement is: $ARGUMENTS\nGenerate a doc.")

    import app as app_module
    monkeypatch.setattr(app_module, "COMMANDS_DIR", cmd_dir)

    from app import read_prompt
    result = read_prompt("requirements", "build a pipeline")
    assert "build a pipeline" in result
    assert "$ARGUMENTS" not in result
    assert "non-interactive mode" in result


def test_read_prompt_empty_arguments(tmp_path, monkeypatch):
    cmd_dir = tmp_path / "commands"
    cmd_dir.mkdir()
    (cmd_dir / "de-requirements.md").write_text("Requirement: $ARGUMENTS")

    import app as app_module
    monkeypatch.setattr(app_module, "COMMANDS_DIR", cmd_dir)

    from app import read_prompt
    result = read_prompt("requirements", "")
    assert "$ARGUMENTS" not in result


def test_run_claude_returns_output(monkeypatch):
    import subprocess
    from app import run_claude

    mock_result = type("R", (), {"returncode": 0, "stdout": "hello output", "stderr": ""})()
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

    result = run_claude("some prompt")
    assert result == {"output": "hello output", "status": "ok"}


def test_run_claude_handles_timeout(monkeypatch):
    import subprocess
    from app import run_claude

    def raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=60)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    result = run_claude("prompt")
    assert "timed out" in result["error"].lower()


def test_run_claude_handles_not_found(monkeypatch):
    import subprocess
    from app import run_claude

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError()))
    result = run_claude("prompt")
    assert "not found" in result["error"].lower()


def test_check_deps_design_missing_requirements(tmp_path):
    from app import check_deps
    result = check_deps("design", tmp_path)
    assert result is not None
    assert "requirements" in result.lower()


def test_check_deps_design_satisfied(tmp_path):
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "requirements.md").write_text("done")
    from app import check_deps
    result = check_deps("design", tmp_path)
    assert result is None


def test_check_deps_implement_missing_design(tmp_path):
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "requirements.md").write_text("done")
    from app import check_deps
    result = check_deps("implement", tmp_path)
    assert result is not None
    assert "design" in result.lower()
```

- [ ] **Step 2: Run new tests — verify they fail**

```bash
cd spec-based-ui
python -m pytest tests/test_app.py -v -k "prompt or claude or deps" 2>&1 | head -30
```

Expected: ImportError or AttributeError (functions not defined yet).

- [ ] **Step 3: Add helper functions to `app.py`**

Add these three functions at module level (outside `create_app`, after the constants):

```python
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
```

- [ ] **Step 4: Run helper tests — verify they pass**

```bash
cd spec-based-ui
python -m pytest tests/test_app.py -v -k "prompt or claude or deps"
```

Expected: 9 new tests PASS (7 auth tests still pass too).

- [ ] **Step 5: Commit**

```bash
git add spec-based-ui/app.py spec-based-ui/tests/test_app.py
git commit -m "feat: add read_prompt, run_claude, check_deps helpers"
```

---

## Task 4: Routes — `/run`, `/approve`, `/feedback`

**Files:**
- Modify: `spec-based-ui/app.py` (add three routes inside `create_app`)
- Modify: `spec-based-ui/tests/test_app.py` (add route tests)

- [ ] **Step 1: Add route tests to `test_app.py`**

Append to `spec-based-ui/tests/test_app.py`:

```python
def test_run_requirements_success(client, tmp_path, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "COMMANDS_DIR",
        Path(__file__).parent.parent.parent / "spec-based" / ".claude" / "commands")

    (tmp_path / "admin" / "specs").mkdir(parents=True)
    (tmp_path / "admin" / ".temp").mkdir(parents=True)

    monkeypatch.setattr(app_module, "run_claude",
        lambda p: {"output": "# Requirements\nGoal: test", "status": "ok"})

    client.post("/login", data={"password": "admin"})
    response = client.post("/run/requirements",
        json={"input": "build a test pipeline"},
        content_type="application/json")

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert "Requirements" in data["output"]


def test_run_design_blocked_without_requirements(client, tmp_path, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "SESSIONS_DIR", tmp_path)
    (tmp_path / "admin" / "specs").mkdir(parents=True)

    client.post("/login", data={"password": "admin"})
    response = client.post("/run/design",
        json={"input": ""},
        content_type="application/json")

    assert response.status_code == 200
    data = response.get_json()
    assert "error" in data
    assert "requirements" in data["error"].lower()


def test_approve_requirements(client, tmp_path, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "SESSIONS_DIR", tmp_path)

    user_dir = tmp_path / "admin"
    (user_dir / ".temp").mkdir(parents=True)
    (user_dir / "specs").mkdir(parents=True)
    (user_dir / ".temp" / "requirements.md").write_text("# Requirements\nGoal: test")

    client.post("/login", data={"password": "admin"})
    with client.session_transaction() as sess:
        sess["last_command"] = "requirements"

    response = client.post("/approve/requirements")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert (user_dir / "specs" / "requirements.md").exists()


def test_approve_fails_when_nothing_staged(client, tmp_path, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "SESSIONS_DIR", tmp_path)
    (tmp_path / "admin" / ".temp").mkdir(parents=True)
    (tmp_path / "admin" / "specs").mkdir(parents=True)

    client.post("/login", data={"password": "admin"})
    with client.session_transaction() as sess:
        sess["last_command"] = "requirements"

    response = client.post("/approve/requirements")
    data = response.get_json()
    assert "error" in data


def test_feedback_reruns_claude(client, tmp_path, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(app_module, "COMMANDS_DIR",
        Path(__file__).parent.parent.parent / "spec-based" / ".claude" / "commands")

    (tmp_path / "admin" / ".temp").mkdir(parents=True)
    (tmp_path / "admin" / "specs").mkdir(parents=True)

    monkeypatch.setattr(app_module, "run_claude",
        lambda p: {"output": "# Requirements v2\nGoal: revised", "status": "ok"})

    client.post("/login", data={"password": "admin"})
    with client.session_transaction() as sess:
        sess["last_command"] = "requirements"
        sess["last_prompt"] = "original prompt"

    response = client.post("/feedback/requirements",
        json={"feedback": "add more detail about SLAs"},
        content_type="application/json")

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert "revised" in data["output"]
```

- [ ] **Step 2: Run route tests — verify they fail**

```bash
cd spec-based-ui
python -m pytest tests/test_app.py -v -k "run or approve or feedback" 2>&1 | head -20
```

Expected: 404 responses (routes not defined yet).

- [ ] **Step 3: Add `/run/<command>` route inside `create_app` in `app.py`**

Add after the `/dashboard` route:

```python
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
```

- [ ] **Step 4: Add `_write_temp` helper and `/approve/<command>` route**

Add `_write_temp` as a module-level function after `check_deps`:

```python
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
```

Then add `/approve/<command>` route inside `create_app`:

```python
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
```

- [ ] **Step 5: Add `/feedback/<command>` route inside `create_app`**

```python
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
```

- [ ] **Step 6: Run all route tests — verify they pass**

```bash
cd spec-based-ui
python -m pytest tests/test_app.py -v
```

Expected: all tests PASS (7 auth + 9 helper + 5 route = 21 tests).

- [ ] **Step 7: Commit**

```bash
git add spec-based-ui/app.py spec-based-ui/tests/test_app.py
git commit -m "feat: add /run, /approve, /feedback routes"
```

---

## Task 5: `login.html` Template

**Files:**
- Create: `spec-based-ui/templates/login.html`

- [ ] **Step 1: Create `templates/` directory and write `login.html`**

```bash
mkdir -p spec-based-ui/templates
```

Write to `spec-based-ui/templates/login.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>DE Assistant — Login</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: monospace;
            background: #1e1e1e;
            color: #d4d4d4;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
        }
        .card {
            background: #252526;
            border: 1px solid #444;
            padding: 40px;
            width: 320px;
        }
        h1 { font-size: 16px; color: #fff; margin-bottom: 24px; }
        label { font-size: 12px; color: #888; display: block; margin-bottom: 6px; }
        input[type="password"] {
            width: 100%;
            background: #3c3c3c;
            border: 1px solid #555;
            color: #d4d4d4;
            padding: 10px;
            font-family: monospace;
            font-size: 14px;
            margin-bottom: 16px;
        }
        button {
            width: 100%;
            background: #0e639c;
            color: #fff;
            border: none;
            padding: 10px;
            font-family: monospace;
            font-size: 14px;
            cursor: pointer;
        }
        button:hover { background: #1177bb; }
        .error {
            color: #f48771;
            font-size: 12px;
            margin-bottom: 16px;
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>DE Assistant</h1>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <form method="POST">
            <label for="password">Password</label>
            <input type="password" id="password" name="password" autofocus placeholder="Enter password">
            <button type="submit">Login →</button>
        </form>
    </div>
</body>
</html>
```

- [ ] **Step 2: Verify login page renders**

```bash
cd spec-based-ui
python -m pytest tests/test_app.py::test_login_page_loads -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add spec-based-ui/templates/login.html
git commit -m "feat: add login.html template"
```

---

## Task 6: `index.html` Template

**Files:**
- Create: `spec-based-ui/templates/index.html`

- [ ] **Step 1: Write `index.html`**

Write to `spec-based-ui/templates/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>DE Assistant</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: monospace; background: #1e1e1e; color: #d4d4d4; height: 100vh; display: flex; flex-direction: column; }
        header { background: #2d2d2d; padding: 12px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #444; flex-shrink: 0; }
        header h1 { font-size: 15px; color: #fff; }
        .logout { color: #888; text-decoration: none; font-size: 12px; }
        .logout:hover { color: #fff; }
        .main { display: flex; flex: 1; overflow: hidden; }
        /* Sidebar */
        .sidebar { width: 220px; background: #252526; border-right: 1px solid #444; padding: 16px; display: flex; flex-direction: column; gap: 20px; flex-shrink: 0; }
        .step h3 { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
        .btn-run { background: #0e639c; color: #fff; border: none; padding: 8px 12px; cursor: pointer; font-family: monospace; font-size: 12px; width: 100%; text-align: left; }
        .btn-run:hover:not(:disabled) { background: #1177bb; }
        .btn-run:disabled { background: #3c3c3c; color: #555; cursor: not-allowed; }
        .divider { border-top: 1px solid #444; }
        .input-label { font-size: 11px; color: #888; margin-bottom: 6px; }
        #user-input { width: 100%; background: #3c3c3c; border: 1px solid #555; color: #d4d4d4; padding: 8px; font-family: monospace; font-size: 12px; resize: vertical; min-height: 90px; }
        /* Output panel */
        .output-panel { flex: 1; display: flex; flex-direction: column; min-width: 0; }
        .output-header { padding: 10px 16px; background: #2d2d2d; font-size: 11px; color: #888; border-bottom: 1px solid #444; flex-shrink: 0; }
        #output-content { flex: 1; overflow-y: auto; padding: 16px; white-space: pre-wrap; font-size: 13px; line-height: 1.6; }
        #output-content.empty { color: #555; font-style: italic; }
        #output-content.loading { color: #888; }
        #output-content.error { color: #f48771; }
        .output-footer { border-top: 1px solid #444; padding: 12px 16px; background: #252526; flex-shrink: 0; }
        .action-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
        .btn-approve { background: #388a34; color: #fff; border: none; padding: 8px 14px; cursor: pointer; font-family: monospace; font-size: 12px; }
        .btn-approve:hover:not(:disabled) { background: #4caa45; }
        .btn-approve:disabled { background: #3c3c3c; color: #555; cursor: not-allowed; }
        .btn-feedback-toggle { background: #4a3900; color: #ffd700; border: none; padding: 8px 14px; cursor: pointer; font-family: monospace; font-size: 12px; }
        .btn-feedback-toggle:hover { background: #6a5200; }
        #status-msg { font-size: 12px; color: #888; }
        #status-msg.error { color: #f48771; }
        .feedback-area { display: none; margin-top: 10px; }
        .feedback-area.visible { display: flex; flex-direction: column; gap: 8px; }
        #feedback-text { width: 100%; background: #3c3c3c; border: 1px solid #555; color: #d4d4d4; padding: 8px; font-family: monospace; font-size: 12px; resize: vertical; min-height: 60px; }
        .btn-submit { background: #6a1a1a; color: #ff9999; border: none; padding: 8px 14px; cursor: pointer; font-family: monospace; font-size: 12px; align-self: flex-start; }
        .btn-submit:hover { background: #8a2a2a; }
    </style>
</head>
<body>
    <header>
        <h1>DE Assistant</h1>
        <a href="/logout" class="logout">[Logout]</a>
    </header>
    <div class="main">
        <div class="sidebar">
            <div class="step">
                <h3>1. Requirements</h3>
                <button class="btn-run" id="btn-requirements" onclick="runCommand('requirements')">Run ▶</button>
            </div>
            <div class="step">
                <h3>2. Design</h3>
                <button class="btn-run" id="btn-design" onclick="runCommand('design')"
                    {% if not requirements_done %}disabled{% endif %}>Run ▶</button>
            </div>
            <div class="step">
                <h3>3. Implement</h3>
                <button class="btn-run" id="btn-implement" onclick="runCommand('implement')"
                    {% if not design_done %}disabled{% endif %}>Run ▶</button>
            </div>
            <div class="divider"></div>
            <div>
                <div class="input-label">Input (for Requirements)</div>
                <textarea id="user-input" placeholder="Describe your data pipeline..."></textarea>
            </div>
        </div>
        <div class="output-panel">
            <div class="output-header">Output</div>
            <div id="output-content" class="{% if last_output %}{% else %}empty{% endif %}">
                {% if last_output %}{{ last_output }}{% else %}Run a command to see output here.{% endif %}
            </div>
            <div class="output-footer">
                <div class="action-row">
                    <button class="btn-approve" id="btn-approve" onclick="approveCommand()"
                        {% if not last_command %}disabled{% endif %}>✓ Approve</button>
                    <button class="btn-feedback-toggle" onclick="toggleFeedback()">Feedback ▼</button>
                    <span id="status-msg"></span>
                </div>
                <div class="feedback-area" id="feedback-area">
                    <textarea id="feedback-text" placeholder="Describe what to change..."></textarea>
                    <button class="btn-submit" onclick="submitFeedback()">Submit Feedback</button>
                </div>
            </div>
        </div>
    </div>
    <script>
        let currentCommand = '{{ last_command or "" }}';

        function setOutput(text, cls) {
            const el = document.getElementById('output-content');
            el.textContent = text;
            el.className = cls || '';
        }
        function setStatus(msg, isError) {
            const el = document.getElementById('status-msg');
            el.textContent = msg;
            el.className = isError ? 'error' : '';
        }

        function runCommand(command) {
            if (command === 'requirements') {
                const input = document.getElementById('user-input').value.trim();
                if (!input) { setStatus('Please enter a requirement in the input box.', true); return; }
            }
            setOutput('Running ' + command + '...', 'loading');
            document.getElementById('btn-approve').disabled = true;
            currentCommand = command;

            fetch('/run/' + command, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({input: document.getElementById('user-input').value})
            })
            .then(r => r.json())
            .then(data => {
                if (data.error) { setOutput(data.error, 'error'); setStatus(''); }
                else {
                    setOutput(data.output, '');
                    document.getElementById('btn-approve').disabled = false;
                    setStatus('Saved to .temp/ — review then approve or give feedback.');
                }
            })
            .catch(() => setOutput('Network error — please try again.', 'error'));
        }

        function approveCommand() {
            if (!currentCommand) return;
            fetch('/approve/' + currentCommand, {method: 'POST'})
            .then(r => r.json())
            .then(data => {
                if (data.error) { setStatus(data.error, true); }
                else {
                    setStatus('Approved and saved to specs/.');
                    document.getElementById('btn-approve').disabled = true;
                    if (currentCommand === 'requirements') document.getElementById('btn-design').disabled = false;
                    if (currentCommand === 'design') document.getElementById('btn-implement').disabled = false;
                }
            });
        }

        function toggleFeedback() {
            document.getElementById('feedback-area').classList.toggle('visible');
        }

        function submitFeedback() {
            const text = document.getElementById('feedback-text').value.trim();
            if (!text) { setStatus('Please enter feedback before submitting.', true); return; }
            setOutput('Regenerating...', 'loading');
            document.getElementById('btn-approve').disabled = true;

            fetch('/feedback/' + currentCommand, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({feedback: text})
            })
            .then(r => r.json())
            .then(data => {
                if (data.error) { setOutput(data.error, 'error'); }
                else {
                    setOutput(data.output, '');
                    document.getElementById('feedback-text').value = '';
                    document.getElementById('feedback-area').classList.remove('visible');
                    document.getElementById('btn-approve').disabled = false;
                    setStatus('Regenerated — review then approve or give more feedback.');
                }
            });
        }
    </script>
</body>
</html>
```

- [ ] **Step 2: Smoke-test template renders by starting the app**

```bash
cd spec-based-ui
python app.py &
sleep 2
curl -s http://localhost:5000/ | grep -c "redirect\|login\|DE Assistant"
kill %1
```

Expected: output > 0 (page responded).

- [ ] **Step 3: Commit**

```bash
git add spec-based-ui/templates/
git commit -m "feat: add login.html and index.html templates"
```

---

## Task 7: Final Smoke Test + Cleanup

- [ ] **Step 1: Run full test suite**

```bash
cd spec-based-ui
python -m pytest tests/ -v
```

Expected: all tests PASS, 0 failures.

- [ ] **Step 2: Start the app and verify login flow in browser**

```bash
python app.py
```

Open `http://<vm-external-ip>:5000` in your browser (GCP firewall rule must allow port 5000).

Verify:
- Login page loads
- Wrong password shows "Invalid password"
- Correct password (`admin`) redirects to dashboard
- Dashboard shows three Run buttons (Design and Implement disabled)
- Logout redirects to login

- [ ] **Step 3: Test Requirements command end-to-end**

In the browser:
1. Type a requirement in the input box: `"build a daily pipeline from MySQL to BigQuery"`
2. Click `Run ▶` on Requirements
3. Verify output appears in the right panel
4. Click `✓ Approve`
5. Verify Design button becomes enabled

- [ ] **Step 4: Verify `.gitignore` covers session content**

```bash
cd spec-based-ui
git status
```

Expected: `sessions/admin/specs/requirements.md` does NOT appear (gitignored).

- [ ] **Step 5: Final commit**

```bash
git add spec-based-ui/
git status  # verify nothing unexpected is staged
git commit -m "feat: complete spec-based-ui Flask app"
git push origin main
```
