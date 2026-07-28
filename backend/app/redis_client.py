import redis.asyncio as redis

from app.config import settings

redis_client: redis.Redis | None = None


def init_redis():
    global redis_client
    redis_client = redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=2,
        health_check_interval=30,
        retry_on_timeout=True,
    )
    return redis_client


def get_redis() -> redis.Redis:
    return redis_client


# ---------- 摘要缓存 ----------

SUMMARY_KEY_PREFIX = "chat:session"
# Task 40: TTL 迁移到 config.py，原位置引用 settings
SUMMARY_TTL = settings.CHAT_SUMMARY_TTL  # 1 小时


def _summary_key(session_id: int) -> str:
    return f"{SUMMARY_KEY_PREFIX}:{session_id}:summary"


async def get_summary_cache(session_id: int) -> str | None:
    """获取缓存的对话摘要"""
    redis = get_redis()
    if not redis:
        return None
    return await redis.get(_summary_key(session_id))


async def set_summary_cache(session_id: int, summary: str, ttl: int = SUMMARY_TTL) -> None:
    """缓存对话摘要"""
    redis = get_redis()
    if not redis:
        return
    await redis.set(_summary_key(session_id), summary, ex=ttl)
