"""Tests for app.core.events.EventBus

Task 19: 验证 close() 不清空 _subscribers，close→init 后订阅仍有效。
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.events import EventBus


@pytest.fixture
def reset_event_bus():
    """每个测试前后重置 EventBus 类变量状态"""
    original_redis = EventBus._redis
    original_subs = EventBus._subscribers.copy()
    original_task = EventBus._listener_task
    EventBus._redis = None
    EventBus._subscribers.clear()
    EventBus._listener_task = None
    yield
    EventBus._redis = original_redis
    EventBus._subscribers.clear()
    EventBus._subscribers.update(original_subs)
    EventBus._listener_task = original_task


# ---------- SubTask 19.2: close→init 后订阅仍有效 ----------
class TestEventBusClosePreservesSubscribers:
    """close() 不清空 _subscribers，支持 close→init 后订阅恢复"""

    @pytest.mark.asyncio
    async def test_close_does_not_clear_subscribers(self, reset_event_bus):
        """close() 应保留 _subscribers 中的订阅"""
        handler = AsyncMock()
        await EventBus.subscribe(EventBus.DOCUMENT_PARSED, handler)
        assert len(EventBus._subscribers[EventBus.DOCUMENT_PARSED]) == 1

        # mock Redis 和 listener_task
        fake_redis = MagicMock()
        fake_redis.aclose = AsyncMock()
        EventBus._redis = fake_redis
        EventBus._listener_task = None  # 避免 cancel 真实 task

        await EventBus.close()

        # 关键断言：_subscribers 不应被清空
        assert EventBus.DOCUMENT_PARSED in EventBus._subscribers
        assert len(EventBus._subscribers[EventBus.DOCUMENT_PARSED]) == 1
        assert EventBus._subscribers[EventBus.DOCUMENT_PARSED][0] is handler

    @pytest.mark.asyncio
    async def test_close_then_init_preserves_subscriptions(self, reset_event_bus):
        """close→init 后订阅仍有效（核心场景）"""
        handler = AsyncMock()
        await EventBus.subscribe(EventBus.DOCUMENT_UPLOADED, handler)
        assert EventBus.DOCUMENT_UPLOADED in EventBus._subscribers

        # mock Redis：close 时 aclose，init 时 from_url 返回新实例
        first_redis = MagicMock()
        first_redis.aclose = AsyncMock()
        second_redis = MagicMock()
        second_redis.pubsub = MagicMock()
        fake_pubsub = MagicMock()
        fake_pubsub.subscribe = AsyncMock()
        fake_pubsub.listen = MagicMock(return_value=iter([]))
        fake_pubsub.close = AsyncMock()
        fake_pubsub.unsubscribe = AsyncMock()
        second_redis.pubsub.return_value = fake_pubsub

        with patch("app.core.events.aioredis.from_url", return_value=second_redis):
            EventBus._redis = first_redis
            EventBus._listener_task = None

            # close
            await EventBus.close()
            assert EventBus._redis is None
            # _subscribers 仍保留
            assert EventBus.DOCUMENT_UPLOADED in EventBus._subscribers

            # init
            await EventBus.init()
            # 订阅应仍存在
            assert EventBus.DOCUMENT_UPLOADED in EventBus._subscribers
            assert EventBus._subscribers[EventBus.DOCUMENT_UPLOADED][0] is handler

            # 清理 listener_task
            if EventBus._listener_task:
                EventBus._listener_task.cancel()
                try:
                    await EventBus._listener_task
                except asyncio.CancelledError:
                    pass
                EventBus._listener_task = None

    @pytest.mark.asyncio
    async def test_close_clears_redis_and_listener_task(self, reset_event_bus):
        """close() 仍应关闭 Redis 连接和 listener task"""
        fake_redis = MagicMock()
        fake_redis.aclose = AsyncMock()
        EventBus._redis = fake_redis

        # 创建一个真实的 listener task 用于 cancel 测试
        async def long_running():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                return

        EventBus._listener_task = asyncio.create_task(long_running())

        await EventBus.close()

        fake_redis.aclose.assert_awaited_once()
        assert EventBus._redis is None
        assert EventBus._listener_task is None

    @pytest.mark.asyncio
    async def test_subscribe_after_close_still_works(self, reset_event_bus):
        """close 后仍可 subscribe（_subscribers 未被清空）"""
        handler1 = AsyncMock()
        await EventBus.subscribe(EventBus.KB_CREATED, handler1)

        EventBus._redis = None
        EventBus._listener_task = None
        await EventBus.close()

        # close 后再 subscribe 新 handler
        handler2 = AsyncMock()
        await EventBus.subscribe(EventBus.KB_CREATED, handler2)

        # 两个 handler 都应在
        assert len(EventBus._subscribers[EventBus.KB_CREATED]) == 2

    @pytest.mark.asyncio
    async def test_multiple_close_calls_safe(self, reset_event_bus):
        """多次调用 close() 不应抛出异常"""
        EventBus._redis = None
        EventBus._listener_task = None

        await EventBus.close()  # 不应抛出
        await EventBus.close()  # 再次调用也不应抛出
        await EventBus.close()  # 第三次

        assert EventBus._redis is None
        assert EventBus._listener_task is None

    @pytest.mark.asyncio
    async def test_subscribers_survive_close_with_real_listener_task(self, reset_event_bus):
        """带真实 listener_task 的 close 也应保留 _subscribers"""
        handler = AsyncMock()
        await EventBus.subscribe(EventBus.CHAT_MESSAGE_SENT, handler)

        # 用 mock Redis 启动 listener
        fake_redis = MagicMock()
        fake_redis.pubsub = MagicMock()
        fake_pubsub = MagicMock()
        fake_pubsub.subscribe = AsyncMock()
        # listen() 立即返回空迭代器，让 listener 自然结束
        fake_pubsub.listen = MagicMock(return_value=iter([]))
        fake_pubsub.close = AsyncMock()
        fake_pubsub.unsubscribe = AsyncMock()
        fake_redis.pubsub.return_value = fake_pubsub
        fake_redis.aclose = AsyncMock()

        with patch("app.core.events.aioredis.from_url", return_value=fake_redis):
            await EventBus.init()
            assert EventBus._redis is not None
            # 等待 listener 启动
            await asyncio.sleep(0.05)

            await EventBus.close()
            # _subscribers 应保留
            assert EventBus.CHAT_MESSAGE_SENT in EventBus._subscribers
            assert EventBus._subscribers[EventBus.CHAT_MESSAGE_SENT][0] is handler
            assert EventBus._redis is None
            assert EventBus._listener_task is None


class TestEventBusSubscribeAndPublish:
    """基础 subscribe/publish 行为验证"""

    @pytest.mark.asyncio
    async def test_subscribe_adds_handler(self, reset_event_bus):
        """subscribe 应将 handler 添加到 _subscribers"""
        handler = AsyncMock()
        await EventBus.subscribe(EventBus.DOCUMENT_DELETED, handler)
        assert EventBus.DOCUMENT_DELETED in EventBus._subscribers
        assert handler in EventBus._subscribers[EventBus.DOCUMENT_DELETED]

    @pytest.mark.asyncio
    async def test_subscribe_multiple_handlers_same_event(self, reset_event_bus):
        """同一事件可订阅多个 handler"""
        h1 = AsyncMock()
        h2 = AsyncMock()
        await EventBus.subscribe(EventBus.KB_UPDATED, h1)
        await EventBus.subscribe(EventBus.KB_UPDATED, h2)
        assert len(EventBus._subscribers[EventBus.KB_UPDATED]) == 2

    @pytest.mark.asyncio
    async def test_publish_without_redis_does_not_raise(self, reset_event_bus):
        """无 Redis 连接时 publish 不应抛出"""
        EventBus._redis = None
        await EventBus.publish(EventBus.DOCUMENT_PARSED, {"doc_id": 1})

    @pytest.mark.asyncio
    async def test_publish_with_redis_calls_publish(self, reset_event_bus):
        """有 Redis 连接时 publish 应调用 redis.publish"""
        fake_redis = MagicMock()
        fake_redis.publish = AsyncMock()
        EventBus._redis = fake_redis

        await EventBus.publish(EventBus.DOCUMENT_PARSED, {"doc_id": 42})

        fake_redis.publish.assert_awaited_once()
        args = fake_redis.publish.await_args
        assert args[0][0] == "events"
        import json
        msg = json.loads(args[0][1])
        assert msg["event_type"] == EventBus.DOCUMENT_PARSED
        assert msg["payload"]["doc_id"] == 42
