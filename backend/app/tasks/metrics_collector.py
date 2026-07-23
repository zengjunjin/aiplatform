import asyncio

from loguru import logger
from sqlalchemy import func, select

from app.core.metrics import (
    ACTIVE_SESSIONS,
    DB_POOL_IDLE,
    DB_POOL_IN_USE,
    DB_POOL_SIZE,
    RAG_DOCUMENT_COUNT,
    TOTAL_DOCUMENTS,
    TOTAL_USERS,
)
from app.database import async_session, engine
from app.db.chat_session import ChatSession
from app.db.document import Document
from app.db.user import User


async def update_business_metrics() -> None:
    try:
        async with async_session() as db:
            # Task 35: 合并 user/doc/session 三次 count 查询为单 SQL 子查询，减少 RTT
            counts_row = (
                await db.execute(
                    select(
                        select(func.count())
                        .select_from(User)
                        .scalar_subquery()
                        .label("user_count"),
                        select(func.count())
                        .select_from(Document)
                        .scalar_subquery()
                        .label("doc_count"),
                        select(func.count())
                        .select_from(ChatSession)
                        .scalar_subquery()
                        .label("session_count"),
                    )
                )
            ).one()
            TOTAL_USERS.set(counts_row.user_count or 0)
            TOTAL_DOCUMENTS.set(counts_row.doc_count or 0)
            ACTIVE_SESSIONS.set(counts_row.session_count or 0)

            # Task 1.4: 按 KB 分组查询文档数，更新 RAG_DOCUMENT_COUNT 指标
            # 仅统计未软删除的文档（Document.deleted_at IS NULL）
            kb_rows = await db.execute(
                select(Document.kb_id, func.count(Document.id))
                .where(Document.deleted_at.is_(None))
                .group_by(Document.kb_id)
            )
            for kb_id, count in kb_rows.all():
                RAG_DOCUMENT_COUNT.labels(kb_id=str(kb_id)).set(count or 0)
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
