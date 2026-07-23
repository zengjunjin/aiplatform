import time

from loguru import logger
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.base import Base

# Task 26: 慢查询阈值（秒），超过此值的 SQL 将以 warning 记录
_SLOW_QUERY_THRESHOLD_SECONDS = 0.1


# Task 26: before_cursor_execute / after_cursor_execute 事件监听
# 仅记录耗时 >100ms 的慢查询；不在 DEBUG 模式打印全部 SQL（移除 echo=settings.DEBUG）。
# 监听 Engine 类（而非具体实例），使同一组回调对 sync_engine 和 async_engine.sync_engine
# 均生效——SQLAlchemy 的事件分发会向所有 Engine 实例广播。
@event.listens_for(Engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._query_start_time = time.perf_counter()


@event.listens_for(Engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    start = getattr(context, "_query_start_time", None)
    if start is None:
        return
    elapsed = time.perf_counter() - start
    if elapsed > _SLOW_QUERY_THRESHOLD_SECONDS:
        # 截断 statement 前 200 字符避免日志过长
        logger.warning(f"Slow query ({elapsed:.3f}s): {statement[:200]}")


engine = create_async_engine(
    settings.database_url_async,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    # Task 26: PostgreSQL 服务端语句超时（30s），防止长查询拖垮连接池
    connect_args={"server_settings": {"statement_timeout": "30000"}},
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
