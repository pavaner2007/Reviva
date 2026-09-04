"""
database.py — SQLAlchemy engine, session factory, and Base declarative.

The SQLite file is always placed at:
    <project_root>/backend/recovery_agent.db

The path is resolved relative to this file's location so the app works
correctly regardless of which directory the process is started from.
"""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# ---------------------------------------------------------------------------
# Path resolution — robust against different working directories
# ---------------------------------------------------------------------------
# This file lives at: recovery-agent/backend/app/database.py
# The database must live at: recovery-agent/backend/recovery_agent.db
_BACKEND_DIR: Path = Path(__file__).resolve().parent.parent
DATABASE_PATH: Path = _BACKEND_DIR / "recovery_agent.db"

DATABASE_URL: str = f"sqlite:///{DATABASE_PATH}"

# ---------------------------------------------------------------------------
# Engine — check_same_thread=False is required for SQLite + FastAPI
# ---------------------------------------------------------------------------
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,  # Set True temporarily to debug SQL queries
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Declarative base — all ORM models inherit from this
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency — yields a DB session and closes it after the request
# ---------------------------------------------------------------------------
def get_db():
    """
    Yields a SQLAlchemy session.
    Use as a FastAPI Depends() dependency.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helper for scripts (seed_data.py) that don't use FastAPI dependency injection
# ---------------------------------------------------------------------------
def create_session():
    """Return a plain SessionLocal instance for use in scripts."""
    return SessionLocal()


# ---------------------------------------------------------------------------
# Table creation helper — called at app startup
# ---------------------------------------------------------------------------
def init_db() -> None:
    """Create all tables if they do not already exist."""
    # Import models so SQLAlchemy's metadata is populated before create_all
    import app.models  # noqa: F401  # side-effect import

    Base.metadata.create_all(bind=engine)
