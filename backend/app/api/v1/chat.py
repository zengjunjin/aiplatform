"""Chat 路由装配层（Blade 2 Step 3：瘦身后仅保留 APIRouter/Depends/限流）。

业务核心：
- SSE 流式编排 `ChatPipeline`（app/core/chat_pipeline.py），
- Feedback 路由已迁移至 `app/api/v1/feedback.py`。

依赖方向：chat.py → chat_pipeline → services / rag / models，
不再反向依赖 main.py（sse_registry 解耦）。
"""
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import (
    RATE_LIMIT_DEFAULT,
    RATE_LIMIT_MODERATE,
    RATE_LIMIT_STRICT,
    settings,
)
from app.services.chat_pipeline import ChatPipeline
from app.core.middleware import limiter
from app.database import get_db
from app.db.user import User
from app.schemas.chat import MessageCreate, MessageOut, SessionCreate, SessionOut, SessionUpdate
from app.schemas.common import ok, paginated_ok
from app.services import chat_service
from app.services.audit_service import log_audit

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions")
@limiter.limit(RATE_LIMIT_MODERATE)
async def create_session(
    req: SessionCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await chat_service.create_session(req, user.id, db)
    await log_audit(
        action="chat.session.create",
        user_id=user.id,
        request=request,
        details={"session_id": session.id},
    )
    return ok(data=SessionOut.model_validate(session).model_dump())


@router.get("/sessions")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def list_sessions(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(settings.CHAT_SESSION_PAGE_SIZE, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sessions, total = await chat_service.list_sessions(user.id, db, page, page_size)
    items = [SessionOut.model_validate(s).model_dump() for s in sessions]
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.get("/sessions/{session_id}")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def get_session(
    request: Request,
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await chat_service.get_session(session_id, user.id, db)
    messages, _ = await chat_service.get_messages(session_id, user.id, db, page=1, page_size=100)
    return ok(
        data={
            "session": SessionOut.model_validate(session).model_dump(),
            "messages": [MessageOut.model_validate(m).model_dump() for m in messages],
        }
    )


@router.put("/sessions/{session_id}")
@limiter.limit(RATE_LIMIT_MODERATE)
async def update_session(
    session_id: int,
    req: SessionUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await chat_service.update_session(session_id, req, user.id, db)
    await log_audit(
        action="chat.session.update",
        user_id=user.id,
        request=request,
        details={"session_id": session_id},
    )
    return ok(data=SessionOut.model_validate(session).model_dump())


@router.delete("/sessions/{session_id}")
@limiter.limit(RATE_LIMIT_MODERATE)
async def delete_session(
    session_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await chat_service.delete_session(session_id, user.id, db)
    await log_audit(
        action="chat.session.delete",
        user_id=user.id,
        request=request,
        details={"session_id": session_id},
    )
    return ok(message="Deleted")


@router.get("/sessions/{session_id}/messages")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def get_messages(
    request: Request,
    session_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(settings.CHAT_MESSAGE_PAGE_SIZE, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    messages, total = await chat_service.get_messages(session_id, user.id, db, page, page_size)
    items = [MessageOut.model_validate(m).model_dump() for m in messages]
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.post("/sessions/{session_id}/messages")
@limiter.limit(RATE_LIMIT_STRICT)
async def send_message(
    request: Request,
    session_id: int,
    req: MessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 使用注入的 db 验证 session 归属（短持有，路由返回后即释放）
    session = await chat_service.get_session(session_id, user.id, db)

    # SSE 并发计数器：__aenter__ 做 INCR + 429 检查；__aexit__ 由 ChatPipeline.stream finally 负责 DECR
    counter_cm: AsyncIterator[None] = ChatPipeline.make_sse_counter(user.id)
    counter_entered = False
    try:
        await counter_cm.__aenter__()
        counter_entered = True
        return StreamingResponse(
            ChatPipeline.stream(
                session_id, req.content, session.kb_id, session.title, req.model, counter_cm
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
    except Exception:
        # __aenter__ 自身抛 429 已在内部 DECR，不重复 __aexit__；
        # 其余 __aenter__ 成功后才进入此分支补做 __aexit__ 释放。
        logger.debug(f"SSE streaming setup failed for user_id={user.id}, re-raising")
        if counter_entered:
            await counter_cm.__aexit__(None, None, None)
        raise


@router.post("/sessions/{session_id}/cancel")
@limiter.limit(RATE_LIMIT_MODERATE)
async def cancel_generation(
    session_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消指定 session 当前进行中的流式生成（Redis 取消标志，下轮 token 检查生效）。"""
    await chat_service.get_session(session_id, user.id, db)
    await chat_service.request_cancel(session_id)
    await log_audit(
        action="chat.cancel", user_id=user.id, request=request, details={"session_id": session_id}
    )
    return ok(message="Cancellation requested")
