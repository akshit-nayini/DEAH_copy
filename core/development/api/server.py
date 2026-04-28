"""Unified FastAPI application — DEAH Development Pod.

Mounts all routes under a single server so the UI team has one base URL.

Start:
    cd DEAH/core/development
    python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

Docs:
    http://localhost:8000/docs      (Swagger UI)
    http://localhost:8000/redoc     (ReDoc)

Environment variables:
    LLM_PROVIDER       anthropic | openai | gemini   (default: anthropic)
    LLM_API_KEY        API key for selected provider
    GIT_REPO_PATH      Path to git repo root (enables git commit step)
    GIT_PUSH_REMOTE    true | false  (default: false)
    OUTPUT_ROOT        Directory to write generated artifacts (default: output)

Endpoint map:
    POST  /api/v1/runs                          Code Gen — start a pipeline run
    GET   /api/v1/runs/{id}                     Code Gen — get run status
    POST  /api/v1/runs/{id}/checkpoint          Code Gen — submit checkpoint decision
    GET   /api/v1/runs                          Code Gen — list all runs
    POST  /api/v1/optimize-review               Code Gen — optimize + review existing files

    POST  /api/v1/deploy                        Deploy   — trigger deployment
    GET   /api/v1/deploy/{id}                   Deploy   — get deploy status
    GET   /api/v1/deploy                        Deploy   — list all deploys

    GET   /healthz                              Ops      — health check
"""
from __future__ import annotations
import logging
import os
import sys
from pathlib import Path

# sys.path setup — must be done before any local imports
_server_dir = Path(__file__).resolve().parent        # api/
_dev_root = _server_dir.parent                       # core/development/
_repo_root = _dev_root.parent.parent                 # DEAH/
_de_dev = _repo_root / "de_development"
for _p in [str(_dev_root), str(_repo_root), str(_de_dev)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.code_gen import router as code_gen_router
from api.routes.deploy import router as deploy_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(
    title="DEAH — Data Engineering Automation Hub API",
    description=(
        "Unified REST API for the DEAH Development Pod.\n\n"
        "**Code Gen Pod** — generates BigQuery DDL/DML/SP and Airflow DAGs from "
        "Implementation.md + mapping.csv with three human approval checkpoints.\n\n"
        "**Deploy Pod** — applies approved artifacts to GCP: BigQuery tables, "
        "stored procedures, Airflow DAGs, Dataflow Flex Templates, and audit table setup."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(code_gen_router)
app.include_router(deploy_router)


@app.get("/healthz", tags=["ops"])
def health_check() -> dict:
    return {"status": "ok", "service": "deah-development-pod"}
