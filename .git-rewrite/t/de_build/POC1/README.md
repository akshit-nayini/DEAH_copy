# Data Engineering Hub — Code Generator & Optimizer Agent

> **POD:** Data Engineering Hub | **Ownership:** Rakesh + Elan + Vamsee | **Resources:** Varun, Sanay

Part of the **AgentHub** ecosystem. This agent consumes approved data model designs from the Data Design POD and generates production-ready, optimized, and quality-validated BigQuery data engineering code.

---

## What it does

```
Data Design POD (API) → Input Parser → DDL Gen → DML Gen → Self-Review → Output Package
```

| Module | Purpose |
|--------|---------|
| **Input Parser** | Validates and hydrates API payload from Data Design POD into internal objects |
| **DDL Generator** | Generates BigQuery `CREATE TABLE` with partitioning, clustering, PII tags, SCD-2 columns |
| **DML Generator** | Generates transformation SQL: SCD Type-2 MERGE, SCD Type-1, incremental append, full refresh |
| **Self-Review Agent** | Automated correctness + security review with PASS / CONDITIONAL PASS / FAIL verdicts |
| **Output Packager** | Organizes artifacts in Git-ready project structure with MANIFEST and review reports |

## Quick start

```bash
# Clone the repo
git clone https://github.com/ahemadshaik/DEAH.git
cd DEAH/de_build

# Set up environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the POC pipeline on the sample e-commerce data model
cd de_hub_agent
python3 main.py sample_payloads/ecommerce_medium.json

# Output will be in: de_hub_agent/output/poc-demo-001/
```

## Sample output

Running the pipeline on the 6-table e-commerce model produces:

```
output/poc-demo-001/
├── ddl/
│   ├── dim_customer.sql          # SCD-2 with surrogate key, effective dates, row hash
│   ├── dim_product.sql           # SCD-1 dimension
│   ├── dim_shipping_region.sql   # Reference dimension (full refresh)
│   ├── fct_orders.sql            # Fact table (incremental append)
│   ├── fct_daily_sales_summary.sql  # Derived aggregate (full refresh)
│   ├── stg_order_events.sql      # Staging (incremental)
│   └── _grants.sql               # PII access control statements
├── dml/
│   ├── merge_dim_customer.sql    # SCD-2 MERGE with FARM_FINGERPRINT + SHA256
│   ├── merge_dim_product.sql     # SCD-1 MERGE with hash comparison
│   ├── append_fct_orders.sql     # High-water-mark incremental + ROW_NUMBER dedup
│   ├── append_stg_order_events.sql
│   ├── refresh_fct_daily_sales_summary.sql
│   └── refresh_dim_shipping_region.sql
├── MANIFEST.json                 # File inventory with SHA-256 hashes
├── REVIEW_REPORT.json            # Machine-readable review results
└── REVIEW_REPORT.md              # Human-readable review summary
```

**Pipeline result:** Quality Score 85/100, Verdict: CONDITIONAL_PASS (5 PII masking warnings on dim_customer)

## Project structure

```
de_build/
├── de_hub_agent/
│   ├── main.py                   # Pipeline orchestrator (entry point)
│   ├── core/
│   │   └── models.py             # 30+ Pydantic models (input/output schemas)
│   ├── modules/
│   │   ├── input_parser/
│   │   │   └── parser.py         # Payload validation & hydration
│   │   ├── ddl_gen/
│   │   │   └── generator.py      # BigQuery DDL generation
│   │   ├── dml_gen/
│   │   │   └── generator.py      # SCD-2, SCD-1, incremental, full refresh
│   │   └── self_review/
│   │       └── reviewer.py       # Correctness + security checks
│   ├── config/
│   │   └── naming.yaml           # Naming conventions configuration
│   ├── prompts/                   # Jinja2 prompt templates (MVP-1+)
│   │   ├── ddl/bigquery/
│   │   ├── dml/bigquery/
│   │   └── review/
│   ├── sample_payloads/
│   │   └── ecommerce_medium.json # 6-table e-commerce test payload
│   └── tests/                    # pytest test suite
├── docs/                          # Architecture & design documents
├── requirements.txt
├── Dockerfile                     # Container build (coming Sprint 1)
├── .gitignore
└── README.md
```

## Supported patterns

| Pattern | BigQuery Implementation | Trigger |
|---------|------------------------|---------|
| **SCD Type-2** | MERGE + FARM_FINGERPRINT surrogate key + SHA256 hash diff + effective_from/to/is_current | `refresh_strategy: scd_type_2` |
| **SCD Type-1** | MERGE with hash comparison, overwrite on change | `refresh_strategy: scd_type_1` |
| **Incremental Append** | INSERT with high-water-mark + ROW_NUMBER dedup | `refresh_strategy: incremental_append` |
| **Full Refresh** | CREATE OR REPLACE TABLE AS SELECT | `refresh_strategy: full_refresh` |

## Self-review checks

| Dimension | Checks |
|-----------|--------|
| **Correctness** | DDL completeness (all tables/columns), DML mapping coverage, PK references, partition alignment |
| **Security** | Secret detection (7 regex patterns), PII masking validation, credential scanning |

Verdict logic: any CRITICAL → FAIL, only WARNINGs → CONDITIONAL PASS, clean → PASS.

## MVP roadmap

| Phase | Timeline | Scope |
|-------|----------|-------|
| **MVP-1** ← current | Apr 7 – May 1 | Input Parser + DDL Gen + DML Gen + Basic Self-Review + CLI |
| MVP-2 | May 4 – May 29 | dbt Model Gen + Airflow DAG Gen + Optimization Engine |
| MVP-3 | Jun 1 – Jun 26 | Full Self-Review (5 dims) + Auto-Fix + Testing POD handoff |
| MVP-4 | Jun 29 – Jul 24 | Multi-dialect (Snowflake, Spark) + PySpark Gen |

## Input payload contract

The agent receives a JSON payload from the Data Design POD via `POST /api/v1/generate`. See `sample_payloads/ecommerce_medium.json` for the full schema. Key fields:

- `data_model.tables[]` — table name, layer, columns, PKs, FKs, partition/cluster config, refresh strategy
- `pipeline_architecture` — pattern (batch/streaming), source systems, data flow
- `tech_stack` — target platform (bigquery), orchestrator, modeling tool
- `transformation_rules[]` — business rules as SQL expressions or natural language
- `column_mappings[]` — source-to-target column mapping with optional transform logic

## Team

| Role | Name | Focus Area |
|------|------|------------|
| Lead / Architect | Rakesh | Input parser, DDL/DML core, correctness review |
| Lead / LLM | Elan | Claude API integration, prompt templates, optimization |
| Lead / Integration | Vamsee | FastAPI, CLI, Testing POD handoff |
| Developer | Varun | Transformation rules, security review |
| Developer | Sanay | Infrastructure, naming enforcement, output packaging |

## Contributing

1. Create a feature branch from `main`: `git checkout -b feature/your-feature`
2. Follow naming conventions in `config/naming.yaml`
3. Add tests in `tests/` for any new module
4. Run `python3 -m pytest tests/` before pushing
5. Run `ruff check .` for linting
6. Open a PR against `main` with a description linking to the requirement ID (e.g., `req_cg_007`)

## Related documents

- [Requirements (83 items)](docs/) — `Agenthub_DataEngHub_CodeGen_SelfReview_Requirements.xlsx`
- [Architecture & System Design](docs/) — `DE_Hub_Architecture_SystemDesign.docx`
- [Implementation Plan](docs/) — `DE_Hub_Implementation_Plan.xlsx`
- [Prompt Templates](docs/) — `DE_Hub_Prompt_Templates.docx`
