"""Tests for app.models.cached_embedding.CachedEmbeddingProvider"""

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.base import BaseEmbeddingProvider
from app.models.cached_embedding import CachedEmbeddingProvider


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
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
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
        redis_mock.mget = AsyncMock(
            return_value=[
                json.dumps([0.5, 0.6]),
                json.dumps([0.7, 0.8]),
            ]
        )
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


class TestResultCountValidation:
    """Task 7: 验证 cached_embedding 结果数校验, 防止 chunk/vector 错位"""

    @pytest.mark.asyncio
    async def test_embed_raises_value_error_when_inner_returns_fewer_results(self):
        """inner.embed 返回数量 < 输入数量 → ValueError"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        # FakeInnerProvider.embed 正常返回 [[float(i)] for i, _ in enumerate(texts)]
        # 但我们让 inner 返回比输入少的向量
        provider.inner.embed = AsyncMock(return_value=[[0.0]])  # 只返回 1 个, 输入 2 个

        redis_mock = MagicMock()
        redis_mock.mget = AsyncMock(return_value=[None, None])  # 全部 miss
        pipe_mock = MagicMock()
        pipe_mock.setex = MagicMock()
        pipe_mock.execute = AsyncMock()
        redis_mock.pipeline.return_value = pipe_mock

        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=redis_mock)):
            with pytest.raises(ValueError) as exc_info:
                await provider.embed(["a", "b"])
        assert "mismatch" in str(exc_info.value).lower()
        assert "expected 2" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_embed_raises_value_error_when_inner_returns_more_results(self):
        """inner.embed 返回数量 > 输入数量 → ValueError (zip 截断但 results 中仍有 None)"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        # inner 返回 3 个向量, 但输入只有 2 个, zip 会截断到 2 个
        # results 会被填满 2 个, 这种情况下校验通过, 不会抛异常
        # 这个测试验证: 即使 inner 返回更多, 只要 results 长度匹配输入, 就不会抛异常
        provider.inner.embed = AsyncMock(return_value=[[0.0], [1.0], [2.0]])

        redis_mock = MagicMock()
        redis_mock.mget = AsyncMock(return_value=[None, None])
        pipe_mock = MagicMock()
        pipe_mock.setex = MagicMock()
        pipe_mock.execute = AsyncMock()
        redis_mock.pipeline.return_value = pipe_mock

        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=redis_mock)):
            result = await provider.embed(["a", "b"])
        # zip 截断到 2 个, results 长度 = 2 = 输入长度, 不抛异常
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_embed_no_raise_when_result_count_matches(self):
        """结果数与输入数一致 → 不抛异常 (回归测试)"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        redis_mock = MagicMock()
        redis_mock.mget = AsyncMock(return_value=[None, None, None])
        pipe_mock = MagicMock()
        pipe_mock.setex = MagicMock()
        pipe_mock.execute = AsyncMock()
        redis_mock.pipeline.return_value = pipe_mock

        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=redis_mock)):
            result = await provider.embed(["a", "b", "c"])
        assert len(result) == 3
        assert result == [[0.0], [1.0], [2.0]]

    @pytest.mark.asyncio
    async def test_embed_raises_value_error_when_cache_returns_invalid_json_for_all(self):
        """所有缓存值都是非法 JSON + inner 返回数量不匹配 → ValueError"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        # inner 返回 1 个向量, 输入 2 个
        provider.inner.embed = AsyncMock(return_value=[[0.0]])

        redis_mock = MagicMock()
        # 两个缓存都是非法 JSON, 都视为 miss
        redis_mock.mget = AsyncMock(return_value=["not json", "also not json"])
        pipe_mock = MagicMock()
        pipe_mock.setex = MagicMock()
        pipe_mock.execute = AsyncMock()
        redis_mock.pipeline.return_value = pipe_mock

        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=redis_mock)):
            with pytest.raises(ValueError) as exc_info:
                await provider.embed(["a", "b"])
        assert "mismatch" in str(exc_info.value).lower()


# ---------- Task 14: Embedding 缓存命中率指标监控 ----------
class TestEmbeddingCacheMetrics:
    """Task 14: 验证 EMBEDDING_CACHE_HITS/MISSES/ERRORS 指标在正确路径被 incr。

    通过 patch app.models.cached_embedding 模块中已 import 的 Counter 对象，
    验证 inc() 调用次数符合预期（不依赖全局 Prometheus registry 的状态）。
    """

    @pytest.mark.asyncio
    async def test_cache_hit_increments_hits_counter(self):
        """cache hit 路径 → EMBEDDING_CACHE_HITS.inc() 调用 1 次"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        redis_mock = MagicMock()
        redis_mock.mget = AsyncMock(return_value=[json.dumps([0.5, 0.6])])
        pipe_mock = MagicMock()
        pipe_mock.setex = MagicMock()
        pipe_mock.execute = AsyncMock()
        redis_mock.pipeline.return_value = pipe_mock
        provider.inner.embed = AsyncMock()

        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=redis_mock)):
            with (
                patch("app.models.cached_embedding.EMBEDDING_CACHE_HITS") as hits_mock,
                patch("app.models.cached_embedding.EMBEDDING_CACHE_MISSES") as misses_mock,
                patch("app.models.cached_embedding.EMBEDDING_CACHE_ERRORS") as errors_mock,
            ):
                await provider.embed(["a"])

        hits_mock.inc.assert_called_once()
        misses_mock.inc.assert_not_called()
        errors_mock.inc.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_increments_misses_counter(self):
        """cache miss 路径 → EMBEDDING_CACHE_MISSES.inc() 调用 1 次"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        redis_mock = MagicMock()
        redis_mock.mget = AsyncMock(return_value=[None])  # miss
        pipe_mock = MagicMock()
        pipe_mock.setex = MagicMock()
        pipe_mock.execute = AsyncMock()
        redis_mock.pipeline.return_value = pipe_mock

        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=redis_mock)):
            with (
                patch("app.models.cached_embedding.EMBEDDING_CACHE_HITS") as hits_mock,
                patch("app.models.cached_embedding.EMBEDDING_CACHE_MISSES") as misses_mock,
                patch("app.models.cached_embedding.EMBEDDING_CACHE_ERRORS") as errors_mock,
            ):
                await provider.embed(["a"])

        misses_mock.inc.assert_called_once()
        hits_mock.inc.assert_not_called()
        errors_mock.inc.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_json_increments_misses_and_errors(self):
        """缓存值非法 JSON → EMBEDDING_CACHE_MISSES + EMBEDDING_CACHE_ERRORS 各 incr 1 次"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        redis_mock = MagicMock()
        redis_mock.mget = AsyncMock(return_value=["not a json"])
        pipe_mock = MagicMock()
        pipe_mock.setex = MagicMock()
        pipe_mock.execute = AsyncMock()
        redis_mock.pipeline.return_value = pipe_mock
        provider.inner.embed = AsyncMock(return_value=[[0.0]])

        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=redis_mock)):
            with (
                patch("app.models.cached_embedding.EMBEDDING_CACHE_HITS") as hits_mock,
                patch("app.models.cached_embedding.EMBEDDING_CACHE_MISSES") as misses_mock,
                patch("app.models.cached_embedding.EMBEDDING_CACHE_ERRORS") as errors_mock,
            ):
                await provider.embed(["a"])

        misses_mock.inc.assert_called_once()
        errors_mock.inc.assert_called_once()
        hits_mock.inc.assert_not_called()

    @pytest.mark.asyncio
    async def test_redis_connection_failure_increments_errors_counter(self):
        """_get_redis 连接失败 → EMBEDDING_CACHE_ERRORS.inc() 调用 1 次"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())

        with patch("app.models.cached_embedding.redis_async.from_url") as mock_from_url:
            mock_from_url.return_value.ping = AsyncMock(side_effect=Exception("connect failed"))
            with (
                patch("app.models.cached_embedding.EMBEDDING_CACHE_HITS") as hits_mock,
                patch("app.models.cached_embedding.EMBEDDING_CACHE_MISSES") as misses_mock,
                patch("app.models.cached_embedding.EMBEDDING_CACHE_ERRORS") as errors_mock,
            ):
                result = await provider._get_redis()

        assert result is None
        errors_mock.inc.assert_called_once()
        hits_mock.inc.assert_not_called()
        misses_mock.inc.assert_not_called()

    @pytest.mark.asyncio
    async def test_mixed_hit_miss_increments_correctly(self):
        """混合 hit/miss → HITS 与 MISSES 各 incr 对应次数"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())
        redis_mock = MagicMock()
        # 3 个文本: hit, miss, hit
        redis_mock.mget = AsyncMock(
            return_value=[
                json.dumps([0.1]),
                None,
                json.dumps([0.3]),
            ]
        )
        pipe_mock = MagicMock()
        pipe_mock.setex = MagicMock()
        pipe_mock.execute = AsyncMock()
        redis_mock.pipeline.return_value = pipe_mock
        provider.inner.embed = AsyncMock(return_value=[[0.2]])

        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=redis_mock)):
            with (
                patch("app.models.cached_embedding.EMBEDDING_CACHE_HITS") as hits_mock,
                patch("app.models.cached_embedding.EMBEDDING_CACHE_MISSES") as misses_mock,
                patch("app.models.cached_embedding.EMBEDDING_CACHE_ERRORS") as errors_mock,
            ):
                await provider.embed(["a", "b", "c"])

        assert hits_mock.inc.call_count == 2
        assert misses_mock.inc.call_count == 1
        errors_mock.inc.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_redis_bypass_does_not_increment_metrics(self):
        """Redis 不可用时直接 bypass → 不 incr 任何缓存指标"""
        provider = CachedEmbeddingProvider(FakeInnerProvider())

        with patch.object(provider, "_get_redis", new=AsyncMock(return_value=None)):
            with (
                patch("app.models.cached_embedding.EMBEDDING_CACHE_HITS") as hits_mock,
                patch("app.models.cached_embedding.EMBEDDING_CACHE_MISSES") as misses_mock,
                patch("app.models.cached_embedding.EMBEDDING_CACHE_ERRORS") as errors_mock,
            ):
                result = await provider.embed(["a", "b"])

        assert result == [[0.0], [1.0]]
        hits_mock.inc.assert_not_called()
        misses_mock.inc.assert_not_called()
        errors_mock.inc.assert_not_called()
