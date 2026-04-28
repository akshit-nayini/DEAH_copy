FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Install only the packages that pip can resolve cleanly.
# Heavy/broken auto-added entries (apache-airflow, jaydebeapi, socket, decimal, common)
# are stdlib or too heavyweight for the API server — skip them.
RUN pip install --no-cache-dir \
    pydantic>=2.7 \
    python-dotenv>=1.0 \
    "fastapi>=0.111.0" \
    "uvicorn[standard]>=0.29.0" \
    "anthropic>=0.39.0" \
    "pymysql>=1.1.0" \
    claude-agent-sdk \
    "anyio>=4.0.0"

COPY core/ ./core/

EXPOSE 8000

# Run from /app so `from api.server import app` resolves under core/development/
CMD ["python", "-m", "uvicorn", "core.development.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
