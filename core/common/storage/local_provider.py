import asyncio
from pathlib import Path
from core.common.storage.base import BaseStorageProvider


class LocalStorageProvider(BaseStorageProvider):
    """Stores files on the local filesystem under base_path."""

    def __init__(self, base_path: str = "./local_storage"):
        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def write(self, path: str, data: bytes) -> str:
        target = self.base_path / path

        def _write():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        await asyncio.to_thread(_write)
        return str(Path(path))

    async def read(self, path: str) -> bytes:
        target = self.base_path / path
        if not target.exists():
            raise FileNotFoundError(f"File not found in local storage: {path}")
        return await asyncio.to_thread(target.read_bytes)

    async def delete(self, path: str) -> None:
        target = self.base_path / path

        def _delete():
            if target.exists():
                target.unlink()

        await asyncio.to_thread(_delete)

    async def list_files(self, prefix: str = "") -> list[dict]:
        search_root = self.base_path / prefix if prefix else self.base_path

        def _list():
            results = []
            if not search_root.exists():
                return results
            for entry in search_root.rglob("*"):
                if entry.is_file():
                    relative = entry.relative_to(self.base_path)
                    stat = entry.stat()
                    results.append(
                        {
                            "name": str(relative),
                            "size": stat.st_size,
                            "updated": stat.st_mtime,
                        }
                    )
            return results

        return await asyncio.to_thread(_list)
