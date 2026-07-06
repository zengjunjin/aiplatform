import asyncio
from loguru import logger
from app.core.metrics import TOTAL_DOCUMENTS, TOTAL_USERS, ACTIVE_SESSIONS, DB_POOL_SIZE, DB_POOL_IN_USE, DB_POOL_IDLE
from app.database import engine, async_session
from sqlalchemy import select, func
from app.db.user import User
from app.db.document import Document
from app.db.chat_session import ChatSession


async def update_business_metrics():
    try:
        async with async_session() as db:
            user_count = await db.scalar(select(func.count()).select_from(User))
            TOTAL_USERS.set(user_count or 0)

            doc_count = await db.scalar(select(func.count()).select_from(Document))
            TOTAL_DOCUMENTS.set(doc_count or 0)

            session_count = await db.scalar(select(func.count()).select_from(ChatSession))
            ACTIVE_SESSIONS.set(session_count or 0)
    except Exception as e:
        logger.warning(f"Failed to update business metrics: {e}")


def update_db_pool_metrics():
    try:
        pool = engine.pool
        DB_POOL_SIZE.set(pool.size())
        DB_POOL_IDLE.set(pool.checkedin())
        DB_POOL_IN_USE.set(pool.checkedout())
    except Exception as e:
        logger.warning(f"Failed to update DB pool metrics: {e}")


async def metrics_collector_loop(interval: int = 60):
    logger.info(f"Starting metrics collector loop (interval={interval}s)")
    while True:
        try:
            await update_business_metrics()
            update_db_pool_metrics()
        except Exception as e:
            logger.error(f"Metrics collector error: {e}")
        await asyncio.sleep(interval)
