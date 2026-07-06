"""Tests for app.api.v1.auth route handlers (HTTP endpoints)"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.requests import Request
from app.api.v1 import auth
from app.core.exceptions import AuthError, ConflictError
from app.db.user import User


@pytest.fixture
def user():
    u = MagicMock(spec=User)
    u.id = 1
    u.username = "tester"
    u.email = "t@example.com"
    u.role = "user"
    u.is_active = True
    u.created_at = MagicMock()
    u.created_at.isoformat.return_value = "2026-01-01T00:00:00"
    return u


@pytest.fixture
def db():
    return AsyncMock()


@pytest.fixture
def request_mock():
    """真实 starlette Request，limiter 装饰器需要"""
    scope = {
        "type": "http", "method": "POST", "path": "/api/v1/auth/register",
        "headers": [], "query_string": b"", "client": ("127.0.0.1", 8000),
    }
    return Request(scope)


class TestRegisterRoute:
    @pytest.mark.asyncio
    async def test_register_success(self, user, db, request_mock):
        req = MagicMock()
        with patch("app.services.auth_service.register", new=AsyncMock(return_value=user)):
            with patch("app.services.audit_service.log_audit", new=AsyncMock()):
                result = await auth.register(request=request_mock, req=req, db=db)
        assert result["data"]["username"] == "tester"


class TestLoginRoute:
    @pytest.mark.asyncio
    async def test_login_success(self, user, db, request_mock):
        tokens = {"access_token": "at", "refresh_token": "rt", "user": {"id": 1}}
        req = MagicMock()
        req.username = "tester"
        with patch("app.services.auth_service.login", new=AsyncMock(return_value=tokens)):
            with patch("app.services.audit_service.log_audit", new=AsyncMock()):
                result = await auth.login(request=request_mock, req=req, db=db)
        assert result["data"]["access_token"] == "at"

    @pytest.mark.asyncio
    async def test_login_failure_logs_audit_and_reraises(self, db, request_mock):
        """AppException 失败 → 记录 audit fail 后重新抛出"""
        req = MagicMock()
        req.username = "tester"
        # AuthError 继承 AppException，isinstance 检查会通过
        # 注意：auth.py 用 `from app.services.audit_service import log_audit`
        # 所以 patch 路径是 app.api.v1.auth.log_audit
        with patch("app.services.auth_service.login", new=AsyncMock(side_effect=AuthError("bad"))):
            with patch("app.api.v1.auth.log_audit", new=AsyncMock()) as mock_audit:
                with pytest.raises(AuthError):
                    await auth.login(request=request_mock, req=req, db=db)
        # 应记录 fail audit
        audit_calls = mock_audit.await_args_list
        assert any(c.kwargs.get("result") == "fail" for c in audit_calls)

    @pytest.mark.asyncio
    async def test_login_non_app_exception_no_audit_fail(self, db, request_mock):
        """非 AppException 异常 → 不记录 fail audit"""
        req = MagicMock()
        req.username = "tester"
        with patch("app.services.auth_service.login", new=AsyncMock(side_effect=ValueError("boom"))):
            with patch("app.api.v1.auth.log_audit", new=AsyncMock()) as mock_audit:
                with pytest.raises(ValueError):
                    await auth.login(request=request_mock, req=req, db=db)
        # 不应有 fail audit
        audit_calls = mock_audit.await_args_list
        assert not any(c.kwargs.get("result") == "fail" for c in audit_calls)


class TestRefreshRoute:
    @pytest.mark.asyncio
    async def test_refresh_success(self, db):
        tokens = {"access_token": "at", "refresh_token": "rt"}
        req = MagicMock()
        with patch("app.services.auth_service.refresh_token", new=AsyncMock(return_value=tokens)):
            result = await auth.refresh(req=req, db=db)
        assert result["data"]["access_token"] == "at"


class TestMeRoute:
    @pytest.mark.asyncio
    async def test_me_returns_user(self, user):
        result = await auth.me(user=user)
        assert result["data"]["username"] == "tester"


class TestLogoutRoute:
    @pytest.mark.asyncio
    async def test_logout_with_bearer_token(self, user, db):
        """Authorization: Bearer xxx → 加入黑名单"""
        request_mock = MagicMock()
        request_mock.headers.get.return_value = "Bearer xxx.token.yyy"
        with patch("app.services.auth_service.add_to_blacklist", new=AsyncMock()) as mock_bl:
            with patch("app.services.audit_service.log_audit", new=AsyncMock()):
                result = await auth.logout(user=user, request=request_mock, db=db)
        mock_bl.assert_awaited_once_with("xxx.token.yyy", "access")
        assert "message" in result

    @pytest.mark.asyncio
    async def test_logout_without_bearer_token(self, user, db):
        """无 Authorization 头 → 不加入黑名单"""
        request_mock = MagicMock()
        request_mock.headers.get.return_value = ""
        with patch("app.services.auth_service.add_to_blacklist", new=AsyncMock()) as mock_bl:
            with patch("app.services.audit_service.log_audit", new=AsyncMock()):
                result = await auth.logout(user=user, request=request_mock, db=db)
        mock_bl.assert_not_awaited()
        assert "message" in result


class TestChangePasswordRoute:
    @pytest.mark.asyncio
    async def test_change_password_success(self, user, db):
        request_mock = MagicMock()
        req = MagicMock()
        req.old_password = "Old123!@#"
        req.new_password = "New123!@#"
        with patch("app.services.user_service.change_password", new=AsyncMock()) as mock_cp:
            with patch("app.services.audit_service.log_audit", new=AsyncMock()):
                result = await auth.change_password(req=req, user=user, db=db, request=request_mock)
        mock_cp.assert_awaited_once_with(user.id, "Old123!@#", "New123!@#", db)
        assert "message" in result
