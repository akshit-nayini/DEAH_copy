"""
agents/generator/agent.py
--------------------------
GeneratorAgent: pure business logic.
Takes ICD + AC text, calls the LLM once per category, returns list of test case dicts.

Modes:
  run()                — New Project: full generation for selected categories
  run_incremental()    — Existing Project: generate only for new/uncovered columns
  run_change_request() — Change Request: generate for changed columns + flag regression TCs
  run_edge_cases()     — Edge Cases: boundary/null/special-char categories only
  load_existing()      — Repurpose: load latest output without LLM call

Provider is controlled entirely by LLM_PROVIDER in .env.
API keys are resolved automatically by the common LLM factory.
"""

from __future__ import annotations
import csv
import io
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import LLM_UTILITY_ROOT, LLM_PROVIDER, LLM_MODEL, LLM_MAX_TOKENS, GENERATOR_OUTPUT_DIR
from agents.generator.prompts import (
    SYSTEM_PROMPT,
    ALL_CATEGORIES,
    EDGE_CASE_CATEGORIES,
    build_category_prompt,
    build_user_prompt,
    build_incremental_prompt,
)
from services.icd_parser import ICDParserService
from storage.local_storage import save_csv, save_excel, build_stem

sys.path.insert(0, str(LLM_UTILITY_ROOT))
from core.utilities.llm import create_llm_client


# Default values for all 13 test case fields
_TC_DEFAULTS = {
    "column":        "ALL",
    "precondition":  "",
    "input_data":    "",
    "steps":         "",
    "query":         "",
    "sql_hint":      "",
    "expected_result": "",
    "priority":      "Medium",
    "linked_ac":     "N/A",
}


def _parse_json(raw: str) -> list[dict] | None:
    """Robust JSON extraction: strip markdown fences, parse, regex fallback."""
    clean = raw.strip()
    if clean.startswith("```"):
        clean = re.sub(r'^```(?:json)?\s*', '', clean)
        clean = re.sub(r'\s*```$', '', clean.strip())
        clean = clean.strip()
    try:
        result = json.loads(clean)
        return result if isinstance(result, list) else None
    except json.JSONDecodeError:
        m = re.search(r'\[.*\]', clean, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return None


class GeneratorAgent:
    """
    Generates test cases from ICD + Acceptance Criteria.

    Uses one LLM call per category with ICD metadata-enriched prompts.
    """

    # ── Repurpose ──────────────────────────────────────────────────────────────

    def existing_files(self) -> list[Path]:
        """Return all previously generated CSVs, newest first."""
        return sorted(
            GENERATOR_OUTPUT_DIR.glob("*.csv"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

    def load_existing(self) -> dict:
        """Repurpose the latest existing test case CSV — no LLM call."""
        files = self.existing_files()
        if not files:
            raise FileNotFoundError(
                f"No existing test cases found in {GENERATOR_OUTPUT_DIR}. "
                "Run Generate first."
            )
        latest = files[0]
        cases  = pd.read_csv(latest).fillna("").to_dict("records")
        print(f"=== GeneratorAgent: repurposing {latest.name} ({len(cases)} test cases) ===")
        return {"cases": cases, "csv_path": str(latest), "source": "repurposed"}

    # ── Core engine ────────────────────────────────────────────────────────────

    def _run_categories(
        self,
        icd: str,
        ac: str,
        categories: list[str],
        icd_filename: str | None = None,
        start_tc_num: int = 1,
    ) -> list[dict]:
        """
        Core engine: one LLM call per category, merged results.
        Uses ICDParserService to enrich prompts with schema metadata.
        """
        llm = create_llm_client(LLM_PROVIDER, model=LLM_MODEL or None)

        # Parse ICD for metadata — degrade gracefully if parsing fails
        meta = ICDParserService(icd).parse()
        if meta.get("error"):
            print(f"  [GeneratorAgent] ICD parse warning: {meta['error']} — using raw ICD")
            meta = {
                "schema_text": icd, "table_name": "target_table",
                "col_count": 0, "column_defs": [],
                "pii_cols": [], "pk_cols": [], "enum_cols": [],
            }

        print(f"  Table: {meta['table_name']}  |  {meta['col_count']} columns  |  "
              f"PK: {meta['pk_cols']}  |  PII: {meta['pii_cols']}")

        all_cases: list[dict] = []
        tc_counter = start_tc_num

        for category in categories:
            prompt = build_category_prompt(category, meta, ac, tc_counter, tc_count=2)
            print(f"  [{category}] calling LLM...", end=" ", flush=True)
            try:
                response = llm.complete(prompt, system=SYSTEM_PROMPT, max_tokens=LLM_MAX_TOKENS)
                cases    = _parse_json(response.content)
                if cases is None:
                    # Retry once
                    response = llm.complete(prompt, system=SYSTEM_PROMPT, max_tokens=LLM_MAX_TOKENS)
                    cases = _parse_json(response.content)
                if not cases:
                    print("SKIP (JSON parse failed after retry)")
                    continue
                for tc in cases:
                    for k, v in _TC_DEFAULTS.items():
                        tc.setdefault(k, v)
                    tc["tc_id"]    = f"TC-{tc_counter:03d}"
                    tc["category"] = category
                    tc_counter    += 1
                    all_cases.append(tc)
                print(f"{len(cases)} TCs")
            except Exception as exc:
                print(f"ERROR: {exc}")
                continue

        return all_cases

    # ── Modes ──────────────────────────────────────────────────────────────────

    def run(
        self,
        icd: str,
        ac: str,
        icd_filename: str | None = None,
        categories: list[str] | None = None,
    ) -> list[dict]:
        """
        New Project: full generation for selected categories.
        categories=None generates all 12 categories.
        """
        cats = categories if categories is not None else ALL_CATEGORIES
        print(f"=== GeneratorAgent: New Project — {len(cats)} categories via '{LLM_PROVIDER}' ===")
        cases    = self._run_categories(icd, ac, cats, icd_filename=icd_filename)
        stem     = build_stem(icd_filename, "testcases")
        csv_path = save_csv(cases, GENERATOR_OUTPUT_DIR, stem=stem)
        save_excel(cases, GENERATOR_OUTPUT_DIR, stem=stem,
                   sheet_name="Test Cases", verdict_col=None)
        print(f"=== Saved {len(cases)} test cases to {csv_path} ===")
        return cases

    def run_edge_cases(
        self,
        icd: str,
        ac: str,
        icd_filename: str | None = None,
    ) -> dict:
        """
        Edge Cases mode: generates only Boundary Values, Null/Empty, Special Characters.
        """
        print(f"=== GeneratorAgent: Edge Cases — {EDGE_CASE_CATEGORIES} ===")
        cases    = self._run_categories(icd, ac, EDGE_CASE_CATEGORIES, icd_filename=icd_filename)
        stem     = build_stem(icd_filename, "testcases")
        csv_path = save_csv(cases, GENERATOR_OUTPUT_DIR, stem=stem)
        save_excel(cases, GENERATOR_OUTPUT_DIR, stem=stem,
                   sheet_name="Test Cases", verdict_col=None)
        print(f"=== Saved {len(cases)} edge-case TCs to {csv_path} ===")
        return {
            "cases":      cases,
            "source":     "edge_cases",
            "categories": EDGE_CASE_CATEGORIES,
            "csv_path":   str(csv_path),
        }

    def run_incremental(
        self,
        new_icd: str,
        ac: str,
        icd_filename: str | None = None,
        categories: list[str] | None = None,
    ) -> dict:
        """
        Existing Project: generate test cases only for columns not yet covered.
        Uses ICDParserService for exact column-name set detection.
        Falls back to text-search heuristic if ICD cannot be parsed.
        """
        cats  = categories if categories is not None else ALL_CATEGORIES
        files = self.existing_files()

        if not files:
            cases    = self.run(new_icd, ac, icd_filename=icd_filename, categories=cats)
            csv_path = str(self.existing_files()[0]) if self.existing_files() else ""
            return {"cases": cases, "new_cases": cases, "csv_path": csv_path,
                    "new_columns": [], "source": "full"}

        existing_cases = pd.read_csv(files[0]).fillna("").to_dict("records")

        # Exact column-name detection via ICDParserService
        meta = ICDParserService(new_icd).parse()
        if not meta.get("error") and meta.get("column_defs"):
            icd_col_names = {d["name"] for d in meta["column_defs"]}
            covered_cols  = {
                str(tc.get("column", "")).strip()
                for tc in existing_cases
                if str(tc.get("column", "")).strip() not in ("", "ALL")
            }
            new_columns = [n for n in icd_col_names if n not in covered_cols]
        else:
            # Fallback: text-search heuristic
            icd_col_names_list, _ = self._parse_icd_columns(new_icd)
            new_columns = self._find_new_columns(icd_col_names_list, existing_cases)

        if not new_columns:
            print("=== GeneratorAgent: no new columns detected — returning existing ===")
            return {
                "cases":       existing_cases,
                "new_cases":   [],
                "csv_path":    str(files[0]),
                "new_columns": [],
                "source":      "no_new_columns",
            }

        # Build delta ICD with only new-column rows
        _, icd_rows = self._parse_icd_columns(new_icd)
        new_col_set = set(new_columns)
        delta_rows  = [
            r for r in icd_rows
            if (r.get("target_column") or r.get("column_name") or "").strip() in new_col_set
        ]
        if delta_rows:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=list(delta_rows[0].keys()))
            writer.writeheader()
            writer.writerows(delta_rows)
            delta_icd = buf.getvalue()
        else:
            delta_icd = new_icd

        max_tc = 0
        for tc in existing_cases:
            try:
                max_tc = max(max_tc, int(str(tc.get("tc_id", "0")).replace("TC-", "")))
            except ValueError:
                pass

        print(f"=== GeneratorAgent: Incremental — {len(new_columns)} new columns, "
              f"starting TC-{max_tc + 1:03d} ===")

        new_cases = self._run_categories(
            delta_icd, ac, cats,
            icd_filename=icd_filename,
            start_tc_num=max_tc + 1,
        )
        merged   = existing_cases + new_cases
        stem     = build_stem(icd_filename, "testcases")
        csv_path = save_csv(merged, GENERATOR_OUTPUT_DIR, stem=stem)
        save_excel(merged, GENERATOR_OUTPUT_DIR, stem=stem,
                   sheet_name="Test Cases", verdict_col=None)
        print(f"=== Saved {len(merged)} merged TCs "
              f"({len(existing_cases)} existing + {len(new_cases)} new) to {csv_path} ===")
        return {
            "cases":       merged,
            "new_cases":   new_cases,
            "csv_path":    str(csv_path),
            "new_columns": list(new_columns),
            "source":      "incremental",
        }

    def run_change_request(
        self,
        icd: str,
        ac: str,
        changed_columns: list[str],
        categories: list[str] | None = None,
        icd_filename: str | None = None,
        change_reason: str = "",
    ) -> dict:
        """
        Change Request: generate TCs only for the specified changed columns in
        selected categories, then flag existing TCs that cover those columns as [REGRESSION].
        """
        cats  = categories if categories is not None else ALL_CATEGORIES
        files = self.existing_files()
        existing_cases = pd.read_csv(files[0]).fillna("").to_dict("records") if files else []

        # Build delta ICD with only changed-column rows
        _, icd_rows = self._parse_icd_columns(icd)
        changed_set = set(changed_columns)
        delta_rows  = [
            r for r in icd_rows
            if (r.get("target_column") or r.get("column_name") or "").strip() in changed_set
        ]
        if delta_rows:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=list(delta_rows[0].keys()))
            writer.writeheader()
            writer.writerows(delta_rows)
            delta_icd = buf.getvalue()
        else:
            delta_icd = icd  # fallback: use full ICD if no rows matched

        max_tc = 0
        for tc in existing_cases:
            try:
                max_tc = max(max_tc, int(str(tc.get("tc_id", "0")).replace("TC-", "")))
            except ValueError:
                pass

        print(f"=== GeneratorAgent: Change Request — columns: {changed_columns}, "
              f"{len(cats)} categories, TC-{max_tc + 1:03d}+ ===")

        new_cases = self._run_categories(
            delta_icd, ac, cats,
            icd_filename=icd_filename,
            start_tc_num=max_tc + 1,
        )
        if change_reason:
            for tc in new_cases:
                tc["change_reason"] = change_reason

        # Flag regression: existing TCs that reference any changed column
        changed_lower    = {c.lower() for c in changed_columns}
        regression_cases = []
        for tc in existing_cases:
            tc_col = str(tc.get("column", "")).lower()
            tc_txt = (tc.get("test_name", "") + " " + tc.get("description", "")).lower()
            if tc_col in changed_lower or any(c in tc_txt for c in changed_lower):
                tc["linked_ac"] = str(tc.get("linked_ac", "N/A")).rstrip() + " [REGRESSION]"
                regression_cases.append(tc)

        merged   = existing_cases + new_cases
        stem     = build_stem(icd_filename, "testcases")
        csv_path = save_csv(merged, GENERATOR_OUTPUT_DIR, stem=stem)
        save_excel(merged, GENERATOR_OUTPUT_DIR, stem=stem,
                   sheet_name="Test Cases", verdict_col=None)
        print(f"=== Saved {len(merged)} TCs "
              f"({len(new_cases)} new CR + {len(regression_cases)} flagged regression) "
              f"to {csv_path} ===")
        return {
            "cases":            merged,
            "new_cases":        new_cases,
            "regression_cases": regression_cases,
            "csv_path":         str(csv_path),
            "changed_columns":  changed_columns,
            "source":           "change_request",
        }

    # ── Legacy helpers (kept for backward compatibility) ──────────────────────

    def _parse_icd_columns(self, icd_text: str) -> tuple[list[str], list[dict]]:
        """Parse ICD CSV text. Returns (unique column names, all row dicts)."""
        reader = csv.DictReader(io.StringIO(icd_text))
        rows   = list(reader)
        seen   = set()
        columns: list[str] = []
        for row in rows:
            col = (
                row.get("target_column") or row.get("column_name") or
                row.get("Target Column") or row.get("Column Name") or ""
            ).strip()
            if col and col not in seen:
                seen.add(col)
                columns.append(col)
        return columns, rows

    def _find_new_columns(
        self, icd_columns: list[str], existing_cases: list[dict]
    ) -> list[str]:
        """Return columns from icd_columns not mentioned in any existing test case (text heuristic)."""
        covered = " ".join(
            (tc.get("test_name", "") + " " + tc.get("description", "")).lower()
            for tc in existing_cases
        )
        return [col for col in icd_columns if col.lower() not in covered]