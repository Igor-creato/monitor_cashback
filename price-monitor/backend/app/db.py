from collections.abc import Generator

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def create_db_engine(database_url: str):
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


engine = create_db_engine(settings.database_url) if settings.database_url else None
SessionLocal = sessionmaker(bind=engine) if engine is not None else None


def get_db() -> Generator[Session]:
    if SessionLocal is None:
        raise HTTPException(status_code=500, detail="Database is not configured.")

    with SessionLocal() as session:
        yield session
