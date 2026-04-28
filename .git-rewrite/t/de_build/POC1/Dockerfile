FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY de_hub_agent/ ./de_hub_agent/

ENV PYTHONPATH=/app/de_hub_agent
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python3", "de_hub_agent/main.py"]
CMD ["de_hub_agent/sample_payloads/ecommerce_medium.json"]
