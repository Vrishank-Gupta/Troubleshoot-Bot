from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _get_engine():
    settings = get_settings()
    dsn = settings.pg_dsn
    kwargs: dict = {"echo": settings.is_dev}
    if dsn.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    elif "pooler.supabase.com" in dsn:
        kwargs["poolclass"] = NullPool
    return create_engine(dsn, **kwargs)


engine = _get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
