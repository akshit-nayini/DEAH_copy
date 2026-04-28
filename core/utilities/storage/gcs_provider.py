import asyncio
import io
import os
from google.cloud import storage as gcs
from core.utilities.storage.base import BaseStorageProvider


class GCSStorageProvider(BaseStorageProvider):
    """Stores files in Google Cloud Storage."""

    def __init__(
        self,
        bucket_name: str = os.environ.get("GCS_BUCKET_NAME", "deah"),
        project_id: str = os.environ.get("GCS_PROJECT_ID", "verizon-data"),
        credentials_path: str | None = os.environ.get("GCS_CREDENTIALS_PATH"),
    ):
        self.bucket_name = bucket_name
        if credentials_path and os.path.isfile(credentials_path):
            self._client = gcs.Client.from_service_account_json(
                credentials_path, project=project_id
            )
        else:
            self._client = gcs.Client(project=project_id)
        self._bucket = self._client.bucket(bucket_name)

    async def write(self, path: str, data: bytes) -> str:
        blob = self._bucket.blob(path)
        buf = io.BytesIO(data)
        await asyncio.to_thread(blob.upload_from_file, buf)
        return path

    async def read(self, path: str) -> bytes:
        blob = self._bucket.blob(path)
        return await asyncio.to_thread(blob.download_as_bytes)

    async def delete(self, path: str) -> None:
        blob = self._bucket.blob(path)
        await asyncio.to_thread(blob.delete)

    async def list_files(self, prefix: str = "") -> list[dict]:
        def _list():
            blobs = self._client.list_blobs(self.bucket_name, prefix=prefix or None)
            results = []
            for blob in blobs:
                results.append(
                    {
                        "name": blob.name,
                        "size": blob.size,
                        "updated": blob.updated.timestamp() if blob.updated else None,
                    }
                )
            return results

        return await asyncio.to_thread(_list)
