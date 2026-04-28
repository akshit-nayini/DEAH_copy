"""
orchestrator.py — Runs the DE design pipeline by executing each agent's test script.

Routing (ticket mode — requirements must be run separately first):
    new development  →  data_model → architecture → mermaid2drawio → implementation_steps
    enhancement      →  data_model → architecture → mermaid2drawio → implementation_steps
    bug              →  implementation_steps only

Routing (manual mode):
    new development  →  data_model → architecture → mermaid2drawio → implementation_steps
    enhancement      →  data_model → architecture → mermaid2drawio → implementation_steps
    bug              →  implementation_steps only

Usage:
    # Ticket mode — looks up existing requirements output from metadata DB
    #               (run test_requirements.py --ticket SCRUM-5 first)
    python orchestration/orchestrator.py --ticket SCRUM-5
    python orchestration/orchestrator.py --ticket SCRUM-5 --schema data_model/sample_input/table_schema.csv

    # Manual mode — provide all inputs explicitly
    python orchestration/orchestrator.py \\
        --type "new development" \\
        --project "Customer 360 Data Platform" \\
        --requirements output/requirements.json \\
        --schema data_model/sample_input/table_schema.csv

Env vars required:
    ANTHROPIC_API_KEY   — Anthropic API key
    JIRA_EMAIL          — Jira account email
    JIRA_API_KEY        — Jira API token
    GIT_BRANCH_URL      — Git branch URL for pushing outputs
    GIT_PAT             — Git personal access token
    DB_HOST / DB_USER / DB_PASSWORD / DB_NAME — metadata DB connection
"""

import json
import subprocess
import sys
import glob
import os
import time
from pathlib import Path

ROOT      = Path(__file__).resolve().parent.parent   # agents/
REPO_ROOT = Path(__file__).resolve().parents[4]      # DEAH/
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.utilities.db_tools.agent_output_metadata import get_latest_output

# Where each agent writes its output files
ARCH_OUTPUT_DIR    = ROOT / "architecture/outputs"
DM_OUTPUT_DIR      = ROOT / "data_model/output"
DRAWIO_OUTPUT_DIR  = ROOT / "mermaid2drawio-converter/drawio_output"

_MAX_RETRIES  = 3
_BACKOFF_BASE = 5   # seconds — gives Anthropic API time to recover from 529
_AGENT_GAP    = 15  # seconds to wait between agents so each git push fully settles


def _run_with_retry(cmd: list, label: str) -> None:
    """Run a subprocess, retrying on non-zero exit with exponential backoff."""
    for attempt in range(_MAX_RETRIES):
        try:
            subprocess.run(cmd, check=True)
            return
        except subprocess.CalledProcessError as exc:
            if attempt < _MAX_RETRIES - 1:
                wait = _BACKOFF_BASE * (2 ** attempt)
                print(f"[orchestrator] {label} failed (exit {exc.returncode}) — "
                      f"retrying in {wait}s (attempt {attempt + 1}/{_MAX_RETRIES})")
                time.sleep(wait)
            else:
                print(f"[orchestrator] {label} failed after {_MAX_RETRIES} attempts.")
                raise


# ─────────────────────────────────────────────
# Routing
# ─────────────────────────────────────────────

ROUTING = {
    "new development": ["data_model", "architecture", "mermaid2drawio", "implementation_steps"],
    "enhancement":     ["data_model", "architecture", "mermaid2drawio", "implementation_steps"],
    "bug":             ["implementation_steps"],
}


# ─────────────────────────────────────────────
# Command runners
# ─────────────────────────────────────────────

def run_requirements(ticket: str):
    cmd = [
        sys.executable,
        str(ROOT / "requirements_gathering/test_requirements.py"),
        "--ticket", ticket,
    ]
    _run_with_retry(cmd, "requirements")


def run_data_model(requirements: str = None, schema: str = None, ticket: str = None):
    cmd = [sys.executable, str(ROOT / "data_model/test_data_model.py")]
    if ticket:
        cmd += ["--ticket", ticket]
    else:
        cmd += ["--requirements", requirements]
    if schema:
        cmd += ["--schema", schema]
    _run_with_retry(cmd, "data_model")


def run_architecture(requirements: str = None, ticket: str = None):
    cmd = [sys.executable, str(ROOT / "architecture/test_architecture.py")]
    if ticket:
        cmd += ["--ticket", ticket]
    else:
        cmd += ["--input", requirements]
    _run_with_retry(cmd, "architecture")


def run_implementation_steps(request_type: str = None, project: str = None,
                              architecture: str = None, data_model: str = None,
                              requirements: str = None, ticket: str = None):
    cmd = [sys.executable, str(ROOT / "implementation_steps/test_impl_steps.py")]
    if ticket:
        cmd += ["--ticket", ticket]
    else:
        cmd += ["--type", request_type, "--project", project]
        if architecture:
            cmd += ["--architecture", architecture]
        if data_model:
            cmd += ["--data-model", data_model]
        if requirements:
            cmd += ["--requirements", requirements]
    _run_with_retry(cmd, "implementation_steps")


def _split_arch_mmd(mmd_path: str) -> list:
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

    subgraphs = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("subgraph "):
            sg_rest = stripped[len("subgraph "):].strip()
            sg_id   = sg_rest.split("[")[0].strip()
            body = []
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
        return [mmd_path]

    stem       = Path(mmd_path).stem
    run_prefix = stem[:-5] if stem.endswith("_flow") else stem
    out_dir    = Path(mmd_path).parent

    out_paths = []
    for sg_id, sg_header, body in subgraphs:
        is_rec  = sg_id == "rec" or "recommended" in sg_header.lower()
        m       = _re.search(r"Option\s+(\d+)", sg_header, _re.IGNORECASE)
        opt_num = m.group(1) if m else sg_id.lstrip("o") or "?"
        suffix  = f"_flow_option{opt_num}_recommended" if is_rec else f"_flow_option{opt_num}"

        out_lines = []
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


def run_mermaid2drawio(arch_mmds: list = None, dm_mmd: str = None, output: str = None):
    """
    Run the mermaid2drawio converter agent via its CLI module.

    Invokes:  python -m mermaid2drawio.cli --file <specific.mmd> --output <dir>

    Uses --file mode so only the current run's .mmd files are converted,
    not all historical files in the output directory.
    arch_mmds is a list of per-option .mmd paths produced by _split_arch_mmd().
    """
    pkg_dir    = ROOT / "mermaid2drawio-converter"
    output_dir = output or str(DRAWIO_OUTPUT_DIR)

    files = []
    for i, m in enumerate(arch_mmds or []):
        files.append((f"architecture_option{i+1}", m))
    if dm_mmd:
        files.append(("data_model", dm_mmd))

    if not files:
        print("[mermaid2drawio] No .mmd files provided — skipping.")
        return

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    for label, mmd_path in files:
        out_file = str(Path(output_dir) / (Path(mmd_path).stem + ".drawio"))
        cmd = [
            sys.executable, "-m", "mermaid2drawio.cli",
            "--file", mmd_path,
            "--output", out_file,
            "-v",
        ]
        print(f"\n[orchestrator] Running mermaid2drawio on {label}: {mmd_path}")
        for attempt in range(_MAX_RETRIES):
            try:
                subprocess.run(cmd, check=True, cwd=str(pkg_dir))
                break
            except subprocess.CalledProcessError as exc:
                if attempt < _MAX_RETRIES - 1:
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    print(f"[orchestrator] mermaid2drawio ({label}) failed "
                          f"(exit {exc.returncode}) — retrying in {wait}s "
                          f"(attempt {attempt + 1}/{_MAX_RETRIES})")
                    time.sleep(wait)
                else:
                    print(f"[orchestrator] mermaid2drawio ({label}) failed "
                          f"after {_MAX_RETRIES} attempts.")
                    raise

    # Delete per-option split .mmd files — only the combined arch .mmd is kept
    for label, mmd_path in files:
        if label.startswith("architecture_option"):
            Path(mmd_path).unlink(missing_ok=True)


def find_latest_arch_handoff() -> str:
    """Find the architecture summary JSON written by the most recent run."""
    matches = sorted(
        glob.glob(str(ARCH_OUTPUT_DIR / "arc_*_summary.json")),
        key=os.path.getmtime,
        reverse=True,
    )
    if not matches:
        raise FileNotFoundError(
            f"No architecture summary found in {ARCH_OUTPUT_DIR}. "
            "architecture agent may have failed."
        )
    return matches[0]


def find_latest_dm_summary() -> str:
    """Find the data_model summary JSON written by the most recent run."""
    matches = sorted(
        glob.glob(str(DM_OUTPUT_DIR / "model_*_summary.json")),
        key=os.path.getmtime,
        reverse=True,
    )
    if not matches:
        raise FileNotFoundError(
            f"No data_model summary found in {DM_OUTPUT_DIR}. "
            "data_model agent may have failed."
        )
    return matches[0]


def find_latest_arch_flow_mmd() -> str:
    """Find the architecture flow .mmd written by the most recent run."""
    matches = sorted(
        glob.glob(str(ARCH_OUTPUT_DIR / "arc_*_flow.mmd")),
        key=os.path.getmtime,
        reverse=True,
    )
    if not matches:
        raise FileNotFoundError(
            f"No architecture flow .mmd found in {ARCH_OUTPUT_DIR}. "
            "architecture agent may have failed."
        )
    return matches[0]


def find_latest_dm_er_mmd() -> str:
    """Find the data_model ER diagram .mmd written by the most recent run."""
    matches = sorted(
        glob.glob(str(DM_OUTPUT_DIR / "model_*_er_diagram.mmd")),
        key=os.path.getmtime,
        reverse=True,
    )
    if not matches:
        raise FileNotFoundError(
            f"No data_model ER diagram .mmd found in {DM_OUTPUT_DIR}. "
            "data_model agent may have failed."
        )
    return matches[0]


def find_latest_drawio_summary() -> str:
    """
    Find the most recently generated .drawio file in the mermaid2drawio
    output directory. Used to confirm the converter produced output.
    """
    matches = sorted(
        glob.glob(str(DRAWIO_OUTPUT_DIR / "*.drawio")),
        key=os.path.getmtime,
        reverse=True,
    )
    if not matches:
        raise FileNotFoundError(
            f"No .drawio files found in {DRAWIO_OUTPUT_DIR}. "
            "mermaid2drawio agent may have failed."
        )
    return matches[0]


# ─────────────────────────────────────────────
# Pipeline
# ─────────────────────────────────────────────

def run_pipeline_from_ticket(ticket: str, schema_csv: str = None):
    """Run the pipeline from metadata — requirements agent must have been run first."""

    # Determine routing from the requirements output already in metadata
    print(f"\nPipeline (ticket mode): {ticket}")
    req_json     = get_latest_output(ticket, "Requirements", "JSON", REPO_ROOT)
    req_data     = json.loads(req_json.read_text(encoding="utf-8"))
    request_type = req_data.get("request_type", "new development").lower()
    plan         = ROUTING.get(request_type, ROUTING["new development"])
    print(f"Route: {request_type}  →  {' → '.join(plan)}\n")

    # Step 1 — data_model (skipped for bug)
    if "data_model" in plan:
        run_data_model(ticket=ticket, schema=schema_csv)
        print(f"\n[orchestrator] Waiting {_AGENT_GAP}s for git push to settle …")
        time.sleep(_AGENT_GAP)

    # Step 2 — architecture (skipped for bug)
    if "architecture" in plan:
        run_architecture(ticket=ticket)
        print(f"\n[orchestrator] Waiting {_AGENT_GAP}s for git push to settle …")
        time.sleep(_AGENT_GAP)

    # Step 3 — mermaid2drawio (converts architecture + data_model .mmd → .drawio)
    if "mermaid2drawio" in plan:
        run_mermaid2drawio(
            arch_mmds=_split_arch_mmd(find_latest_arch_flow_mmd()),
            dm_mmd=find_latest_dm_er_mmd(),
        )
        print(f"\n[orchestrator] Waiting {_AGENT_GAP}s for git push to settle …")
        time.sleep(_AGENT_GAP)

    # Step 4 — implementation_steps
    if "implementation_steps" in plan:
        run_implementation_steps(ticket=ticket)

    print("\nPipeline complete.")


def run_pipeline(request_type: str, project: str,
                 requirements_json: str, schema_csv: str = None):

    plan = ROUTING.get(request_type, ROUTING["new development"])
    print(f"\nPipeline: {request_type}  →  {' → '.join(plan)}\n")

    dm_summary   = None
    arch_manifest = None

    # Step 1 — data_model (skipped for bug)
    if "data_model" in plan:
        run_data_model(requirements_json, schema_csv)
        dm_summary = find_latest_dm_summary()
        print(f"\n  data_model summary : {dm_summary}")
        print(f"\n[orchestrator] Waiting {_AGENT_GAP}s for git push to settle …")
        time.sleep(_AGENT_GAP)

    # Step 2 — architecture (skipped for bug)
    if "architecture" in plan:
        run_architecture(requirements_json)
        arch_manifest = find_latest_arch_handoff()
        print(f"\n  architecture manifest: {arch_manifest}")
        print(f"\n[orchestrator] Waiting {_AGENT_GAP}s for git push to settle …")
        time.sleep(_AGENT_GAP)

    # Step 3 — mermaid2drawio (converts architecture + data_model .mmd → .drawio)
    if "mermaid2drawio" in plan:
        run_mermaid2drawio(
            arch_mmds=_split_arch_mmd(find_latest_arch_flow_mmd()),
            dm_mmd=find_latest_dm_er_mmd(),
        )
        drawio_summary = find_latest_drawio_summary()
        print(f"\n  drawio summary: {drawio_summary}")
        print(f"\n[orchestrator] Waiting {_AGENT_GAP}s for git push to settle …")
        time.sleep(_AGENT_GAP)

    # Step 4 — implementation_steps (always last)
    if "implementation_steps" in plan:
        run_implementation_steps(
            request_type = request_type,
            project      = project,
            architecture = arch_manifest,
            data_model   = dm_summary,
            requirements = requirements_json if request_type == "bug" else None,
        )

    print("\nPipeline complete.")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    # Ticket mode — resolves everything automatically
    parser.add_argument("--ticket", help="Jira ticket ID — runs full pipeline automatically")
    # Manual mode
    parser.add_argument("--type",         choices=["new development", "enhancement", "bug"])
    parser.add_argument("--project",      help="Project name")
    parser.add_argument("--requirements", help="Path to requirements JSON")
    parser.add_argument("--schema",       default=None, help="Path to schema CSV (data_model)")
    args = parser.parse_args()

    if args.ticket:
        run_pipeline_from_ticket(ticket=args.ticket, schema_csv=args.schema)
    else:
        if not all([args.type, args.project, args.requirements]):
            parser.error("--type, --project, and --requirements are all required when --ticket is not provided")
        run_pipeline(
            request_type      = args.type,
            project           = args.project,
            requirements_json = args.requirements,
            schema_csv        = args.schema,
        )
