from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from price_monitor.core.config import get_settings


def create_db_engine(database_url: str | None = None) -> Engine:
    settings = get_settings()
    return create_engine(
        database_url or settings.database_url,
        pool_pre_ping=True,
        pool_recycle=settings.db_pool_recycle_seconds,
    )


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_db_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _session_factory


def get_session() -> Iterator[Session]:
    with get_session_factory()() as session:
        yield session
