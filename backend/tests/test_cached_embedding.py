"""Tests for app.models.cached_embedding.CachedEmbeddingProvider"""
import pytest
import json
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch
from app.models.cached_embedding import CachedEmbeddingProvider
from app.models.base import BaseEmbeddingProvider


class FakeInnerProvider(BaseEmbeddingProvider):
    """测试用 inner provider"""
    model = "test-model"
    _dim = 768

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(i)] for i, _ in enumerate(texts)]


class TestCacheKey:
    def test_cache_key_format(self):
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        text = "hello"
        key = provider._cache_key(text)
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()
        assert key == f"embed:cache:test-model:{h}"

    def test_cache_key_deterministic(self):
        """相同 text → 相同 key"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        assert provider._cache_key("abc") == provider._cache_key("abc")

    def test_cache_key_different_for_different_text(self):
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        assert provider._cache_key("a") != provider._cache_key("b")


class TestDimProperty:
    def test_dim_delegates_to_inner(self):
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        assert provider.dim == 768

    def test_dim_reflects_inner_change(self):
        inner = FakeInnerProvider()
        provider = CachedEmbeddingProvider(inner)
        inner._dim = 1024
        assert provider.dim == 1024


class TestEmbedWithoutRedis:
    @pytest.mark.asyncio
    async def test_embed_empty_texts_returns_empty(self):
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        result = await provider.embed([])
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_bypasses_cache_when_redis_unavailable(self):
        """Redis 不可用 → 直接调用 inner.embed"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=None)):
            result = await provider.embed(["a", "b"])
        assert result == [[0.0], [1.0]]


class TestEmbedWithCache:
    @pytest.mark.asyncio
    async def test_embed_all_cache_miss(self):
        """全部 cache miss → 调 inner + 写缓存"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        redis_mock = MagicMock()
        redis_mock.mget = AsyncMock(return_value=[None, None])
        pipe_mock = MagicMock()
        pipe_mock.setex = MagicMock()
        pipe_mock.execute = AsyncMock()
        redis_mock.pipeline.return_value = pipe_mock

        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=redis_mock)):
            result = await provider.embed(["a", "b"])
        assert result == [[0.0], [1.0]]
        redis_mock.mget.assert_awaited_once()
        pipe_mock.setex.assert_called()  # 2 次
        assert pipe_mock.setex.call_count == 2
        pipe_mock.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_embed_all_cache_hit(self):
        """全部 cache hit → 不调 inner，不写缓存"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        redis_mock = MagicMock()
        redis_mock.mget = AsyncMock(return_value=[
            json.dumps([0.5, 0.6]),
            json.dumps([0.7, 0.8]),
        ])
        pipe_mock = MagicMock()
        pipe_mock.setex = MagicMock()
        pipe_mock.execute = AsyncMock()
        redis_mock.pipeline.return_value = pipe_mock

        # mock inner.embed 验证不被调用
        provider.inner.embed = AsyncMock()

        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=redis_mock)):
            result = await provider.embed(["a", "b"])
        assert result == [[0.5, 0.6], [0.7, 0.8]]
        provider.inner.embed.assert_not_awaited()
        pipe_mock.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_embed_partial_cache_hit(self):
        """部分 cache hit → 只对 miss 的调用 inner"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        redis_mock = MagicMock()
        # 第 0 个 hit，第 1 个 miss
        redis_mock.mget = AsyncMock(return_value=[json.dumps([0.5]), None])
        pipe_mock = MagicMock()
        pipe_mock.setex = MagicMock()
        pipe_mock.execute = AsyncMock()
        redis_mock.pipeline.return_value = pipe_mock

        provider.inner.embed = AsyncMock(return_value=[[1.0, 2.0]])

        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=redis_mock)):
            result = await provider.embed(["a", "b"])
        # a 来自缓存，b 来自 inner
        assert result == [[0.5], [1.0, 2.0]]
        provider.inner.embed.assert_awaited_once_with(["b"])
        pipe_mock.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_embed_handles_invalid_cached_json(self):
        """缓存中是非法 JSON → 视为 miss，重新计算"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        redis_mock = MagicMock()
        redis_mock.mget = AsyncMock(return_value=["not a json", None])
        pipe_mock = MagicMock()
        pipe_mock.setex = MagicMock()
        pipe_mock.execute = AsyncMock()
        redis_mock.pipeline.return_value = pipe_mock

        provider.inner.embed = AsyncMock(return_value=[[0.0], [1.0]])

        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=redis_mock)):
            result = await provider.embed(["a", "b"])
        # 两个都重新计算
        assert len(result) == 2
        provider.inner.embed.assert_awaited_once_with(["a", "b"])
        assert pipe_mock.setex.call_count == 2

    @pytest.mark.asyncio
    async def test_embed_cache_ttl_is_7_days(self):
        """缓存 TTL = 7*24*3600 = 604800 秒"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        assert provider._cache_ttl == 7 * 24 * 3600
        assert provider._cache_ttl == 604800

        redis_mock = MagicMock()
        redis_mock.mget = AsyncMock(return_value=[None])
        pipe_mock = MagicMock()
        pipe_mock.setex = MagicMock()
        pipe_mock.execute = AsyncMock()
        redis_mock.pipeline.return_value = pipe_mock

        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=redis_mock)):
            await provider.embed(["a"])

        # 验证 setex 的 TTL 参数
        args = pipe_mock.setex.call_args
        assert args[0][1] == 604800


class TestGetRedis:
    @pytest.mark.asyncio
    async def test_get_redis_caches_client(self):
        """_get_redis 第二次调用复用缓存的 client"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        fake_redis = MagicMock()
        fake_redis.ping = AsyncMock()

        with patch("app.models.cached_embedding.redis_async.from_url", return_value=fake_redis):
            r1 = await provider._get_redis()
            r2 = await provider._get_redis()
        assert r1 is fake_redis
        assert r2 is fake_redis
        # from_url 只调用一次
        fake_redis.ping.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_redis_returns_none_on_connection_failure(self):
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        with patch("app.models.cached_embedding.redis_async.from_url") as mock_from_url:
            mock_from_url.return_value.ping = AsyncMock(side_effect=Exception("connect failed"))
            result = await provider._get_redis()
        assert result is None
        # 再次调用也不会重试（_redis 已设为 None）
        # 注意：实现中失败时 _redis 仍是 None，所以下次会重试
        # 但本次断言重点是返回 None
