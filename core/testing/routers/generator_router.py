"""
routers/generator_router.py
----------------------------
Flask Blueprint for the Test Case Generator UI.
Routes: /, /ping, /categories, /read-latest, /check-existing, /repurpose,
        /generate, /generate-cr, /generate-incremental,
        /save-to-git, /export/csv, /export/excel
"""

from __future__ import annotations
import sys
from pathlib import Path

import pandas as pd
from flask import Blueprint, Response, jsonify, request, send_file

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import LLM_PROVIDER, GENERATOR_OUTPUT_DIR
from agents.generator.agent import GeneratorAgent
from agents.generator.connectors import GeneratorConnector
from agents.generator.prompts import ALL_CATEGORIES, EDGE_CASE_CATEGORIES
from services.git_service import GitService

generator_bp = Blueprint("generator", __name__)

_HTML_PATH = Path(__file__).parent.parent / "agents/generator/ui.html"


def _page() -> str:
    return _HTML_PATH.read_text(encoding="utf-8")


def _latest_csv() -> str:
    csvs = sorted(GENERATOR_OUTPUT_DIR.glob("*.csv"),
                  key=lambda f: f.stat().st_mtime, reverse=True)
    return str(csvs[0]) if csvs else ""


# ── Routes ────────────────────────────────────────────────────────────────────

@generator_bp.route("/")
def index():
    return Response(_page(), mimetype="text/html; charset=utf-8")


@generator_bp.route("/ping")
def ping():
    from config import VALIDATOR_PORT
    return jsonify({"ok": True, "provider": LLM_PROVIDER, "validator_port": VALIDATOR_PORT})


@generator_bp.route("/categories")
def get_categories():
    """Return available validation categories for UI checkbox population."""
    return jsonify({
        "categories":           ALL_CATEGORIES,
        "edge_case_categories": EDGE_CASE_CATEGORIES,
    })


@generator_bp.route("/read-latest")
def read_latest():
    try:
        connector = GeneratorConnector()
        data      = connector.load_latest()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@generator_bp.route("/list-icd-files")
def list_icd_files():
    """
    Return all ICD CSV files available in the design pod output, newest first.
    Also returns source ICD info inferred from the latest test cases file.
    """
    try:
        connector = GeneratorConnector()
        files     = connector.list_icd_files()
        source    = connector.source_icd_info()   # may be None
        return jsonify({"files": files, "source_icd": source})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@generator_bp.route("/read-icd")
def read_icd():
    """
    Load a specific ICD file by filename query param.
    GET /read-icd?filename=model_SCRUM-42_20260413_09_mapping.csv
    """
    try:
        filename = request.args.get("filename", "").strip()
        if not filename:
            return jsonify({"error": "filename query parameter is required."}), 400
        connector = GeneratorConnector()
        data      = connector.load_by_filename(filename)
        return jsonify(data)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@generator_bp.route("/check-existing")
def check_existing():
    try:
        agent = GeneratorAgent()
        files = agent.existing_files()
        if not files:
            return jsonify({"exists": False, "files": []})
        return jsonify({
            "exists": True,
            "files": [
                {
                    "filename":  f.name,
                    "file_path": str(f),
                    "modified":  f.stat().st_mtime,
                    "row_count": sum(1 for _ in f.open()) - 1,
                }
                for f in files
            ],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@generator_bp.route("/repurpose")
def repurpose():
    try:
        agent  = GeneratorAgent()
        result = agent.load_existing()
        return jsonify({
            "test_cases": result["cases"],
            "csv_path":   result["csv_path"],
            "source":     "repurposed",
        })
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@generator_bp.route("/generate", methods=["POST"])
def generate():
    """
    New Project / Existing Project / Edge Cases generation.
    Body: {icd, ac, icd_filename?, mode?, categories?}
      mode: "new" (default) | "existing" | "edge"
    """
    try:
        body         = request.get_json(force=True) or {}
        icd          = (body.get("icd")          or "").strip()
        ac           = (body.get("ac")           or "").strip()
        icd_filename = (body.get("icd_filename") or "").strip() or None
        categories   = body.get("categories") or None   # list[str] | null
        mode         = (body.get("mode") or "new").strip().lower()

        if not icd or not ac:
            return jsonify({"error": "Both ICD and Acceptance Criteria are required."}), 400

        agent = GeneratorAgent()

        if mode == "edge":
            result = agent.run_edge_cases(icd, ac, icd_filename=icd_filename)
            return jsonify({
                "test_cases":      result["cases"],
                "source":          result["source"],
                "categories_used": result["categories"],
                "csv_path":        result["csv_path"],
            })

        if mode == "existing":
            result = agent.run_incremental(icd, ac, icd_filename=icd_filename,
                                           categories=categories)
            return jsonify(result)

        # mode == "new" (default)
        cases = agent.run(icd, ac, icd_filename=icd_filename, categories=categories)
        return jsonify({"test_cases": cases, "csv_path": _latest_csv()})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@generator_bp.route("/generate-cr", methods=["POST"])
def generate_cr():
    """
    Change Request mode.
    Body: {icd, ac, changed_columns: ["col1","col2",...], categories?: [...], icd_filename?}
    """
    try:
        body            = request.get_json(force=True) or {}
        icd             = (body.get("icd")          or "").strip()
        ac              = (body.get("ac")           or "").strip()
        changed_columns = body.get("changed_columns") or []
        categories      = body.get("categories")      or None
        icd_filename    = (body.get("icd_filename")  or "").strip() or None
        change_reason   = (body.get("change_reason") or "").strip()

        if not icd or not ac:
            return jsonify({"error": "ICD and Acceptance Criteria are required."}), 400
        if not changed_columns:
            return jsonify({"error": "changed_columns list is required for Change Request mode."}), 400

        agent  = GeneratorAgent()
        result = agent.run_change_request(
            icd, ac, changed_columns,
            categories=categories,
            icd_filename=icd_filename,
            change_reason=change_reason,
        )
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@generator_bp.route("/generate-incremental", methods=["POST"])
def generate_incremental():
    """Legacy endpoint — kept for backward compatibility. Proxies to /generate?mode=existing."""
    try:
        body         = request.get_json(force=True) or {}
        icd          = (body.get("icd")          or "").strip()
        ac           = (body.get("ac")           or "").strip()
        icd_filename = (body.get("icd_filename") or "").strip() or None
        categories   = body.get("categories") or None

        if not icd or not ac:
            return jsonify({"error": "Both ICD and Acceptance Criteria are required."}), 400

        agent  = GeneratorAgent()
        result = agent.run_incremental(icd, ac, icd_filename=icd_filename,
                                       categories=categories)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@generator_bp.route("/save-to-git", methods=["POST"])
def save_to_git():
    """
    Commit and push the latest generated test-case files to Git.
    Body (optional): { "filename": "exact_stem.csv" }
    If filename is omitted, the most-recently-modified CSV+XLSX pair is used.
    """
    try:
        body     = request.get_json(force=True) or {}
        filename = (body.get("filename") or "").strip()

        if filename:
            # Find the specific file pair by stem
            stem = Path(filename).stem
            csv_file  = GENERATOR_OUTPUT_DIR / f"{stem}.csv"
            xlsx_file = GENERATOR_OUTPUT_DIR / f"{stem}.xlsx"
        else:
            # Use the most recent CSV and its paired XLSX
            csvs = sorted(GENERATOR_OUTPUT_DIR.glob("*.csv"),
                          key=lambda f: f.stat().st_mtime, reverse=True)
            if not csvs:
                return jsonify({"ok": False, "message": "No test case files found to save."}), 400
            csv_file  = csvs[0]
            xlsx_file = csv_file.with_suffix(".xlsx")

        files_to_push = [f for f in [csv_file, xlsx_file] if f.exists()]
        if not files_to_push:
            return jsonify({"ok": False, "message": f"File not found: {csv_file.name}"}), 404

        commit_msg = f"feat(testing): add generated test cases — {csv_file.name}"
        git = GitService()
        result = git.commit_and_push(files_to_push, commit_msg)
        status_code = 200 if result["ok"] else 500
        return jsonify(result), status_code

    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@generator_bp.route("/test-source-db", methods=["POST"])
def test_source_db():
    """
    Test the configured source DB connection (reads from db_config.json).
    No body required.
    Returns: { ok, message, tables, config }
    """
    try:
        from services.source_db_service import SourceDbService
        result = SourceDbService().test_connection()
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "message": str(e), "tables": [], "config": {}}), 500


@generator_bp.route("/source-db-config")
def source_db_config():
    """Return the active source DB config (no password) for the UI banner."""
    try:
        from services.source_db_service import SourceDbService
        cfg = SourceDbService().get_config()
        return jsonify({"ok": True, "config": cfg})
    except Exception as e:
        return jsonify({"ok": False, "config": {}}), 500


@generator_bp.route("/generate-synthetic", methods=["POST"])
def generate_synthetic():
    """
    Generate synthetic data from the ICD mapping CSV and insert into BigQuery.
    Body: { "icd_filename": "model_SCRUM-153_20260421_11_mapping.csv" }
    If icd_filename is omitted, uses the latest ICD file.
    """
    try:
        from config import ICD_DIR
        from services.synthetic_data_service import SyntheticDataService

        body         = request.get_json(force=True) or {}
        icd_filename = (body.get("icd_filename") or "").strip()

        if icd_filename:
            icd_path = ICD_DIR / icd_filename
        else:
            from agents.generator.connectors import _datehr_key
            candidates = sorted(ICD_DIR.glob("*.csv"), key=_datehr_key, reverse=True)
            if not candidates:
                return jsonify({"ok": False, "message": "No ICD mapping files found."}), 400
            icd_path = candidates[0]

        result = SyntheticDataService().generate_and_insert(str(icd_path))
        status_code = 200 if result["ok"] else 500
        return jsonify(result), status_code

    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@generator_bp.route("/export/csv")
def export_csv():
    csvs = sorted(GENERATOR_OUTPUT_DIR.glob("*.csv"),
                  key=lambda f: f.stat().st_mtime, reverse=True)
    if not csvs:
        return "No test cases generated yet.", 400
    return send_file(str(csvs[0]), as_attachment=True,
                     download_name=csvs[0].name, mimetype="text/csv")


@generator_bp.route("/export/excel")
def export_excel():
    xlsxs = sorted(GENERATOR_OUTPUT_DIR.glob("*.xlsx"),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    if not xlsxs:
        return "No test cases generated yet.", 400
    return send_file(str(xlsxs[0]), as_attachment=True,
                     download_name=xlsxs[0].name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
