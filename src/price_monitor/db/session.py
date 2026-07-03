from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from price_monitor.core.config import get_settings

_SessionLocal: sessionmaker[Session] | None = None


def create_db_engine(database_url: str | None = None) -> Engine:
    settings = get_settings()
    return create_engine(
        database_url or settings.database_url,
        pool_pre_ping=True,
        pool_recycle=settings.db_pool_recycle_seconds,
    )


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=create_db_engine(), autoflush=False, autocommit=False)
    return _SessionLocal


def get_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
