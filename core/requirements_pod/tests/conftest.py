import json
import os
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from core.requirements_pod.database.models import Base
from core.requirements_pod.database.session import get_db
from core.requirements_pod.config import get_settings, Settings
from core.utilities.llm.provider_base import BaseLLMProvider
from core.utilities.storage.base import BaseStorageProvider

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "mock_llm_response.json")

# ── In-memory SQLite ──────────────────────────────────────────────────────────

TEST_DATABASE_URL = "sqlite:///:memory:"

# StaticPool ensures all threads share the same SQLite in-memory connection.
# Without it, SingletonThreadPool gives each thread its own empty in-memory DB,
# so tables created in the test thread are invisible to the ASGI event-loop thread.
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db() -> Session:
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


# ── Mock LLM provider ─────────────────────────────────────────────────────────

class _MockLLM(BaseLLMProvider):
    async def extract_tasks(self, text: str, system_prompt: str) -> list[dict]:
        with open(FIXTURE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)


@pytest.fixture
def mock_llm() -> BaseLLMProvider:
    return _MockLLM()


# ── Mock storage provider ─────────────────────────────────────────────────────

class _MockStorage(BaseStorageProvider):
    def __init__(self):
        self._store: dict[str, bytes] = {}

    async def write(self, path: str, data: bytes) -> str:
        self._store[path] = data
        return path

    async def read(self, path: str) -> bytes:
        if path not in self._store:
            raise FileNotFoundError(f"Not found in mock storage: {path}")
        return self._store[path]

    async def list_files(self, prefix: str = "") -> list[dict]:
        return [
            {"name": k, "size": len(v), "updated": None}
            for k, v in self._store.items()
            if k.startswith(prefix)
        ]

    async def delete(self, path: str) -> None:
        self._store.pop(path, None)


@pytest.fixture
def mock_storage() -> _MockStorage:
    return _MockStorage()


# ── Test settings override ────────────────────────────────────────────────────

@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        DATABASE_URL=TEST_DATABASE_URL,
        LLM_PROVIDER="mock",
        STORAGE_PROVIDER="local",
        PROJECT_CONTEXT_FILE="./docs/project_context.md",
    )


# ── FastAPI TestClient ────────────────────────────────────────────────────────

@pytest.fixture
def client(db: Session, mock_llm: BaseLLMProvider, mock_storage: _MockStorage, test_settings: Settings):
    from core.requirements_pod.main import app
    from core.requirements_pod.api.v1.files import _get_llm, _get_storage

    def override_db():
        try:
            yield db
        finally:
            pass

    def override_llm():
        return mock_llm

    def override_storage():
        return mock_storage

    def override_settings():
        return test_settings

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[_get_llm] = override_llm
    app.dependency_overrides[_get_storage] = override_storage
    app.dependency_overrides[get_settings] = override_settings

    # Patch the module-level engine imported by main.py's lifespan so it uses
    # the in-memory SQLite engine instead of the production DB from config.env.
    from unittest.mock import patch
    import core.requirements_pod.main as _main_mod
    with patch.object(_main_mod, "engine", test_engine):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()
