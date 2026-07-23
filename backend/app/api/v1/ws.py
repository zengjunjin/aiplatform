"""WebSocket 实时通知端点。

通过 WebSocket 子协议 (Sec-WebSocket-Protocol: bearer.{token}) 传递 JWT token，
避免 token 暴露在 URL 查询参数和访问日志中。
连接后自动注册到 NotificationManager 并接收实时通知。

WebSocket 安全策略：
- Origin 校验：浏览器 Origin 必须在白名单（settings.WEBSOCKET_ALLOWED_ORIGINS）。
  空 Origin（非浏览器客户端，如 curl/Python websockets）允许通过。
- 单用户最大并发连接数：settings.WEBSOCKET_MAX_CONNECTIONS_PER_USER（默认 5）。
- 接收循环超时：settings.WEBSOCKET_RECV_TIMEOUT（默认 30s 无消息则关闭）。
- 消息频率限制：settings.WEBSOCKET_RATE_LIMIT_PER_MINUTE（默认 10/分钟，超过则关闭）。
  使用 Redis 跨进程计数；Redis 不可用时降级为内存计数。

WebSocket 自定义关闭码：
- 4001: 认证失败（无/无效/错误类型 token）
- 4003: Forbidden Origin
- 4004: Too Many Connections per user
- 4005: Rate Limited
- 4006: Ping Timeout
"""

import asyncio
from collections import OrderedDict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from app.config import settings
from app.core.events import EventBus
from app.core.notification_manager import NotificationManager
from app.core.redis_scripts import _INCR_EXPIRE_LUA
from app.core.security import decode_token
from app.redis_client import get_redis

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
                "message": "知识库评估已完成",
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


# 进程内消息频率计数（仅在 Redis 不可用时使用，不具备跨进程能力）
# Task 50: 使用 OrderedDict 实现 LRU，避免长期运行后内存无限增长
_inproc_rate_counters: OrderedDict[str, list[float]] = OrderedDict()
# Task 40: LRU 上限迁移到 config.py，原位置引用 settings
_INPROC_RATE_LRU_MAX = settings.WEBSOCKET_INPROC_RATE_LRU_MAX


def _trim_inproc_counters() -> None:
    """LRU 淘汰：超过上限时移除最久未访问的 user_id 计数。"""
    while len(_inproc_rate_counters) > _INPROC_RATE_LRU_MAX:
        _inproc_rate_counters.popitem(last=False)


async def _heartbeat(websocket: WebSocket, state: dict) -> None:
    """Task 33: 服务端心跳协程。

    每 30s 发送 ``{"event":"ping"}``，若连续 3 次未收到客户端 pong
    响应则主动 ``websocket.close()``，避免 NAT 空闲超时导致的死连接。

    state: 共享状态 dict
        - "pong_received": bool，由接收循环在收到 pong 时置 True
        - "pong_event": asyncio.Event，由接收循环在收到 pong 时 set()
        - "running": bool，False 时心跳退出
    """
    pong_event: asyncio.Event = state["pong_event"]
    missed = 0
    while state.get("running", True):
        # Task 40: 心跳间隔/超时/上限迁移到 config.py
        await asyncio.sleep(settings.WEBSOCKET_HEARTBEAT_INTERVAL)
        if not state.get("running", True):
            return
        pong_event.clear()
        state["pong_received"] = False
        try:
            await websocket.send_json({"event": "ping"})
        except Exception as e:
            logger.debug(f"Heartbeat send ping failed: {e}")
            return
        # 等待客户端 pong（宽限期由 config 控制，使用 asyncio.Event 替代 0.1s 轮询）
        # 连接断开时 finally 中 heartbeat_task.cancel() 会以 CancelledError 中断等待
        if not state.get("running", True):
            return
        got_pong = False
        try:
            await asyncio.wait_for(
                pong_event.wait(), timeout=settings.WEBSOCKET_HEARTBEAT_PONG_TIMEOUT
            )
            got_pong = True
        except asyncio.TimeoutError:
            got_pong = False
        if got_pong:
            missed = 0
        else:
            missed += 1
            if missed >= settings.WEBSOCKET_HEARTBEAT_MAX_MISSED:
                logger.warning(
                    f"WebSocket heartbeat: {settings.WEBSOCKET_HEARTBEAT_MAX_MISSED} missed pongs, closing connection"
                )
                try:
                    await websocket.close(code=4006, reason="Ping timeout")
                except Exception as e:
                    logger.debug(f"Heartbeat close failed: {e}")
                return


async def _check_rate_limit(user_id: str) -> bool:
    """检查单用户消息频率限制。

    优先使用 Redis 跨进程计数；Redis 不可用时降级为进程内内存计数。
    限流窗口 60 秒，超过 settings.WEBSOCKET_RATE_LIMIT_PER_MINUTE 返回 False。

    Returns:
        bool: True 表示允许通过；False 表示被限流。
    """
    limit = settings.WEBSOCKET_RATE_LIMIT_PER_MINUTE
    redis = get_redis()
    if redis is not None:
        rate_key = f"ws_rate:{user_id}"
        try:
            # Task 40: 窗口时间迁移到 config.py
            count = await redis.eval(
                _INCR_EXPIRE_LUA, 1, rate_key, settings.WEBSOCKET_RATE_LIMIT_WINDOW
            )
            return count <= limit
        except Exception as e:
            logger.warning(f"Redis rate limit failed, fallback to inproc: {e}")

    # 降级：进程内滑动窗口计数（仅本进程有效）
    now = asyncio.get_running_loop().time()
    # Task 40: 窗口时间迁移到 config.py
    window = float(settings.WEBSOCKET_RATE_LIMIT_WINDOW)
    history = _inproc_rate_counters.get(user_id, [])
    # 清理过期记录
    history = [t for t in history if now - t < window]
    if len(history) >= limit:
        _inproc_rate_counters[user_id] = history
        _inproc_rate_counters.move_to_end(user_id)
        _trim_inproc_counters()
        return False
    history.append(now)
    _inproc_rate_counters[user_id] = history
    _inproc_rate_counters.move_to_end(user_id)
    _trim_inproc_counters()
    return True


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 连接端点，通过子协议传递 JWT token。

    客户端连接方式: new WebSocket(url, [`bearer.${token}`])
    服务端从 Sec-WebSocket-Protocol 头提取 token 并验证签名。
    """
    # --- Origin 校验（在 accept 之前；close 无需 accept 也可调用）---
    origin = websocket.headers.get("origin", "")
    allowed_origins = settings.websocket_allowed_origins_list
    if origin and origin not in allowed_origins:
        logger.warning(f"WebSocket rejected: forbidden origin={origin!r}")
        await websocket.close(code=4003, reason="Forbidden Origin")
        return

    # 从 Sec-WebSocket-Protocol 头提取 token
    protocols = websocket.headers.get("sec-websocket-protocol", "")
    token = None
    # Task 58: 保存原始 subprotocol 字符串，避免后续用 token 重构（减少 token 字符串操作）
    # WebSocket 规范要求服务端回传客户端提供的子协议之一，不能改为固定字符串或哈希前缀
    selected_protocol = None
    for proto in protocols.split(","):
        proto = proto.strip()
        if proto.startswith("bearer."):
            token = proto[7:]
            selected_protocol = proto
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
    # 注意：accept 只能调用一次（Starlette 限制）
    # Task 58: 直接使用客户端提供的原始 subprotocol 字符串，避免用 token 重构
    await websocket.accept(subprotocol=selected_protocol)

    # 注册到 NotificationManager（含单用户连接数限制）
    connected = await NotificationManager.connect(user_id, websocket)
    if not connected:
        # connect() 已经 close 了连接（code=4004），直接返回
        return

    logger.info(f"WebSocket authenticated: user_id={user_id}")

    recv_timeout = settings.WEBSOCKET_RECV_TIMEOUT
    # Task 33: 启动服务端心跳协程（独立 task，不阻塞主接收循环）
    heartbeat_state = {"pong_received": True, "running": True}
    heartbeat_task = asyncio.create_task(_heartbeat(websocket, heartbeat_state))
    try:
        # 发送欢迎消息
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket connected",
            "user_id": user_id,
        })

        # 循环接收消息（保持连接活跃，处理 ping/pong）
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(), timeout=recv_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"WebSocket ping timeout: user_id={user_id} "
                    f"({recv_timeout}s no message)"
                )
                try:
                    await websocket.close(code=4006, reason="Ping timeout")
                except Exception as e:
                    logger.debug(f"Recv timeout close failed: {e}")
                break

            # 频率限制（10/分钟，超过则关闭）
            if not await _check_rate_limit(user_id):
                logger.warning(
                    f"WebSocket rate limited: user_id={user_id} "
                    f"(>{settings.WEBSOCKET_RATE_LIMIT_PER_MINUTE}/min)"
                )
                try:
                    await websocket.close(code=4005, reason="Rate limited")
                except Exception as e:
                    logger.debug(f"Rate limit close failed: {e}")
                break

            # 客户端可以发送 ping，服务端回复 pong（向后兼容文本心跳）
            if data == "ping":
                await websocket.send_text("pong")
                continue

            # Task 33: 处理客户端 pong 响应（服务端心跳的应答）
            if data == "pong" or data == '{"event":"pong"}':
                heartbeat_state["pong_received"] = True
                heartbeat_state["pong_event"].set()
                continue
    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected: user_id={user_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user_id={user_id}: {e}")
    finally:
        # 停止心跳协程
        heartbeat_state["running"] = False
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError as e:
            # 取消心跳协程是预期行为，仅 debug 记录
            logger.debug(f"Heartbeat task cancelled: {e}")
        except Exception as e:
            # 其他异常可能掩盖心跳 bug，需 error 级别记录
            logger.error(f"Heartbeat task await failed: {e}")
        await NotificationManager.disconnect(user_id, websocket)
