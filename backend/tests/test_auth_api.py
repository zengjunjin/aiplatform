"""Tests for authentication API and auth_service.

Covers:
- Register / login / refresh / logout flow
- Password strength validation
- JWT blacklist (logout) behavior
- Conflict on duplicate username/email
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthError, ConflictError, ValidationError
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.db.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest
from app.services import auth_service


@pytest.fixture
def fake_user():
    """模拟数据库中已存在的 admin 用户。"""
    u = MagicMock(spec=User)
    u.id = 1
    u.username = "admin"
    u.email = "admin@example.com"
    u.role = "admin"
    u.is_active = True
    u.password_hash = auth_service.hash_password("Admin123!@#")
    return u


class TestPasswordValidation:
    """validate_password_strength - 设计文档要求 ≥8 字符 + 大小写 + 数字 + 特殊字符。"""

    def test_strong_password_passes(self):
        auth_service.validate_password_strength("Admin123!@#")

    def test_short_password_rejected(self):
        with pytest.raises(ValidationError):
            auth_service.validate_password_strength("Aa1!")

    def test_no_uppercase_rejected(self):
        with pytest.raises(ValidationError):
            auth_service.validate_password_strength("admin123!@#")

    def test_no_lowercase_rejected(self):
        with pytest.raises(ValidationError):
            auth_service.validate_password_strength("ADMIN123!@#")

    def test_no_digit_rejected(self):
        with pytest.raises(ValidationError):
            auth_service.validate_password_strength("Admin!@#abc")

    def test_no_special_char_rejected(self):
        with pytest.raises(ValidationError):
            auth_service.validate_password_strength("Admin12345")


class TestRegister:
    @pytest.mark.asyncio
    async def test_register_success(self, fake_user, make_auth_db):
        """注册新用户：DB 返回 None → 创建用户 → 返回 User 对象"""
        db = make_auth_db(user=None)

        # 模拟 db.add 后 db.refresh 填充 id
        async def fake_refresh(obj, *args, **kwargs):
            obj.id = 99

        db.refresh = AsyncMock(side_effect=fake_refresh)

        req = RegisterRequest(
            username="newuser",
            email="new@example.com",
            password="Strong123!@#",
        )
        user = await auth_service.register(req, db)

        assert user.username == "newuser"
        assert user.email == "new@example.com"
        assert user.role == "user"
        assert user.id == 99
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_duplicate_username_raises_conflict(self, fake_user, make_auth_db):
        """已存在用户名/邮箱 → ConflictError"""
        db = make_auth_db(user=fake_user)  # execute 返回已存在 user
        req = RegisterRequest(
            username="admin",
            email="another@example.com",
            password="Strong123!@#",
        )
        with pytest.raises(ConflictError):
            await auth_service.register(req, db)

    @pytest.mark.asyncio
    async def test_register_weak_password_raises_validation_error(self, make_auth_db):
        """弱密码 → ValidationError（service 层强度校验，在查重之前抛出）。
        RegisterRequest 限制 password ≥8 字符，所以这里用 9 字符但缺大写字母和特殊字符的弱密码。"""
        db = make_auth_db(user=None)
        req = RegisterRequest(
            username="weakpwd",
            email="weak@example.com",
            password="abcdef123",  # 9 字符但缺大写字母和特殊字符
        )
        with pytest.raises(ValidationError):
            await auth_service.register(req, db)


class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success_returns_tokens(self, fake_user, make_auth_db):
        """正确密码登录 → 返回 access/refresh token + user 信息"""
        db = make_auth_db(user=fake_user)
        req = LoginRequest(username="admin", password="Admin123!@#")
        result = await auth_service.login(req, db)

        assert "access_token" in result
        assert "refresh_token" in result
        assert result["token_type"] == "bearer"
        # 修复（v0.4.0）：用 settings.ACCESS_TOKEN_EXPIRE_MINUTES 动态计算，
        # 避免容器 .env 覆盖默认值（如 60 分钟）时测试失败
        from app.config import settings as _settings

        assert result["expires_in"] == _settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        assert result["user"]["id"] == fake_user.id
        assert result["user"]["username"] == "admin"
        assert result["user"]["role"] == "admin"

        # 验证 access token 可解码且类型正确
        payload = decode_token(result["access_token"])
        assert payload is not None
        assert payload["type"] == "access"
        assert payload["sub"] == str(fake_user.id)
        assert payload["role"] == "admin"

    @pytest.mark.asyncio
    async def test_login_wrong_password_raises_auth_error(self, fake_user, make_auth_db):
        """密码错误 → AuthError"""
        db = make_auth_db(user=fake_user)
        req = LoginRequest(username="admin", password="WrongPassword!1")
        with pytest.raises(AuthError):
            await auth_service.login(req, db)

    @pytest.mark.asyncio
    async def test_login_nonexistent_user_raises_auth_error(self, make_auth_db):
        """用户不存在 → AuthError（不暴露用户是否存在）"""
        db = make_auth_db(user=None)
        req = LoginRequest(username="ghost", password="Any123!@#")
        with pytest.raises(AuthError):
            await auth_service.login(req, db)

    @pytest.mark.asyncio
    async def test_login_disabled_user_raises_auth_error(self, fake_user, make_auth_db):
        """账户被禁用 → AuthError"""
        fake_user.is_active = False
        db = make_auth_db(user=fake_user)
        req = LoginRequest(username="admin", password="Admin123!@#")
        with pytest.raises(AuthError):
            await auth_service.login(req, db)
        fake_user.is_active = True  # 还原

    @pytest.mark.asyncio
    async def test_login_supports_email(self, fake_user, make_auth_db):
        """LoginRequest.username 字段同时支持 username 和 email"""
        db = make_auth_db(user=fake_user)
        req = LoginRequest(username="admin@example.com", password="Admin123!@#")
        result = await auth_service.login(req, db)
        assert "access_token" in result


class TestRefreshToken:
    @pytest.mark.asyncio
    async def test_refresh_success(self, fake_user, make_auth_db):
        """有效 refresh token → 返回新的 access + refresh token"""
        db = make_auth_db(user=fake_user)
        refresh = create_refresh_token(str(fake_user.id))
        req = RefreshRequest(refresh_token=refresh)
        result = await auth_service.refresh_token(req.refresh_token, db)

        assert "access_token" in result
        assert "refresh_token" in result
        # 新 access token 可解码
        payload = decode_token(result["access_token"])
        assert payload["type"] == "access"
        assert payload["sub"] == str(fake_user.id)

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_rejected(self, fake_user, make_auth_db):
        """用 access token 当 refresh token → AuthError"""
        db = make_auth_db(user=fake_user)
        access = create_access_token(str(fake_user.id))
        with pytest.raises(AuthError):
            await auth_service.refresh_token(access, db)

    @pytest.mark.asyncio
    async def test_refresh_invalid_token_rejected(self, fake_user, make_auth_db):
        """无效 refresh token → AuthError"""
        db = make_auth_db(user=fake_user)
        with pytest.raises(AuthError):
            await auth_service.refresh_token("invalid.token.string", db)

    @pytest.mark.asyncio
    async def test_refresh_disabled_user_rejected(self, fake_user, make_auth_db):
        """refresh 时用户已被禁用 → AuthError"""
        fake_user.is_active = False
        db = make_auth_db(user=fake_user)
        refresh = create_refresh_token(str(fake_user.id))
        with pytest.raises(AuthError):
            await auth_service.refresh_token(refresh, db)
        fake_user.is_active = True

    @pytest.mark.asyncio
    async def test_refresh_nonexistent_user_rejected(self, make_auth_db):
        """refresh 时用户已删除 → AuthError"""
        db = make_auth_db(user=None)
        refresh = create_refresh_token("9999")
        with pytest.raises(AuthError):
            await auth_service.refresh_token(refresh, db)


class TestJWTBlacklist:
    """JWT 黑名单（登出）逻辑 - 设计文档 A2 要求。"""

    @pytest.mark.asyncio
    async def test_add_to_blacklist_stores_key_with_ttl(self, fake_user):
        """登出 → 在 Redis 写入 blacklist key，带 TTL"""
        token = create_access_token(str(fake_user.id))
        redis_mock = MagicMock()
        redis_mock.setex = AsyncMock()

        # auth_service.add_to_blacklist 内部通过 `from app.redis_client import get_redis`
        # 引入 redis，所以 patch app.redis_client.get_redis 即可
        with patch("app.redis_client.get_redis", return_value=redis_mock):
            from app.services.auth_service import add_to_blacklist

            await add_to_blacklist(token, "access")

        redis_mock.setex.assert_awaited_once()
        args = redis_mock.setex.await_args
        key, ttl, value = args[0]
        assert key.startswith("auth:blacklist:access:")
        assert ttl > 0
        assert value == "1"

    @pytest.mark.asyncio
    async def test_is_blacklisted_true_when_key_exists(self):
        """Redis 中存在 key → True"""
        redis_mock = MagicMock()
        redis_mock.exists = AsyncMock(return_value=1)

        with patch("app.redis_client.get_redis", return_value=redis_mock):
            from app.services.auth_service import is_blacklisted

            result = await is_blacklisted("any.token.here", "access")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_blacklisted_false_when_key_absent(self):
        """Redis 中无 key → False"""
        redis_mock = MagicMock()
        redis_mock.exists = AsyncMock(return_value=0)

        with patch("app.redis_client.get_redis", return_value=redis_mock):
            from app.services.auth_service import is_blacklisted

            result = await is_blacklisted("any.token.here", "access")
        assert result is False

    @pytest.mark.asyncio
    async def test_add_to_blacklist_invalid_token_noop(self):
        """无效 token → 不写 Redis，不抛异常"""
        redis_mock = MagicMock()
        redis_mock.setex = AsyncMock()

        with patch("app.redis_client.get_redis", return_value=redis_mock):
            from app.services.auth_service import add_to_blacklist

            await add_to_blacklist("invalid.token", "access")
        # setex 不应被调用
        redis_mock.setex.assert_not_awaited()


class TestDepsBlacklistCheck:
    """get_current_user 在解码 token 后应检查黑名单 - 设计文档 A2 Step 3。"""

    @pytest.mark.asyncio
    async def test_blacklisted_token_rejected(self, fake_user, make_auth_db):
        """token 在黑名单中 → AuthError"""
        from fastapi.security import HTTPAuthorizationCredentials

        from app.api.deps import get_current_user

        token = create_access_token(str(fake_user.id))
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        # mock db 返回该用户
        db = make_auth_db(user=fake_user)

        # mock redis 命中黑名单
        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(return_value="1")

        with patch("app.api.deps.get_redis", return_value=redis_mock):
            with pytest.raises(AuthError):
                await get_current_user(credentials=creds, db=db)
