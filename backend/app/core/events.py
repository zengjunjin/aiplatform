"""轻量级事件总线（基于 Redis Pub/Sub）。

支持的事件类型：
- document.uploaded
- document.parsed
- document.deleted
- kb.created
- kb.updated
- chat.message.sent
- evaluation.completed
"""

import json
import asyncio
from typing import Callable, Awaitable
from loguru import logger
import redis.asyncio as aioredis
from app.config import settings


class EventBus:
    """轻量级事件总线（基于 Redis Pub/Sub）"""

    # 事件类型枚举
    DOCUMENT_UPLOADED = "document.uploaded"
    DOCUMENT_PARSED = "document.parsed"
    DOCUMENT_DELETED = "document.deleted"
    KB_CREATED = "kb.created"
    KB_UPDATED = "kb.updated"
    CHAT_MESSAGE_SENT = "chat.message.sent"
    EVALUATION_COMPLETED = "evaluation.completed"

    _redis: aioredis.Redis | None = None
    _subscribers: dict[str, list[Callable[[dict], Awaitable[None]]]] = {}
    _listener_task: asyncio.Task | None = None

    @classmethod
    async def init(cls):
        """初始化 Redis 连接并启动监听器"""
        cls._redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        cls._listener_task = asyncio.create_task(cls._listen())
        logger.info("EventBus initialized with Redis Pub/Sub")

    @classmethod
    async def publish(cls, event_type: str, payload: dict):
        """发布事件"""
        message = json.dumps({"event_type": event_type, "payload": payload})
        if cls._redis:
            await cls._redis.publish("events", message)
        logger.info(f"Event published: {event_type}")

    @classmethod
    async def subscribe(cls, event_type: str, handler: Callable[[dict], Awaitable[None]]):
        """订阅事件，handler 接收 payload dict"""
        if event_type not in cls._subscribers:
            cls._subscribers[event_type] = []
        cls._subscribers[event_type].append(handler)
        logger.debug(f"Handler subscribed to event: {event_type}")

    @classmethod
    async def _listen(cls):
        """内部监听 Redis Pub/Sub 通道，分发事件给本地订阅者

        带自动重连: 非取消异常时等待 5 秒后重试, 避免事件总线永久失效。
        """
        while True:
            if not cls._redis:
                await asyncio.sleep(1)
                continue
            pubsub = None
            try:
                pubsub = cls._redis.pubsub()
                await pubsub.subscribe("events")
                logger.info("EventBus listener started on channel 'events'")
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                        event_type = data.get("event_type", "")
                        payload = data.get("payload", {})
                        handlers = cls._subscribers.get(event_type, [])
                        for handler in handlers:
                            try:
                                await handler(payload)
                            except Exception as e:
                                logger.error(f"Event handler error for {event_type}: {e}")
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid event message: {message['data']}")
            except asyncio.CancelledError:
                # 正常关闭: 清理后退出
                if pubsub is not None:
                    try:
                        await pubsub.unsubscribe("events")
                        await pubsub.close()
                    except Exception:
                        pass
                logger.info("EventBus listener stopped")
                return
            except Exception as e:
                logger.error(f"EventBus listener error: {e}, reconnecting in 5s...")
                if pubsub is not None:
                    try:
                        await pubsub.close()
                    except Exception:
                        pass
                await asyncio.sleep(5)

    @classmethod
    async def close(cls):
        """关闭连接和监听器"""
        if cls._listener_task:
            cls._listener_task.cancel()
            try:
                await cls._listener_task
            except asyncio.CancelledError:
                pass
            cls._listener_task = None
        if cls._redis:
            await cls._redis.aclose()
            cls._redis = None
        cls._subscribers.clear()
        logger.info("EventBus closed")