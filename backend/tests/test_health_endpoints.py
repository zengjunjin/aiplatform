"""Tests for Task 45: /healthz 与 /readyz 健康端点分离.

覆盖:
  - /healthz: liveness probe, 永远返回 200 + {"status": "ok"}
  - /readyz: readiness probe, 探测 DB/Redis/Qdrant
    - 全部就绪 → 200 + {"status": "ready", "checks": {...}}
    - 任一失败 → 503 + {"status": "not_ready", "checks": {...}}
  - /health: 向后兼容端点（保持 legacy 响应格式不变）
"""
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
        patch("app.main._check_db", new=AsyncMock(return_value=(False, "error: connection refused"))),
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
        patch("app.main._check_qdrant", new=AsyncMock(return_value=(False, "error: connection refused"))),
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


@pytest.mark.asyncio
async def test_health_legacy_endpoint_still_works():
    """/health 向后兼容端点保持 legacy 响应格式（{"code": 0, ...}）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 0
    assert data["data"]["status"] == "healthy"


def test_health_endpoints_registered():
    """验证 /healthz 与 /readyz 路由已注册。"""
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/healthz" in paths, "/healthz 路由未注册"
    assert "/readyz" in paths, "/readyz 路由未注册"
