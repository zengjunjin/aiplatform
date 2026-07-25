"""Tests for WebSocket endpoint (app.api.v1.ws) and NotificationManager.

覆盖 Task 20：
- SubTask 20.1: Origin 白名单校验
- SubTask 20.2: 单用户最大连接数 (5)
- SubTask 20.3: 消息频率限制 (10/分钟)
- SubTask 20.4: ping/pong 超时（30s）

注意：通过直接调用 websocket_endpoint 函数 + mock WebSocket 进行单元测试，
避免 TestClient/httpx 版本不兼容问题。
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from starlette.websockets import WebSocket

from app.api.v1 import ws as ws_module
from app.core.notification_manager import NotificationManager

# ---------- Helpers / Fixtures ----------


class MockWebSocket:
    """最小化的 WebSocket mock，支持 headers / accept / close / send_json / receive_text"""

    def __init__(self, headers: dict[str, str] | None = None):
        # Starlette WebSocket.headers 大小写不敏感
        self._headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.accepted = False
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str | None = None
        self.sent: list = []
        # receive_text 行为可被测试覆写
        self._receive_queue: asyncio.Queue = asyncio.Queue()

    @property
    def headers(self):
        return self._headers

    async def accept(self, subprotocol: str | None = None):
        self.accepted = True
        self.accept_subprotocol = subprotocol

    async def close(self, code: int = 1000, reason: str | None = None):
        self.closed = True
        self.close_code = code
        self.close_reason = reason

    async def send_json(self, data):
        self.sent.append(("json", data))

    async def send_text(self, text: str):
        self.sent.append(("text", text))

    async def receive_text(self):
        return await self._receive_queue.get()


@pytest.fixture
def reset_notification_manager():
    """每个测试前后清空 NotificationManager._connections 和进程内限流计数"""
    original = NotificationManager._connections.copy()
    original_rate = ws_module._inproc_rate_counters.copy()
    NotificationManager._connections.clear()
    # 重置 lock，避免跨测试事件循环绑定问题
    NotificationManager._lock = None
    ws_module._inproc_rate_counters.clear()
    yield
    NotificationManager._connections.clear()
    NotificationManager._connections.update(original)
    NotificationManager._lock = None
    ws_module._inproc_rate_counters.clear()
    ws_module._inproc_rate_counters.update(original_rate)


@pytest.fixture
def fake_access_token():
    """生成一个有效的 access token payload（mock decode_token 返回值）"""
    return {"sub": "1", "type": "access"}


@pytest.fixture
def short_recv_timeout(monkeypatch):
    """将接收超时缩短为 0.05s 以便测试"""
    from app.config import settings

    monkeypatch.setattr(settings, "WEBSOCKET_RECV_TIMEOUT", 0.05)
    yield


# ---------- SubTask 20.1: Origin 校验 ----------


class TestOriginValidation:
    """Origin 白名单校验"""

    @pytest.mark.asyncio
    async def test_forbidden_origin_rejected_with_4003(self, reset_notification_manager):
        """非白名单 Origin 应被拒绝，返回 4003，且不 accept"""
        ws = MockWebSocket(
            headers={
                "origin": "https://evil.example.com",
                "sec-websocket-protocol": "bearer.some.token",
            }
        )
        await ws_module.websocket_endpoint(ws)
        assert ws.closed is True
        assert ws.close_code == 4003
        assert ws.accepted is False  # 拒绝前不应 accept

    @pytest.mark.asyncio
    async def test_forbidden_origin_does_not_call_decode_token(self, reset_notification_manager):
        """非白名单 Origin 应在 token 解析之前被拒绝"""
        ws = MockWebSocket(
            headers={
                "origin": "https://evil.example.com",
                "sec-websocket-protocol": "bearer.some.token",
            }
        )
        with patch.object(ws_module, "decode_token") as mock_decode:
            await ws_module.websocket_endpoint(ws)
            mock_decode.assert_not_called()

    @pytest.mark.asyncio
    async def test_allowed_origin_proceeds_to_token_check(
        self, reset_notification_manager, fake_access_token, short_recv_timeout
    ):
        """白名单 Origin 应通过 Origin 校验进入 token 校验"""
        ws = MockWebSocket(
            headers={
                "origin": "http://localhost:5173",
                "sec-websocket-protocol": "bearer.some.token",
            }
        )
        with patch.object(ws_module, "decode_token", return_value=fake_access_token):
            with patch.object(NotificationManager, "connect", new=AsyncMock(return_value=True)):
                with patch.object(NotificationManager, "disconnect", new=AsyncMock()):
                    await ws_module.websocket_endpoint(ws)
        assert ws.accepted is True
        assert ws.close_code != 4003  # 不应因 Origin 被拒
        # 应因 ping 超时被关闭（receive_text 阻塞 → 超时）
        assert ws.close_code == 4006

    @pytest.mark.asyncio
    async def test_empty_origin_proceeds_to_token_check(
        self, reset_notification_manager, fake_access_token, short_recv_timeout
    ):
        """空 Origin（非浏览器客户端）应允许通过"""
        ws = MockWebSocket(
            headers={
                "origin": "",
                "sec-websocket-protocol": "bearer.some.token",
            }
        )
        with patch.object(ws_module, "decode_token", return_value=fake_access_token):
            with patch.object(NotificationManager, "connect", new=AsyncMock(return_value=True)):
                with patch.object(NotificationManager, "disconnect", new=AsyncMock()):
                    await ws_module.websocket_endpoint(ws)
        assert ws.accepted is True
        assert ws.close_code != 4003
        assert ws.close_code == 4006

    @pytest.mark.asyncio
    async def test_tauri_release_origins_accepted(
        self, reset_notification_manager, fake_access_token, short_recv_timeout
    ):
        """Tauri 2 release 模式所需的两个 origins 必须通过"""
        for origin in ("https://tauri.localhost", "http://tauri.localhost"):
            ws = MockWebSocket(
                headers={
                    "origin": origin,
                    "sec-websocket-protocol": "bearer.some.token",
                }
            )
            with patch.object(ws_module, "decode_token", return_value=fake_access_token):
                with patch.object(NotificationManager, "connect", new=AsyncMock(return_value=True)):
                    with patch.object(NotificationManager, "disconnect", new=AsyncMock()):
                        await ws_module.websocket_endpoint(ws)
            assert ws.accepted is True, f"Origin {origin} should be accepted"
            assert ws.close_code != 4003
            assert ws.close_code == 4006


# ---------- SubTask 20.2: 单用户连接数限制 ----------


class TestNotificationManagerConnectionLimit:
    """NotificationManager 单用户连接数限制 (5)"""

    @pytest.mark.asyncio
    async def test_sixth_connection_rejected_with_4004(self, reset_notification_manager):
        """第 6 个连接应被拒绝，返回 False 并 close"""
        # 创建 5 个已 accept 的 mock WebSocket
        sockets = []
        for _i in range(5):
            mock_ws = AsyncMock()
            mock_ws.close = AsyncMock()
            ok = await NotificationManager.connect("user1", mock_ws)
            assert ok is True
            sockets.append(mock_ws)

        # 第 6 个应被拒绝
        sixth = AsyncMock()
        sixth.close = AsyncMock()
        ok = await NotificationManager.connect("user1", sixth)
        assert ok is False
        # 应调用 close with code=4004
        sixth.close.assert_called_once()
        args, kwargs = sixth.close.call_args
        assert kwargs.get("code") == 4004

    @pytest.mark.asyncio
    async def test_first_five_connections_accepted(self, reset_notification_manager):
        """前 5 个连接应成功"""
        for _i in range(5):
            mock_ws = AsyncMock()
            ok = await NotificationManager.connect("user1", mock_ws)
            assert ok is True
        # 验证内部状态
        assert len(NotificationManager._connections["user1"]) == 5

    @pytest.mark.asyncio
    async def test_limit_is_per_user(self, reset_notification_manager):
        """不同用户互不影响"""
        for _i in range(5):
            await NotificationManager.connect("user1", AsyncMock())
        # user2 仍可连接
        ok = await NotificationManager.connect("user2", AsyncMock())
        assert ok is True

    @pytest.mark.asyncio
    async def test_disconnect_frees_slot(self, reset_notification_manager):
        """断开后释放配额"""
        sockets = []
        for _i in range(5):
            mock_ws = AsyncMock()
            await NotificationManager.connect("user1", mock_ws)
            sockets.append(mock_ws)

        # 断开一个
        await NotificationManager.disconnect("user1", sockets[0])
        # 新连接应成功
        ok = await NotificationManager.connect("user1", AsyncMock())
        assert ok is True


# ---------- SubTask 17.1: send_to_user 并行 ----------
class TestSendToUserParallel:
    """send_to_user 使用 asyncio.gather 并行发送 + return_exceptions 隔离失败"""

    @pytest.mark.asyncio
    async def test_send_to_user_sends_to_all_connections_in_parallel(
        self, reset_notification_manager
    ):
        """向单用户推送应并行发送到该用户的所有连接"""
        ws_a = AsyncMock()
        ws_a.send_text = AsyncMock()
        ws_b = AsyncMock()
        ws_b.send_text = AsyncMock()
        await NotificationManager.connect("user1", ws_a)
        await NotificationManager.connect("user1", ws_b)

        await NotificationManager.send_to_user("user1", {"type": "ping", "data": "hello"})

        ws_a.send_text.assert_awaited_once()
        ws_b.send_text.assert_awaited_once()
        # 内容应是 JSON 序列化后的消息
        import json as _json

        expected = _json.dumps({"type": "ping", "data": "hello"}, ensure_ascii=False)
        for ws in (ws_a, ws_b):
            assert ws.send_text.await_args[0][0] == expected

    @pytest.mark.asyncio
    async def test_send_to_user_isolates_failed_connections(self, reset_notification_manager):
        """单个连接发送失败不应阻断其他连接，失败连接应被移除"""
        # 用 spec=WebSocket 让 isinstance(r, WebSocket) 通过，
        # 否则 notification_manager.send_to_user 中 dead = [r for r in results if isinstance(r, WebSocket)]
        # 会因 AsyncMock 不是 WebSocket 子类而过滤掉 bad_ws，导致 bad_ws 未被移除。
        good_ws = AsyncMock(spec=WebSocket)
        good_ws.send_text = AsyncMock()
        bad_ws = AsyncMock(spec=WebSocket)
        bad_ws.send_text = AsyncMock(side_effect=RuntimeError("connection closed"))

        await NotificationManager.connect("user1", good_ws)
        await NotificationManager.connect("user1", bad_ws)

        # 推送不应抛出
        await NotificationManager.send_to_user("user1", {"type": "ping"})

        good_ws.send_text.assert_awaited_once()
        bad_ws.send_text.assert_awaited_once()
        # bad_ws 应被移除，good_ws 仍保留
        assert good_ws in NotificationManager._connections["user1"]
        assert bad_ws not in NotificationManager._connections["user1"]

    @pytest.mark.asyncio
    async def test_send_to_user_uses_gather_not_sequential(self, reset_notification_manager):
        """验证 send_to_user 使用 asyncio.gather（并行）而非串行 await"""
        import asyncio

        ws1 = AsyncMock()
        ws2 = AsyncMock()

        send_order = []

        async def slow_send(text):
            send_order.append("start1")
            await asyncio.sleep(0.05)
            send_order.append("end1")

        async def slow_send2(text):
            send_order.append("start2")
            await asyncio.sleep(0.05)
            send_order.append("end2")

        ws1.send_text = slow_send
        ws2.send_text = slow_send2

        await NotificationManager.connect("user1", ws1)
        await NotificationManager.connect("user1", ws2)

        await NotificationManager.send_to_user("user1", {"type": "ping"})
        # 并行：两个 start 应在两个 end 之前
        starts = [i for i, x in enumerate(send_order) if x.startswith("start")]
        # 如果是串行，会 start1, end1, start2, end2 - starts=[0,2], ends=[1,3]
        # 如果是并行，会 start1, start2, end1, end2 (or similar) - starts=[0,1], ends=[2,3]
        assert starts == [0, 1], f"Expected parallel start, got order: {send_order}"


# ---------- SubTask 17.2: _connections asyncio.Lock 保护 ----------
class TestConnectionsLock:
    """_connections 修改受 asyncio.Lock 保护"""

    @pytest.mark.asyncio
    async def test_lock_is_initialized_on_first_use(self, reset_notification_manager):
        """锁在首次使用时 lazy 初始化"""
        NotificationManager._lock = None
        lock = NotificationManager._get_lock()
        assert lock is not None
        assert isinstance(lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_concurrent_connects_are_serialized(self, reset_notification_manager):
        """并发 connect 不会破坏 _connections 结构"""
        # 并发 5 个 connect，最终应有 5 个连接
        sockets = [AsyncMock() for _ in range(5)]
        await asyncio.gather(*[NotificationManager.connect("user1", ws) for ws in sockets])
        assert len(NotificationManager._connections["user1"]) == 5

    @pytest.mark.asyncio
    async def test_concurrent_connect_and_disconnect_safe(self, reset_notification_manager):
        """并发 connect + disconnect 不应导致 _connections 状态错误"""
        sockets = [AsyncMock() for _ in range(3)]
        for ws in sockets:
            await NotificationManager.connect("user1", ws)

        # 并发：同时 connect 新的和 disconnect 已有的
        new_ws = AsyncMock()
        await asyncio.gather(
            NotificationManager.connect("user1", new_ws),
            NotificationManager.disconnect("user1", sockets[0]),
        )
        # 最终应有 3 个连接（原 3 - 1 + 1）
        assert len(NotificationManager._connections["user1"]) == 3
        assert sockets[0] not in NotificationManager._connections["user1"]
        assert new_ws in NotificationManager._connections["user1"]


# ---------- SubTask 20.3: 消息频率限制 ----------


class TestRateLimit:
    """_check_rate_limit 函数：10/分钟，超过则 False"""

    @pytest.mark.asyncio
    async def test_redis_rate_limit_allows_under_limit(self, reset_notification_manager):
        """Redis 模式下：计数 ≤ 10 允许通过"""
        fake_redis = AsyncMock()
        # 模拟 incr 每次返回递增
        counts = iter([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])

        async def fake_incr(key):
            return next(counts)

        fake_redis.incr = fake_incr
        fake_redis.expire = AsyncMock()

        with patch.object(ws_module, "get_redis", return_value=fake_redis):
            for _ in range(10):
                assert await ws_module._check_rate_limit("user1") is True

    @pytest.mark.asyncio
    async def test_redis_rate_limit_blocks_over_limit(self, reset_notification_manager):
        """Redis 模式下：计数 > 10 拒绝"""
        fake_redis = AsyncMock()
        counts = iter([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])

        async def fake_incr(key):
            return next(counts)

        fake_redis.incr = fake_incr
        fake_redis.expire = AsyncMock()

        with patch.object(ws_module, "get_redis", return_value=fake_redis):
            for _ in range(10):
                assert await ws_module._check_rate_limit("user1") is True
            # 第 11 次应被拒
            assert await ws_module._check_rate_limit("user1") is False

    @pytest.mark.asyncio
    async def test_redis_exception_falls_back_to_inproc(self, reset_notification_manager):
        """Redis 异常时降级为内存计数"""
        fake_redis = AsyncMock()
        fake_redis.incr = AsyncMock(side_effect=Exception("Redis down"))

        with patch.object(ws_module, "get_redis", return_value=fake_redis):
            # Redis 异常 → 降级到内存，前 10 次允许
            for _ in range(10):
                assert await ws_module._check_rate_limit("user_fb") is True
            # 第 11 次应被拒
            assert await ws_module._check_rate_limit("user_fb") is False

    @pytest.mark.asyncio
    async def test_no_redis_falls_back_to_inproc(self, reset_notification_manager):
        """Redis 未初始化时降级为内存计数"""
        with patch.object(ws_module, "get_redis", return_value=None):
            for _ in range(10):
                assert await ws_module._check_rate_limit("user_noredis") is True
            assert await ws_module._check_rate_limit("user_noredis") is False


# ---------- SubTask 20.4: ping/pong 超时（间接验证配置） ----------


class TestPingPongTimeoutConfig:
    """ping/pong 超时配置可用（实际超时行为集成测试难做，仅验证配置读取）"""

    def test_recv_timeout_setting(self):
        from app.config import settings

        assert settings.WEBSOCKET_RECV_TIMEOUT == 30

    def test_rate_limit_setting(self):
        from app.config import settings

        assert settings.WEBSOCKET_RATE_LIMIT_PER_MINUTE == 10

    def test_max_connections_setting(self):
        from app.config import settings

        assert settings.WEBSOCKET_MAX_CONNECTIONS_PER_USER == 5

    def test_websocket_allowed_origins_includes_tauri(self):
        """白名单必须包含 Tauri 2 release 模式所需 origins"""
        from app.config import settings

        origins = settings.websocket_allowed_origins_list
        assert "https://tauri.localhost" in origins
        assert "http://tauri.localhost" in origins
