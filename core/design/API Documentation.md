# DEAH Design Agents — API Reference

Base URL: `http://35.209.107.68:9190`

All endpoints accept and return JSON. Paths in request bodies are relative to `core/design/agents/`.

---

## Quick Summary

| Endpoint | Method | Description |
|---|---|---|
| `/requirements/from-jira` | POST | Extract requirements from a Jira ticket |
| `/requirements/from-document` | POST | Extract requirements from a document file |
| `/data-model` | POST | Generate data model from requirements |
| `/architecture` | POST | Generate architecture design from requirements |
| `/implementation-steps` | POST | Generate implementation steps |
| `/pipeline` | POST | Run all agents end-to-end in sequence |
| `/outputs` | GET | List all output files on disk |

---

## 1. Requirements — from Jira

**`POST /requirements/from-jira`**

Fetches the Jira ticket and extracts structured requirements. Automatically reads all linked work items and sub-tasks in a single pass — their content and comments are consolidated into one output using the parent ticket ID throughout.

### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `ticket_id` | string | Yes | Jira ticket ID, e.g. `"SCRUM-5"` |
| `write_back` | boolean | No | Write result back to Jira (default: `false`) |

```json
{
  "ticket_id": "SCRUM-5",
  "write_back": false
}
```

### Response

| Field | Description |
|---|---|
| `output_path` | Path to saved requirements JSON file |
| `markdown_path` | Path to saved requirements Markdown file |
| `result` | Full requirements object (use this for downstream calls) |
| `git` | Git push status (`null` if not configured) |

```json
{
  "output_path": "/home/.../requirements_gathering/output/req_SCRUM-5_20260416_10.json",
  "markdown_path": "/home/.../requirements_gathering/output/req_SCRUM-5_20260416_10.md",
  "result": {
    "ticket_id": "SCRUM-5",
    "project_name": "Customer 360",
    "request_type": "new development"
  },
  "git": null
}
```

---

## 2. Requirements — from Document

**`POST /requirements/from-document`**

Extracts requirements from an existing document file.

### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `document_path` | string | Yes | Path to document, relative to `agents/` |

```json
{
  "document_path": "requirements_gathering/requirements_template.txt"
}
```

### Response — same shape as `/requirements/from-jira`.

---

## 3. Data Model

**`POST /data-model`**

Generates ER diagram and source-to-target column mapping from requirements.

### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `ticket_id` | string | Yes | Auto-resolves latest requirements from metadata DB |
| `schema_path` | string | No | Path to DB schema CSV (enables live table mapping) |

```json
{
  "ticket_id": "SCRUM-5",
  "schema_path": "data_model/sample_input/table_schema.csv"
}
```

### Response

| Field | Description |
|---|---|
| `output_files.summary_json` | Path to summary JSON — pass to `/implementation-steps` or `/pipeline` |
| `output_files.er_diagram_mmd` | Path to Mermaid ER diagram file |
| `output_files.mapping_csv` | Path to source→target column mapping CSV |
| `handoff_summary` | Parsed summary object |
| `source_target_mapping` | Column mapping data |
| `er_mermaid_diagram` | Raw Mermaid diagram text |
| `git` | Git push status |

```json
{
  "output_files": {
    "summary_json":   "/home/.../data_model/output/model_SCRUM-5_20260416_10_summary.json",
    "er_diagram_mmd": "/home/.../data_model/output/model_SCRUM-5_20260416_10_er_diagram.mmd",
    "mapping_csv":    "/home/.../data_model/output/model_SCRUM-5_20260416_10_mapping.csv"
  },
  "handoff_summary": { ... },
  "source_target_mapping": [ ... ],
  "er_mermaid_diagram": "erDiagram ...",
  "git": null
}
```

---

## 4. Architecture

**`POST /architecture`**

Generates architecture design and flow diagram from requirements.

### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `ticket_id` | string | Yes | Auto-resolves latest requirements from metadata DB |

```json
{
  "ticket_id": "SCRUM-5"
}
```

### Response

| Field | Description |
|---|---|
| `output_files.summary_json` | Path to summary JSON — pass to `/implementation-steps` or `/pipeline` |
| `output_files.report_md` | Path to full architecture narrative report |
| `output_files.flow_mmd` | Path to Mermaid architecture flow diagram |
| `handoff_summary` | Parsed summary object |
| `manifest_summary` | Component/service manifest |
| `skipped` | `true` if agent determined architecture step was not needed |
| `git` | Git push status |

```json
{
  "run_id": "arc_SCRUM-5_20260416_10",
  "skipped": false,
  "output_files": {
    "summary_json": "/home/.../architecture/outputs/arc_SCRUM-5_20260416_10_summary.json",
    "report_md":    "/home/.../architecture/outputs/arc_SCRUM-5_20260416_10_report.md",
    "flow_mmd":     "/home/.../architecture/outputs/arc_SCRUM-5_20260416_10_flow.mmd"
  },
  "handoff_summary": { ... },
  "manifest_summary": { ... },
  "git": null
}
```

---

## 5. Implementation Steps

**`POST /implementation-steps`**

Generates a step-by-step implementation plan. `request_type` and all inputs are auto-resolved from the metadata DB using the ticket ID.

### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `ticket_id` | string | Yes | Auto-resolves all inputs from metadata DB |

```json
{
  "ticket_id": "SCRUM-5"
}
```

### Response

| Field | Description |
|---|---|
| `output_path` | Path to saved implementation plan Markdown file |
| `markdown` | Full implementation plan as Markdown text |
| `project_name` | Project name used |
| `request_type` | Request type used |
| `git` | Git push status |

```json
{
  "project_name": "Customer 360 Data Platform",
  "request_type": "new development",
  "output_path": "/home/.../implementation_steps/output/impl_SCRUM-5_20260416_10.md",
  "markdown": "# Implementation Steps\n...",
  "git": null
}
```

---

## 6. Full Pipeline

**`POST /pipeline`**

Runs all agents in sequence: Data Model → Architecture → Mermaid→DrawIO → Implementation Steps. Data Model, Architecture, and Mermaid→DrawIO are skipped automatically for `request_type = "bug"`. All inputs are auto-resolved from the metadata DB using the ticket ID.

### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `ticket_id` | string | Yes | Auto-resolves requirements and derives all inputs |
| `schema_path` | string | No | Path to DB schema CSV (used by Data Model step) |

```json
{
  "ticket_id": "SCRUM-5",
  "schema_path": "data_model/sample_input/table_schema.csv"
}
```

### Response

| Field | Description |
|---|---|
| `data_model_path` | Path to data model summary JSON |
| `architecture_path` | Path to architecture summary JSON |
| `data_model` | Data model result (or `{"error": "..."}` if failed) |
| `architecture` | Architecture result (or `{"error": "..."}` if failed) |
| `mermaid2drawio` | DrawIO conversion result with `drawio_files` list (or `{"error": "..."}`) — `null` for bug |
| `implementation_steps` | Impl steps result with `output_path` and `markdown` |
| `git` | Git push status per agent |

```json
{
  "data_model_path": "/home/.../data_model/output/model_SCRUM-5_20260416_10_summary.json",
  "architecture_path": "/home/.../architecture/outputs/arc_SCRUM-5_20260416_10_summary.json",
  "data_model": { ... },
  "architecture": { ... },
  "mermaid2drawio": {
    "drawio_files": [
      "/home/.../drawio_output/arc_SCRUM-5_20260416_10_flow_option1.drawio",
      "/home/.../drawio_output/arc_SCRUM-5_20260416_10_flow_option2.drawio",
      "/home/.../drawio_output/arc_SCRUM-5_20260416_10_flow_option3_recommended.drawio",
      "/home/.../drawio_output/model_SCRUM-5_20260416_10_er_diagram.drawio"
    ]
  },
  "implementation_steps": {
    "output_path": "/home/.../implementation_steps/output/impl_SCRUM-5_20260416_10.md",
    "markdown": "# Implementation Steps\n...",
    "git": null
  },
  "git": {
    "data_model": null,
    "architecture": null,
    "mermaid2drawio": null,
    "implementation_steps": null
  }
}
```

---

## 7. List Output Files

**`GET /outputs`**

No request body. Returns all agent output files on disk, newest first.

### Response

```json
{
  "requirements": {
    "json":     [ ".../req_SCRUM-5_20260416_10.json" ],
    "markdown": [ ".../req_SCRUM-5_20260416_10.md" ]
  },
  "data_model": {
    "summary_json":   [ ".../model_SCRUM-5_20260416_10_summary.json" ],
    "er_diagram_mmd": [ ".../model_SCRUM-5_20260416_10_er_diagram.mmd" ],
    "mapping_csv":    [ ".../model_SCRUM-5_20260416_10_mapping.csv" ]
  },
  "architecture": {
    "summary_json": [ ".../arc_SCRUM-5_20260416_10_summary.json" ],
    "report_md":    [ ".../arc_SCRUM-5_20260416_10_report.md" ],
    "flow_mmd":     [ ".../arc_SCRUM-5_20260416_10_flow.mmd" ]
  },
  "mermaid2drawio": [
    ".../drawio_output/arc_SCRUM-5_20260416_10_flow_option1.drawio",
    ".../drawio_output/arc_SCRUM-5_20260416_10_flow_option2.drawio",
    ".../drawio_output/arc_SCRUM-5_20260416_10_flow_option3_recommended.drawio",
    ".../drawio_output/model_SCRUM-5_20260416_10_er_diagram.drawio"
  ],
  "implementation_steps": [ ".../impl_SCRUM-5_20260416_10.md" ]
}
```

---

## Error Responses

| HTTP Status | Meaning |
|---|---|
| `400` | Bad request — invalid input or missing required fields |
| `404` | Not found — agent hasn't been run yet for this ticket (ticket_id mode only) |
| `422` | Validation error — missing required `ticket_id` field |
| `500` | Agent or server error — check `detail` field for message |

All errors return:

```json
{
  "detail": "human-readable error message"
}
```
