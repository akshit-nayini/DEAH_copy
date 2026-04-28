"""
routers/validator_router.py
----------------------------
Flask Blueprint for the Result Validator Agent UI.
Routes: /, /ping, /load-from-git, /validate, /export/csv, /export/excel
"""

from __future__ import annotations
import io
import math
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
from flask import Blueprint, Response, jsonify, request, send_file

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import VALIDATOR_OUTPUT_DIR, GITHUB_PAT
from agents.validator.agent import ValidatorAgent
from agents.validator.connectors import ValidatorConnector
from services.audit_service import AuditService
from services.git_service import GitService
from storage.local_storage import read_file

validator_bp = Blueprint("validator", __name__)

# In-memory store for last run
_last_results: list[dict] = []

# ── Git Processor state ────────────────────────────────────────────────────────
_gp_state: dict = {
    "running": False, "done": False,
    "logs": [], "returncode": None, "started_at": None,
}


def _run_gp_background(token: str, webhook: str, repo: str) -> None:
    from config import DEAH_ROOT
    gp_path = DEAH_ROOT / "core/testing/agents/git_processor/git_processor.py"
    env = {**os.environ, "GITHUB_TOKEN": token, "TEAMS_WEBHOOK_URL": webhook}
    try:
        proc = subprocess.Popen(
            [sys.executable, str(gp_path), "--repo", repo],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in proc.stdout:
            _gp_state["logs"].append(line.rstrip())
        proc.wait()
        _gp_state["returncode"] = proc.returncode
    except Exception as exc:
        _gp_state["logs"].append(f"ERROR starting git processor: {exc}")
        _gp_state["returncode"] = -1
    finally:
        _gp_state["running"] = False
        _gp_state["done"] = True

# ── Page HTML ─────────────────────────────────────────────────────────────────
_HTML_PATH = Path(__file__).parent.parent / "agents/validator/ui.html"


def _page() -> str:
    return _HTML_PATH.read_text(encoding="utf-8")


# ── Routes ────────────────────────────────────────────────────────────────────

@validator_bp.route("/")
def index():
    return Response(_page(), mimetype="text/html; charset=utf-8")


@validator_bp.route("/ping")
def ping():
    return jsonify({"ok": True})


@validator_bp.route("/load-from-git")
def load_from_git():
    try:
        connector = ValidatorConnector()
        data      = connector.load_latest()
        print(f"[ValidatorConnector] Loading from Git: {data['file_path']}")
        # Don't return records in this call — just metadata
        return jsonify({
            "filename":  data["filename"],
            "file_path": data["file_path"],
            "row_count": data["row_count"],
            "columns":   data["columns"],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@validator_bp.route("/validate", methods=["POST"])
def validate():
    global _last_results
    try:
        body     = request.get_json(force=True) or {}
        csv_path = body.get("csv_path", "")

        if not csv_path:
            return jsonify({"error": "csv_path is required."}), 400

        p = Path(csv_path)
        if not p.exists():
            return jsonify({"error": f"File not found: {csv_path}"}), 404

        df = read_file(p)
        required = {"tc_id", "query", "expected_result"}
        missing  = required - set(df.columns)
        if missing:
            return jsonify({"error": f"CSV missing columns: {missing}"}), 400

        # Replace pandas NaN with None so JSON serialization produces null (not NaN)
        records = df.where(pd.notnull(df), None).to_dict("records")

        mode         = (body.get("mode") or "synthetic").strip()
        icd_filename = (body.get("icd_filename") or "").strip()
        mysql_config = body.get("mysql_config") or None

        print(f"=== ValidatorAgent: starting BQ validation (mode={mode}) ===")
        agent    = ValidatorAgent()
        results  = agent.run(records, source_filename=p.name,
                             icd_filename=icd_filename, mode=mode,
                             mysql_config=mysql_config)
        _last_results = results

        # Sanitize: replace any float NaN that survived into results with None (→ JSON null)
        def _clean(v):
            return None if isinstance(v, float) and math.isnan(v) else v
        results_clean = [{k: _clean(v) for k, v in r.items()} for r in results]

        return jsonify({"results": results_clean})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@validator_bp.route("/save-to-git", methods=["POST"])
def save_to_git():
    """
    Commit and push the latest validation result files to Git.
    Body (optional): { "filename": "exact_stem.csv" }
    If filename is omitted, the most-recently-modified CSV+XLSX pair is used.
    """
    try:
        body     = request.get_json(force=True) or {}
        filename = (body.get("filename") or "").strip()

        if filename:
            stem      = Path(filename).stem
            csv_file  = VALIDATOR_OUTPUT_DIR / f"{stem}.csv"
            xlsx_file = VALIDATOR_OUTPUT_DIR / f"{stem}.xlsx"
        else:
            csvs = sorted(VALIDATOR_OUTPUT_DIR.glob("*.csv"),
                          key=lambda f: f.stat().st_mtime, reverse=True)
            if not csvs:
                return jsonify({"ok": False, "message": "No validation result files found to save."}), 400
            csv_file  = csvs[0]
            xlsx_file = csv_file.with_suffix(".xlsx")

        files_to_push = [f for f in [csv_file, xlsx_file] if f.exists()]
        if not files_to_push:
            return jsonify({"ok": False, "message": f"File not found: {csv_file.name}"}), 404

        commit_msg = f"feat(testing): add validation results — {csv_file.name}"
        git    = GitService()
        result = git.commit_and_push(files_to_push, commit_msg)
        status_code = 200 if result["ok"] else 500
        return jsonify(result), status_code

    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@validator_bp.route("/validate-pipeline", methods=["POST"])
def validate_pipeline():
    """
    Compare source data vs BQ target table for all tables in the ICD mapping.
    Body: { mode: 'synthetic'|'source_db', icd_filename: str, mysql_config?: dict }
    """
    try:
        from config import ICD_DIR
        from services.comparison_service import ComparisonService

        body         = request.get_json(force=True) or {}
        mode         = (body.get("mode") or "synthetic").strip()
        icd_filename = (body.get("icd_filename") or "").strip()
        mysql_config = body.get("mysql_config") or None

        if icd_filename:
            icd_path = ICD_DIR / icd_filename
        else:
            from agents.generator.connectors import _datehr_key
            candidates = sorted(ICD_DIR.glob("*.csv"), key=_datehr_key, reverse=True)
            if not candidates:
                return jsonify({"ok": False, "table_results": [],
                                "message": "No ICD mapping files found"}), 400
            icd_path = candidates[0]

        if not icd_path.exists():
            return jsonify({"ok": False, "table_results": [],
                            "message": f"ICD file not found: {icd_path.name}"}), 404

        result = ComparisonService().compare(str(icd_path), mode, mysql_config)
        return jsonify(result), 200 if result["ok"] else 500

    except Exception as e:
        return jsonify({"ok": False, "table_results": [],
                        "message": str(e)}), 500


@validator_bp.route("/git-processor/run", methods=["POST"])
def gp_run():
    """Start the git processor pipeline in a background thread."""
    if _gp_state["running"]:
        return jsonify({"ok": False, "message": "Git processor is already running."}), 409

    body = request.get_json(force=True) or {}
    # Priority: UI-supplied token → GITHUB_TOKEN env → GITHUB_PAT env/config
    token   = (body.get("token") or os.environ.get("GITHUB_TOKEN") or GITHUB_PAT or "").strip()
    webhook = (body.get("webhook") or os.environ.get("TEAMS_WEBHOOK_URL", "")).strip()
    repo    = (body.get("repo")    or os.environ.get("GIT_PROCESSOR_REPO", "ahemadshaik/DEAH"))

    if not token:
        return jsonify({"ok": False, "need_token": True,
                        "message": "No GitHub token found. Enter your PAT below."}), 400

    _gp_state.update({
        "running": True, "done": False, "logs": [],
        "returncode": None,
        "started_at": datetime.utcnow().isoformat() + "Z",
    })
    threading.Thread(
        target=_run_gp_background, args=(token, webhook, repo), daemon=True
    ).start()
    return jsonify({"ok": True, "message": "Git processor started."})


@validator_bp.route("/git-processor/status")
def gp_status():
    """Return current git processor state + accumulated log lines."""
    return jsonify(_gp_state)


@validator_bp.route("/audit/history")
def audit_history():
    """
    GET /audit/history?scrum_id=SCRUM-5&limit=50
    Returns recent validation runs (newest first) with pass-rate trend.
    """
    try:
        scrum_id = (request.args.get("scrum_id") or "").strip() or None
        limit    = int(request.args.get("limit", 50))
        svc      = AuditService()
        history  = svc.get_history(scrum_id=scrum_id, limit=limit)
        trend    = svc.get_trend(scrum_id=scrum_id, limit=limit)
        return jsonify({"history": history, "trend": trend})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@validator_bp.route("/audit/run/<run_id>")
def audit_run_detail(run_id: str):
    """GET /audit/run/<run_id> — all TC results for one run."""
    try:
        results = AuditService().get_run_detail(run_id)
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@validator_bp.route("/audit/compare")
def audit_compare():
    """
    GET /audit/compare?run_a=<id>&run_b=<id>
    Diff two runs — returns verdict changes per TC.
    """
    try:
        run_a = (request.args.get("run_a") or "").strip()
        run_b = (request.args.get("run_b") or "").strip()
        if not run_a or not run_b:
            return jsonify({"error": "run_a and run_b query params are required"}), 400
        diff = AuditService().compare_runs(run_a, run_b)
        return jsonify(diff)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@validator_bp.route("/export/csv")
def export_csv():
    csvs = sorted(VALIDATOR_OUTPUT_DIR.glob("*.csv"),
                  key=lambda f: f.stat().st_mtime, reverse=True)
    if not csvs:
        return "No validation results yet.", 400
    return send_file(str(csvs[0]), as_attachment=True,
                     download_name=csvs[0].name, mimetype="text/csv")


@validator_bp.route("/export/excel")
def export_excel():
    xlsxs = sorted(VALIDATOR_OUTPUT_DIR.glob("*.xlsx"),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    if not xlsxs:
        return "No validation results yet.", 400
    return send_file(str(xlsxs[0]), as_attachment=True,
                     download_name=xlsxs[0].name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
