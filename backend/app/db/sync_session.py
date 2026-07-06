"""Synchronous database session for Celery tasks.

Async SQLAlchemy (asyncpg) does not mix well with Celery's sync worker:
each run_async() creates+closes a new event loop, but the shared async
engine keeps connection objects tied to the first (now-closed) loop,
leading to "Event loop is closed" and "'NoneType' object has no
attribute 'send'" errors.

This module provides a synchronous SQLAlchemy session using psycopg2,
which is safe to use inside Celery tasks.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings


sync_engine = create_engine(
    settings.database_url_sync,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    future=True,
)

SyncSession = sessionmaker(
    bind=sync_engine,
    expire_on_commit=False,
    autoflush=False,
)


def get_sync_session() -> Session:
    """Return a new synchronous session. Use as a context manager."""
    return SyncSession()
