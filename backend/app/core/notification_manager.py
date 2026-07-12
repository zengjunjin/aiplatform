"""WebSocket 通知管理器。

管理 WebSocket 连接池，按用户 ID 分发消息。
支持单用户推送和全量广播。
"""

import json
from fastapi import WebSocket
from loguru import logger


class NotificationManager:
    """管理 WebSocket 连接池，按用户 ID 分发消息"""

    _connections: dict[str, list[WebSocket]] = {}

    @classmethod
    async def connect(cls, user_id: str, websocket: WebSocket):
        """注册 WebSocket 连接"""
        await websocket.accept()
        if user_id not in cls._connections:
            cls._connections[user_id] = []
        cls._connections[user_id].append(websocket)
        logger.info(f"WebSocket connected: user_id={user_id}, total_connections={len(cls._connections[user_id])}")

    @classmethod
    async def disconnect(cls, user_id: str, websocket: WebSocket):
        """移除 WebSocket 连接"""
        if user_id in cls._connections:
            try:
                cls._connections[user_id].remove(websocket)
            except ValueError:
                pass
            if not cls._connections[user_id]:
                del cls._connections[user_id]
        logger.info(f"WebSocket disconnected: user_id={user_id}")

    @classmethod
    async def send_to_user(cls, user_id: str, notification: dict):
        """向指定用户发送通知"""
        message = json.dumps(notification, ensure_ascii=False)
        connections = cls._connections.get(user_id, [])
        dead_connections = []
        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception as e:
                logger.warning(f"Failed to send to user {user_id}: {e}")
                dead_connections.append(ws)
        for ws in dead_connections:
            try:
                connections.remove(ws)
            except ValueError:
                pass

    @classmethod
    async def broadcast(cls, notification: dict):
        """向所有用户广播通知"""
        message = json.dumps(notification, ensure_ascii=False)
        dead_connections: list[tuple[str, WebSocket]] = []
        for user_id, connections in cls._connections.items():
            for ws in connections:
                try:
                    await ws.send_text(message)
                except Exception as e:
                    logger.warning(f"Failed to broadcast to user {user_id}: {e}")
                    dead_connections.append((user_id, ws))
        for user_id, ws in dead_connections:
            await cls.disconnect(user_id, ws)

    @classmethod
    def get_connection_count(cls) -> dict[str, int]:
        """获取当前连接数统计"""
        return {uid: len(conns) for uid, conns in cls._connections.items()}