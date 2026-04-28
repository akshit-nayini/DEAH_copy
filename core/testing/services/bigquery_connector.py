"""
services/bigquery_connector.py
--------------------------------
BigQuery connector for the Testing POD.
Reads credentials from GOOGLE_APPLICATION_CREDENTIALS env var or
GCP_SA_KEY_PATH set in .env.

Usage (from bq_service.py):
    from services.bigquery_connector import create_bigquery_client
    client = create_bigquery_client()
"""

from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import GCP_PROJECT_ID, GCP_SA_KEY_PATH


def create_bigquery_client():
    """
    Create and return an authenticated BigQuery client.

    Authentication order:
    1. GCP_SA_KEY_PATH from .env  → service account JSON key file
    2. GOOGLE_APPLICATION_CREDENTIALS env var
    3. Application Default Credentials (gcloud auth application-default login)
    """
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError:
        raise ImportError(
            "google-cloud-bigquery not installed. "
            "Run: pip install google-cloud-bigquery"
        )

    key_path = GCP_SA_KEY_PATH or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

    if key_path and Path(key_path).exists():
        credentials = service_account.Credentials.from_service_account_file(
            key_path,
            scopes=["https://www.googleapis.com/auth/bigquery"],
        )
        client = bigquery.Client(project=GCP_PROJECT_ID, credentials=credentials)
        print(f"[BQConnector] authenticated via service account: {Path(key_path).name}")
    else:
        # Fall back to ADC (works on GCP VMs with attached SA)
        client = bigquery.Client(project=GCP_PROJECT_ID)
        print("[BQConnector] authenticated via Application Default Credentials")

    return client


def create_dataset_if_missing(client, dataset_id: str, location: str = "US") -> None:
    """Create a BigQuery dataset if it does not already exist."""
    from google.cloud import bigquery
    from google.api_core.exceptions import Conflict

    dataset_ref = f"{GCP_PROJECT_ID}.{dataset_id}"
    dataset     = bigquery.Dataset(dataset_ref)
    dataset.location = location

    try:
        client.create_dataset(dataset, timeout=30)
        print(f"[BQConnector] dataset '{dataset_ref}' created.")
    except Conflict:
        print(f"[BQConnector] dataset '{dataset_ref}' already exists — skipping creation.")