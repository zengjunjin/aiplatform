"""WebSocket 通知管理器。

管理 WebSocket 连接池，按用户 ID 分发消息。
支持单用户推送和全量广播。
"""

import asyncio
import json

from fastapi import WebSocket
from loguru import logger

from app.config import settings
from app.redis_client import get_redis


class NotificationManager:
    """管理 WebSocket 连接池，按用户 ID 分发消息"""

    _connections: dict[str, list[WebSocket]] = {}
    _lock: asyncio.Lock | None = None

    # Task 34: 离线消息 Redis list key 前缀与 TTL
    _OFFLINE_KEY_PREFIX = "ws:offline:"
    # Task 40: TTL 迁移到 config.py，原位置引用 settings
    _OFFLINE_TTL = settings.WEBSOCKET_OFFLINE_MESSAGE_TTL  # 7 天（秒）

    @classmethod
    def _get_lock(cls) -> asyncio.Lock:
        """获取 _connections 并发锁（lazy init，避免跨事件循环绑定问题）"""
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    @classmethod
    def max_connections_per_user(cls) -> int:
        """单用户最大并发连接数（来自 settings）"""
        return settings.WEBSOCKET_MAX_CONNECTIONS_PER_USER

    @classmethod
    async def connect(cls, user_id: str, websocket: WebSocket) -> bool:
        """注册 WebSocket 连接（调用方需先 websocket.accept()）。

        Args:
            user_id: 用户 ID
            websocket: 已 accept 的 WebSocket 实例

        Returns:
            bool: True 表示注册成功；False 表示因超过单用户连接数上限被拒绝
                  （此时连接已被服务端 close，调用方应直接 return）。
        """
        async with cls._get_lock():
            existing = cls._connections.get(user_id, [])
            limit = cls.max_connections_per_user()
            if len(existing) >= limit:
                try:
                    await websocket.close(code=4004, reason="Too many connections per user")
                except Exception as e:
                    logger.warning(f"Failed to close exceeded WebSocket for user_id={user_id}: {e}")
                logger.warning(
                    f"WebSocket rejected: user_id={user_id} exceeded max connections "
                    f"({len(existing)}/{limit})"
                )
                return False
            existing.append(websocket)
            cls._connections[user_id] = existing
            logger.info(
                f"WebSocket connected: user_id={user_id}, "
                f"total_connections={len(existing)}"
            )

        # Task 34: 连接成功后拉取并推送离线消息（锁外执行避免阻塞其他连接操作）
        await cls._deliver_offline_messages(user_id, websocket)
        return True

    @classmethod
    async def _deliver_offline_messages(cls, user_id: str, websocket: WebSocket) -> None:
        """Task 34: 拉取离线消息并推送，然后删除 Redis list。

        用户重新连接时，先将离线期间暂存的消息按顺序推送给当前连接，
        推送完成后 DEL 整个 list 避免重复投递。
        """
        redis = get_redis()
        if not redis:
            return
        key = f"{cls._OFFLINE_KEY_PREFIX}{user_id}"
        try:
            messages = await redis.lrange(key, 0, -1)
            if not messages:
                return
            for msg in messages:
                try:
                    await websocket.send_text(msg)
                except Exception as e:
                    logger.warning(
                        f"Failed to deliver offline message to user {user_id}: {e}"
                    )
                    break
            await redis.delete(key)
            logger.info(
                f"Delivered {len(messages)} offline messages to user_id={user_id}"
            )
        except Exception as e:
            logger.warning(f"Failed to fetch offline messages for user {user_id}: {e}")

    @classmethod
    async def _store_offline_message(cls, user_id: str, message: str) -> None:
        """Task 34: 将离线消息存入 Redis list，TTL 7 天。

        用户离线时 send_to_user 调用此方法暂存消息，等待用户重新连接时拉取。
        """
        redis = get_redis()
        if not redis:
            return
        key = f"{cls._OFFLINE_KEY_PREFIX}{user_id}"
        try:
            await redis.rpush(key, message)
            await redis.expire(key, cls._OFFLINE_TTL)
        except Exception as e:
            logger.warning(f"Failed to store offline message for user {user_id}: {e}")

    @classmethod
    async def disconnect(cls, user_id: str, websocket: WebSocket) -> None:
        """移除 WebSocket 连接"""
        async with cls._get_lock():
            if user_id in cls._connections:
                try:
                    cls._connections[user_id].remove(websocket)
                except ValueError:
                    pass
                if not cls._connections[user_id]:
                    del cls._connections[user_id]
        logger.info(f"WebSocket disconnected: user_id={user_id}")

    @classmethod
    async def send_to_user(cls, user_id: str, notification: dict) -> None:
        """向指定用户发送通知（并行发送给该用户的所有连接）"""
        message = json.dumps(notification, ensure_ascii=False)
        async with cls._get_lock():
            connections = list(cls._connections.get(user_id, []))

        if not connections:
            # Task 34: 用户离线，将消息持久化到 Redis list（TTL 7 天）
            await cls._store_offline_message(user_id, message)
            return

        async def _send(ws: WebSocket) -> WebSocket | None:
            try:
                await ws.send_text(message)
                return None
            except Exception as e:
                logger.warning(f"Failed to send to user {user_id}: {e}")
                return ws

        results = await asyncio.gather(
            *[_send(ws) for ws in connections],
            return_exceptions=True,
        )
        dead = [r for r in results if isinstance(r, WebSocket)]
        if dead:
            async with cls._get_lock():
                cur = cls._connections.get(user_id, [])
                for ws in dead:
                    try:
                        cur.remove(ws)
                    except ValueError:
                        pass

    @classmethod
    async def broadcast(cls, notification: dict) -> None:
        """向所有用户广播通知（并行发送，return_exceptions 隔离单连接失败）

        注意：此方法被 tests/test_ws.py 用于验证广播逻辑，
        当前生产入口未直接调用，但保留以维持测试覆盖率，勿删除。
        """
        message = json.dumps(notification, ensure_ascii=False)
        # 快照当前 (user_id, ws) 列表，避免在持有锁时进行 I/O
        async with cls._get_lock():
            targets = [
                (user_id, ws)
                for user_id, conns in cls._connections.items()
                for ws in conns
            ]

        if not targets:
            return

        async def _send(user_id: str, ws: WebSocket) -> tuple[str, WebSocket] | None:
            try:
                await ws.send_text(message)
                return None
            except Exception as e:
                logger.warning(f"Failed to broadcast to user {user_id}: {e}")
                return (user_id, ws)

        results = await asyncio.gather(
            *[_send(uid, ws) for uid, ws in targets],
            return_exceptions=True,
        )
        dead: list[tuple[str, WebSocket]] = [r for r in results if isinstance(r, tuple)]
        for user_id, ws in dead:
            await cls.disconnect(user_id, ws)
