import json
from typing import Any

from loguru import logger

from app.config import settings
from app.redis_client import get_redis


async def cache_get(key: str) -> Any | None:
    try:
        redis = get_redis()  # get_redis is sync, returns Redis | None
        if not redis:
            return None
        data = await redis.get(key)
        if data:
            return json.loads(data)
        return None
    except Exception as e:
        logger.warning(f"cache_get failed for key '{key}': {e}")
        return None


async def cache_set(key: str, value: Any, ttl: int = settings.CACHE_DEFAULT_TTL) -> bool:
    try:
        redis = get_redis()
        if not redis:
            return False
        await redis.setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))
        return True
    except Exception as e:
        logger.warning(f"cache_set failed for key '{key}': {e}")
        return False


async def cache_delete(key: str) -> bool:
    try:
        redis = get_redis()
        if not redis:
            return False
        await redis.delete(key)
        return True
    except Exception as e:
        logger.warning(f"cache_delete failed for key '{key}': {e}")
        return False


async def cache_delete_pattern(pattern: str) -> int:
    try:
        redis = get_redis()
        if not redis:
            return 0
        keys = []
        async for key in redis.scan_iter(match=pattern):
            keys.append(key)
        if keys:
            await redis.delete(*keys)
        return len(keys)
    except Exception as e:
        logger.warning(f"cache_delete_pattern failed for pattern '{pattern}': {e}")
        return 0
