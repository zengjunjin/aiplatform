"""Unit tests for app.redis_client.

覆盖目标:
- init_redis(): 创建并返回 redis_client
- get_redis(): 返回 redis_client (含 None 分支)
- _summary_key(): key 格式
- get_summary_cache(): None / 非 None 两条分支
- set_summary_cache(): None / 非 None 两条分支 + 默认 ttl
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import redis_client as redis_module
from app.config import settings


@pytest.fixture(autouse=True)
def _reset_redis_client():
    """每个测试前后重置 redis_client 为 None，避免模块状态泄漏。"""
    original = redis_module.redis_client
    redis_module.redis_client = None
    yield
    redis_module.redis_client = original


class TestInitRedis:
    def test_init_redis_creates_client_and_returns_it(self):
        """init_redis 调用 redis.from_url 并把结果赋给 redis_client，同时返回它。"""
        fake_redis = MagicMock()
        with patch(
            "app.redis_client.redis.from_url", return_value=fake_redis
        ) as mock_from_url:
            result = redis_module.init_redis()

        assert result is fake_redis
        assert redis_module.redis_client is fake_redis
        mock_from_url.assert_called_once_with(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

    def test_init_redis_uses_settings_redis_url(self):
        """验证 from_url 的第一个位置参数来自 settings.redis_url。"""
        fake_redis = MagicMock()
        with patch(
            "app.redis_client.redis.from_url", return_value=fake_redis
        ) as mock_from_url:
            redis_module.init_redis()
        args, _ = mock_from_url.call_args
        assert args[0] == settings.redis_url


class TestGetRedis:
    def test_get_redis_returns_none_when_not_initialized(self):
        """redis_client 为 None 时 get_redis 返回 None。"""
        assert redis_module.get_redis() is None

    def test_get_redis_returns_client_when_set(self):
        """redis_client 被赋值后 get_redis 返回同一实例。"""
        fake_redis = MagicMock()
        redis_module.redis_client = fake_redis
        assert redis_module.get_redis() is fake_redis


class TestSummaryKey:
    def test_summary_key_format(self):
        """_summary_key 返回 'chat:session:{id}:summary' 格式。"""
        assert redis_module._summary_key(1) == "chat:session:1:summary"

    def test_summary_key_different_ids(self):
        """不同 session_id 生成不同 key。"""
        assert redis_module._summary_key(0) == "chat:session:0:summary"
        assert redis_module._summary_key(99) == "chat:session:99:summary"
        assert redis_module._summary_key(12345) == "chat:session:12345:summary"

    def test_summary_key_prefix_constant(self):
        """SUMMARY_KEY_PREFIX 常量为 'chat:session'。"""
        assert redis_module.SUMMARY_KEY_PREFIX == "chat:session"


class TestGetSummaryCache:
    @pytest.mark.asyncio
    async def test_returns_none_when_redis_not_initialized(self):
        """redis_client 为 None 时返回 None，不抛异常。"""
        result = await redis_module.get_summary_cache(1)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_value_when_redis_present(self):
        """redis_client 存在时调用 redis.get(key) 并返回结果。"""
        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(return_value="cached summary")
        redis_module.redis_client = fake_redis

        result = await redis_module.get_summary_cache(42)

        assert result == "cached summary"
        fake_redis.get.assert_awaited_once_with("chat:session:42:summary")

    @pytest.mark.asyncio
    async def test_returns_none_when_key_missing(self):
        """redis 中无对应 key 时返回 None。"""
        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(return_value=None)
        redis_module.redis_client = fake_redis

        result = await redis_module.get_summary_cache(7)
        assert result is None
        fake_redis.get.assert_awaited_once_with("chat:session:7:summary")


class TestSetSummaryCache:
    @pytest.mark.asyncio
    async def test_noop_when_redis_not_initialized(self):
        """redis_client 为 None 时直接返回，不抛异常。"""
        # 不应抛异常
        await redis_module.set_summary_cache(1, "summary")

    @pytest.mark.asyncio
    async def test_calls_redis_set_with_explicit_ttl(self):
        """redis_client 存在时调用 redis.set(key, summary, ex=ttl)。"""
        fake_redis = AsyncMock()
        fake_redis.set = AsyncMock()
        redis_module.redis_client = fake_redis

        await redis_module.set_summary_cache(5, "my summary", ttl=120)

        fake_redis.set.assert_awaited_once_with(
            "chat:session:5:summary", "my summary", ex=120
        )

    @pytest.mark.asyncio
    async def test_uses_default_ttl_from_settings(self):
        """未传 ttl 时使用 settings.CHAT_SUMMARY_TTL (=3600)。"""
        fake_redis = AsyncMock()
        fake_redis.set = AsyncMock()
        redis_module.redis_client = fake_redis

        await redis_module.set_summary_cache(10, "default ttl summary")

        fake_redis.set.assert_awaited_once_with(
            "chat:session:10:summary",
            "default ttl summary",
            ex=settings.CHAT_SUMMARY_TTL,
        )

    @pytest.mark.asyncio
    async def test_default_ttl_is_3600(self):
        """SUMMARY_TTL 模块常量等于 settings.CHAT_SUMMARY_TTL。"""
        assert redis_module.SUMMARY_TTL == settings.CHAT_SUMMARY_TTL == 3600
