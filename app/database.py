from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


class Base(DeclarativeBase):
    pass


@lru_cache(maxsize=1)
def get_database_url() -> str:
    return os.getenv(
        "PETOPS_DATABASE_URL",
        "postgresql+psycopg://petops:petops@localhost:5432/petops",
    )


@lru_cache(maxsize=1)
def get_engine():
    url = get_database_url()
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_connection, _):
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


def SessionLocal():
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def reset_database_caches():
    if get_engine.cache_info().currsize:
        try:
            get_engine().dispose()
        except Exception:
            pass
    get_engine.cache_clear()
    get_database_url.cache_clear()
