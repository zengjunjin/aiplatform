"""Tests for app.api.deps"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.api import deps
from app.core.exceptions import AuthError, ForbiddenError
from app.core.security import create_access_token, create_refresh_token
from app.db.user import User


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
    async def test_disabled_user_raises(self, make_user):
        """用户被禁用 → AuthError"""
        user = make_user(is_active=False)
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))
        with patch("app.api.deps.get_redis", return_value=None):
            with pytest.raises(AuthError):
                await deps.get_current_user(credentials=creds, db=db)

    @pytest.mark.asyncio
    async def test_valid_user_returns_user(self, make_user):
        """完整有效 token → 返回 user"""
        user = make_user()
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))
        with patch("app.api.deps.get_redis", return_value=None):
            result = await deps.get_current_user(credentials=creds, db=db)
        assert result is user


class TestUserCache:
    """用户信息 Redis 缓存 - Task 32。"""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_user_without_db_query(self):
        """缓存命中 → 不查 DB，直接返回缓存用户"""
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock()  # 不应被调用

        cached_data = {
            "id": 1,
            "username": "tester",
            "email": "t@example.com",
            "role": "user",
            "is_active": True,
        }
        redis_mock = MagicMock()
        # 第 1 次 get：黑名单检查（None）；第 2 次 get：缓存命中
        redis_mock.get = AsyncMock(side_effect=[None, json.dumps(cached_data)])
        redis_mock.setex = AsyncMock()

        with patch("app.api.deps.get_redis", return_value=redis_mock):
            result = await deps.get_current_user(credentials=creds, db=db)

        assert result.id == 1
        assert result.username == "tester"
        assert result.email == "t@example.com"
        assert result.role == "user"
        assert result.is_active is True
        db.execute.assert_not_awaited()
        redis_mock.setex.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cache_miss_queries_db_and_writes_cache(self, make_user):
        """缓存未命中 → 查 DB 并写入缓存"""
        user = make_user()
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(side_effect=[None, None])  # 黑名单 None，缓存 None
        redis_mock.setex = AsyncMock()

        with patch("app.api.deps.get_redis", return_value=redis_mock):
            result = await deps.get_current_user(credentials=creds, db=db)

        assert result is user
        db.execute.assert_awaited_once()
        redis_mock.setex.assert_awaited_once()
        args = redis_mock.setex.await_args.args
        assert args[0] == "user:1"
        assert args[1] == deps.USER_CACHE_TTL
        cached = json.loads(args[2])
        # 缓存中不应包含敏感字段
        assert "password_hash" not in cached
        assert cached["id"] == 1
        assert cached["username"] == "tester"
        assert cached["role"] == "user"
        assert cached["is_active"] is True

    @pytest.mark.asyncio
    async def test_cache_corrupted_falls_back_to_db(self, make_user):
        """缓存 JSON 损坏 → 回退到 DB 查询"""
        user = make_user()
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(side_effect=[None, "{invalid json"])
        redis_mock.setex = AsyncMock()

        with patch("app.api.deps.get_redis", return_value=redis_mock):
            result = await deps.get_current_user(credentials=creds, db=db)

        assert result is user
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cache_missing_fields_falls_back_to_db(self, make_user):
        """缓存 dict 缺少必要字段 → 回退到 DB"""
        user = make_user()
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

        redis_mock = MagicMock()
        # 缺少 email 字段
        redis_mock.get = AsyncMock(side_effect=[None, json.dumps({"id": 1, "username": "x"})])
        redis_mock.setex = AsyncMock()

        with patch("app.api.deps.get_redis", return_value=redis_mock):
            result = await deps.get_current_user(credentials=creds, db=db)

        assert result is user
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_redis_read_failure_falls_back_to_db(self, make_user):
        """Redis 读异常 → 回退到 DB"""
        user = make_user()
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

        redis_mock = MagicMock()
        # 黑名单 OK，缓存读异常
        redis_mock.get = AsyncMock(side_effect=[None, Exception("Redis down")])
        redis_mock.setex = AsyncMock()

        with patch("app.api.deps.get_redis", return_value=redis_mock):
            result = await deps.get_current_user(credentials=creds, db=db)

        assert result is user
        db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_redis_write_failure_returns_user(self, make_user):
        """Redis 写异常 → 仍返回用户"""
        user = make_user()
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(side_effect=[None, None])
        redis_mock.setex = AsyncMock(side_effect=Exception("Redis write failed"))

        with patch("app.api.deps.get_redis", return_value=redis_mock):
            result = await deps.get_current_user(credentials=creds, db=db)

        assert result is user

    @pytest.mark.asyncio
    async def test_disabled_user_not_cached(self, make_user):
        """禁用用户 → 不写入缓存（且抛 AuthError）"""
        user = make_user(is_active=False)
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(side_effect=[None, None])
        redis_mock.setex = AsyncMock()

        with patch("app.api.deps.get_redis", return_value=redis_mock):
            with pytest.raises(AuthError):
                await deps.get_current_user(credentials=creds, db=db)

        redis_mock.setex.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_redis_unavailable_falls_back_to_db(self, make_user):
        """Redis 不可用 → 直接查 DB"""
        user = make_user()
        token = create_access_token("1")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

        with patch("app.api.deps.get_redis", return_value=None):
            result = await deps.get_current_user(credentials=creds, db=db)

        assert result is user
        db.execute.assert_awaited_once()


class TestUserCacheSerialization:
    """缓存序列化/反序列化辅助函数。"""

    def test_serialize_user_excludes_password_hash(self, make_user):
        """_serialize_user 不包含 password_hash"""
        user = make_user()
        user.password_hash = "secret_hash"
        data = deps._serialize_user(user)
        assert "password_hash" not in data
        assert set(data.keys()) == {"id", "username", "email", "role", "is_active"}

    def test_serialize_user_includes_required_fields(self, make_user):
        """_serialize_user 包含鉴权所需字段"""
        user = make_user(user_id=42, role="admin")
        user.email = "admin@example.com"
        data = deps._serialize_user(user)
        assert data == {
            "id": 42,
            "username": "tester",
            "email": "admin@example.com",
            "role": "admin",
            "is_active": True,
        }

    def test_deserialize_user_constructs_user(self):
        """_deserialize_user 正确构造 User 实例"""
        data = {
            "id": 7,
            "username": "alice",
            "email": "alice@example.com",
            "role": "user",
            "is_active": True,
        }
        user = deps._deserialize_user(data)
        assert isinstance(user, User)
        assert user.id == 7
        assert user.username == "alice"
        assert user.email == "alice@example.com"
        assert user.role == "user"
        assert user.is_active is True

    def test_user_cache_key_format(self):
        """_user_cache_key 返回 user:{id} 格式"""
        assert deps._user_cache_key(1) == "user:1"
        assert deps._user_cache_key(42) == "user:42"


class TestGetAdminUser:
    @pytest.mark.asyncio
    async def test_admin_role_returns_user(self, make_user):
        user = make_user(role="admin")
        result = await deps.get_admin_user(user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_non_admin_role_raises_forbidden(self, make_user):
        user = make_user(role="user")
        with pytest.raises(ForbiddenError):
            await deps.get_admin_user(user=user)
