"""Tests for app.core.cache (Redis-backed cache helpers)"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from app.core import cache


@pytest.fixture
def redis_mock():
    r = MagicMock()
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock()
    r.delete = AsyncMock()
    r.scan_iter = MagicMock(return_value=iter([]))
    return r


class TestCacheGet:
    @pytest.mark.asyncio
    async def test_cache_get_returns_none_when_redis_unavailable(self):
        with patch("app.core.cache.get_redis", return_value=None):
            result = await cache.cache_get("foo")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_get_returns_none_when_key_missing(self, redis_mock):
        redis_mock.get = AsyncMock(return_value=None)
        with patch("app.core.cache.get_redis", return_value=redis_mock):
            result = await cache.cache_get("foo")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_get_returns_deserialized_value(self, redis_mock):
        redis_mock.get = AsyncMock(return_value=json.dumps({"a": 1}))
        with patch("app.core.cache.get_redis", return_value=redis_mock):
            result = await cache.cache_get("foo")
        assert result == {"a": 1}

    @pytest.mark.asyncio
    async def test_cache_get_handles_exception_returns_none(self, redis_mock):
        redis_mock.get = AsyncMock(side_effect=Exception("redis down"))
        with patch("app.core.cache.get_redis", return_value=redis_mock):
            # 不抛异常，返回 None
            result = await cache.cache_get("foo")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_get_handles_invalid_json(self, redis_mock):
        """Redis 中存了非法 JSON → 返回 None"""
        redis_mock.get = AsyncMock(return_value="not a json")
        with patch("app.core.cache.get_redis", return_value=redis_mock):
            result = await cache.cache_get("foo")
        assert result is None


class TestCacheSet:
    @pytest.mark.asyncio
    async def test_cache_set_returns_false_when_redis_unavailable(self):
        with patch("app.core.cache.get_redis", return_value=None):
            result = await cache.cache_set("k", "v")
        assert result is False

    @pytest.mark.asyncio
    async def test_cache_set_calls_setex_with_ttl(self, redis_mock):
        with patch("app.core.cache.get_redis", return_value=redis_mock):
            result = await cache.cache_set("k", {"a": 1}, ttl=600)
        assert result is True
        redis_mock.setex.assert_awaited_once()
        args = redis_mock.setex.await_args
        key, ttl, value = args[0]
        assert key == "k"
        assert ttl == 600
        assert json.loads(value) == {"a": 1}

    @pytest.mark.asyncio
    async def test_cache_set_default_ttl_is_300(self, redis_mock):
        with patch("app.core.cache.get_redis", return_value=redis_mock):
            await cache.cache_set("k", "v")
        args = redis_mock.setex.await_args
        assert args[0][1] == 300

    @pytest.mark.asyncio
    async def test_cache_set_handles_exception_returns_false(self, redis_mock):
        redis_mock.setex = AsyncMock(side_effect=Exception("redis down"))
        with patch("app.core.cache.get_redis", return_value=redis_mock):
            result = await cache.cache_set("k", "v")
        assert result is False

    @pytest.mark.asyncio
    async def test_cache_set_serializes_with_default_str_for_non_serializable(self, redis_mock):
        """非 JSON 序列化对象 → 用 default=str 转字符串"""

        class Obj:
            def __str__(self):
                return "obj_str"

        with patch("app.core.cache.get_redis", return_value=redis_mock):
            await cache.cache_set("k", Obj())
        args = redis_mock.setex.await_args
        # 不抛异常即说明 default=str 生效
        assert args[0][2] is not None


class TestCacheDelete:
    @pytest.mark.asyncio
    async def test_cache_delete_returns_false_when_redis_unavailable(self):
        with patch("app.core.cache.get_redis", return_value=None):
            result = await cache.cache_delete("k")
        assert result is False

    @pytest.mark.asyncio
    async def test_cache_delete_calls_redis_delete(self, redis_mock):
        with patch("app.core.cache.get_redis", return_value=redis_mock):
            result = await cache.cache_delete("k")
        assert result is True
        redis_mock.delete.assert_awaited_once_with("k")

    @pytest.mark.asyncio
    async def test_cache_delete_handles_exception(self, redis_mock):
        redis_mock.delete = AsyncMock(side_effect=Exception("redis down"))
        with patch("app.core.cache.get_redis", return_value=redis_mock):
            result = await cache.cache_delete("k")
        assert result is False


class TestCacheDeletePattern:
    @pytest.mark.asyncio
    async def test_cache_delete_pattern_returns_zero_when_no_redis(self):
        with patch("app.core.cache.get_redis", return_value=None):
            result = await cache.cache_delete_pattern("foo:*")
        assert result == 0

    @pytest.mark.asyncio
    async def test_cache_delete_pattern_deletes_matching_keys(self, redis_mock):
        keys = ["foo:1", "foo:2", "foo:3"]

        # scan_iter 返回 async iterator
        async def fake_scan_iter(match=None):
            for k in keys:
                yield k

        redis_mock.scan_iter = fake_scan_iter
        with patch("app.core.cache.get_redis", return_value=redis_mock):
            result = await cache.cache_delete_pattern("foo:*")
        assert result == 3
        # delete 用 *keys 解包
        redis_mock.delete.assert_awaited_once_with(*keys)

    @pytest.mark.asyncio
    async def test_cache_delete_pattern_no_keys_returns_zero(self, redis_mock):
        async def fake_scan_iter(match=None):
            return
            yield  # make it an async generator

        redis_mock.scan_iter = fake_scan_iter
        with patch("app.core.cache.get_redis", return_value=redis_mock):
            result = await cache.cache_delete_pattern("foo:*")
        assert result == 0
        redis_mock.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cache_delete_pattern_handles_exception(self, redis_mock):
        # 抛异常的 scan_iter
        async def fake_scan_iter(match=None):
            raise Exception("redis down")
            yield  # unreachable, makes it an async generator

        redis_mock.scan_iter = fake_scan_iter
        with patch("app.core.cache.get_redis", return_value=redis_mock):
            result = await cache.cache_delete_pattern("foo:*")
        assert result == 0
