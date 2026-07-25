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
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# Task 27: 连接池配置统一引用 settings，避免与 async engine (database.py) 不一致
sync_engine = create_engine(
    settings.database_url_sync,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_timeout=settings.DB_POOL_TIMEOUT,
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
