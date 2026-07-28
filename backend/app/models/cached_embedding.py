"""Embedding provider with Redis cache.

Wraps any BaseEmbeddingProvider to add Redis-based caching.
Cache key: embed:cache:{model}:{sha256(text)}
TTL: 7 days

Task 14: 添加 Prometheus 指标监控缓存命中率
- EMBEDDING_CACHE_HITS: cache hit 计数
- EMBEDDING_CACHE_MISSES: cache miss 计数
- EMBEDDING_CACHE_ERRORS: Redis 连接/解码错误计数
"""

import hashlib
import json

import redis.asyncio as redis_async
from loguru import logger

from app.config import settings
from app.core.metrics import EMBEDDING_CACHE_ERRORS, EMBEDDING_CACHE_HITS, EMBEDDING_CACHE_MISSES
from app.models.base import BaseEmbeddingProvider


class CachedEmbeddingProvider(BaseEmbeddingProvider):
    """Embedding provider with Redis cache layer."""

    def __init__(self, inner: BaseEmbeddingProvider):
        self.inner = inner
        self._redis: redis_async.Redis | None = None
        self._cache_ttl = settings.EMBEDDING_CACHE_TTL

    @property
    def dim(self) -> int:
        return self.inner.dim

    async def _get_redis(self) -> redis_async.Redis | None:
        if self._redis is None:
            try:
                self._redis = redis_async.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                await self._redis.ping()
            except Exception as e:
                # Task 14: Redis 连接失败 → 记录 error 指标
                EMBEDDING_CACHE_ERRORS.inc()
                logger.warning(f"Embedding cache redis init failed: {e}")
                self._redis = None
        return self._redis

    def reset_connection(self) -> None:
        """重置 Redis 连接，强制下次使用时在当前事件循环中重建。

        Celery worker 中每次任务创建新 event loop，单例的 Redis 连接
        绑定到创建时的 loop，跨 loop 复用会触发 'Event loop is closed'。
        """
        self._redis = None

    async def close(self) -> None:
        """关闭 Redis 连接池和内部 provider。"""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        await self.inner.close()

    def _cache_key(self, text: str) -> str:
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"embed:cache:{self.inner.model}:{h}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        redis = await self._get_redis()
        if not redis:
            # No Redis available, bypass cache
            return await self.inner.embed(texts)

        results: list[list[float] | None] = [None] * len(texts)
        cache_keys = [self._cache_key(t) for t in texts]
        miss_indices: list[int] = []
        miss_texts: list[str] = []

        # Try to get from cache
        cached = await redis.mget(cache_keys)
        for i, val in enumerate(cached):
            if val is not None:
                try:
                    results[i] = json.loads(val)
                    # Task 14: cache hit
                    EMBEDDING_CACHE_HITS.inc()
                except (json.JSONDecodeError, TypeError):
                    # Task 14: JSON 解析失败 → cache miss + error
                    EMBEDDING_CACHE_MISSES.inc()
                    EMBEDDING_CACHE_ERRORS.inc()
                    miss_indices.append(i)
                    miss_texts.append(texts[i])
            else:
                # Task 14: cache miss
                EMBEDDING_CACHE_MISSES.inc()
                miss_indices.append(i)
                miss_texts.append(texts[i])

        # Compute embeddings for misses
        if miss_texts:
            miss_results = await self.inner.embed(miss_texts)
            # Store in cache
            pipe = redis.pipeline()
            for idx, emb in zip(miss_indices, miss_results, strict=False):
                results[idx] = emb
                pipe.setex(cache_keys[idx], self._cache_ttl, json.dumps(emb))
            await pipe.execute()

        # All results should be filled now; validate count to avoid chunk/vector misalignment
        if any(r is None for r in results):
            raise ValueError(
                f"Embedding result count mismatch: expected {len(texts)}, "
                f"got {sum(1 for r in results if r is not None)}"
            )
        return results
