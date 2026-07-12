"""WebSocket 实时通知端点。

通过 WebSocket 子协议 (Sec-WebSocket-Protocol: bearer.{token}) 传递 JWT token，
避免 token 暴露在 URL 查询参数和访问日志中。
连接后自动注册到 NotificationManager 并接收实时通知。
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.security import decode_token
from app.core.notification_manager import NotificationManager
from app.core.events import EventBus
from loguru import logger

router = APIRouter()


async def _on_document_parsed(payload: dict):
    """文档解析完成时，通知上传者"""
    uploader_id = payload.get("uploader_id")
    if uploader_id:
        await NotificationManager.send_to_user(
            str(uploader_id),
            {
                "type": "document.parsed",
                "title": "文档解析完成",
                "message": f"文档 {payload.get('filename', '')} 解析完成",
                "data": payload,
            },
        )


async def _on_evaluation_completed(payload: dict):
    """评估完成时，通知发起者"""
    user_id = payload.get("user_id")
    if user_id:
        await NotificationManager.send_to_user(
            str(user_id),
            {
                "type": "evaluation.completed",
                "title": "评估完成",
                "message": f"知识库评估已完成",
                "data": payload,
            },
        )


# 注册事件订阅（在模块加载时注册，使用 flag 防止重复注册）
_event_handlers_registered = False


async def _register_event_handlers():
    global _event_handlers_registered
    if _event_handlers_registered:
        return
    await EventBus.subscribe(EventBus.DOCUMENT_PARSED, _on_document_parsed)
    await EventBus.subscribe(EventBus.EVALUATION_COMPLETED, _on_evaluation_completed)
    _event_handlers_registered = True


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 连接端点，通过子协议传递 JWT token。

    客户端连接方式: new WebSocket(url, [`bearer.${token}`])
    服务端从 Sec-WebSocket-Protocol 头提取 token 并验证签名。
    """
    # 从 Sec-WebSocket-Protocol 头提取 token
    protocols = websocket.headers.get("sec-websocket-protocol", "")
    token = None
    for proto in protocols.split(","):
        proto = proto.strip()
        if proto.startswith("bearer."):
            token = proto[7:]
            break

    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    payload = decode_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    if payload.get("type") != "access":
        await websocket.close(code=4001, reason="Invalid token type")
        return

    user_id = str(payload.get("sub", ""))
    if not user_id:
        await websocket.close(code=4001, reason="Invalid token subject")
        return

    # 注册事件处理器（首次连接时注册）
    await _register_event_handlers()

    # Accept with the subprotocol (WebSocket spec 要求服务端回传选中的子协议)
    await websocket.accept(subprotocol=f"bearer.{token}")

    # 注册到 NotificationManager
    await NotificationManager.connect(user_id, websocket)
    logger.info(f"WebSocket authenticated: user_id={user_id}")

    try:
        # 发送欢迎消息
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket connected",
            "user_id": user_id,
        })

        # 循环接收消息（保持连接活跃，处理 ping/pong）
        while True:
            data = await websocket.receive_text()
            # 客户端可以发送 ping，服务端回复 pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected: user_id={user_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user_id={user_id}: {e}")
    finally:
        await NotificationManager.disconnect(user_id, websocket)