"""Tests for Task 45: /healthz 与 /readyz 健康端点分离.

覆盖:
  - /healthz: liveness probe, 永远返回 200 + {"status": "ok"}
  - /readyz: readiness probe, 探测 DB/Redis/Qdrant
    - 全部就绪 → 200 + {"status": "ready", "checks": {...}}
    - 任一失败 → 503 + {"status": "not_ready", "checks": {...}}
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_healthz_returns_ok():
    """/healthz liveness probe 永远返回 200 + {"status": "ok"}。

    不探测任何外部依赖，只要进程能响应即视为存活。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz_all_healthy_returns_200():
    """所有依赖（DB/Redis/Qdrant）就绪时 /readyz 返回 200 + ready。"""
    with (
        patch("app.main._check_db", new=AsyncMock(return_value=(True, "ok"))),
        patch("app.main._check_redis", new=AsyncMock(return_value=(True, "ok"))),
        patch("app.main._check_qdrant", new=AsyncMock(return_value=(True, "ok"))),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/readyz")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["checks"] == {"db": "ok", "redis": "ok", "qdrant": "ok"}


@pytest.mark.asyncio
async def test_readyz_db_failure_returns_503():
    """DB 探测失败时 /readyz 返回 503 + not_ready，db check 包含错误信息。"""
    with (
        patch(
            "app.main._check_db", new=AsyncMock(return_value=(False, "error: connection refused"))
        ),
        patch("app.main._check_redis", new=AsyncMock(return_value=(True, "ok"))),
        patch("app.main._check_qdrant", new=AsyncMock(return_value=(True, "ok"))),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/readyz")

    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "not_ready"
    assert "error" in data["checks"]["db"]
    assert data["checks"]["redis"] == "ok"
    assert data["checks"]["qdrant"] == "ok"


@pytest.mark.asyncio
async def test_readyz_redis_failure_returns_503():
    """Redis 探测失败时 /readyz 返回 503 + not_ready。"""
    with (
        patch("app.main._check_db", new=AsyncMock(return_value=(True, "ok"))),
        patch("app.main._check_redis", new=AsyncMock(return_value=(False, "error: ping timeout"))),
        patch("app.main._check_qdrant", new=AsyncMock(return_value=(True, "ok"))),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/readyz")

    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "not_ready"
    assert "error" in data["checks"]["redis"]
    assert data["checks"]["db"] == "ok"
    assert data["checks"]["qdrant"] == "ok"


@pytest.mark.asyncio
async def test_readyz_qdrant_failure_returns_503():
    """Qdrant 探测失败时 /readyz 返回 503 + not_ready。"""
    with (
        patch("app.main._check_db", new=AsyncMock(return_value=(True, "ok"))),
        patch("app.main._check_redis", new=AsyncMock(return_value=(True, "ok"))),
        patch(
            "app.main._check_qdrant",
            new=AsyncMock(return_value=(False, "error: connection refused")),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/readyz")

    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "not_ready"
    assert "error" in data["checks"]["qdrant"]
    assert data["checks"]["db"] == "ok"
    assert data["checks"]["redis"] == "ok"


@pytest.mark.asyncio
async def test_readyz_all_failure_returns_503():
    """所有依赖都失败时 /readyz 返回 503，所有 checks 包含错误信息。"""
    with (
        patch("app.main._check_db", new=AsyncMock(return_value=(False, "error: db down"))),
        patch("app.main._check_redis", new=AsyncMock(return_value=(False, "error: redis down"))),
        patch("app.main._check_qdrant", new=AsyncMock(return_value=(False, "error: qdrant down"))),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/readyz")

    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "not_ready"
    assert "error" in data["checks"]["db"]
    assert "error" in data["checks"]["redis"]
    assert "error" in data["checks"]["qdrant"]


@pytest.mark.asyncio
async def test_readyz_response_contains_all_three_checks():
    """/readyz 响应必须包含 db/redis/qdrant 三个 check 项。"""
    with (
        patch("app.main._check_db", new=AsyncMock(return_value=(True, "ok"))),
        patch("app.main._check_redis", new=AsyncMock(return_value=(True, "ok"))),
        patch("app.main._check_qdrant", new=AsyncMock(return_value=(True, "ok"))),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/readyz")

    data = resp.json()
    assert set(data["checks"].keys()) == {"db", "redis", "qdrant"}


def test_health_endpoints_registered():
    """验证 /healthz 与 /readyz 路由已注册。"""
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/healthz" in paths, "/healthz 路由未注册"
    assert "/readyz" in paths, "/readyz 路由未注册"


# ---------- 阶段 5: /readyz 探测超时一致性 ----------
class TestReadyzCheckTimeout:
    """验证 _check_db / _check_redis / _check_qdrant 在依赖慢响应时
    被 asyncio.wait_for(timeout=2) 截断，避免 /readyz 长时间挂起。

    覆盖 spec 阶段 5 验收点：模拟 DB 慢响应，/readyz 在 2 秒内返回。
    """

    @pytest.mark.asyncio
    async def test_check_db_slow_response_timed_out(self):
        """DB 探测慢响应（sleep 5s）应在 2s 内被超时截断，返回 (False, error)."""
        import time

        from app.main import _check_db

        async def slow_check():
            await asyncio.sleep(5)  # 模拟 DB 慢响应
            return True, "ok"

        with patch("app.main.health_checks.check_db", side_effect=slow_check):
            start = time.monotonic()
            ok, msg = await _check_db()
            elapsed = time.monotonic() - start

        assert ok is False
        assert "error" in msg or "timeout" in msg.lower()
        # 验证超时生效：实际耗时远小于 5s（留 1s 余量给 mock/调度开销）
        assert elapsed < 3.0, f"expected <3s, got {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_check_redis_slow_response_timed_out(self):
        """Redis 探测慢响应应在 2s 内被超时截断。"""
        import time

        from app.main import _check_redis

        async def slow_check():
            await asyncio.sleep(5)
            return True, "ok"

        with patch("app.main.health_checks.check_redis", side_effect=slow_check):
            start = time.monotonic()
            ok, msg = await _check_redis()
            elapsed = time.monotonic() - start

        assert ok is False
        assert "error" in msg or "timeout" in msg.lower()
        assert elapsed < 3.0, f"expected <3s, got {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_check_qdrant_slow_response_timed_out(self):
        """Qdrant 探测慢响应应在 2s 内被超时截断。"""
        import time

        from app.main import _check_qdrant

        async def slow_check():
            await asyncio.sleep(5)
            return True, "ok"

        with patch("app.main.health_checks.check_qdrant", side_effect=slow_check):
            start = time.monotonic()
            ok, msg = await _check_qdrant()
            elapsed = time.monotonic() - start

        assert ok is False
        assert "error" in msg or "timeout" in msg.lower()
        assert elapsed < 3.0, f"expected <3s, got {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_readyz_returns_within_timeout_when_db_slow(self):
        """端到端：DB 慢响应时 /readyz 端点应在 ~2s 内返回 503。"""
        import time

        async def slow_db():
            await asyncio.sleep(5)
            return True, "ok"

        with (
            patch("app.main.health_checks.check_db", side_effect=slow_db),
            patch("app.main._check_redis", new=AsyncMock(return_value=(True, "ok"))),
            patch("app.main._check_qdrant", new=AsyncMock(return_value=(True, "ok"))),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test", timeout=10
            ) as client:
                start = time.monotonic()
                resp = await client.get("/readyz")
                elapsed = time.monotonic() - start

        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "not_ready"
        assert "error" in data["checks"]["db"]
        # DB 慢响应被 2s 超时截断，端点总耗时远小于 5s
        assert elapsed < 3.5, f"expected <3.5s, got {elapsed:.2f}s"
