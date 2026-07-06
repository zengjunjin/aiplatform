"""Tests for streaming generation cancel (Phase F3).

Tests the cancel flag mechanism via Redis without spinning up a real LLM.
"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from app.services import chat_service


@pytest.fixture
def redis_mock():
    """Mock Redis client."""
    r = MagicMock()
    r.set = AsyncMock()
    r.exists = AsyncMock(return_value=0)
    r.delete = AsyncMock()
    r.get = AsyncMock(return_value=None)
    return r


class TestCancelKeyFormat:
    def test_cancel_key_session_level(self):
        """未提供 message_id → session 级别 key"""
        key = chat_service._cancel_key(session_id=42)
        assert key == "chat:cancel:session:42:current"

    def test_cancel_key_message_level(self):
        """提供 message_id → message 级别 key"""
        key = chat_service._cancel_key(session_id=42, message_id=99)
        assert key == "chat:cancel:session:42:msg:99"


class TestRequestCancel:
    @pytest.mark.asyncio
    async def test_request_cancel_sets_redis_key_with_ttl(self, redis_mock):
        """request_cancel 写入 Redis，带 TTL"""
        with patch("app.services.chat_service.get_redis", return_value=redis_mock):
            await chat_service.request_cancel(session_id=42, ttl=300)
        redis_mock.set.assert_awaited_once()
        args = redis_mock.set.await_args
        key, value = args[0]
        assert key == "chat:cancel:session:42:current"
        assert value == "1"
        # kwargs 应包含 ex=300
        assert args[1].get("ex") == 300

    @pytest.mark.asyncio
    async def test_request_cancel_with_message_id(self, redis_mock):
        """带 message_id 的取消"""
        with patch("app.services.chat_service.get_redis", return_value=redis_mock):
            await chat_service.request_cancel(session_id=42, message_id=99, ttl=60)
        args = redis_mock.set.await_args
        key, _ = args[0]
        assert key == "chat:cancel:session:42:msg:99"
        assert args[1].get("ex") == 60

    @pytest.mark.asyncio
    async def test_request_cancel_noop_when_redis_unavailable(self):
        """Redis 不可用 → 不抛异常"""
        with patch("app.services.chat_service.get_redis", return_value=None):
            await chat_service.request_cancel(session_id=42)  # 不应抛异常


class TestIsCancelled:
    @pytest.mark.asyncio
    async def test_is_cancelled_false_when_no_flag(self, redis_mock):
        """无 cancel 标志 → False"""
        redis_mock.exists = AsyncMock(return_value=0)
        with patch("app.services.chat_service.get_redis", return_value=redis_mock):
            result = await chat_service.is_cancelled(session_id=42)
        assert result is False

    @pytest.mark.asyncio
    async def test_is_cancelled_true_when_session_flag_exists(self, redis_mock):
        """session 级别 cancel 标志存在 → True"""
        redis_mock.exists = AsyncMock(return_value=1)
        with patch("app.services.chat_service.get_redis", return_value=redis_mock):
            result = await chat_service.is_cancelled(session_id=42)
        assert result is True

    @pytest.mark.asyncio
    async def test_is_cancelled_true_when_message_flag_exists(self, redis_mock):
        """message 级别 cancel 标志存在 → True"""
        # 第一次 exists（message 级）返回 1
        redis_mock.exists = AsyncMock(return_value=1)
        with patch("app.services.chat_service.get_redis", return_value=redis_mock):
            result = await chat_service.is_cancelled(session_id=42, message_id=99)
        assert result is True

    @pytest.mark.asyncio
    async def test_is_cancelled_no_redis_returns_false(self):
        """Redis 不可用 → False（不阻断生成）"""
        with patch("app.services.chat_service.get_redis", return_value=None):
            result = await chat_service.is_cancelled(session_id=42)
        assert result is False


class TestClearCancel:
    @pytest.mark.asyncio
    async def test_clear_cancel_deletes_both_keys(self, redis_mock):
        """clear_cancel 同时删除 message 级和 session 级 key"""
        with patch("app.services.chat_service.get_redis", return_value=redis_mock):
            await chat_service.clear_cancel(session_id=42, message_id=99)
        redis_mock.delete.assert_awaited_once()
        args = redis_mock.delete.await_args
        keys = args[0]
        assert "chat:cancel:session:42:msg:99" in keys
        assert "chat:cancel:session:42:current" in keys

    @pytest.mark.asyncio
    async def test_clear_cancel_no_redis_noop(self):
        with patch("app.services.chat_service.get_redis", return_value=None):
            await chat_service.clear_cancel(session_id=42)  # 不抛异常


class TestCancelFlowIntegration:
    """模拟完整的取消流程：request_cancel → is_cancelled → clear_cancel"""

    @pytest.mark.asyncio
    async def test_full_cancel_flow(self):
        """模拟流式生成中的取消流程"""
        # 用一个真实状态的 mock
        state = {"flag": False}

        async def fake_exists(key):
            return 1 if state["flag"] else 0

        async def fake_set(key, value, ex=None):
            state["flag"] = True
            return True

        async def fake_delete(*keys):
            state["flag"] = False
            return len(keys)

        r = MagicMock()
        r.exists = AsyncMock(side_effect=fake_exists)
        r.set = AsyncMock(side_effect=fake_set)
        r.delete = AsyncMock(side_effect=fake_delete)

        with patch("app.services.chat_service.get_redis", return_value=r):
            # 1. 初始状态：未取消
            assert await chat_service.is_cancelled(session_id=1) is False

            # 2. 用户请求取消
            await chat_service.request_cancel(session_id=1)
            assert await chat_service.is_cancelled(session_id=1) is True

            # 3. 生成循环检测到取消，停止生成
            # 4. finally 块清理标志
            await chat_service.clear_cancel(session_id=1)
            assert await chat_service.is_cancelled(session_id=1) is False
