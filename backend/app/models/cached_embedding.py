"""Embedding provider with Redis cache.

Wraps any BaseEmbeddingProvider to add Redis-based caching.
Cache key: embed:cache:{model}:{sha1(text)}
TTL: 7 days
"""
import hashlib
import json
from typing import Optional
import redis.asyncio as redis_async
from app.models.base import BaseEmbeddingProvider
from app.config import settings


class CachedEmbeddingProvider(BaseEmbeddingProvider):
    """Embedding provider with Redis cache layer."""

    def __init__(self, inner: BaseEmbeddingProvider):
        self.inner = inner
        self._redis: Optional[redis_async.Redis] = None
        self._cache_ttl = 7 * 24 * 3600  # 7 days

    @property
    def dim(self) -> int:
        return self.inner.dim

    async def _get_redis(self) -> Optional[redis_async.Redis]:
        if self._redis is None:
            try:
                self._redis = redis_async.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                await self._redis.ping()
            except Exception:
                self._redis = None
        return self._redis

    def _cache_key(self, text: str) -> str:
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()
        return f"embed:cache:{self.inner.model}:{h}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        redis = await self._get_redis()
        if not redis:
            # No Redis available, bypass cache
            return await self.inner.embed(texts)

        results: list[Optional[list[float]]] = [None] * len(texts)
        cache_keys = [self._cache_key(t) for t in texts]
        miss_indices: list[int] = []
        miss_texts: list[str] = []

        # Try to get from cache
        cached = await redis.mget(cache_keys)
        for i, val in enumerate(cached):
            if val is not None:
                try:
                    results[i] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    miss_indices.append(i)
                    miss_texts.append(texts[i])
            else:
                miss_indices.append(i)
                miss_texts.append(texts[i])

        # Compute embeddings for misses
        if miss_texts:
            miss_results = await self.inner.embed(miss_texts)
            # Store in cache
            pipe = redis.pipeline()
            for idx, emb in zip(miss_indices, miss_results):
                results[idx] = emb
                pipe.setex(cache_keys[idx], self._cache_ttl, json.dumps(emb))
            await pipe.execute()

        # All results should be filled now
        return [r for r in results if r is not None]
