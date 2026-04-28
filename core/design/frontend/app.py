"""
app.py — Streamlit frontend for DEAH Design Agents API

Run from core/design/frontend/:
    streamlit run app.py

Requires the FastAPI server to be running:
    cd ../api && uvicorn main:app --reload --port 8000
"""

import json

import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="DEAH Design Agents", layout="wide")

API_BASE = st.sidebar.text_input("API Base URL", value="http://localhost:9190").rstrip("/")

st.title("DEAH Design Agents")

# ── Navigation ────────────────────────────────────────────────────────────────

PAGES = [
    "Requirements — Jira",
    "Requirements — Document",
    "Data Model",
    "Architecture",
    "Implementation Steps",
    "Full Pipeline",
    "View Outputs",
]

page = st.sidebar.radio("Select Agent", PAGES)


# ── Helpers ───────────────────────────────────────────────────────────────────

def post(endpoint: str, payload: dict):
    try:
        r = requests.post(f"{API_BASE}{endpoint}", json=payload, timeout=1800)
        try:
            body = r.json()
        except Exception:
            body = {"error": r.text.strip() or f"Empty response body (HTTP {r.status_code})"}
        return r.status_code, body
    except requests.exceptions.ConnectionError:
        return None, {"error": f"Could not connect to {API_BASE}. Is the server running?"}
    except Exception as e:
        return None, {"error": str(e)}


def get(endpoint: str):
    try:
        r = requests.get(f"{API_BASE}{endpoint}", timeout=1000)
        try:
            body = r.json()
        except Exception:
            body = {"error": r.text.strip() or f"Empty response body (HTTP {r.status_code})"}
        return r.status_code, body
    except requests.exceptions.ConnectionError:
        return None, {"error": f"Could not connect to {API_BASE}. Is the server running?"}
    except Exception as e:
        return None, {"error": str(e)}


def show_response(status: int | None, data: dict):
    if status is None:
        st.error(data.get("error", "Unknown error"))
        return
    if status >= 400:
        st.error(f"HTTP {status}")
        st.json(data)
    else:
        st.success(f"HTTP {status} — OK")
        st.json(data)


# ── Pages ─────────────────────────────────────────────────────────────────────

# 1. Requirements — Jira ───────────────────────────────────────────────────────
if page == "Requirements — Jira":
    st.header("Requirements — From Jira Ticket")
    st.caption(
        "CLI: `py requirements_gathering/test_requirements.py --source jira --ticket SCRUM-5`"
    )

    ticket_id  = st.text_input("Jira Ticket ID", value="SCRUM-5")
    write_back = st.checkbox("Write back to Jira (adds comment)", value=False)

    if st.button("Run", disabled=not ticket_id):
        with st.spinner("Calling Requirements Agent..."):
            status, data = post(
                "/requirements/from-jira",
                {"ticket_id": ticket_id, "write_back": write_back},
            )
        print(data)
        if status and status < 400:
            st.info(f"JSON saved to: `{data.get('output_path', '')}`")
            st.info(f"Markdown saved to: `{data.get('markdown_path', '')}`")
            with st.expander("Full Result", expanded=False):
                st.json(data.get("result", data))
        else:
            show_response(status, data)


# 3. Requirements — Document ───────────────────────────────────────────────────
elif page == "Requirements — Document":
    st.header("Requirements — From Document")
    st.caption(
        "CLI: `py requirements_gathering/test_requirements.py --source document --file path/to/file.txt`"
    )
    st.info("Path is relative to `core/design/agents/` (same as CLI).")

    doc_path = st.text_input(
        "Document Path",
        value="requirements_gathering/requirements_template.txt",
    )

    if st.button("Run", disabled=not doc_path):
        with st.spinner("Calling Requirements Agent..."):
            status, data = post("/requirements/from-document", {"document_path": doc_path})
        print(data)
        if status and status < 400:
            st.info(f"JSON saved to: `{data.get('output_path', '')}`")
            st.info(f"Markdown saved to: `{data.get('markdown_path', '')}`")
            with st.expander("Full Result", expanded=False):
                st.json(data.get("result", data))
        else:
            show_response(status, data)


# 4. Data Model ────────────────────────────────────────────────────────────────
elif page == "Data Model":
    st.header("Data Model Agent")
    st.caption(
        "CLI: `py data_model/test_data_model.py --ticket SCRUM-5`  "
        "or  `py data_model/test_data_model.py --requirements <path> [--schema <path>]`"
    )

    dm_ticket = st.text_input("Jira Ticket ID", value="SCRUM-5", key="dm_ticket")
    payload   = {"ticket_id": dm_ticket.strip()} if dm_ticket.strip() else {}
    disabled  = not dm_ticket.strip()

    schema_path = st.text_input(
        "Schema CSV path (optional)",
        value="data_model/sample_input/table_schema.csv",
        key="dm_schema",
    )

    if st.button("Run", disabled=disabled):
        if schema_path.strip():
            payload["schema_path"] = schema_path.strip()

        with st.spinner("Calling Data Model Agent..."):
            status, data = post("/data-model", payload)
        print(data)
        if status and status < 400:
            files = data.get("output_files", {})
            st.subheader("Output Files")
            st.write(f"- **Summary JSON** (use in Implementation Steps): `{files.get('summary_json')}`")
            st.write(f"- **ER Diagram (.mmd)**: `{files.get('er_diagram_mmd')}`")
            st.write(f"- **Mapping CSV**: `{files.get('mapping_csv')}`")

            with st.expander("Handoff Summary", expanded=True):
                st.json(data.get("handoff_summary", {}))
            with st.expander("Source to Target Mapping", expanded=True):
                st.json(data.get("source_target_mapping", {}))
            with st.expander("ER Diagram", expanded=True):
                mermaid_code = data.get("er_mermaid_diagram", "")
                if mermaid_code:
                    import streamlit.components.v1 as components
                    html = f"""
                    <div class="mermaid">{mermaid_code}</div>
                    <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
                    <script>mermaid.initialize({{startOnLoad: true}});</script>
                    """
                    components.html(html, height=500, scrolling=True)
                else:
                    st.info("No ER diagram available.")
        else:
            show_response(status, data)


# 5. Architecture ──────────────────────────────────────────────────────────────
elif page == "Architecture":
    st.header("Architecture Agent")
    st.caption(
        "CLI: `py architecture/test_architecture.py --ticket SCRUM-5`  "
        "or  `py architecture/test_architecture.py --input <requirements_path>`"
    )

    arch_ticket   = st.text_input("Jira Ticket ID", value="SCRUM-5", key="arch_ticket")
    arch_payload  = {"ticket_id": arch_ticket.strip()} if arch_ticket.strip() else {}
    arch_disabled = not arch_ticket.strip()

    if st.button("Run", disabled=arch_disabled):
        with st.spinner("Calling Architecture Agent..."):
            status, data = post("/architecture", arch_payload)
        print(data)
        if status and status < 400:
            files = data.get("output_files", {})
            st.subheader("Output Files")
            st.write(f"- **Summary JSON** (use in Implementation Steps): `{files.get('summary_json')}`")
            st.write(f"- **Architecture Report (.md)**: `{files.get('report_md')}`")
            st.write(f"- **Flow Diagram (.mmd)**: `{files.get('flow_mmd')}`")
  
            with st.expander("Handoff Summary", expanded=True):
                st.json(data.get("handoff_summary", {}))
            with st.expander("Overall Manifest Summary", expanded=True):
                st.json(data.get("manifest_summary", {}))
        else:
            show_response(status, data)


# 6. Implementation Steps ──────────────────────────────────────────────────────
elif page == "Implementation Steps":
    st.header("Implementation Steps Agent")
    st.caption(
        "CLI: `py implementation_steps/test_impl_steps.py --ticket SCRUM-5`  "
        "or  `py implementation_steps/test_impl_steps.py --type ... --project ...`"
    )

    impl_ticket   = st.text_input("Jira Ticket ID", value="SCRUM-5", key="impl_ticket")
    payload       = {"ticket_id": impl_ticket.strip()} if impl_ticket.strip() else {}
    impl_disabled = not impl_ticket.strip()
    st.caption("request_type and project_name are derived automatically from the ticket metadata.")

    if st.button("Run", disabled=impl_disabled):

        with st.spinner("Calling Implementation Steps Agent..."):
            status, data = post("/implementation-steps", payload)
        print(data)
        if status and status < 400:
            st.info(f"Output saved to: `{data.get('output_path')}`")
            with st.expander("Implementation Plan (Markdown)", expanded=True):
                st.markdown(data.get("markdown", ""))
        else:
            show_response(status, data)


# 7. Full Pipeline ─────────────────────────────────────────────────────────────
elif page == "Full Pipeline":
    st.header("Full Pipeline")
    st.caption(
        "CLI: `py orchestration/orchestrator.py --ticket SCRUM-5`  "
        "or  `py orchestration/orchestrator.py --type ... --project ... --requirements ... [--schema ...]`"
    )
    st.info("Runs Data Model + Architecture then Implementation Steps in sequence.")

    pipe_ticket   = st.text_input("Jira Ticket ID", value="SCRUM-5", key="pipe_ticket")
    pipe_payload: dict = {"ticket_id": pipe_ticket.strip()} if pipe_ticket.strip() else {}
    pipe_disabled = not pipe_ticket.strip()
    st.caption("request_type and project_name are derived automatically from the ticket metadata.")

    schema_path = st.text_input(
        "Schema CSV path (optional — used by Data Model)",
        value="data_model/sample_input/table_schema.csv",
        key="pipe_schema",
    )

    if st.button("Run Pipeline", disabled=pipe_disabled):
        if schema_path.strip():
            pipe_payload["schema_path"] = schema_path.strip()

        with st.spinner("Running full pipeline — this may take a few minutes..."):
            status, data = post("/pipeline", pipe_payload)
        print(data)
        if status and status < 400:
            dm   = data.get("data_model")
            arch = data.get("architecture")
            impl = data.get("implementation_steps", {})

            # Data Model + Architecture — only shown for new development / enhancement
            if dm is not None or arch is not None:
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Data Model")
                    if isinstance(dm, dict) and "error" in dm:
                        st.error(dm["error"])
                    else:
                        st.success("Done")
                        st.write(f"File: `{data.get('data_model_path')}`")
                        with st.expander("Summary"):
                            st.json(dm or {})

                with col2:
                    st.subheader("Architecture")
                    if isinstance(arch, dict) and "error" in arch:
                        st.error(arch["error"])
                    else:
                        st.success("Done")
                        st.write(f"File: `{data.get('architecture_path')}`")
                        with st.expander("Summary"):
                            st.json(arch or {})

            # Implementation Steps — always shown
            st.subheader("Implementation Steps")
            if isinstance(impl, dict) and impl.get("skipped"):
                st.warning(impl.get("reason", "Skipped"))
            elif isinstance(impl, dict) and "error" in impl:
                st.error(impl["error"])
            else:
                st.success("Done")
                st.info(f"Output saved to: `{impl.get('output_path')}`")
                with st.expander("Implementation Plan (Markdown)", expanded=True):
                    st.markdown(impl.get("markdown", ""))
        else:
            show_response(status, data)


# 8. View Outputs ──────────────────────────────────────────────────────────────
elif page == "View Outputs":
    st.header("View Outputs")
    st.caption("Lists all output files produced by the agents (newest first).")

    if st.button("Refresh"):
        status, data = get("/outputs")

        if status and status < 400:
            tabs = st.tabs(["Requirements", "Data Model", "Architecture", "Mermaid→DrawIO", "Implementation Steps"])

            with tabs[0]:
                req = data.get("requirements", {})
                for label, key in [("JSON", "json"), ("Markdown", "markdown")]:
                    files = req.get(key, [])
                    st.markdown(f"**{label}**")
                    if files:
                        for f in files:
                            st.code(f)
                    else:
                        st.caption("None")

            with tabs[1]:
                dm = data.get("data_model", {})
                for label, key in [
                    ("Summary JSON", "summary_json"),
                    ("ER Diagram (.mmd)", "er_diagram_mmd"),
                    ("Mapping CSV", "mapping_csv"),
                ]:
                    files = dm.get(key, [])
                    st.markdown(f"**{label}**")
                    if files:
                        for f in files:
                            st.code(f)
                    else:
                        st.caption("None")

            with tabs[2]:
                arc = data.get("architecture", {})
                for label, key in [
                    ("Summary JSON", "summary_json"),
                    ("Report (.md)", "report_md"),
                    ("Flow Diagram (.mmd)", "flow_mmd"),
                ]:
                    files = arc.get(key, [])
                    st.markdown(f"**{label}**")
                    if files:
                        for f in files:
                            st.code(f)
                    else:
                        st.caption("None")

            with tabs[3]:
                files = data.get("mermaid2drawio", [])
                if files:
                    for f in files:
                        st.code(f)
                else:
                    st.info("No .drawio files found.")

            with tabs[4]:
                files = data.get("implementation_steps", [])
                if files:
                    for f in files:
                        st.code(f)
                else:
                    st.info("No output files found.")
        else:
            show_response(status, data)
