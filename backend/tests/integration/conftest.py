"""集成测试 conftest - 使用真实 PostgreSQL + Redis

隔离策略:
- 使用现有 rag_platform 数据库（rag 用户无 CREATE DATABASE 权限）
- 使用独立 Redis DB: 15
- 每个测试函数执行前 TRUNCATE 所有表 + 清空 Redis + 重置 limiter
- 所有 async fixture 为 function-scoped, 确保在同一函数级事件循环中运行
- 中间件使用纯 ASGI 实现（非 BaseHTTPMiddleware），避免 call_next 跨 loop 问题
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from httpx import AsyncClient, ASGITransport

from app.config import settings
from app.main import app
import app.redis_client as redis_client_mod
import app.database as db_mod

# test_doc_management.py 和 test_all_api.py 是独立脚本（模块顶层调用 sys.exit
# 或使用 urllib.request + main() 函数），不是 pytest 测试模块。
# 若被 pytest 导入会导致收集阶段 INTERNALERROR 或 fixture 解析错误，
# 因此显式排除其收集。
collect_ignore = ["test_doc_management.py", "test_all_api.py"]


def pytest_collection_modifyitems(config, items):
    """给所有集成测试加上 integration marker。

    自动为 tests/integration/ 目录下所有收集到的测试项添加 integration 标记，
    使 ``-m "not integration"`` 能正确过滤。
    注意: 不再添加 asyncio(loop_scope="session"), 因为 pytest-asyncio 0.23.8
    在 session-scoped loop 和 function-scoped fixture 之间存在跨 loop 问题。
    所有 fixture 使用默认的 function-scoped 事件循环。
    """
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


ALL_TABLES = [
    "audit_logs",
    "chat_messages",
    "chat_sessions",
    "document_chunks",
    "documents",
    "knowledge_bases",
    "users",
]

_sync_engine = None


def _get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(settings.database_url_sync)
    return _sync_engine


def _sync_truncate():
    tables_sql = ", ".join(ALL_TABLES)
    engine = _get_sync_engine()
    with engine.connect() as conn:
        conn.execute(text(f"TRUNCATE TABLE {tables_sql} RESTART IDENTITY CASCADE"))
        conn.commit()


def _flush_redis_sync():
    """同步清空 Redis DB 15, 避免跨事件循环问题。

    使用独立的同步 Redis 连接, 不依赖 async test_redis。
    """
    import redis as redis_lib
    client = redis_lib.Redis(
        host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=15, decode_responses=True
    )
    client.flushdb()
    client.close()


def _reset_limiter():
    """重置 slowapi limiter 的 MemoryStorage 计数，避免测试间限流状态残留。"""
    from app.core.middleware import limiter
    limiter.reset()


@pytest.fixture
async def _rebuild_async_engine():
    """在函数级事件循环中重建 async engine，避免跨 loop 问题。

    使用 NullPool 确保每个连接独立创建, 不在事件循环间复用。
    """
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


@pytest.fixture
async def test_redis(_rebuild_async_engine):
    """每个测试函数创建独立的 async Redis client, 绑定到当前函数级事件循环。"""
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


@pytest.fixture(autouse=True)
def clean_db():
    """每个测试前清空 DB 表 + Redis + limiter 计数，确保测试隔离。

    全部使用同步操作 (psycopg2 + sync redis), 避免跨事件循环问题。
    async test_redis (function-scoped) 在 clean_db 之后运行, 创建独立的
    async Redis 连接绑定到当前函数级事件循环。
    """
    _sync_truncate()
    _flush_redis_sync()
    _reset_limiter()
    yield
    _sync_truncate()
    _flush_redis_sync()
    _reset_limiter()


@pytest.fixture
async def client(test_redis):
    """Function-scoped AsyncClient, 确保与 test_redis 在同一事件循环中。

    中间件已改为纯 ASGI 实现（非 BaseHTTPMiddleware），不再通过
    anyio.create_task_group() 创建后台任务，避免了跨事件循环问题。
    limiter 的 MemoryStorage 在每个测试前由 clean_db fixture 重置，
    因此使用固定 IP 不会触发限流。
    """
    transport = ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
