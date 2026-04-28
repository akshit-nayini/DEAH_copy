"""Input parser for the Development Pod.

Accepts two input formats — auto-detected, no flags needed:

  Format A (raw requirements)
    --impl   requirements.json        RequirementsOutput JSON from design pod
    --mapping table_schema.csv        Source schema export (Oracle / MySQL / Postgres)

  Format B (pre-processed)
    --impl   Implementation.md        Markdown implementation document
    --mapping mapping.csv             Already-formatted pipeline mapping CSV

Details can live in either file; the parser merges what it finds.
"""
from __future__ import annotations
import csv
import io
import json
import os
import re
import uuid
from pathlib import Path

from api.models import CloudProvider, PipelineInput
from db import build_metadata_engine

_REQUIRED_MAPPING_COLUMNS = {
    "source_table", "source_column", "target_table",
    "target_column", "target_data_type",
}

_SOURCE_SCHEMA_COLUMNS = {"table_name", "column_name", "data_type"}

_ORACLE_SPECIFIC_TYPES = {
    "VARCHAR2", "NUMBER", "CLOB", "NCLOB", "NCHAR", "NVARCHAR2",
    "XMLTYPE", "BFILE", "RAW", "BINARY_FLOAT", "BINARY_DOUBLE",
}

_MYSQL_SPECIFIC_TYPES = {
    "TINYINT", "MEDIUMINT", "MEDIUMTEXT", "LONGTEXT", "TINYTEXT",
    "ENUM", "SET", "YEAR", "DATETIME",
}


def parse_inputs_from_ticket(
    ticket_id: str,
    repo_root: "Path | str | None" = None,
    project_id: str | None = None,
    dataset_id: str | None = None,
    environment: str | None = None,
    cloud_provider: str = "gcp",
    region: str = "us-central1",
) -> "PipelineInput":
    """
    Fetch ALL output documents for a ticket from the metadata DB.

    Queries agent_output_metadata for every (AGENT, FILE_TYPE) combination,
    keeping the latest row per pair (ordered by CREATED_TS DESC).

    Supported file types:
      MD, MERMAID, MMD  → merged into implementation_md with agent section headers
      JSON              → converted to readable markdown and merged into implementation_md
      CSV               → used as mapping_csv (DataModel agent CSV preferred)
      DOC, DOCX         → text extracted (requires python-docx) and merged into implementation_md
      other             → read as plain text and merged into implementation_md

    repo_root: path to the DEAH repo root (default: auto-detected from this file's location).

    Raises FileNotFoundError if no records are found for the ticket.
    """
    import logging as _logging
    from pathlib import Path as _Path

    _logger = _logging.getLogger(__name__)

    if repo_root is None:
        repo_root = _Path(__file__).resolve().parent.parent.parent  # → DEAH/
    repo_root = _Path(repo_root)

    docs = _get_all_ticket_documents(ticket_id, repo_root)
    _logger.info("Ticket %s: found %d document(s) in metadata DB", ticket_id, len(docs))

    impl_parts: list[str] = [f"# Ticket: {ticket_id}\n"]
    mapping_csv: str = ""

    for doc in docs:
        ft = doc["file_type"]          # already upper-cased
        path = doc["path"]
        agent = doc["agent"]
        filename = doc["filename"]

        if not path.exists():
            _logger.warning("File not found, skipping: %s", path)
            continue

        _logger.info("Loading [%s] %s (type=%s)", agent, filename, ft)

        if ft in ("MD", "MERMAID", "MMD"):
            content = path.read_text(encoding="utf-8")
            impl_parts.append(f"\n## [{agent}] {filename}\n\n{content}")

        elif ft == "JSON":
            raw = path.read_text(encoding="utf-8")
            try:
                data = json.loads(raw)
                impl_parts.append(_json_to_md_section(agent, filename, data))
            except json.JSONDecodeError:
                impl_parts.append(f"\n## [{agent}] {filename}\n\n```\n{raw}\n```")

        elif ft == "CSV":
            csv_content = path.read_text(encoding="utf-8")
            # Prefer the DataModel agent's CSV; accept any CSV if none yet
            if not mapping_csv or agent.lower() == "datamodel":
                mapping_csv = csv_content

        elif ft in ("DOC", "DOCX"):
            text_content = _read_word_doc(path)
            if text_content:
                impl_parts.append(f"\n## [{agent}] {filename}\n\n{text_content}")
            else:
                _logger.warning("Could not extract text from %s — skipping", filename)

        else:
            # Best-effort: try UTF-8 text read
            try:
                content = path.read_text(encoding="utf-8")
                impl_parts.append(f"\n## [{agent}] {filename}\n\n```\n{content}\n```")
            except Exception:
                _logger.warning("Cannot read binary file %s — skipping", filename)

    impl_md = "\n".join(impl_parts)

    # Auto-convert a source-schema CSV to the expected mapping format
    if mapping_csv:
        first_line = mapping_csv.splitlines()[0] if mapping_csv.strip() else ""
        headers = {h.strip().lower() for h in first_line.split(",")}
        if _SOURCE_SCHEMA_COLUMNS.issubset(headers):
            mapping_csv = _source_schema_to_mapping_csv(mapping_csv)

    project_id  = project_id  or os.environ.get("PROJECT_ID",  "")
    dataset_id  = dataset_id  or os.environ.get("DATASET_ID",  "")
    environment = environment or os.environ.get("ENV", "dev")

    request_id = _extract_request_id(impl_md) or ticket_id

    return PipelineInput(
        request_id=request_id,
        implementation_md=impl_md,
        mapping_csv=mapping_csv,
        project_id=project_id,
        dataset_id=dataset_id,
        environment=environment,
        cloud_provider=CloudProvider(cloud_provider.lower()),
        region=region,
    )


def _get_all_ticket_documents(ticket_id: str, repo_root: "Path") -> list[dict]:
    """
    Query agent_output_metadata for the most recent document per file type
    for a ticket (ORDER BY CREATED_TS DESC LIMIT 1 per type).

    Supported file types queried:
      MD, MERMAID, MMD  → implementation document / design diagrams
      CSV               → column mapping
      JSON              → structured requirements / design artefacts
      DOC, DOCX         → Word documents

    Returns a list of dicts (one per found file type).
    Raises FileNotFoundError if no documents are found at all.
    """
    from sqlalchemy import text

    # Fetch the single latest row per file-type for this ticket.
    # ORDER BY CREATED_TS DESC LIMIT 1 ensures we always pick the newest version.
    _SQL = """
        SELECT AGENT, FILE_TYPE, PATH, FILENAME, CREATED_TS
        FROM agent_output_metadata
        WHERE IDENTIFIER = :ticket_id AND FILE_TYPE = :file_type
        ORDER BY CREATED_TS DESC
        LIMIT 1
    """

    # Query every supported file type.  MERMAID / MMD are diagram files
    # (e.g. from the Design pod) that contain architecture / data-flow diagrams
    # — they are merged into the implementation document for the planner.
    _FILE_TYPES = ("MD", "MERMAID", "MMD", "CSV", "JSON", "DOC", "DOCX")

    engine = build_metadata_engine()
    result: list[dict] = []

    with engine.connect() as conn:
        for file_type in _FILE_TYPES:
            row = conn.execute(
                text(_SQL),
                {"ticket_id": ticket_id, "file_type": file_type},
            ).fetchone()
            if row is None:
                continue
            # repo_root is DEAH/ — row.PATH is stored relative to DEAH's parent (e.g.
            # "DEAH/core/output/SCRUM-1"), so we step up one level to build the full path.
            file_path = Path(repo_root).parent / row.PATH / row.FILENAME
            result.append({
                "agent":     row.AGENT,
                "file_type": row.FILE_TYPE.upper(),
                "path":      file_path,
                "filename":  row.FILENAME,
            })

    # FileNotFoundError is reused here (rather than a custom exception) to stay
    # consistent with the caller in parse_inputs_from_ticket(), which already
    # handles FileNotFoundError for both missing files and missing DB rows.
    if not result:
        raise FileNotFoundError(
            f"No outputs found for ticket {ticket_id!r} in AGENT_OUTPUT_METADATA "
            f"(checked {', '.join(_FILE_TYPES)}). Ensure the design/requirements "
            "agents have been run for this ticket first."
        )

    return result


def _json_to_md_section(agent: str, filename: str, data: "dict | list") -> str:
    """Convert a parsed JSON object/array into a readable markdown section."""
    header = f"\n## [{agent}] {filename}\n"
    if isinstance(data, dict):
        lines = [header]
        for key, value in data.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                lines.append(f"- **{key}**: {value}")
            elif isinstance(value, list):
                lines.append(f"- **{key}**:")
                for item in value:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"- **{key}**: {json.dumps(value)}")
        return "\n".join(lines)
    return f"{header}```json\n{json.dumps(data, indent=2)}\n```"


def _read_word_doc(path: "Path") -> str:
    """Extract plain text from a .docx file. Returns empty string if unavailable."""
    try:
        import docx  # type: ignore[import]
        doc = docx.Document(str(path))
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
    except ImportError:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "python-docx not installed; cannot read %s. "
            "Install with: pip install python-docx", path.name
        )
        return ""
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).warning("Could not read Word doc %s: %s", path.name, exc)
        return ""


def parse_inputs(
    impl_md_path: str,
    mapping_csv_path: str,
    project_id: str | None = None,
    dataset_id: str | None = None,
    environment: str | None = None,
    cloud_provider: str = "gcp",
    region: str = "us-central1",
) -> PipelineInput:
    """
    Read the two input files and return a validated PipelineInput.

    impl_md_path      — path to Implementation.md  OR  requirements.json
    mapping_csv_path  — path to mapping.csv         OR  source schema CSV

    project_id / dataset_id / environment:
        Resolved in this order:
          1. Explicit argument (CLI --project / --dataset / --env)
          2. Environment variable: PROJECT_ID / DATASET_ID / ENV
          3. Empty string — planner will raise a clarifying question if needed

    Raises:
        FileNotFoundError: if either file is missing.
        ValueError: if required data cannot be derived from the inputs.
    """
    # Resolve from env vars when not explicitly passed
    project_id  = project_id  or os.environ.get("PROJECT_ID",  "")
    dataset_id  = dataset_id  or os.environ.get("DATASET_ID",  "")
    environment = environment or os.environ.get("ENV", "dev")
    impl_path = Path(impl_md_path)
    map_path = Path(mapping_csv_path)

    if not impl_path.exists():
        raise FileNotFoundError(f"Implementation doc not found: {impl_md_path}")
    if not map_path.exists():
        raise FileNotFoundError(f"Mapping/schema file not found: {mapping_csv_path}")

    if impl_path.suffix.lower() == ".json":
        requirements = json.loads(impl_path.read_text(encoding="utf-8"))
        impl_md = _requirements_json_to_md(requirements)
    else:
        impl_md = impl_path.read_text(encoding="utf-8")
        requirements = {}

    csv_raw = map_path.read_text(encoding="utf-8")
    first_line = csv_raw.splitlines()[0] if csv_raw.strip() else ""
    headers = {h.strip().lower() for h in first_line.split(",")}

    if _SOURCE_SCHEMA_COLUMNS.issubset(headers):
        mapping_csv = _source_schema_to_mapping_csv(csv_raw)
    else:
        mapping_csv = csv_raw
        _validate_mapping_csv(mapping_csv)

    request_id = _extract_request_id(impl_md) or f"req-{uuid.uuid4().hex[:8]}"

    return PipelineInput(
        request_id=request_id,
        implementation_md=impl_md,
        mapping_csv=mapping_csv,
        project_id=project_id,
        dataset_id=dataset_id,
        environment=environment,
        cloud_provider=CloudProvider(cloud_provider.lower()),
        region=region,
    )


def _requirements_json_to_md(req: dict) -> str:
    lines: list[str] = []

    project = req.get("project_name", "Unknown Project")
    lines.append(f"# Implementation Specification: {project}\n")

    if req.get("ticket_id"):
        lines.append(f"**Request ID:** {req['ticket_id']}")
    if req.get("request_type"):
        lines.append(f"**Request Type:** {req['request_type']}")
    lines.append("")

    if req.get("objective"):
        lines.append(f"## Objective\n{req['objective']}\n")

    if req.get("business_context"):
        lines.append(f"## Business Context\n{req['business_context']}\n")

    if req.get("functional_requirements"):
        lines.append("## Functional Requirements")
        for item in req["functional_requirements"]:
            lines.append(f"- {item}")
        lines.append("")

    data_req = req.get("data_requirements") or {}
    if any(data_req.values()):
        lines.append("## Data Requirements")
        if data_req.get("source_systems"):
            lines.append(f"- Source Systems: {', '.join(data_req['source_systems'])}")
        if data_req.get("data_types"):
            lines.append(f"- Data Type: {data_req['data_types']}")
        if data_req.get("volume"):
            lines.append(f"- Volume: {data_req['volume']}")
        if data_req.get("frequency"):
            lines.append(f"- Frequency / Schedule: {data_req['frequency']}")
        lines.append("")

    tech = req.get("technology") or {}
    if any(tech.values()):
        lines.append("## Technology Stack")
        if tech.get("stack"):
            lines.append(f"- Cloud / Platform: {tech['stack']}")
        if tech.get("environment"):
            lines.append(f"- Environment: {tech['environment']}")
        if tech.get("cloud_or_onprem"):
            lines.append(f"- Deployment Model: {tech['cloud_or_onprem']}")
        lines.append("")

    nfr = {k: v for k, v in (req.get("non_functional") or {}).items() if v}
    if nfr:
        lines.append("## Non-Functional Requirements")
        for k, v in nfr.items():
            lines.append(f"- {k.replace('_', ' ').title()}: {v}")
        lines.append("")

    security = {k: v for k, v in (req.get("security") or {}).items() if v}
    if security:
        lines.append("## Security")
        for k, v in security.items():
            lines.append(f"- {k.replace('_', ' ').title()}: {v}")
        lines.append("")

    if req.get("acceptance_criteria"):
        lines.append("## Acceptance Criteria")
        for c in req["acceptance_criteria"]:
            lines.append(f"- {c}")
        lines.append("")

    assumptions = list(req.get("assumptions") or []) + list(req.get("inferred_assumptions") or [])
    if assumptions:
        lines.append("## Assumptions")
        for a in assumptions:
            lines.append(f"- {a}")
        lines.append("")

    return "\n".join(lines)


def _source_schema_to_mapping_csv(csv_raw: str) -> str:
    reader = csv.DictReader(io.StringIO(csv_raw))
    rows = [{k.strip().lower(): (v or "").strip() for k, v in row.items()} for row in reader]

    if not rows:
        raise ValueError("Source schema CSV contains no data rows.")

    out_rows: list[dict] = []
    for row in rows:
        table = row.get("table_name", "").upper()
        column = row.get("column_name", "").upper()

        raw_type = row.get("column_type") or row.get("data_type", "")
        precision = row.get("precision") or row.get("length") or ""
        scale = row.get("scale", "")

        nullable_raw = row.get("nullable") or row.get("is_nullable") or "YES"
        is_pk = row.get("primary_key", row.get("column_key", "")).upper() in (
            "YES", "PRI", "Y", "TRUE", "1"
        )

        bq_type = _oracle_type_to_bigquery(raw_type, precision, scale)

        out_rows.append({
            "source_table":     table,
            "source_column":    column,
            "source_data_type": raw_type.upper(),
            "target_table":     "stg_" + table.lower(),
            "target_column":    column.lower(),
            "target_data_type": bq_type,
            "nullable":         "true" if _is_nullable(nullable_raw) else "false",
            "is_pk":            "true" if is_pk else "false",
            "is_pii":           "false",
            "transformation":   "",
            "notes":            row.get("description", ""),
        })

    fieldnames = [
        "source_table", "source_column", "source_data_type",
        "target_table", "target_column", "target_data_type",
        "nullable", "is_pk", "is_pii", "transformation", "notes",
    ]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(out_rows)
    return out.getvalue()


def _oracle_type_to_bigquery(data_type: str, precision: str = "", scale: str = "") -> str:
    base = re.sub(r"\(.*\)", "", data_type.strip().upper()).strip()

    m = re.search(r"\((\d+)(?:,(\d+))?\)", data_type)
    if m:
        precision = precision or m.group(1)
        scale = scale or (m.group(2) or "0")

    try:
        p = int(precision) if precision else None
        s = int(scale) if scale else None
    except ValueError:
        p = s = None

    if base in ("VARCHAR2", "VARCHAR", "CHAR", "NCHAR", "NVARCHAR2", "NVARCHAR",
                "CLOB", "NCLOB", "LONG", "XMLTYPE", "TEXT", "TINYTEXT",
                "MEDIUMTEXT", "LONGTEXT", "BFILE"):
        return "STRING"

    if base in ("NUMBER", "NUMERIC", "DECIMAL"):
        if s and s > 0:
            return "NUMERIC"
        if p and p <= 18:
            return "INT64"
        return "NUMERIC"

    if base in ("INTEGER", "INT", "SMALLINT", "TINYINT", "BYTEINT", "BIGINT"):
        return "INT64"

    if base in ("FLOAT", "DOUBLE", "DOUBLE PRECISION",
                "BINARY_FLOAT", "BINARY_DOUBLE", "REAL"):
        return "FLOAT64"

    if base == "DATE":
        return "DATE"

    if base == "DATETIME":
        return "DATETIME"

    if base.startswith("TIMESTAMP"):
        return "TIMESTAMP"

    if base in ("INTERVAL YEAR TO MONTH", "INTERVAL DAY TO SECOND", "INTERVAL"):
        return "STRING"

    if base in ("BLOB", "RAW", "LONG RAW", "VARBINARY", "BINARY"):
        return "BYTES"

    if base in ("BOOLEAN", "BOOL"):
        return "BOOL"

    return "STRING"


def _is_nullable(value: str) -> bool:
    return value.strip().upper() not in ("NOT NULL", "NO", "N", "FALSE", "0")


def _validate_mapping_csv(csv_content: str) -> None:
    reader = csv.DictReader(io.StringIO(csv_content))
    headers = {h.strip().lower() for h in (reader.fieldnames or [])}
    missing = _REQUIRED_MAPPING_COLUMNS - headers
    if missing:
        raise ValueError(
            f"Mapping CSV missing required column(s): {', '.join(sorted(missing))}. "
            f"Required: {', '.join(sorted(_REQUIRED_MAPPING_COLUMNS))}."
        )
    rows = list(reader)
    if not rows:
        raise ValueError("Mapping CSV has no data rows.")


def _detect_source_system_from_csv(csv_raw: str) -> tuple[str, float]:
    try:
        reader = csv.DictReader(io.StringIO(csv_raw))
        rows = [
            {k.strip().lower(): (v or "").strip() for k, v in row.items()}
            for row in reader
        ]
    except Exception:
        return "unknown", 0.0

    oracle_hits = 0
    mysql_hits = 0
    for row in rows:
        raw_type = (
            row.get("column_type")
            or row.get("data_type")
            or row.get("source_data_type", "")
        ).upper()
        base = re.sub(r"\(.*\)", "", raw_type).strip()
        if base in _ORACLE_SPECIFIC_TYPES:
            oracle_hits += 1
        if base in _MYSQL_SPECIFIC_TYPES:
            mysql_hits += 1

    if oracle_hits > 0 and mysql_hits == 0:
        return "oracle", 1.0
    if mysql_hits > 0 and oracle_hits == 0:
        return "mysql", 1.0
    total = len(rows) or 1
    if oracle_hits > mysql_hits:
        return "oracle", oracle_hits / total
    if mysql_hits > oracle_hits:
        return "mysql", mysql_hits / total
    return "unknown", 0.0


def _detect_source_system_from_doc(impl_md: str) -> str:
    text = impl_md.upper()
    if "MYSQL" in text:
        return "mysql"
    if "ORACLE" in text:
        return "oracle"
    if "POSTGRES" in text or "POSTGRESQL" in text:
        return "postgres"
    return "unknown"


def _inject_source_system_note(impl_md: str, mapping_csv: str) -> str:
    csv_system, confidence = _detect_source_system_from_csv(mapping_csv)
    if csv_system == "unknown" or confidence < 0.3:
        return impl_md

    doc_system = _detect_source_system_from_doc(impl_md)

    if doc_system != "unknown" and doc_system != csv_system:
        example_types = (
            "VARCHAR2, NUMBER, DATE"
            if csv_system == "oracle"
            else "TINYINT, ENUM, DATETIME"
        )
        note = (
            f"<!-- SOURCE SYSTEM CONFLICT DETECTED\n"
            f"     This document references {doc_system.upper()} as the source system.\n"
            f"     However, the mapping CSV contains {csv_system.upper()}-exclusive column\n"
            f"     types ({example_types}), strongly suggesting the source is\n"
            f"     {csv_system.upper()}, not {doc_system.upper()}.\n"
            f"     ACTION REQUIRED: Raise this as a BLOCKER question — ask the user\n"
            f"     to confirm which source system is correct before proceeding.\n"
            f"-->\n\n"
        )
        return note + impl_md

    if doc_system == "unknown":
        note = (
            f"<!-- SOURCE SYSTEM NOT EXPLICITLY STATED IN DOCUMENT\n"
            f"     The mapping CSV contains {csv_system.upper()}-exclusive column types\n"
            f"     (confidence: {confidence:.0%}), suggesting the source may be\n"
            f"     {csv_system.upper()} — but this has not been confirmed by the author.\n"
            f"     ACTION REQUIRED: Raise this as a BLOCKER question — ask the user\n"
            f"     to confirm the source system before proceeding.\n"
            f"-->\n\n"
        )
        return note + impl_md

    note = (
        f"<!-- SOURCE SYSTEM CONFIRMED: {csv_system.upper()}\n"
        f"     Both the implementation document body and the mapping CSV column\n"
        f"     types ({csv_system.upper()}-exclusive types detected) agree that the\n"
        f"     source is {csv_system.upper()}. Do NOT raise this as a question.\n"
        f"     Dataset/project names are labels only and must be ignored when\n"
        f"     determining source system.\n"
        f"-->\n\n"
    )
    return note + impl_md


def _extract_request_id(impl_md: str) -> str | None:
    match = re.search(
        r"(?:request[-_]?id|ticket|JIRA|REQ)[:\s]+([A-Z]+-\d+|req-[a-f0-9]+)",
        impl_md,
        re.IGNORECASE,
    )
    return match.group(1) if match else None
