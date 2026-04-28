from abc import ABC, abstractmethod


class BaseStorageProvider(ABC):
    @abstractmethod
    async def write(self, path: str, data: bytes) -> str:
        """Write bytes to the given path. Returns the storage path."""
        raise NotImplementedError

    @abstractmethod
    async def read(self, path: str) -> bytes:
        """Read and return the bytes at the given storage path."""
        raise NotImplementedError

    @abstractmethod
    async def list_files(self, prefix: str = "") -> list[dict]:
        """List files under the given prefix. Returns list of dicts with at least 'name' and 'size'."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Delete the file at the given storage path. No-op if the file does not exist."""
        raise NotImplementedError
