"""Database engine, connection pooling, and session management for ClipForge v2.0."""

from __future__ import annotations

import contextlib
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.paths import DB_PATH, ensure_dirs

ensure_dirs()

DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """Enforce Write-Ahead Logging (WAL) and foreign keys on all SQLite connections."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.execute("PRAGMA busy_timeout=5000;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.close()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=engine,
)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for yielding database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextlib.contextmanager
def db_session() -> Generator[Session, None, None]:
    """Context manager for background workers and CLI scripts."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Initialize database tables idempotently and migrate new columns."""
    from app.database import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    try:
        with engine.connect() as conn:
            cursor = conn.connection.cursor()
            cursor.execute("PRAGMA table_info(jobs)")
            existing_cols = {col[1] for col in cursor.fetchall()}
            if "request_json" not in existing_cols:
                cursor.execute("ALTER TABLE jobs ADD COLUMN request_json TEXT")
            if "checkpoint_json" not in existing_cols:
                cursor.execute("ALTER TABLE jobs ADD COLUMN checkpoint_json TEXT")
            conn.connection.commit()
    except Exception:
        pass
