# WebApp

Full-stack web application for the DEAH AI Orchestration Platform. Provides a React frontend and three Spring Boot backends that proxy requests to FastAPI AI agents.

---

## Architecture Overview

```
Browser (port 6005)
    │
    ├── /api/v1/design/* ──► Design Backend (8082) ──► FastAPI Design Agent (9190)
    └── /api/*           ──► Requirements Backend (8080) ──► FastAPI Requirements Agent (8001)
```

---

## Directory Structure

```
WebApp/
├── frontend/           # React + TypeScript UI (Vite, port 6005)
├── backend/            # Spring Boot backends (Maven, Java 17)
│   └── src/main/java/com/prodapt/
│       ├── requirements/   # Port 8080
│       ├── design/         # Port 8082
│       └── development/    # (port TBD)
└── requirements_pod/   # Dockerised frontend (nginx, port 80)
```

---

## Frontend

**Stack:** React 18, TypeScript 5, Vite 5

**Dev server:** `http://0.0.0.0:6005`

### Setup

```bash
cd WebApp/frontend
npm install
npm run dev
```

### Vite Proxy Rules

| Prefix | Target | Backend |
|---|---|---|
| `/api/v1/design` | `http://localhost:8082` | Design |
| `/api` | `http://localhost:8080` | Requirements |

### Key Source Files

| Path | Purpose |
|---|---|
| `src/App.tsx` | Root component, global state, module orchestration |
| `src/modules/design.ts` | Design module sub-module definitions |
| `src/components/DetailPanel.tsx` | Side panel — input forms and run controls |
| `src/components/DesignInputModal.tsx` | Modal to collect Jira ticket ID / document path |
| `src/services/designApi.ts` | Typed client for Design backend endpoints |
| `src/services/requirementsApi.ts` | Typed client for Requirements backend endpoints |

---

## Backend

**Stack:** Java 17, Spring Boot 3.2.3, Maven, Spring WebFlux (WebClient)

Three Spring Boot applications share the same Maven project. Run each with its own Spring profile.

### Requirements Backend (port 8080)

```bash
cd WebApp/backend
mvn spring-boot:run
```

Config: `src/main/resources/application.yml`

FastAPI agent URL (env override): `REQUIREMENTS_AGENT_URL` (default `http://localhost:8001`)

### Design Backend (port 8082)

```bash
cd WebApp/backend
mvn spring-boot:run -Dspring-boot.run.arguments=--spring.config.name=application-design \
  -Dspring-boot.run.mainClass=com.prodapt.design.DesignApplication
```

Config: `src/main/resources/application-design.yml`

FastAPI agent URL (env override): `DESIGN_AGENT_URL` (default `http://35.209.107.68:9190`)

### Design Backend API Endpoints

All routes are prefixed with `/api/v1/design`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/requirements/from-jira` | Extract requirements from a Jira ticket |
| `POST` | `/requirements/from-document` | Extract requirements from a document |
| `POST` | `/data-model` | Generate data model |
| `POST` | `/architecture` | Generate architecture diagram |
| `POST` | `/implementation-steps` | Generate implementation steps |
| `POST` | `/pipeline` | Run full design pipeline |
| `GET` | `/outputs` | List generated output files |

---

## FastAPI Agents

These are Python services that the Spring Boot backends call internally.

### Requirements Agent

```bash
cd core/requirements
python3 -m uvicorn main:app --host 0.0.0.0 --port 8001
```

### Design Agent

```bash
cd core/design/api
python3 -m uvicorn main:app --host 0.0.0.0 --port 9190
```

> Note: run from inside `core/design/api/` — the `api/` directory has no `__init__.py` so the module path must be `main:app`, not `core.design.api.main:app`.

---

## Dockerised Frontend (requirements_pod)

```bash
cd WebApp/requirements_pod
docker build -t deah-frontend .
docker run -p 80:80 deah-frontend
```

---

## Port Reference

| Service | Port | Notes |
|---|---|---|
| Frontend (Vite dev) | 6005 | Proxies to backends |
| Requirements Backend | 8080 | Spring Boot |
| Design Backend | 8082 | Spring Boot, profile `design` |
| Requirements FastAPI Agent | 8001 | Python |
| Design FastAPI Agent | 9190 | Python (default: 35.209.107.68) |
| Frontend (Docker/nginx) | 80 | Production container |

---

## Environment Variables

| Variable | Default | Used By |
|---|---|---|
| `REQUIREMENTS_AGENT_URL` | `http://localhost:8001` | Requirements backend |
| `REQUIREMENTS_AGENT_TIMEOUT` | `300` | Requirements backend |
| `DESIGN_AGENT_URL` | `http://35.209.107.68:9190` | Design backend |
| `DESIGN_AGENT_TIMEOUT` | `600` | Design backend |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Both backends |
