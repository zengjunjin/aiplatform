"""轻量级事件总线（基于 Redis Pub/Sub）。

支持的事件类型：
- document.uploaded
- document.parsed
- document.deleted
- kb.created
- kb.updated
- kb.deleted
- chat.message.sent
- evaluation.completed
"""

import asyncio
import json
from collections.abc import Awaitable, Callable

import redis.asyncio as aioredis
from loguru import logger

from app.config import settings


class EventBus:
    """轻量级事件总线（基于 Redis Pub/Sub）"""

    # 事件类型枚举
    DOCUMENT_UPLOADED = "document.uploaded"
    DOCUMENT_PARSED = "document.parsed"
    DOCUMENT_DELETED = "document.deleted"
    KB_CREATED = "kb.created"
    KB_UPDATED = "kb.updated"
    KB_DELETED = "kb.deleted"
    CHAT_MESSAGE_SENT = "chat.message.sent"
    EVALUATION_COMPLETED = "evaluation.completed"

    _redis: aioredis.Redis | None = None
    _subscribers: dict[str, list[Callable[[dict], Awaitable[None]]]] = {}
    _listener_task: asyncio.Task | None = None

    @classmethod
    async def init(cls) -> None:
        """初始化 Redis 连接并启动监听器"""
        cls._redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        cls._listener_task = asyncio.create_task(cls._listen())
        logger.info("EventBus initialized with Redis Pub/Sub")

    @classmethod
    async def publish(cls, event_type: str, payload: dict) -> None:
        """发布事件"""
        message = json.dumps({"event_type": event_type, "payload": payload})
        if cls._redis:
            await cls._redis.publish("events", message)
        logger.info(f"Event published: {event_type}")

    @classmethod
    async def subscribe(cls, event_type: str, handler: Callable[[dict], Awaitable[None]]) -> None:
        """订阅事件，handler 接收 payload dict"""
        if event_type not in cls._subscribers:
            cls._subscribers[event_type] = []
        cls._subscribers[event_type].append(handler)
        logger.debug(f"Handler subscribed to event: {event_type}")

    @classmethod
    def subscribe_sync(cls, event_type: str, handler: Callable[[dict], Awaitable[None]]) -> None:
        """同步注册事件处理器（与 subscribe 等价，但无需 await）。

        供模块加载时注册订阅者使用，避免在 import 阶段调用 async 函数。
        """
        cls._subscribers.setdefault(event_type, [])
        if handler not in cls._subscribers[event_type]:
            cls._subscribers[event_type].append(handler)
        logger.debug(f"Handler subscribed to event: {event_type}")

    @classmethod
    async def _listen(cls) -> None:
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
                    except Exception as e:
                        logger.debug(f"EventBus unsubscribe on shutdown failed: {e}")
                logger.info("EventBus listener stopped")
                return
            except Exception as e:
                logger.error(f"EventBus listener error: {e}, reconnecting in 5s...")
                if pubsub is not None:
                    try:
                        await pubsub.close()
                    except Exception as e:
                        logger.debug(f"EventBus pubsub close on error failed: {e}")
                await asyncio.sleep(5)

    @classmethod
    async def close(cls) -> None:
        """关闭连接和监听器

        注意：不清空 _subscribers，以支持 close→init 后订阅仍有效
        （例如 Celery worker 重启或 FastAPI lifespan 重新初始化场景）。
        订阅者通过 subscribe() 显式注册，通过进程退出自然清除；
        如需手动清空，调用方应显式访问 _subscribers.clear()。
        """
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
        # 不清空 _subscribers：支持 close→init 后订阅恢复
        logger.info("EventBus closed")
