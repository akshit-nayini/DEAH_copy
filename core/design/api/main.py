
"""
main.py — DEAH Design Agents FastAPI
Maps HTTP endpoints 1-to-1 with the CLI test scripts.

Run from core/design/api/:
    uvicorn main:app --reload --port 8000

Interactive docs: http://localhost:8000/docs
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Path setup ────────────────────────────────────────────────────────────────
# Mirror how each test script sets sys.path before importing its agent.
#
#   requirements:    ROOT = requirements_gathering/  → from gathering.agent import ...
#   data_model:      ROOT = agents/                 → from data_model import ...
#   architecture:    ROOT = architecture/            → from agent import ArchitectureAgent
#   impl_steps:      ROOT = implementation_steps/   → from implementation_steps.agent import ...

_API_DIR    = Path(__file__).resolve().parent
_DESIGN_DIR = _API_DIR.parent
_AGENTS_DIR = _DESIGN_DIR / "agents"
_REPO_ROOT  = _AGENTS_DIR.parents[2]   # DEAH/ — same as REPO_ROOT in test scripts

sys.path.insert(0, str(_REPO_ROOT))            # makes `core.utilities` importable
sys.path.insert(0, str(_AGENTS_DIR / "requirements_gathering"))
sys.path.insert(0, str(_AGENTS_DIR))
sys.path.insert(0, str(_AGENTS_DIR / "architecture"))
sys.path.insert(0, str(_AGENTS_DIR / "implementation_steps"))

# Load .env from core/design/ or project root
load_dotenv(_DESIGN_DIR / ".env")
load_dotenv()

print("INFO: All agents use Claude Code SDK — authentication via `claude login` OAuth session (no API key required).")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve(path: str) -> Path:
    """
    Resolve a path the same way the CLI does — relative to agents/ dir.
    If the path is already absolute it is returned as-is.
    """
    p = Path(path)
    return p if p.is_absolute() else (_AGENTS_DIR / p)



def _glob_latest(pattern: str) -> Optional[str]:
    """Return the most recently modified file matching glob pattern, or None."""
    matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return matches[0] if matches else None


def _split_arch_mmd(mmd_path: str) -> list[str]:
    """
    Split a combined architecture .mmd (multiple subgraphs) into per-option
    standalone flowchart LR files.  Returns list of written .mmd paths.
    Named: arc_<ticket>_<run_id>_flow_option<N>.mmd
           arc_<ticket>_<run_id>_flow_option<N>_recommended.mmd
    """
    import re as _re
    text = Path(mmd_path).read_text(encoding="utf-8")
    lines = text.splitlines()

    header_comment = next((l for l in lines if l.strip().startswith("%%")), "")

    # Parse each top-level subgraph block
    subgraphs: list[tuple[str, str, list[str]]] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("subgraph "):
            sg_rest = stripped[len("subgraph "):].strip()
            sg_id   = sg_rest.split("[")[0].strip()   # "rec", "o1", "o2" …
            body: list[str] = []
            i += 1
            depth = 1
            while i < len(lines) and depth > 0:
                l = lines[i].strip()
                if l.startswith("subgraph "):
                    depth += 1
                elif l == "end":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                if depth > 0:
                    body.append(lines[i])
                i += 1
            subgraphs.append((sg_id, sg_rest, body))
        else:
            i += 1

    if not subgraphs:
        return [mmd_path]   # nothing to split — return original

    stem       = Path(mmd_path).stem          # arc_SCRUM-5_20260410_19_flow
    run_prefix = stem[:-5] if stem.endswith("_flow") else stem
    out_dir    = Path(mmd_path).parent

    out_paths: list[str] = []
    for sg_id, sg_header, body in subgraphs:
        is_rec  = sg_id == "rec" or "recommended" in sg_header.lower()
        m       = _re.search(r"Option\s+(\d+)", sg_header, _re.IGNORECASE)
        opt_num = m.group(1) if m else sg_id.lstrip("o") or "?"
        suffix  = f"_flow_option{opt_num}_recommended" if is_rec else f"_flow_option{opt_num}"

        out_lines: list[str] = []
        if header_comment:
            out_lines.append(header_comment)
        out_lines.append("flowchart LR")
        out_lines.append("")
        for bl in body:
            if bl.strip() in ("direction LR", "direction TB", "direction RL", "direction BT"):
                continue
            out_lines.append(bl)

        out_path = str(out_dir / f"{run_prefix}{suffix}.mmd")
        Path(out_path).write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        out_paths.append(out_path)

    return out_paths


def _push_to_git(output_dir: Path, commit_label: str) -> dict:
    """
    Push output_dir contents to git — mirrors _push_output_to_git() in test scripts.
    Returns a status dict included in the API response.
    Non-fatal: returns {"skipped": True} or {"pushed": False, "error": ...} instead of raising.
    Requires GIT_BRANCH_URL and GIT_PAT environment variables.
    """
    branch_url = os.getenv("GIT_BRANCH_URL")
    pat        = os.getenv("GIT_PAT")

    if not branch_url or not pat:
        return {"skipped": True, "reason": "GIT_BRANCH_URL or GIT_PAT not set"}

    if not output_dir.exists():
        return {"skipped": True, "reason": f"Output directory not found: {output_dir}"}

    try:
        from core.utilities.versioning_tools.git_manager import GitRepoManager

        git = GitRepoManager(branch_url=branch_url, pat=pat, local_path=str(_REPO_ROOT))
        git.connect()

        stash = subprocess.run(
            ["git", "stash", "--include-untracked", "--quiet"],
            cwd=str(_REPO_ROOT), capture_output=True, text=True,
        )
        stashed = stash.returncode == 0 and "No local changes" not in stash.stdout

        try:
            git.pull()
        finally:
            if stashed:
                subprocess.run(["git", "stash", "pop", "--quiet"], cwd=str(_REPO_ROOT), check=False)

        subprocess.run(["git", "add", str(output_dir)], cwd=str(_REPO_ROOT), check=True)
        git.commit(commit_label, add_all=False)
        git.push()
        return {"pushed": True, "branch": git.target_branch, "commit": commit_label}
    except Exception as e:
        return {"pushed": False, "error": str(e)}


def _log_outputs(
    identifier: str,
    agent: str,
    request_type: str,
    output_dir: Path,
    glob_pattern: str,
) -> None:
    """
    Write one AGENT_OUTPUT_METADATA row per output file — mirrors what each
    test_*.py does via log_agent_op() after a successful agent run.
    Non-fatal: prints a warning if the DB is unreachable so the API response
    still succeeds.
    """
    from core.utilities.db_tools.agent_output_metadata import log_agent_op
    meta_path = str(output_dir.relative_to(_REPO_ROOT.parent))
    for fpath in output_dir.glob(glob_pattern):
        log_agent_op(
            identifier=identifier,
            agent=agent,
            artifact="API",
            request_type=request_type,
            filename=fpath.name,
            path=meta_path,
        )


def _load_from_metadata(ticket_id: str, agent_name: str) -> dict:
    """
    Look up the latest JSON output for a ticket from the metadata DB
    and return its parsed contents. Mirrors --ticket in the CLI scripts.
    Raises HTTP 404 if no record exists (agent hasn't been run yet).
    Raises HTTP 500 on DB connection or any other metadata error.
    """
    from core.utilities.db_tools.agent_output_metadata import get_latest_output
    try:
        path = get_latest_output(ticket_id, agent_name, "JSON", _REPO_ROOT)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Metadata DB error looking up {agent_name} for {ticket_id!r}: {e}",
        )
    return json.loads(path.read_text(encoding="utf-8"))


# ── Lazy agent imports (server starts even if one agent has missing deps) ──────

def _import_requirements():
    from gathering.agent import RequirementsAgent, RequirementsRejected
    return RequirementsAgent, RequirementsRejected

def _import_data_model():
    from data_model import DataModelAgent
    return DataModelAgent

def _import_architecture():
    from agent import ArchitectureAgent  # architecture/agent.py
    return ArchitectureAgent

def _import_impl_steps():
    from implementation_steps.agent import ImplStepsAgent
    return ImplStepsAgent


# ── Agent configs (mirrors each test script's CONFIG dict) ────────────────────

def _req_config(write_back: bool = False) -> dict:
    return {
        "model":              os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        "jira_base_url":      os.getenv("JIRA_BASE_URL", "https://prodapt-deah.atlassian.net"),
        "jira_email":         os.getenv("JIRA_EMAIL", ""),
        "jira_api_key":       os.getenv("JIRA_API_KEY", ""),
        "write_back_to_jira": write_back,
        "confidence_threshold": 0.6,
    }

def _dm_config() -> dict:
    return {
        "model":       os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        "output_root": str(_AGENTS_DIR / "data_model" / "output"),
    }

def _arch_config() -> dict:
    return {
        "model": {
            "model_id":    os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
            "max_tokens":  16000,
            "temperature": 0.0,
        },
        "confidence_threshold": 0.7,
        "paths": {
            "output_dir": str(_AGENTS_DIR / "architecture" / "outputs"),
        },
    }

def _impl_config() -> dict:
    return {
        "model":       os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        "output_root": str(_AGENTS_DIR / "implementation_steps" / "output"),
    }


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="DEAH Design Agents API",
    version="1.0.0",
    description=(
        "HTTP wrappers for the four design agents. "
        "Each endpoint accepts either a ticket_id (auto-resolves the latest output "
        "from the metadata DB, same as --ticket in the CLI) or explicit file paths "
        "relative to `core/design/agents/` (same as --input/--requirements in the CLI)."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request models ────────────────────────────────────────────────────────────

class JiraRequest(BaseModel):
    ticket_id: str
    write_back: bool = False

    model_config = {"json_schema_extra": {"example": {"ticket_id": "SCRUM-5", "write_back": False}}}

class DocumentRequest(BaseModel):
    """document_path relative to agents/ (or absolute)."""
    document_path: str

    model_config = {"json_schema_extra": {"example": {
        "document_path": "requirements_gathering/requirements_template.txt"
    }}}

class DataModelRequest(BaseModel):
    """Accepts ticket_id — auto-resolves latest Requirements JSON from metadata DB."""
    ticket_id: str
    schema_path: Optional[str] = None

    model_config = {"json_schema_extra": {"example": {
        "ticket_id": "SCRUM-5",
        "schema_path": "data_model/sample_input/table_schema.csv",
    }}}

class ArchitectureRequest(BaseModel):
    """Accepts ticket_id — auto-resolves latest Requirements JSON from metadata DB."""
    ticket_id: str

    model_config = {"json_schema_extra": {"example": {
        "ticket_id": "SCRUM-5",
    }}}

class ImplStepsRequest(BaseModel):
    """Accepts ticket_id — auto-resolves request_type, project_name, and all input JSONs."""
    ticket_id: str

    model_config = {"json_schema_extra": {"example": {
        "ticket_id": "SCRUM-5",
    }}}

class PipelineRequest(BaseModel):
    """Accepts ticket_id — auto-resolves Requirements JSON and derives all inputs."""
    ticket_id: str
    schema_path: Optional[str] = None

    model_config = {"json_schema_extra": {"example": {
        "ticket_id": "SCRUM-5",
        "schema_path": "data_model/sample_input/table_schema.csv",
    }}}


# ── 1. Requirements Gathering ─────────────────────────────────────────────────

@app.post("/requirements/from-jira", tags=["Requirement Agent"])
def requirements_from_jira(req: JiraRequest):
    """
    CLI equivalent:
        py requirements_gathering/test_requirements.py --source jira --ticket SCRUM-5 [--write-back]

    Returns the extracted requirements JSON and the path where it was saved.
    """
    RequirementsAgent, RequirementsRejected = _import_requirements()
    agent = RequirementsAgent(_req_config(req.write_back))
    try:
        result = agent.run_from_jira(req.ticket_id)
    except RequirementsRejected as e:
        raise HTTPException(
            status_code=400,
            detail={"missing_fields": e.missing_fields, "message": e.message},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Save output (same as test_requirements.py)
    from datetime import datetime, timezone
    run_id    = datetime.now(timezone.utc).strftime("%Y%m%d_%H")
    out_dir   = _AGENTS_DIR / "requirements_gathering" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix    = out_dir / f"req_{req.ticket_id}_{run_id}"
    json_path = prefix.with_suffix(".json")
    md_path   = prefix.with_suffix(".md")
    data      = result.to_dict()
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    md_path.write_text(result.to_markdown(), encoding="utf-8")

    _log_outputs(req.ticket_id, "Requirements", data.get("request_type", ""), out_dir, f"req_{req.ticket_id}_{run_id}*")
    git = _push_to_git(out_dir, f"[Requirements] {data.get('project_name', req.ticket_id)} | {data.get('request_type', '')} | outputs")

    return {"output_path": str(json_path), "markdown_path": str(md_path), "result": data, "git": git}


@app.post("/requirements/from-document", tags=["Requirement Agent"])
def requirements_from_document(req: DocumentRequest):
    """
    CLI equivalent:
        py requirements_gathering/test_requirements.py --source document --file path/to/file.txt
    """
    resolved_path = _resolve(req.document_path)
    if not resolved_path.exists():
        raise HTTPException(status_code=400, detail=f"Document not found: {resolved_path}")

    RequirementsAgent, RequirementsRejected = _import_requirements()
    agent = RequirementsAgent(_req_config())
    try:
        result = agent.run_from_document(str(resolved_path))
    except RequirementsRejected as e:
        raise HTTPException(
            status_code=400,
            detail={"missing_fields": e.missing_fields, "message": e.message},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    from datetime import datetime, timezone
    run_id    = datetime.now(timezone.utc).strftime("%Y%m%d_%H")
    out_dir   = _AGENTS_DIR / "requirements_gathering" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    file_stem = resolved_path.stem
    prefix    = out_dir / f"req_{file_stem}_{run_id}"
    json_path = prefix.with_suffix(".json")
    md_path   = prefix.with_suffix(".md")
    data      = result.to_dict()
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    md_path.write_text(result.to_markdown(), encoding="utf-8")

    _log_outputs(file_stem, "Requirements", data.get("request_type", ""), out_dir, f"req_{file_stem}_{run_id}*")
    git = _push_to_git(out_dir, f"[Requirements] {data.get('project_name', file_stem)} | {data.get('request_type', '')} | outputs")

    return {"output_path": str(json_path), "markdown_path": str(md_path), "result": data, "git": git}


# ── 2. Data Model ─────────────────────────────────────────────────────────────

@app.post("/data-model", tags=["Data-model Agent"])
def run_data_model(req: DataModelRequest):
    """
    CLI equivalents:
        py data_model/test_data_model.py --ticket SCRUM-5 [--schema data_model/sample_input/table_schema.csv]
    ticket_id → auto-resolves latest Requirements JSON from metadata DB.
    """
    requirements = _load_from_metadata(req.ticket_id, "Requirements")

    schema_path = str(_resolve(req.schema_path)) if req.schema_path else None

    DataModelAgent = _import_data_model()
    agent = DataModelAgent(_dm_config())
    try:
        output = agent.run(requirements=requirements, schema_csv=schema_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Glob the three output files the agent already wrote inside run():
    #   model_*_summary.json  — summary for downstream agents (pass to /implementation-steps)
    #   model_*_er_diagram.mmd — Mermaid ER diagram
    #   model_*_mapping.csv    — source→target column mapping
    dm_output_dir = Path(_dm_config()["output_root"])
    identifier    = requirements.get("ticket_id") or "unknown"
    from datetime import datetime, timezone
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H")
    _log_outputs(identifier, "DataModel", requirements.get("request_type", ""), dm_output_dir, f"model_{identifier}_{run_id}*")
    git = _push_to_git(dm_output_dir, f"[DataModel] {requirements.get('project_name', identifier)} | {requirements.get('request_type', '')} | outputs")

    summary_path  = _glob_latest(str(dm_output_dir / "model_*_summary.json"))
    er_path       = _glob_latest(str(dm_output_dir / "model_*_er_diagram.mmd"))
    mapping_path  = _glob_latest(str(dm_output_dir / "model_*_mapping.csv"))

    return {
        "output_files": {
            "summary_json":   summary_path,
            "er_diagram_mmd": er_path,
            "mapping_csv":    mapping_path,
        },
        "handoff_summary":       output.summary,
        "source_target_mapping": output.mapping,
        "er_mermaid_diagram":    output.er_diagram,
        "git":                   git,
    }


# ── 3. Architecture ───────────────────────────────────────────────────────────

@app.post("/architecture", tags=["Architecture Agent"])
def run_architecture(req: ArchitectureRequest):
    """
    CLI equivalents:
        py architecture/test_architecture.py --ticket SCRUM-5

    ticket_id → auto-resolves latest Requirements JSON from metadata DB.
    """
    requirements = _load_from_metadata(req.ticket_id, "Requirements")

    ArchitectureAgent = _import_architecture()
    agent = ArchitectureAgent(_arch_config())
    try:
        result = agent.run(requirements)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "Architecture agent failed")

    # Glob the three output files the agent already wrote:
    #   arc_*_summary.json  — handoff for impl steps  (pass to /implementation-steps)
    #   arc_*_report.md     — full narrative report
    #   arc_*_flow.mmd      — Mermaid architecture diagram
    arch_output_dir = _AGENTS_DIR / "architecture" / "outputs"
    identifier      = requirements.get("ticket_id") or "unknown"
    from datetime import datetime, timezone
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H")
    _log_outputs(identifier, "Architecture", requirements.get("request_type", ""), arch_output_dir, f"arc_{identifier}_{run_id}*")
    git = _push_to_git(arch_output_dir, f"[Architecture] {requirements.get('project_name', identifier)} | {requirements.get('request_type', '')} | outputs")

    summary_path    = _glob_latest(str(arch_output_dir / "arc_*_summary.json"))
    report_path     = _glob_latest(str(arch_output_dir / "arc_*_report.md"))
    flow_path       = _glob_latest(str(arch_output_dir / "arc_*_flow.mmd"))

    return {
        "run_id":  result.run_id,
        "skipped": result.skipped,
        "output_files": {
            "summary_json": summary_path,
            "report_md":    report_path,
            "flow_mmd":     flow_path,
        },
        "handoff_summary":  result.handoff_summary,
        "manifest_summary": result.manifest,
        "git":              git,
    }


# ── 4. Implementation Steps ───────────────────────────────────────────────────

@app.post("/implementation-steps", tags=["Implementation-steps Agent"])
def run_implementation_steps(req: ImplStepsRequest):
    """
    CLI equivalent:
        py implementation_steps/test_impl_steps.py --ticket SCRUM-5

    ticket_id → auto-resolves request_type, project_name, and all input JSONs
                from the metadata DB.
    """
    req_data     = _load_from_metadata(req.ticket_id, "Requirements")
    request_type = req_data.get("request_type", "new development")
    project_name = req_data.get("project_name", req.ticket_id)

    if request_type in ("new development", "enhancement"):
        architecture_summary = _load_from_metadata(req.ticket_id, "Architecture")
        data_model_summary   = _load_from_metadata(req.ticket_id, "DataModel") if request_type == "new development" else None
        requirements_summary = None
    else:  # bug
        requirements_summary = req_data
        architecture_summary = None
        data_model_summary   = None

    ImplStepsAgent = _import_impl_steps()
    agent = ImplStepsAgent(_impl_config())
    try:
        output = agent.run(
            request_type=request_type,
            project_name=project_name,
            requirements_summary=requirements_summary,
            architecture_summary=architecture_summary,
            data_model_summary=data_model_summary,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    identifier = req.ticket_id
    _log_outputs(identifier, "ImplSteps", request_type, output.output_path.parent, output.output_path.name)
    git = _push_to_git(output.output_path.parent, f"[ImplSteps] {project_name} | {request_type} | outputs")

    return {
        "project_name": output.project_name,
        "request_type": output.request_type,
        "output_path":  str(output.output_path),
        "markdown":     output.markdown,
        "git":          git,
    }


# ── 5. Full Pipeline ──────────────────────────────────────────────────────────

@app.post("/pipeline", tags=["pipeline orchestration"])
def run_pipeline(req: PipelineRequest):
    """
    CLI equivalent (orchestrator.py):
        py orchestration/orchestrator.py --ticket SCRUM-5 [--schema <path>]

    ticket_id → auto-resolves Requirements JSON and derives request_type + project_name.
    Runs data_model + architecture then implementation_steps in sequence.
    """
    requirements = _load_from_metadata(req.ticket_id, "Requirements")
    request_type = requirements.get("request_type", "new development")
    project_name = requirements.get("project_name", req.ticket_id)

    schema_path = str(_resolve(req.schema_path)) if req.schema_path else None

    from datetime import datetime, timezone
    pipe_run_id   = datetime.now(timezone.utc).strftime("%Y%m%d_%H")
    pipe_id       = requirements.get("ticket_id") or "unknown"
    pipe_req_type = requirements.get("request_type", "")

    dm_result     = None
    arch_result   = None
    drawio_result = None
    dm_path       = None
    arch_path     = None
    dm_git        = None
    arch_git      = None

    # ── Step 1: data_model + architecture (skipped for bug) ───────────────────
    if request_type in ("new development", "enhancement"):

        # Data Model
        dm_git = None
        try:
            DataModelAgent = _import_data_model()
            dm_output = DataModelAgent(_dm_config()).run(requirements, schema_path)
            dm_result = dm_output.summary
            _log_outputs(pipe_id, "DataModel", pipe_req_type, dm_output.output_dir, f"model_{pipe_id}_{pipe_run_id}*")
            dm_git  = _push_to_git(dm_output.output_dir, f"[DataModel] {project_name} | {pipe_req_type} | outputs")
            dm_path = _glob_latest(str(_AGENTS_DIR / "data_model" / "output" / "model_*_summary.json"))
        except Exception as e:
            dm_result = {"error": str(e)}
        time.sleep(15)

        # Architecture
        arch_git = None
        try:
            ArchitectureAgent = _import_architecture()
            arch_output = ArchitectureAgent(_arch_config()).run(requirements)
            if arch_output.skipped:
                arch_result = {"skipped": True, "reason": arch_output.skip_reason}
            elif arch_output.success:
                arch_result = arch_output.handoff_summary
                _log_outputs(pipe_id, "Architecture", pipe_req_type, _AGENTS_DIR / "architecture" / "outputs", f"arc_{pipe_id}_{pipe_run_id}*")
                arch_git  = _push_to_git(_AGENTS_DIR / "architecture" / "outputs", f"[Architecture] {project_name} | {pipe_req_type} | outputs")
                arch_path = _glob_latest(str(_AGENTS_DIR / "architecture" / "outputs" / "arc_*_summary.json"))
            else:
                arch_result = {"error": arch_output.error}
        except Exception as e:
            arch_result = {"error": str(e)}
        time.sleep(15)

        # mermaid2drawio — converts current run's .mmd files to .drawio
        drawio_result = None
        try:
            pkg_dir    = _AGENTS_DIR / "mermaid2drawio-converter"
            drawio_dir = pkg_dir / "drawio_output"
            arch_mmd_combined = _glob_latest(str(_AGENTS_DIR / "architecture" / "outputs" / "arc_*_flow.mmd"))
            arch_mmds  = _split_arch_mmd(arch_mmd_combined) if arch_mmd_combined else []
            dm_mmd     = _glob_latest(str(_AGENTS_DIR / "data_model" / "output" / "model_*_er_diagram.mmd"))
            drawio_dir.mkdir(parents=True, exist_ok=True)
            drawio_files = []
            mmd_tasks = [(f"architecture_option{i+1}", m) for i, m in enumerate(arch_mmds)]
            if dm_mmd:
                mmd_tasks.append(("data_model", dm_mmd))
            for label, mmd_path in mmd_tasks:
                out_file = str(drawio_dir / (Path(mmd_path).stem + ".drawio"))
                out = subprocess.run(
                    [sys.executable, "-m", "mermaid2drawio.cli", "--file", mmd_path,
                     "--output", out_file, "-v"],
                    cwd=str(pkg_dir), capture_output=True, text=True,
                )
                if out.returncode == 0:
                    drawio_files.append(out_file)
                else:
                    raise RuntimeError(f"mermaid2drawio ({label}) failed: {out.stderr.strip()}")
            for m in arch_mmds:
                Path(m).unlink(missing_ok=True)
            _log_outputs(pipe_id, "DrawIO", pipe_req_type, drawio_dir, f"*{pipe_id}_{pipe_run_id}*.drawio")
            drawio_git    = _push_to_git(drawio_dir, f"[DrawIO] {project_name} | {request_type} | outputs")
            drawio_result = {"drawio_files": drawio_files, "git": drawio_git}
        except Exception as e:
            drawio_result = {"error": str(e)}
        time.sleep(15)

    # ── Step 2: implementation_steps ─────────────────────────────────────────
    impl_result = None
    try:
        arch_summary = json.loads(Path(arch_path).read_text()) if arch_path else None
        dm_summary   = json.loads(Path(dm_path).read_text())   if dm_path   else None
        req_summary  = requirements if request_type == "bug" else None

        ImplStepsAgent = _import_impl_steps()
        impl_output = ImplStepsAgent(_impl_config()).run(
            request_type=request_type,
            project_name=project_name,
            requirements_summary=req_summary,
            architecture_summary=arch_summary,
            data_model_summary=dm_summary,
        )
        _log_outputs(pipe_id, "ImplSteps", request_type, impl_output.output_path.parent, impl_output.output_path.name)
        impl_git    = _push_to_git(impl_output.output_path.parent, f"[ImplSteps] {project_name} | {request_type} | outputs")
        impl_result = {
            "output_path": str(impl_output.output_path),
            "markdown":    impl_output.markdown,
            "git":         impl_git,
        }
    except Exception as e:
        impl_result = {"error": str(e)}

    return {
        "data_model_path":      dm_path,
        "architecture_path":    arch_path,
        "data_model":           dm_result,
        "architecture":         arch_result,
        "mermaid2drawio":       drawio_result,
        "implementation_steps": impl_result,
        "git": {
            "data_model":           dm_git,
            "architecture":         arch_git,
            "mermaid2drawio":       drawio_result.get("git") if isinstance(drawio_result, dict) else None,
            "implementation_steps": impl_result.get("git") if isinstance(impl_result, dict) else None,
        },
    }


# ── 6. List output files ──────────────────────────────────────────────────────

@app.get("/outputs", tags=["utilities"])
def list_outputs():
    """List all output files produced by the agents (newest first)."""
    def collect(pattern: str) -> list[str]:
        return sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)

    dm     = _AGENTS_DIR / "data_model/output"
    arc    = _AGENTS_DIR / "architecture/outputs"
    imp    = _AGENTS_DIR / "implementation_steps/output"
    req    = _AGENTS_DIR / "requirements_gathering/output"
    drawio = _AGENTS_DIR / "mermaid2drawio-converter/drawio_output"

    return {
        "requirements": {
            "json": collect(str(req / "req_*.json")),
            "markdown": collect(str(req / "req_*.md")),
        },
        "data_model": {
            "summary_json":   collect(str(dm  / "model_*_summary.json")),
            "er_diagram_mmd": collect(str(dm  / "model_*_er_diagram.mmd")),
            "mapping_csv":    collect(str(dm  / "model_*_mapping.csv")),
        },
        "architecture": {
            "summary_json": collect(str(arc / "arc_*_summary.json")),
            "report_md":    collect(str(arc / "arc_*_report.md")),
            "flow_mmd":     collect(str(arc / "arc_*_flow.mmd")),
        },
        "mermaid2drawio": collect(str(drawio / "*.drawio")),
        "implementation_steps": collect(str(imp / "*.md")),
    }
