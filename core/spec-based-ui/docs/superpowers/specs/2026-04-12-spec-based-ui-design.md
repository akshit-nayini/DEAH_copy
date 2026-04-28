# Spec-Based UI Design

**Date:** 2026-04-12
**Status:** Approved

---

## Overview

A Flask web UI that wraps the `spec-based` Claude Code CLI tool, allowing users to
run the three-stage data engineering workflow (`/de-requirements`, `/de-design`,
`/de-implement`) through a browser instead of a terminal.

The UI reads command prompts directly from `../spec-based/.claude/commands/` and
executes them via `claude -p` subprocess (non-interactive CLI mode). No Claude API
key required — uses the existing `claude` CLI session on the VM.

Deployed on a GCP Linux VM, accessed via browser using a GCP firewall rule on port 5000.

---

## Folder Structure

```
spec-based-ui/
  app.py                    ← Flask app, all routes + CLI subprocess logic
  templates/
    login.html              ← admin/admin login form
    index.html              ← main UI: buttons left, output right, approve/feedback
  sessions/
    admin/
      specs/                ← approved requirements, design, tasks
      src/                  ← approved generated code
      tests/                ← approved mocked tests
      .temp/                ← staging area (gitignored contents)
  .env                      ← ADMIN_PASSWORD=admin (gitignored)
  requirements.txt          ← flask, python-dotenv
  .gitignore
  docs/
    superpowers/
      specs/                ← design docs
      plans/                ← implementation plans
```

The `spec-based-ui/` folder lives alongside `spec-based/` inside the DEAH repo.
Command prompts are read from `../spec-based/.claude/commands/` — no duplication.

---

## UI Layout

```
┌─────────────────────────────────────────────────────────────┐
│  DE Assistant                                    [Logout]   │
├──────────────────┬──────────────────────────────────────────┤
│                  │                                          │
│  1. Requirements │   Output                                 │
│  [Run ▶]        │   ─────────────────────────────────────  │
│                  │   # Requirements: MySQL to BigQuery       │
│  2. Design       │                                          │
│  [Run ▶]        │   **Goal:** Move data from...            │
│                  │   **Inputs:** MySQL tables...            │
│  3. Implement    │                                          │
│  [Run ▶]        │                                          │
│                  │   ─────────────────────────────────────  │
│  ─────────────── │   Saved to .temp/requirements.md        │
│  Input           │                                          │
│  ┌────────────┐  │   [✓ Approve]  [Feedback ▼]            │
│  │            │  │               ┌──────────────────────┐  │
│  │            │  │               │ type feedback here   │  │
│  └────────────┘  │               └──────────────────────┘  │
│                  │               [Submit Feedback]          │
└──────────────────┴──────────────────────────────────────────┘
```

**Behaviour:**
- Input box (bottom left) — user types requirement before clicking Run on step 1.
  Steps 2 and 3 read from `specs/` automatically.
- Run buttons — step 2 disabled until requirements approved; step 3 disabled until
  design + tasks approved.
- Approve — moves `.temp/` file to final location, enables next step's Run button.
- Feedback — reveals text box, user types feedback, clicks Submit, output regenerates.
- Output panel — clears and refills on each Run or feedback submission.
- Output panel content persists across page refresh (stored in Flask session).

---

## Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Redirect to `/login` or `/dashboard` |
| `/login` | GET/POST | Show login form, validate admin/admin |
| `/logout` | GET | Clear session, redirect to `/login` |
| `/dashboard` | GET | Serve `index.html` |
| `/run/<command>` | POST | Run a command, return output as JSON |
| `/approve/<command>` | POST | Move `.temp/` file to final location |
| `/feedback/<command>` | POST | Regenerate with feedback, return new output |

---

## CLI Integration

### Running a command (`/run/<command>`)

1. Read prompt from `../spec-based/.claude/commands/<command>.md`
2. Replace `$ARGUMENTS` with user input from POST body
3. Run `claude -p "<prompt>"` as subprocess with 60s timeout
4. Capture stdout, return as JSON `{"output": "...", "status": "ok"}`
5. Flask writes output to `sessions/<username>/.temp/<file>` directly
   (since we're calling Claude via subprocess, Flask handles file writes,
   not Claude itself)

### Session state (server-side Flask session)

- `logged_in` — bool
- `username` — "admin"
- `last_output` — last Claude response (used by feedback loop)
- `current_step` — active step: "requirements" / "design" / "implement"

---

## Error Handling

### Step dependency checks
- `/run/design` — checks `sessions/<user>/specs/requirements.md` exists.
  Error: "Run Requirements first and approve it before running Design."
- `/run/implement` — checks `sessions/<user>/specs/design.md` and `specs/tasks.md` exist.
  Error: "Run Design first and approve it before running Implement."

### CLI failures
- `claude` not on PATH → `{"error": "claude CLI not found. Is it installed?"}`
- Subprocess timeout (60s) → `{"error": "Claude timed out — please try again."}`
- Non-zero exit code → `{"error": "<stderr content>"}`

### Approve
- `.temp/` file missing → `{"error": "Nothing to approve — run the command first."}`
- Copies file to final location on success.

### Feedback
- Empty feedback text → client-side validation: "Please enter feedback before submitting."
- Appends feedback + previous output to original prompt, re-runs `claude -p`.

---

## Authentication

- Hardcoded: username `admin`, password `admin`
- Stored in `.env` as `ADMIN_PASSWORD=admin`
- Flask session cookie (secret key from `.env`)
- All routes except `/login` require `logged_in` session flag

---

## User Isolation

Each authenticated user gets their own workspace:
```
sessions/<username>/
  specs/
  src/
  tests/
  .temp/
```

Created automatically on first login if not present.

---

## Getting Started

```bash
cd spec-based-ui
pip install -r requirements.txt
python app.py
```

Open `http://<vm-external-ip>:5000` in your browser.
(Requires GCP firewall rule allowing TCP port 5000.)

---

## Dependencies

- `flask` — web framework
- `python-dotenv` — load `.env` config
- `claude` CLI — must be installed and authenticated on the VM
