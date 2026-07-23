"""Tests for Task 27: /metrics 端点保护.

验证 /metrics 端点要求 admin 身份认证，防止未授权的指标信息泄露。
覆盖三种场景:
  1. 未认证访问 → 401 (AuthError)
  2. 非 admin 用户访问 → 403 (ForbiddenError)
  3. admin 用户访问 → 200 + Prometheus 格式内容
"""
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import MagicMock

from app.api.deps import get_admin_user
from app.core.exceptions import AuthError, ForbiddenError
from app.main import app


@pytest.fixture(autouse=True)
def _reset_dependency_overrides():
    """每个测试后清理 dependency_overrides，避免污染其他测试。"""
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_metrics_unauthenticated_returns_401():
    """未认证访问 /metrics → 401 (模拟无 token 场景)."""
    async def _raise_auth_error():
        raise AuthError("Missing authentication token")

    app.dependency_overrides[get_admin_user] = _raise_auth_error

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics")

    assert resp.status_code == 401
    body = resp.json()
    assert body["data"] is None


@pytest.mark.asyncio
async def test_metrics_non_admin_returns_403():
    """非 admin 用户访问 /metrics → 403 (ForbiddenError)."""
    async def _raise_forbidden_error():
        raise ForbiddenError("Admin access required")

    app.dependency_overrides[get_admin_user] = _raise_forbidden_error

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics")

    assert resp.status_code == 403
    body = resp.json()
    assert body["data"] is None


@pytest.mark.asyncio
async def test_metrics_admin_returns_200():
    """admin 用户访问 /metrics → 200 + Prometheus 指标内容."""
    admin_user = MagicMock()
    admin_user.id = 1
    admin_user.role = "admin"

    async def _return_admin():
        return admin_user

    app.dependency_overrides[get_admin_user] = _return_admin

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics")

    assert resp.status_code == 200
    # Prometheus 默认输出 text/plain 且包含版本标记
    assert "text/plain" in resp.headers.get("content-type", "")
    # generate_latest() 至少会返回进程指标等默认内容
    assert resp.text


def test_metrics_route_has_admin_dependency():
    """/metrics 路由必须声明 get_admin_user 依赖（防止回归移除保护）."""
    metrics_route = None
    for route in app.routes:
        if getattr(route, "path", None) == "/metrics":
            metrics_route = route
            break
    assert metrics_route is not None, "/metrics 路由未注册"

    dependant = getattr(metrics_route, "dependant", None)
    assert dependant is not None, "/metrics 路由缺少 dependant 信息"

    # dependant.dependencies 中每个 Dependant 的 call 字段是实际被依赖的可调用对象
    dependency_calls = [d.call for d in dependant.dependencies]
    assert get_admin_user in dependency_calls, (
        "/metrics 端点未声明 get_admin_user 依赖，指标端点未受保护"
    )
