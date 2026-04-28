# DEAH Design Agents — API Setup

Simple FastAPI server to test the four design agents.
Each endpoint mirrors its CLI script exactly — accepts either a **ticket_id** (auto-resolves the
latest output from the metadata DB, same as `--ticket` in the CLI) or **explicit file paths**
relative to `agents/` (same as `--input/--requirements` in the CLI).

---

## 1. Create & activate a virtual environment

```bash
# From core/design/
python -m venv .venv

# Activate — Windows CMD
.venv\Scripts\activate.bat

# Activate — Windows PowerShell
.venv\Scripts\Activate.ps1

# Activate — Mac / Linux
source .venv/bin/activate
```

---

## 2. Install dependencies

```bash
pip install -r requirements.txt
```

---

## 3. Set environment variables

All agents use **Claude Code SDK** — authentication is handled by the `claude login` OAuth session.
`ANTHROPIC_API_KEY` is **not required**.

Create `core/design/.env` (only if you need the optional features below):

```env
# Optional — override default model
# CLAUDE_MODEL=claude-sonnet-4-6

# Required for Jira endpoints
JIRA_BASE_URL=https://prodapt-deah.atlassian.net
JIRA_EMAIL=you@company.com
JIRA_API_KEY=your-jira-token

# Optional — enable git push of agent outputs after each run
# GIT_BRANCH_URL=https://github.com/your-org/your-repo/tree/your-branch
# GIT_PAT=your-personal-access-token

# Required only for live DB connections (no --schema CSV)
# DB_PASSWORD=your-db-password
```

---

## 4. Start the server

### Option A — tmux (recommended for VM / remote sessions)

Run the API and the Streamlit frontend in two persistent tmux windows so both survive SSH disconnects.

```bash
# Create a new named tmux session
tmux new-session -s deah

# --- Window 1: FastAPI server ---
cd ~/DEAH/core/design/api
source ~/venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 9190
```

Open a second pane inside the same session:

```bash
# Press Ctrl+b then Shift+"  (splits pane horizontally)

# --- Pane 2: Streamlit frontend ---
cd ~/DEAH/core/design/frontend
source ~/venv/bin/activate
streamlit run app.py --server.port 9200 --server.address 0.0.0.0
```

| Service | URL |
|---|---|
| FastAPI (Swagger UI) | `http://<VM-IP>:9190/docs` |
| Streamlit frontend   | `http://<VM-IP>:9200` |

**Useful tmux commands:**

| Action | Keys / Command |
|---|---|
| Detach (leave running) | `Ctrl+b` then `d` |
| Reattach later | `tmux attach -t deah` |
| Split pane horizontally | `Ctrl+b` then `Shift+"` |
| Switch between panes | `Ctrl+b` then arrow keys (Up/Down) |
| List sessions | `tmux ls` |
| Kill session | `tmux kill-session -t deah` |

---

### Option B — local (without tmux)

```bash
# From core/design/api/
cd api
uvicorn main:app --port 9190
```

Interactive docs (Swagger UI): **http://localhost:9190/docs**

In a separate terminal:

```bash
# From core/design/frontend/
cd frontend
streamlit run app.py --server.port 9200
```

Streamlit UI: **http://localhost:9200**

---

## 5. Endpoint-to-CLI mapping

| API endpoint | CLI equivalent |
|---|---|
| `POST /requirements/from-jira` | `py requirements_gathering/test_requirements.py --source jira --ticket SCRUM-5` |
| `POST /requirements/from-document` | `py requirements_gathering/test_requirements.py --source document --file ...` |
| `POST /data-model` | `py data_model/test_data_model.py --ticket SCRUM-5` or `--requirements ... --schema ...` |
| `POST /architecture` | `py architecture/test_architecture.py --ticket SCRUM-5` or `--input ...` |
| `POST /implementation-steps` | `py implementation_steps/test_impl_steps.py --ticket SCRUM-5` or `--type ... --project ...` |
| `POST /pipeline` | `py orchestration/orchestrator.py --ticket SCRUM-5` or `--type ... --project ... --requirements ...` |
| `GET  /outputs` | list all output files |

---

## 6. Run each agent individually

### Step 1 — Requirements (from Jira)
```bash
curl -X POST http://localhost:9190/requirements/from-jira \
  -H "Content-Type: application/json" \
  -d '{"ticket_id": "SCRUM-5", "write_back": false}'
```
Response includes `output_path` — use that path in the next steps, or just pass `ticket_id` directly.

> **Note:** The requirements agent automatically reads the parent ticket **and** all linked work items / sub-tasks (e.g. SCRUM-124, SCRUM-125) in a single pass. Comments from every ticket are included. All content is consolidated into one `RequirementsOutput` using the parent ticket ID throughout.

---

### Step 1b — Requirements (from document)
```bash
curl -X POST http://localhost:9190/requirements/from-document \
  -H "Content-Type: application/json" \
  -d '{
    "document_path": "requirements_gathering/requirements_template.txt"
  }'
```
Response includes `output_path` — use that path in the next steps, or pass `ticket_id` directly if the document contains one.

---

### Step 2a — Data Model

```bash
curl -X POST http://localhost:9190/data-model \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "SCRUM-5",
    "schema_path": "data_model/sample_input/table_schema.csv"
  }'
```
Response includes `output_files` with keys `summary_json`, `er_diagram_mmd`, `mapping_csv` — use `summary_json` path in Step 3.

---

### Step 2b — Architecture

```bash
curl -X POST http://localhost:9190/architecture \
  -H "Content-Type: application/json" \
  -d '{"ticket_id": "SCRUM-5"}'
```
Response includes `output_files` with keys `summary_json`, `report_md`, `flow_mmd` — use `summary_json` path in Step 3.

---

### Step 3 — Implementation Steps

```bash
curl -X POST http://localhost:9190/implementation-steps \
  -H "Content-Type: application/json" \
  -d '{"ticket_id": "SCRUM-5"}'
```
`request_type`, `project_name`, and all input JSONs are auto-resolved from the metadata DB.

---

### Full Pipeline (orchestrator equivalent)

```bash
curl -X POST http://localhost:9190/pipeline \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "SCRUM-5",
    "schema_path": "data_model/sample_input/table_schema.csv"
  }'
```
Runs Data Model → Architecture → Mermaid→DrawIO → Implementation Steps in sequence. All inputs auto-resolved from ticket.

---

### List all output files
```bash
curl http://localhost:9190/outputs
```

---

## Output files written to disk

Same locations as the CLI scripts:

```
agents/
  requirements_gathering/output/
    req_SCRUM-5_YYYYMMDD_HH.json           ← requirements JSON

  data_model/output/
    model_SCRUM-5_YYYYMMDD_HH_summary.json     ← pass to /implementation-steps as data_model_path
    model_SCRUM-5_YYYYMMDD_HH_er_diagram.mmd   ← Mermaid ER diagram
    model_SCRUM-5_YYYYMMDD_HH_mapping.csv      ← source→target column mapping

  architecture/outputs/
    arc_SCRUM-5_YYYYMMDD_HH_summary.json   ← pass to /implementation-steps as architecture_path
    arc_SCRUM-5_YYYYMMDD_HH_report.md      ← full narrative report
    arc_SCRUM-5_YYYYMMDD_HH_flow.mmd       ← Mermaid architecture diagram

  implementation_steps/output/
    impl_SCRUM-5_YYYYMMDD_HH.md            ← implementation plan

  mermaid2drawio-converter/drawio_output/
    arc_SCRUM-5_YYYYMMDD_HH_flow_option1.drawio             ← DrawIO architecture option 1
    arc_SCRUM-5_YYYYMMDD_HH_flow_option2.drawio             ← DrawIO architecture option 2
    arc_SCRUM-5_YYYYMMDD_HH_flow_option3_recommended.drawio ← DrawIO architecture option 3 (recommended)
    model_SCRUM-5_YYYYMMDD_HH_er_diagram.drawio             ← DrawIO ER diagram
    (pushed to git + logged to DB after each pipeline run)
```

Use `GET /outputs` to see all files from previous runs.
