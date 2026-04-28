FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmupdf-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY core/requirements_pod/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only what the app needs (build context is repo root)
COPY core/ ./core/

EXPOSE 8000

CMD ["uvicorn", "core.requirements_pod.main:app", "--host", "0.0.0.0", "--port", "8000"]
