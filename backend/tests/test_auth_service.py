"""Tests for app.services.auth_service

覆盖场景:
- 密码哈希与校验（正确密码、错误密码、空密码）
- JWT token 签发（含 iss/aud claims）
- JWT token 刷新（refresh token 轮换）
- 用户注册（用户名重复、邮箱格式、注册事务回滚）
- token 黑名单/失效逻辑（Redis + 内存降级）
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.core.errors import ErrorCode
from app.core.exceptions import AuthError, ConflictError, ValidationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services import auth_service

# ========== 密码哈希与校验 ==========


class TestPasswordHashing:
    """hash_password + verify_password 的端到端验证。"""

    def test_hash_password_correct_password_verifies(self):
        """正确密码应通过校验。"""
        hashed = hash_password("SecretPwd123!")
        assert verify_password("SecretPwd123!", hashed) is True

    def test_hash_password_wrong_password_fails(self):
        """错误密码应校验失败。"""
        hashed = hash_password("SecretPwd123!")
        assert verify_password("WrongPwd456!", hashed) is False

    def test_hash_password_empty_password(self):
        """空字符串密码：hash 不报错，verify 空字符串返回 True。"""
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        # 空字符串与非空不匹配
        assert verify_password("nonempty", hashed) is False

    def test_hash_password_returns_bcrypt_hash(self):
        """hash_password 返回 bcrypt 格式哈希（$2 前缀）。"""
        hashed = hash_password("SecretPwd123!")
        assert hashed.startswith("$2")

    def test_hash_password_different_salts(self):
        """同一密码两次哈希应产生不同结果（不同 salt）。"""
        h1 = hash_password("SecretPwd123!")
        h2 = hash_password("SecretPwd123!")
        assert h1 != h2

    def test_verify_password_invalid_hash_returns_false(self):
        """无效哈希字符串应返回 False 而非抛异常。"""
        assert verify_password("any", "not-a-valid-hash") is False
        assert verify_password("any", "") is False


# ========== 密码强度校验 ==========


class TestValidatePasswordStrength:
    """validate_password_strength 的策略校验。"""

    def test_strong_password_passes(self):
        """满足所有策略的密码不抛异常。"""
        # 不抛异常即通过
        auth_service.validate_password_strength("StrongPwd123!")

    def test_short_password_raises(self):
        """短于 PASSWORD_MIN_LENGTH → ValidationError。"""
        with pytest.raises(ValidationError):
            auth_service.validate_password_strength("Aa1!")

    def test_missing_uppercase_raises(self):
        """缺少大写字母 → ValidationError。"""
        with pytest.raises(ValidationError):
            auth_service.validate_password_strength("strongpwd123!")

    def test_missing_lowercase_raises(self):
        """缺少小写字母 → ValidationError。"""
        with pytest.raises(ValidationError):
            auth_service.validate_password_strength("STRONGPWD123!")

    def test_missing_digit_raises(self):
        """缺少数字 → ValidationError。"""
        with pytest.raises(ValidationError):
            auth_service.validate_password_strength("StrongPwd!!!")

    def test_missing_special_raises(self):
        """缺少特殊字符 → ValidationError。"""
        with pytest.raises(ValidationError):
            auth_service.validate_password_strength("StrongPwd123")


# ========== JWT Token 签发（含 iss/aud claims） ==========


class TestCreateAccessToken:
    """create_access_token 签发的 token 应包含必要 claims。"""

    def test_access_token_contains_iss_and_aud(self):
        """access token 应包含正确的 iss/aud。"""
        token = create_access_token("42")
        payload = decode_token(token)
        assert payload is not None
        assert payload["iss"] == settings.JWT_ISSUER
        assert payload["aud"] == settings.JWT_AUDIENCE
        assert payload["type"] == "access"
        assert payload["sub"] == "42"

    def test_access_token_contains_iat(self):
        """access token 应包含 iat（签发时间）。"""
        token = create_access_token("1")
        payload = decode_token(token)
        assert payload is not None
        assert "iat" in payload

    def test_access_token_contains_exp(self):
        """access token 应包含 exp（过期时间）。"""
        token = create_access_token("1")
        payload = decode_token(token)
        assert payload is not None
        assert "exp" in payload

    def test_access_token_extra_claims_merged(self):
        """extra 参数应合并到 payload。"""
        token = create_access_token("99", extra={"role": "admin", "username": "alice"})
        payload = decode_token(token)
        assert payload is not None
        assert payload["role"] == "admin"
        assert payload["username"] == "alice"


class TestCreateRefreshToken:
    """create_refresh_token 签发的 token 应包含必要 claims。"""

    def test_refresh_token_contains_iss_and_aud(self):
        """refresh token 应包含正确的 iss/aud。"""
        token = create_refresh_token("7")
        payload = decode_token(token)
        assert payload is not None
        assert payload["iss"] == settings.JWT_ISSUER
        assert payload["aud"] == settings.JWT_AUDIENCE
        assert payload["type"] == "refresh"
        assert payload["sub"] == "7"

    def test_refresh_token_contains_iat(self):
        """refresh token 应包含 iat。"""
        token = create_refresh_token("1")
        payload = decode_token(token)
        assert payload is not None
        assert "iat" in payload


# ========== 用户注册 ==========


class TestRegister:
    """register 函数的用户名/邮箱唯一性、密码强度、事务回滚。"""

    @pytest.mark.asyncio
    async def test_register_success(self):
        """注册成功返回新用户。"""
        req = RegisterRequest(username="newuser", email="new@example.com", password="StrongPwd123!")
        db = AsyncMock()
        # execute 返回 None（无冲突）
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        async def fake_refresh(obj, *args, **kwargs):
            obj.id = 99

        db.refresh = AsyncMock(side_effect=fake_refresh)

        with (
            patch("app.services.auth_service.hash_password", return_value="hashed") as mock_hash,
            patch("app.services.auth_service.validate_password_strength"),
        ):
            user = await auth_service.register(req, db)

        assert user.id == 99
        assert user.username == "newuser"
        assert user.email == "new@example.com"
        assert user.role == "user"
        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once()
        mock_hash.assert_called_once_with("StrongPwd123!")

    @pytest.mark.asyncio
    async def test_register_username_duplicate_raises_conflict(self, make_user):
        """用户名已存在 → ConflictError（在 commit 前校验）。"""
        existing = make_user(user_id=1, username="existing", email="other@example.com")
        req = RegisterRequest(
            username="existing", email="new@example.com", password="StrongPwd123!"
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: existing))

        with pytest.raises(ConflictError):
            await auth_service.register(req, db)
        db.add.assert_not_called()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_register_email_duplicate_raises_conflict(self, make_user):
        """邮箱已存在 → ConflictError。"""
        existing = make_user(user_id=1, username="other", email="dup@example.com")
        req = RegisterRequest(username="newuser", email="dup@example.com", password="StrongPwd123!")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: existing))

        with pytest.raises(ConflictError):
            await auth_service.register(req, db)

    @pytest.mark.asyncio
    async def test_register_integrity_error_triggers_rollback(self):
        """commit 抛 IntegrityError → rollback + ConflictError（事务回滚）。"""
        req = RegisterRequest(username="newuser", email="new@example.com", password="StrongPwd123!")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        db.commit = AsyncMock(side_effect=IntegrityError("stmt", "params", "orig"))

        with (
            patch("app.services.auth_service.hash_password", return_value="hashed"),
            patch("app.services.auth_service.validate_password_strength"),
        ):
            with pytest.raises(ConflictError):
                await auth_service.register(req, db)
        db.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_weak_password_raises_validation_error(self):
        """密码强度不足 → ValidationError（在 hash 前校验）。"""
        # "aaaaaaaa" 通过 Pydantic min_length=8，但不符合强度策略（无大写/数字/特殊字符）
        req = RegisterRequest(username="newuser", email="new@example.com", password="aaaaaaaa")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        with pytest.raises(ValidationError):
            await auth_service.register(req, db)
        db.add.assert_not_called()


# ========== 登录 ==========


class TestLogin:
    """login 函数的凭据校验与 token 签发。"""

    @pytest.mark.asyncio
    async def test_login_success(self, make_user):
        """登录成功返回 token 对及用户信息。"""
        user = make_user(user_id=1, username="tester", role="user")
        req = LoginRequest(username="tester", password="StrongPwd123!")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

        with patch("app.services.auth_service.verify_password", return_value=True):
            result = await auth_service.login(req, db)

        assert "access_token" in result
        assert "refresh_token" in result
        assert result["token_type"] == "bearer"
        assert result["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        assert result["user"]["id"] == 1
        assert result["user"]["username"] == "tester"
        assert result["user"]["role"] == "user"

    @pytest.mark.asyncio
    async def test_login_user_not_found_raises(self):
        """用户不存在 → AuthError（INVALID_CREDENTIALS）。"""
        req = LoginRequest(username="nobody", password="StrongPwd123!")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        with pytest.raises(AuthError) as exc:
            await auth_service.login(req, db)
        assert exc.value.code == ErrorCode.INVALID_CREDENTIALS

    @pytest.mark.asyncio
    async def test_login_wrong_password_raises(self, make_user):
        """密码错误 → AuthError（INVALID_CREDENTIALS）。"""
        user = make_user(user_id=1, username="tester")
        req = LoginRequest(username="tester", password="WrongPwd123!")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

        with patch("app.services.auth_service.verify_password", return_value=False):
            with pytest.raises(AuthError) as exc:
                await auth_service.login(req, db)
        assert exc.value.code == ErrorCode.INVALID_CREDENTIALS

    @pytest.mark.asyncio
    async def test_login_inactive_user_raises(self, make_user):
        """用户被禁用 → AuthError。"""
        user = make_user(user_id=1, is_active=False)
        req = LoginRequest(username="tester", password="StrongPwd123!")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

        with patch("app.services.auth_service.verify_password", return_value=True):
            with pytest.raises(AuthError):
                await auth_service.login(req, db)


# ========== JWT Token 刷新（refresh token 轮换） ==========


class TestRefreshToken:
    """refresh_token 函数的轮换与校验逻辑。"""

    @pytest.mark.asyncio
    async def test_refresh_token_success_rotates(self, make_user):
        """成功刷新：返回新 token 对，旧 refresh 加入黑名单（轮换）。"""
        user = make_user(user_id=42, username="tester", role="user")
        old_refresh = create_refresh_token("42")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

        with patch("app.services.auth_service.add_to_blacklist", new=AsyncMock()) as mock_blacklist:
            result = await auth_service.refresh_token(old_refresh, db)

        assert "access_token" in result
        assert "refresh_token" in result
        # 新 refresh token 应与旧的不同（轮换）
        assert result["refresh_token"] != old_refresh
        assert result["user"]["id"] == 42
        # 旧 refresh token 应加入黑名单
        mock_blacklist.assert_awaited_once_with(old_refresh, "refresh")

    @pytest.mark.asyncio
    async def test_refresh_token_invalid_token_raises(self):
        """无效 refresh token（decode 失败）→ AuthError。"""
        db = AsyncMock()
        with pytest.raises(AuthError):
            await auth_service.refresh_token("invalid.token.here", db)

    @pytest.mark.asyncio
    async def test_refresh_token_wrong_type_raises(self):
        """access token 不能用作 refresh token → AuthError。"""
        access = create_access_token("42")
        db = AsyncMock()
        with pytest.raises(AuthError):
            await auth_service.refresh_token(access, db)

    @pytest.mark.asyncio
    async def test_refresh_token_blacklisted_raises(self, make_user):
        """已黑名单的 refresh token → AuthError（提示 revoked）。"""
        user = make_user(user_id=42)
        old_refresh = create_refresh_token("42")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

        with patch("app.services.auth_service.is_blacklisted", new=AsyncMock(return_value=True)):
            with pytest.raises(AuthError) as exc:
                await auth_service.refresh_token(old_refresh, db)
        assert "revoked" in str(exc.value.message).lower()

    @pytest.mark.asyncio
    async def test_refresh_token_malformed_subject_raises(self):
        """sub 不是数字 → AuthError（malformed subject）。"""
        from jwt import encode

        payload = {
            "sub": "not-a-number",
            "exp": datetime.now(UTC) + timedelta(days=1),
            "iat": datetime.now(UTC),
            "type": "refresh",
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        }
        token = encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        db = AsyncMock()

        with patch("app.services.auth_service.is_blacklisted", new=AsyncMock(return_value=False)):
            with pytest.raises(AuthError):
                await auth_service.refresh_token(token, db)

    @pytest.mark.asyncio
    async def test_refresh_token_user_not_found_raises(self):
        """用户不存在 → AuthError。"""
        old_refresh = create_refresh_token("999")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        with patch("app.services.auth_service.is_blacklisted", new=AsyncMock(return_value=False)):
            with pytest.raises(AuthError):
                await auth_service.refresh_token(old_refresh, db)

    @pytest.mark.asyncio
    async def test_refresh_token_inactive_user_raises(self, make_user):
        """用户被禁用 → AuthError。"""
        user = make_user(user_id=42, is_active=False)
        old_refresh = create_refresh_token("42")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

        with patch("app.services.auth_service.is_blacklisted", new=AsyncMock(return_value=False)):
            with pytest.raises(AuthError):
                await auth_service.refresh_token(old_refresh, db)


# ========== Token 黑名单/失效逻辑 ==========


class TestBlacklist:
    """add_to_blacklist + is_blacklisted 的 Redis 路径与内存降级。"""

    @pytest.fixture(autouse=True)
    def _clear_memory_blacklist(self):
        """每个测试前后清空内存黑名单，避免状态污染。"""
        auth_service._memory_blacklist.clear()
        yield
        auth_service._memory_blacklist.clear()

    @pytest.mark.asyncio
    async def test_add_to_blacklist_redis_path(self):
        """Redis 可用时，add_to_blacklist 调用 redis.setex。"""
        token = create_access_token("1")
        redis_mock = MagicMock()
        redis_mock.setex = AsyncMock()

        with patch("app.redis_client.get_redis", return_value=redis_mock):
            await auth_service.add_to_blacklist(token, "access")

        redis_mock.setex.assert_awaited_once()
        args = redis_mock.setex.await_args.args
        assert args[0].startswith("auth:blacklist:access:")
        assert args[1] > 0  # TTL 为正
        assert args[2] == "1"

    @pytest.mark.asyncio
    async def test_is_blacklisted_redis_hit(self):
        """Redis 可用时，is_blacklisted 返回 redis.exists 结果（命中）。"""
        token = create_access_token("1")
        redis_mock = MagicMock()
        redis_mock.exists = AsyncMock(return_value=1)

        with patch("app.redis_client.get_redis", return_value=redis_mock):
            result = await auth_service.is_blacklisted(token, "access")

        assert result is True
        redis_mock.exists.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_is_blacklisted_redis_miss(self):
        """Redis 可用但 key 不存在 → False。"""
        token = create_access_token("1")
        redis_mock = MagicMock()
        redis_mock.exists = AsyncMock(return_value=0)

        with patch("app.redis_client.get_redis", return_value=redis_mock):
            result = await auth_service.is_blacklisted(token, "access")

        assert result is False

    @pytest.mark.asyncio
    async def test_add_to_blacklist_redis_unavailable_falls_back_to_memory(self):
        """Redis 不可用时，降级到内存黑名单。"""
        token = create_access_token("1")

        with patch("app.redis_client.get_redis", return_value=None):
            await auth_service.add_to_blacklist(token, "access")

        # 内存黑名单应有该 token
        assert len(auth_service._memory_blacklist) == 1
        key = f"access:{token}"
        assert key in auth_service._memory_blacklist

    @pytest.mark.asyncio
    async def test_is_blacklisted_redis_unavailable_checks_memory(self):
        """Redis 不可用时，is_blacklisted 检查内存黑名单（命中）。"""
        token = create_access_token("1")

        with patch("app.redis_client.get_redis", return_value=None):
            await auth_service.add_to_blacklist(token, "access")
            result = await auth_service.is_blacklisted(token, "access")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_blacklisted_memory_miss(self):
        """内存黑名单未命中 → False。"""
        token = create_access_token("1")

        with patch("app.redis_client.get_redis", return_value=None):
            result = await auth_service.is_blacklisted(token, "access")
        assert result is False

    @pytest.mark.asyncio
    async def test_add_to_blacklist_invalid_token_skipped(self):
        """无效 token（decode 返回 None）→ 不写入。"""
        with patch("app.redis_client.get_redis", return_value=None):
            await auth_service.add_to_blacklist("invalid.token", "access")

        assert len(auth_service._memory_blacklist) == 0

    @pytest.mark.asyncio
    async def test_add_to_blacklist_expired_token_skipped(self):
        """已过期 token（ttl <= 0）→ 不写入。"""
        from jwt import encode

        payload = {
            "sub": "1",
            "exp": datetime.now(UTC) - timedelta(minutes=1),  # 已过期
            "iat": datetime.now(UTC) - timedelta(minutes=2),
            "type": "access",
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        }
        token = encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

        with patch("app.redis_client.get_redis", return_value=None):
            await auth_service.add_to_blacklist(token, "access")

        assert len(auth_service._memory_blacklist) == 0


class TestMemoryBlacklistHelpers:
    """内存黑名单内部辅助函数（_memory_blacklist_add / _memory_blacklist_contains）。"""

    @pytest.fixture(autouse=True)
    def _clear_memory_blacklist(self):
        auth_service._memory_blacklist.clear()
        yield
        auth_service._memory_blacklist.clear()

    def test_memory_blacklist_add_and_contains(self):
        """加入后能查到。"""
        auth_service._memory_blacklist_add("access", "tok1", datetime.now(UTC).timestamp() + 100)
        assert auth_service._memory_blacklist_contains("access", "tok1") is True

    def test_memory_blacklist_not_contains(self):
        """未加入的 token 查不到。"""
        assert auth_service._memory_blacklist_contains("access", "nope") is False

    def test_memory_blacklist_expired_cleaned(self):
        """过期条目在 contains 检查时被清理。"""
        auth_service._memory_blacklist_add(
            "access",
            "tok1",
            datetime.now(UTC).timestamp() - 10,  # 已过期
        )
        assert auth_service._memory_blacklist_contains("access", "tok1") is False
        # 过期条目应被清理
        assert "access:tok1" not in auth_service._memory_blacklist

    def test_memory_blacklist_eviction_when_full(self):
        """超过 _memory_blacklist_max 时丢弃最旧条目（插入顺序）。"""
        original_max = auth_service._memory_blacklist_max
        auth_service._memory_blacklist_max = 3
        try:
            now = datetime.now(UTC).timestamp() + 100
            auth_service._memory_blacklist_add("access", "t1", now)
            auth_service._memory_blacklist_add("access", "t2", now)
            auth_service._memory_blacklist_add("access", "t3", now)
            auth_service._memory_blacklist_add("access", "t4", now)  # 触发驱逐
            # 最旧的 t1 应被驱逐
            assert "access:t1" not in auth_service._memory_blacklist
            assert "access:t4" in auth_service._memory_blacklist
            assert len(auth_service._memory_blacklist) == 3
        finally:
            auth_service._memory_blacklist_max = original_max
