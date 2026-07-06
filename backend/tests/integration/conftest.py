"""集成测试 conftest - 使用真实 PostgreSQL + Redis

隔离策略:
- 使用现有 rag_platform 数据库（rag 用户无 CREATE DATABASE 权限）
- 使用独立 Redis DB: 15
- 每个测试函数执行前 TRUNCATE 所有表 + 清空 Redis
- 每个测试用不同 client IP 避免 limiter 限流
- 在 session 级事件循环中重建 async engine，避免跨 loop 问题
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from httpx import AsyncClient, ASGITransport

from app.config import settings
from app.main import app
import app.redis_client as redis_client_mod
import app.database as db_mod


def pytest_collection_modifyitems(config, items):
    """给所有集成测试加上 session scope 的 asyncio loop"""
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.asyncio(loop_scope="session"))


@pytest.fixture(scope="session")
def event_loop_policy():
    """session 级事件循环策略"""
    import asyncio
    return asyncio.WindowsSelectorEventLoopPolicy()


ALL_TABLES = [
    "audit_logs",
    "chat_messages",
    "chat_sessions",
    "document_chunks",
    "documents",
    "knowledge_bases",
    "users",
]

_ip_counter = 0

_sync_engine = None


def _get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(settings.database_url_sync)
    return _sync_engine


def _next_ip():
    global _ip_counter
    _ip_counter += 1
    return f"127.0.0.{_ip_counter}"


def _sync_truncate():
    tables_sql = ", ".join(ALL_TABLES)
    engine = _get_sync_engine()
    with engine.connect() as conn:
        conn.execute(text(f"TRUNCATE TABLE {tables_sql} RESTART IDENTITY CASCADE"))
        conn.commit()


@pytest.fixture(autouse=True)
def clean_db():
    _sync_truncate()
    yield
    _sync_truncate()


@pytest.fixture(scope="session")
async def _rebuild_async_engine():
    """在 session 级事件循环中重建 async engine，避免跨 loop 问题。"""
    old_engine = db_mod.engine
    old_session = db_mod.async_session

    from sqlalchemy.pool import NullPool
    new_engine = create_async_engine(
        settings.database_url_async,
        echo=False,
        poolclass=NullPool,
    )
    new_session = async_sessionmaker(
        new_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    db_mod.engine = new_engine
    db_mod.async_session = new_session

    yield new_engine, new_session

    db_mod.engine = old_engine
    db_mod.async_session = old_session
    await new_engine.dispose()


@pytest.fixture(scope="session")
async def test_redis(_rebuild_async_engine):
    import redis as redis_lib
    test_redis_client = redis_lib.asyncio.from_url(
        f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/15",
        encoding="utf-8", decode_responses=True,
    )
    await test_redis_client.flushdb()

    original = redis_client_mod.redis_client
    redis_client_mod.redis_client = test_redis_client

    yield test_redis_client

    await test_redis_client.flushdb()
    await test_redis_client.aclose()
    redis_client_mod.redis_client = original


@pytest.fixture
async def client(test_redis):
    """每个测试用不同 IP 避免限流。"""
    client_ip = _next_ip()
    transport = ASGITransport(app=app, client=(client_ip, 12345))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
