FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY core/design/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core/ ./core/

EXPOSE 8082

# Run from repo root so sys.path manipulation in main.py resolves correctly
CMD ["uvicorn", "core.design.api.main:app", "--host", "0.0.0.0", "--port", "8082"]
