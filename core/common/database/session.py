"""
Common database session factory.

Usage: each agent provides its own concrete session.py (e.g.
core/requirements_pod/db/session.py) that calls make_session_factory()
with its own DATABASE_URL, then re-exports engine, SessionLocal, get_db.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator


def make_session_factory(database_url: str, debug: bool = False):
    """Return (engine, SessionLocal) for the given DATABASE_URL."""
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if "sqlite" in database_url else {},
        echo=debug,
    )
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, session_local


def make_get_db(session_local):
    """Return a FastAPI-compatible get_db() dependency for the given SessionLocal."""
    def get_db() -> Generator[Session, None, None]:
        db = session_local()
        try:
            yield db
        finally:
            db.close()
    return get_db
