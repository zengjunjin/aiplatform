"""Tests for app.api.deps"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.security import HTTPAuthorizationCredentials
from app.api import deps
from app.core.exceptions import AuthError, ForbiddenError
from app.core.security import create_access_token, create_refresh_token
from app.db.user import User


def _make_user(user_id=1, role="user", is_active=True):
    u = MagicMock(spec=User)
    u.id = user_id
    u.role = role
    u.is_active = is_active
    u.username = "tester"
    u.email = "t@example.com"
    return u


class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_no_credentials_raises(self):
        """无 credentials → AuthError"""
        with pytest.raises(AuthError):
            await deps.get_current_user(credentials=None, db=AsyncMock())

    @pytest.mark.asyncio
    async def test_invalid_token_raises(self, monkeypatch):
        """无效 token → AuthError"""
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid.token")
        monkeypatch.setattr(deps, "decode_token", lambda t: None)
        with pytest.raises(AuthError):
            await deps.get_current_user(credentials=creds, db=AsyncMock())

    @pytest.mark.asyncio
    async def test_wrong_token_type_raises(self, monkeypatch):
        """refresh token 当 access token 用 → AuthError"""
        token = create_refresh_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with pytest.raises(AuthError):
            await deps.get_current_user(credentials=creds, db=AsyncMock())

    @pytest.mark.asyncio
    async def test_invalid_subject_raises(self):
        """sub <= 0 → AuthError"""
        # 创建一个 type=access 但 sub=0 的 token（通过修改 decode_token 返回值）
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with patch("app.api.deps.decode_token", return_value={"type": "access", "sub": "0"}):
            with pytest.raises(AuthError):
                await deps.get_current_user(credentials=creds, db=AsyncMock())

    @pytest.mark.asyncio
    async def test_blacklisted_token_raises(self):
        """黑名单 token → AuthError"""
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(return_value="1")
        with patch("app.api.deps.get_redis", return_value=redis_mock):
            with pytest.raises(AuthError):
                await deps.get_current_user(credentials=creds, db=db)

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self):
        """用户被删除 → AuthError"""
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        with patch("app.api.deps.get_redis", return_value=None):
            with pytest.raises(AuthError):
                await deps.get_current_user(credentials=creds, db=db)

    @pytest.mark.asyncio
    async def test_disabled_user_raises(self):
        """用户被禁用 → AuthError"""
        user = _make_user(is_active=False)
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))
        with patch("app.api.deps.get_redis", return_value=None):
            with pytest.raises(AuthError):
                await deps.get_current_user(credentials=creds, db=db)

    @pytest.mark.asyncio
    async def test_valid_user_returns_user(self):
        """完整有效 token → 返回 user"""
        user = _make_user()
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))
        with patch("app.api.deps.get_redis", return_value=None):
            result = await deps.get_current_user(credentials=creds, db=db)
        assert result is user


class TestGetAdminUser:
    @pytest.mark.asyncio
    async def test_admin_role_returns_user(self):
        user = _make_user(role="admin")
        result = await deps.get_admin_user(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_non_admin_role_raises_forbidden(self):
        user = _make_user(role="user")
        with pytest.raises(ForbiddenError):
            await deps.get_admin_user(user=user)


class TestGetOptionalUser:
    @pytest.mark.asyncio
    async def test_no_credentials_returns_none(self):
        """无 credentials → None（不抛错）"""
        result = await deps.get_optional_user(credentials=None, db=AsyncMock())
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_credentials_returns_none(self):
        """无效 credentials → None（吞掉 AuthError）"""
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        with patch("app.api.deps.get_redis", return_value=None):
            result = await deps.get_optional_user(credentials=creds, db=db)
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_credentials_returns_user(self):
        """有效 credentials → user"""
        user = _make_user()
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))
        with patch("app.api.deps.get_redis", return_value=None):
            result = await deps.get_optional_user(credentials=creds, db=db)
        assert result is user
