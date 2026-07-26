import json

from loguru import logger
from sqlalchemy import func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import ForbiddenError, NotFoundError
from app.db.chat_message import ChatMessage
from app.db.chat_session import ChatSession
from app.redis_client import get_redis
from app.schemas.chat import SessionCreate, SessionUpdate


async def create_session(req: SessionCreate, user_id: int, db: AsyncSession) -> ChatSession:
    session = ChatSession(user_id=user_id, kb_id=req.kb_id, title=req.title)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    logger.info(f"Session created: id={session.id} user={user_id} kb={req.kb_id}")
    return session


async def list_sessions(
    user_id: int, db: AsyncSession, page: int = 1, page_size: int = 20
) -> tuple[list[ChatSession], int]:
    count_result = await db.execute(select(func.count()).where(ChatSession.user_id == user_id))
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


async def update_session(
    session_id: int, req: SessionUpdate, user_id: int, db: AsyncSession
) -> ChatSession:
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


async def get_messages(
    session_id: int, user_id: int, db: AsyncSession, page: int = 1, page_size: int = 50
) -> tuple[list[ChatMessage], int]:
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


async def get_history_context(
    session_id: int,
    limit: int = settings.CHAT_HISTORY_LIMIT,
    db: AsyncSession | None = None,
) -> list[dict]:
    """从 Redis 获取最近 N 轮历史，Redis 不可用 / key 不存在 / 查询异常时回退 DB"""
    redis = get_redis()
    if redis:
        try:
            raw = await redis.lrange(f"chat:session:{session_id}:context", 0, limit - 1)
            if raw:
                messages = []
                for item in reversed(raw):
                    try:
                        messages.append(json.loads(item))
                    except json.JSONDecodeError:
                        continue
                return messages
        except Exception as e:
            logger.warning("Redis history fetch failed, fallback to DB: %s", e)
    # DB fallback: Redis 不可用 / key 不存在 / 查询异常
    if db is not None:
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
        msgs = result.scalars().all()
        # 反转为时间正序（与 Redis 路径一致）
        msgs = list(reversed(msgs))
        return [{"role": m.role, "content": m.content} for m in msgs]
    return []


async def append_to_context(session_id: int, role: str, content: str) -> None:
    """追加消息到 Redis 上下文

    使用 pipeline 将 lpush+expire+ltrim 合并为 1 次 RTT，
    SSE 流式场景每条消息节省 2 次 RTT。
    """
    redis = get_redis()
    if not redis:
        return
    msg = json.dumps({"role": role, "content": content}, ensure_ascii=False)
    key = f"chat:session:{session_id}:context"
    pipe = redis.pipeline(transaction=True)
    pipe.lpush(key, msg)
    pipe.expire(key, settings.CHAT_HISTORY_TTL_SECONDS)
    # Keep only last N messages (Task 13: 从 config 常量读取)
    pipe.ltrim(key, 0, settings.CHAT_HISTORY_REDIS_KEEP_RECENT - 1)
    await pipe.execute()


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
    prompt_version: str | None = None,
) -> ChatMessage:
    # Task 10: 记录使用的 prompt 模板版本号
    # 仅 assistant 消息需要记录 prompt_version（user 消息不经过 prompt 构建）
    if prompt_version is None and role == "assistant":
        from app.rag.prompt_builder import get_prompt_version

        prompt_version = get_prompt_version()
    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        referenced_chunks=references,
        token_input=token_input,
        token_output=token_output,
        latency_ms=latency_ms,
        summary_snapshot=summary_snapshot,
        prompt_version=prompt_version,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def create_assistant_placeholder(session_id: int, db: AsyncSession) -> ChatMessage:
    """H6: 预创建助手消息占位记录（空内容），用于在 LLM 流式开始前获取 message_id。

    客户端可在首个 delta 事件中拿到 message_id，便于流式过程中提交反馈。
    流式结束后由 update_assistant_message() 回填完整内容与元数据。
    """
    from app.rag.prompt_builder import get_prompt_version

    msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content="",
        prompt_version=get_prompt_version(),
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def update_assistant_message(
    message_id: int,
    db: AsyncSession,
    content: str,
    references: list | None = None,
    token_input: int | None = None,
    token_output: int | None = None,
    latency_ms: int | None = None,
    summary_snapshot: str | None = None,
) -> bool:
    """H6: 回填占位助手消息的完整内容与元数据。返回 True 表示更新成功。"""
    values: dict = {
        "content": content,
        "referenced_chunks": references,
        "token_input": token_input,
        "token_output": token_output,
        "latency_ms": latency_ms,
    }
    if summary_snapshot is not None:
        values["summary_snapshot"] = summary_snapshot
    stmt = sa_update(ChatMessage).where(ChatMessage.id == message_id).values(**values)
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


# ---------- Phase F3: 流式生成取消 ----------

CANCEL_KEY_PREFIX = "chat:cancel"


def _cancel_key(session_id: int) -> str:
    """取消标志的 Redis key（session 级别）。"""
    return f"{CANCEL_KEY_PREFIX}:session:{session_id}:current"


async def request_cancel(session_id: int, ttl: int = settings.CHAT_CANCEL_TTL) -> None:
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
    return bool(await redis.exists(_cancel_key(session_id)))


async def clear_cancel(session_id: int) -> None:
    """生成结束/取消后清理标志。"""
    redis = get_redis()
    if not redis:
        return
    await redis.delete(_cancel_key(session_id))
