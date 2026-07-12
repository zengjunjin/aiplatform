import json
import time
from typing import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.chat_session import ChatSession
from app.db.chat_message import ChatMessage
from app.db.knowledge_base import KnowledgeBase
from app.core.exceptions import NotFoundError, ForbiddenError
from app.schemas.chat import SessionCreate, SessionUpdate, MessageCreate
from app.redis_client import get_redis
from loguru import logger


async def create_session(req: SessionCreate, user_id: int, db: AsyncSession) -> ChatSession:
    session = ChatSession(user_id=user_id, kb_id=req.kb_id, title=req.title)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    logger.info(f"Session created: id={session.id} user={user_id} kb={req.kb_id}")
    return session


async def list_sessions(user_id: int, db: AsyncSession, page: int = 1, page_size: int = 20):
    count_result = await db.execute(
        select(func.count()).where(ChatSession.user_id == user_id)
    )
    total = count_result.scalar_one()
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return result.scalars().all(), total


async def get_session(session_id: int, user_id: int, db: AsyncSession) -> ChatSession:
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise NotFoundError("Session not found")
    if session.user_id != user_id:
        raise ForbiddenError("Access denied")
    return session


async def update_session(session_id: int, req: SessionUpdate, user_id: int, db: AsyncSession) -> ChatSession:
    session = await get_session(session_id, user_id, db)
    if req.title is not None:
        session.title = req.title
    if req.kb_id is not None:
        session.kb_id = req.kb_id
    await db.commit()
    await db.refresh(session)
    logger.info(f"Session updated: id={session_id} user={user_id}")
    return session


async def delete_session(session_id: int, user_id: int, db: AsyncSession):
    session = await get_session(session_id, user_id, db)
    redis = get_redis()
    if redis:
        await redis.delete(f"chat:session:{session_id}:context")
    await db.delete(session)
    await db.commit()
    logger.info(f"Session deleted: id={session_id} user={user_id}")


async def get_messages(session_id: int, user_id: int, db: AsyncSession, page: int = 1, page_size: int = 50):
    await get_session(session_id, user_id, db)
    count_result = await db.execute(
        select(func.count()).where(ChatMessage.session_id == session_id)
    )
    total = count_result.scalar_one()
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return result.scalars().all(), total


async def get_history_context(session_id: int, limit: int = 8) -> list[dict]:
    '''从 Redis 获取最近 N 轮历史'''
    redis = get_redis()
    if not redis:
        return []
    raw = await redis.lrange(f"chat:session:{session_id}:context", 0, limit - 1)
    messages = []
    for item in reversed(raw):
        try:
            messages.append(json.loads(item))
        except json.JSONDecodeError:
            continue
    return messages


async def append_to_context(session_id: int, role: str, content: str):
    '''追加消息到 Redis 上下文'''
    redis = get_redis()
    if not redis:
        return
    msg = json.dumps({"role": role, "content": content}, ensure_ascii=False)
    await redis.lpush(f"chat:session:{session_id}:context", msg)
    await redis.expire(f"chat:session:{session_id}:context", 86400)
    # Keep only last 20 messages
    await redis.ltrim(f"chat:session:{session_id}:context", 0, 19)


async def save_message(
    session_id: int,
    role: str,
    content: str,
    db: AsyncSession,
    references: list | None = None,
    token_input: int | None = None,
    token_output: int | None = None,
    latency_ms: int | None = None,
    summary_snapshot: str | None = None,
) -> ChatMessage:
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        referenced_chunks=references,
        token_input=token_input,
        token_output=token_output,
        latency_ms=latency_ms,
        summary_snapshot=summary_snapshot,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


# ---------- Phase F3: 流式生成取消 ----------

CANCEL_KEY_PREFIX = "chat:cancel"


def _cancel_key(session_id: int) -> str:
    """取消标志的 Redis key（session 级别）。"""
    return f"{CANCEL_KEY_PREFIX}:session:{session_id}:current"


async def request_cancel(session_id: int, ttl: int = 300) -> None:
    """设置取消标志，流式生成循环在下一次检查时会停止。TTL=5min 自动清理。"""
    redis = get_redis()
    if not redis:
        return
    await redis.set(_cancel_key(session_id), "1", ex=ttl)


async def is_cancelled(session_id: int) -> bool:
    """检查是否被请求取消。"""
    redis = get_redis()
    if not redis:
        return False
    if await redis.exists(_cancel_key(session_id)):
        return True
    return False


async def clear_cancel(session_id: int) -> None:
    """生成结束/取消后清理标志。"""
    redis = get_redis()
    if not redis:
        return
    await redis.delete(_cancel_key(session_id))
