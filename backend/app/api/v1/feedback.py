"""Feedback API 反馈路由：自 chat.py 抽离的 5 个 feedback 端点。

拆分目的（执行文档刀二 Step 1, 架构评审 P1-1）：
- chat.py 瘦身为 session CRUD + SSE 路由装配层，feedback 端点集中到独立模块，
- 职责清晰、可单独限流配置，
- 延迟 import feedback_service 提到模块顶部，消除 5 次函数体内 from app.services import feedback_service。

路由前缀路径保持不变（URL 一个字节不能变，前端已写死）：/chat/messages/... /chat/feedback/...），
由 APIRouter prefix="/chat"，与 chat.py 一致，保证 include_router 注册后路由路径字节级等同。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_admin_user, get_current_user
from app.config import RATE_LIMIT_DEFAULT, RATE_LIMIT_MODERATE
from app.core.middleware import limiter
from app.database import get_db
from app.db.user import User
from app.schemas.common import ok, paginated_ok
from app.schemas.feedback import FeedbackCreate, FeedbackDetailOut, FeedbackOut
from app.services import feedback_service

router = APIRouter(prefix="/chat", tags=["chat"])


def _parse_date_range(start_date: str | None, end_date: str | None) -> tuple:
    """将 ISO 格式字符串解析为 datetime，None 或空则返回 None。

    非法 ISO 字符串抛出 400 (HTTPException) 而非泄漏 500。
    """
    try:
        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date) if end_date else None
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format (expected ISO 8601): {e}",
        ) from e
    return start, end


@router.post("/messages/{message_id}/feedback")
@limiter.limit(RATE_LIMIT_MODERATE)  # Task 24: 反馈提交用更严格的限流
async def submit_feedback(
    message_id: int,
    request: Request,
    req: FeedbackCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交消息反馈（点赞/点踩）"""
    # Task 27: 审计日志在 service 层统一记录（区分新增/更新）
    feedback = await feedback_service.create_feedback(message_id, req, user.id, db)
    return ok(data=FeedbackOut.model_validate(feedback).model_dump())


@router.get("/messages/{message_id}/feedback")
@limiter.limit(RATE_LIMIT_DEFAULT)  # Task 24: 反馈查询限流
async def get_message_feedback(
    message_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取某条消息当前用户的反馈"""
    feedback = await feedback_service.get_feedback(message_id, user.id, db)
    return ok(data=FeedbackOut.model_validate(feedback).model_dump() if feedback else None)


@router.get("/feedback/stats")
@limiter.limit(RATE_LIMIT_DEFAULT)  # Task 24: 反馈统计限流
async def get_feedback_stats(
    request: Request,
    kb_id: int | None = None,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取反馈统计（admin 权限）"""
    stats = await feedback_service.get_feedback_stats(kb_id=kb_id, db=db)
    return ok(data=stats.model_dump())


@router.get("/feedback/analysis")
@limiter.limit(RATE_LIMIT_DEFAULT)  # Task 24: 反馈分析限流
async def get_feedback_analysis(
    request: Request,
    kb_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取反馈分析报告（admin 权限）"""
    start, end = _parse_date_range(start_date, end_date)

    analysis = await feedback_service.analyze_feedback(
        kb_id=kb_id,
        start_date=start,
        end_date=end,
        db=db,
    )
    return ok(data=analysis)


@router.get("/feedback/low-rated")
@limiter.limit(RATE_LIMIT_DEFAULT)  # Task 24: 低分反馈列表限流
async def get_low_rated_feedbacks(
    request: Request,
    kb_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    feedback_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取低分反馈列表（admin 权限）"""
    start, end = _parse_date_range(start_date, end_date)

    details, total = await feedback_service.get_low_rated_feedbacks(
        kb_id=kb_id,
        start_date=start,
        end_date=end,
        feedback_type=feedback_type,
        page=page,
        page_size=page_size,
        db=db,
    )
    # P1-1: 使用 FeedbackDetailOut schema 序列化替代手工拼 dict
    items = [FeedbackDetailOut.model_validate(d).model_dump() for d in details]
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)
