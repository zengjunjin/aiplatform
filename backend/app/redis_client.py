import redis.asyncio as redis
from app.config import settings

redis_client: redis.Redis | None = None


def init_redis():
    global redis_client
    redis_client = redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    return redis_client


def get_redis() -> redis.Redis:
    return redis_client