"""
定时评估任务

每日凌晨 02:00（Asia/Shanghai）执行，自动评估 7 天内有文档变动的活跃 KB。
"""

import asyncio
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import or_, select

from app.database import async_session
from app.db.document import Document
from app.db.knowledge_base import KnowledgeBase
from app.services.evaluation_service import trigger_evaluation
from app.tasks.celery_app import celery_app

# 定时评估默认生成的问题数（与 API 默认值一致）
DEFAULT_NUM_QUESTIONS = 50

# 活跃窗口：7 天内有文档变动视为活跃 KB
ACTIVE_WINDOW_DAYS = 7


@celery_app.task(name="scheduled_evaluation_task")
def scheduled_evaluation_task() -> dict:
    """每日 02:00 自动评估 7 天内有文档变动的 KB。

    逻辑：
    1. 查询 7 天内有文档变动（created_at 或 updated_at）的活跃 KB
    2. 对每个 KB 调用 evaluation_service.trigger_evaluation(trigger_source='scheduled')
    3. 失败隔离：单个 KB 失败不影响其他 KB，logger.exception 记录后继续

    Returns:
        dict: 执行摘要，包含总数、成功数、失败数。
    """

    async def _run():
        cutoff = datetime.now(UTC) - timedelta(days=ACTIVE_WINDOW_DAYS)

        async with async_session() as db:
            # 查询 7 天内有文档变动的活跃 KB（排除软删除文档）
            # 使用 KB owner_id 作为触发者，owner 拥有读权限可绕过权限校验
            result = await db.execute(
                select(KnowledgeBase.id, KnowledgeBase.owner_id)
                .join(Document, Document.kb_id == KnowledgeBase.id)
                .where(
                    Document.deleted_at.is_(None),
                    or_(
                        Document.created_at > cutoff,
                        Document.updated_at > cutoff,
                    ),
                )
                .distinct()
            )
            active_kbs = result.all()

        if not active_kbs:
            logger.info(
                "No active KBs with document changes in the last 7 days, skipping scheduled evaluation"
            )
            return {
                "status": "skipped",
                "reason": "no_active_kbs",
                "total": 0,
                "succeeded": 0,
                "failed": 0,
            }

        logger.info(f"Scheduled evaluation: found {len(active_kbs)} active KBs to evaluate")

        succeeded = 0
        failed = 0
        for kb_id, owner_id in active_kbs:
            # 失败隔离：单个 KB 失败不影响其他 KB
            try:
                async with async_session() as db:
                    await trigger_evaluation(
                        kb_id=kb_id,
                        num_questions=DEFAULT_NUM_QUESTIONS,
                        user_id=owner_id,
                        db=db,
                        trigger_source="scheduled",
                    )
                succeeded += 1
                logger.info(f"Scheduled evaluation dispatched for KB {kb_id}")
            except Exception:
                # logger.exception 记录完整堆栈，继续处理下一个 KB
                failed += 1
                logger.exception(
                    f"Scheduled evaluation failed for KB {kb_id}, continuing with next KB"
                )

        logger.info(
            f"Scheduled evaluation completed: total={len(active_kbs)} succeeded={succeeded} failed={failed}"
        )
        return {
            "status": "completed",
            "total": len(active_kbs),
            "succeeded": succeeded,
            "failed": failed,
        }

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()
