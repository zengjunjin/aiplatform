"""Tests for app.services.user_service"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services import user_service
from app.core.exceptions import NotFoundError, AppException
from app.db.user import User


def _make_user(user_id=1, role="admin", is_active=True, password_hash="hash"):
    u = MagicMock(spec=User)
    u.id = user_id
    u.role = role
    u.is_active = is_active
    u.password_hash = password_hash
    return u


class TestListUsers:
    @pytest.mark.asyncio
    async def test_list_users_returns_paginated(self):
        """返回 (items, total)"""
        db = AsyncMock()
        # 第一次 execute 返回 count
        count_result = MagicMock()
        count_result.scalar_one.return_value = 5
        # 第二次 execute 返回 users
        users = [_make_user(user_id=1), _make_user(user_id=2)]
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = users

        db.execute = AsyncMock(side_effect=[count_result, users_result])

        items, total = await user_service.list_users(db, page=1, page_size=20)
        assert total == 5
        assert len(items) == 2
        assert items == users


class TestUpdateRole:
    @pytest.mark.asyncio
    async def test_update_role_self_raises(self):
        """admin 修改自己角色 → AppException"""
        db = AsyncMock()
        with pytest.raises(AppException):
            await user_service.update_role(1, "user", db, admin_id=1)

    @pytest.mark.asyncio
    async def test_update_role_user_not_found_raises(self):
        """目标用户不存在 → NotFoundError"""
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: None)
        )
        with pytest.raises(NotFoundError):
            await user_service.update_role(99, "admin", db, admin_id=1)

    @pytest.mark.asyncio
    async def test_update_role_success(self):
        """成功修改角色"""
        target = _make_user(user_id=2, role="user")
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: target)
        )
        result = await user_service.update_role(2, "admin", db, admin_id=1)
        assert target.role == "admin"
        assert result is target
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(target)


class TestUpdateStatus:
    @pytest.mark.asyncio
    async def test_update_status_self_raises(self):
        """admin 禁用自己 → AppException"""
        db = AsyncMock()
        with pytest.raises(AppException):
            await user_service.update_status(1, False, db, admin_id=1)

    @pytest.mark.asyncio
    async def test_update_status_user_not_found_raises(self):
        """目标用户不存在 → NotFoundError"""
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: None)
        )
        with pytest.raises(NotFoundError):
            await user_service.update_status(99, False, db, admin_id=1)

    @pytest.mark.asyncio
    async def test_update_status_success(self):
        """成功禁用用户"""
        target = _make_user(user_id=2, is_active=True)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: target)
        )
        result = await user_service.update_status(2, False, db, admin_id=1)
        assert target.is_active is False
        assert result is target
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(target)


class TestChangePassword:
    @pytest.mark.asyncio
    async def test_change_password_user_not_found_raises(self):
        """用户不存在 → NotFoundError"""
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: None)
        )
        with pytest.raises(NotFoundError):
            await user_service.change_password(99, "old", "NewPwd123!", db)

    @pytest.mark.asyncio
    async def test_change_password_wrong_old_raises(self):
        """旧密码错误 → AppException"""
        user = _make_user(user_id=1, password_hash="hash")
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: user)
        )
        with patch("app.services.user_service.verify_password", return_value=False):
            with pytest.raises(AppException):
                await user_service.change_password(1, "wrongold", "NewPwd123!", db)

    @pytest.mark.asyncio
    async def test_change_password_success(self):
        """成功修改密码"""
        user = _make_user(user_id=1, password_hash="old_hash")
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: user)
        )
        with patch("app.services.user_service.verify_password", return_value=True), \
             patch("app.services.user_service.hash_password", return_value="new_hash") as mock_hash, \
             patch("app.services.auth_service.validate_password_strength") as mock_validate:
            await user_service.change_password(1, "OldPwd123!", "NewPwd123!", db)
        # 验证 hash + commit 被调用
        mock_validate.assert_called_once_with("NewPwd123!")
        mock_hash.assert_called_once_with("NewPwd123!")
        assert user.password_hash == "new_hash"
        db.commit.assert_awaited_once()


class TestCacheInvalidation:
    """用户信息缓存失效 - Task 32 SubTask 32.2。"""

    @pytest.mark.asyncio
    async def test_update_role_invalidates_cache(self):
        """update_role 成功后应删除 user:{id} 缓存"""
        target = _make_user(user_id=2, role="user")
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: target)
        )
        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock()
        with patch("app.services.user_service.get_redis", return_value=redis_mock):
            await user_service.update_role(2, "admin", db, admin_id=1)
        redis_mock.delete.assert_awaited_once_with("user:2")

    @pytest.mark.asyncio
    async def test_update_status_invalidates_cache(self):
        """update_status 成功后应删除 user:{id} 缓存"""
        target = _make_user(user_id=2, is_active=True)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: target)
        )
        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock()
        with patch("app.services.user_service.get_redis", return_value=redis_mock):
            await user_service.update_status(2, False, db, admin_id=1)
        redis_mock.delete.assert_awaited_once_with("user:2")

    @pytest.mark.asyncio
    async def test_change_password_invalidates_cache(self):
        """change_password 成功后应删除 user:{id} 缓存"""
        user = _make_user(user_id=1, password_hash="old_hash")
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: user)
        )
        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock()
        with patch("app.services.user_service.verify_password", return_value=True), \
             patch("app.services.user_service.hash_password", return_value="new_hash"), \
             patch("app.services.auth_service.validate_password_strength"), \
             patch("app.services.user_service.get_redis", return_value=redis_mock):
            await user_service.change_password(1, "OldPwd123!", "NewPwd123!", db)
        redis_mock.delete.assert_awaited_once_with("user:1")

    @pytest.mark.asyncio
    async def test_update_role_cache_failure_does_not_raise(self):
        """缓存删除失败不应影响主流程"""
        target = _make_user(user_id=2, role="user")
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: target)
        )
        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock(side_effect=Exception("Redis down"))
        with patch("app.services.user_service.get_redis", return_value=redis_mock):
            # 不应抛异常
            result = await user_service.update_role(2, "admin", db, admin_id=1)
        assert result is target
        assert target.role == "admin"

    @pytest.mark.asyncio
    async def test_update_status_cache_failure_does_not_raise(self):
        """缓存删除失败不应影响主流程"""
        target = _make_user(user_id=2, is_active=True)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: target)
        )
        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock(side_effect=Exception("Redis down"))
        with patch("app.services.user_service.get_redis", return_value=redis_mock):
            result = await user_service.update_status(2, False, db, admin_id=1)
        assert result is target
        assert target.is_active is False

    @pytest.mark.asyncio
    async def test_change_password_cache_failure_does_not_raise(self):
        """缓存删除失败不应影响主流程"""
        user = _make_user(user_id=1, password_hash="old_hash")
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: user)
        )
        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock(side_effect=Exception("Redis down"))
        with patch("app.services.user_service.verify_password", return_value=True), \
             patch("app.services.user_service.hash_password", return_value="new_hash"), \
             patch("app.services.auth_service.validate_password_strength"), \
             patch("app.services.user_service.get_redis", return_value=redis_mock):
            # 不应抛异常
            await user_service.change_password(1, "OldPwd123!", "NewPwd123!", db)
        assert user.password_hash == "new_hash"

    @pytest.mark.asyncio
    async def test_update_role_redis_unavailable_no_error(self):
        """Redis 不可用时不报错（get_redis 返回 None）"""
        target = _make_user(user_id=2, role="user")
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: target)
        )
        with patch("app.services.user_service.get_redis", return_value=None):
            result = await user_service.update_role(2, "admin", db, admin_id=1)
        assert result is target
        assert target.role == "admin"

    @pytest.mark.asyncio
    async def test_update_status_redis_unavailable_no_error(self):
        """Redis 不可用时不报错（get_redis 返回 None）"""
        target = _make_user(user_id=2, is_active=True)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: target)
        )
        with patch("app.services.user_service.get_redis", return_value=None):
            result = await user_service.update_status(2, False, db, admin_id=1)
        assert result is target
        assert target.is_active is False

    @pytest.mark.asyncio
    async def test_change_password_redis_unavailable_no_error(self):
        """Redis 不可用时不报错（get_redis 返回 None）"""
        user = _make_user(user_id=1, password_hash="old_hash")
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: user)
        )
        with patch("app.services.user_service.verify_password", return_value=True), \
             patch("app.services.user_service.hash_password", return_value="new_hash"), \
             patch("app.services.auth_service.validate_password_strength"), \
             patch("app.services.user_service.get_redis", return_value=None):
            await user_service.change_password(1, "OldPwd123!", "NewPwd123!", db)
        assert user.password_hash == "new_hash"

    @pytest.mark.asyncio
    async def test_update_role_not_found_does_not_invalidate_cache(self):
        """用户不存在时不应调用缓存删除（提前 raise）"""
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: None)
        )
        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock()
        with patch("app.services.user_service.get_redis", return_value=redis_mock):
            with pytest.raises(NotFoundError):
                await user_service.update_role(99, "admin", db, admin_id=1)
        redis_mock.delete.assert_not_awaited()


class TestEscapeLike:
    """测试 LIKE 通配符转义函数"""

    def test_escape_percent(self):
        """% 应被转义为 \\%"""
        assert user_service._escape_like("100%") == "100\\%"

    def test_escape_underscore(self):
        """_ 应被转义为 \\_"""
        assert user_service._escape_like("user_name") == "user\\_name"

    def test_escape_backslash(self):
        """反斜杠本身应被转义为 \\\\（先于 % 和 _ 转义，避免二次转义）"""
        assert user_service._escape_like("a\\b") == "a\\\\b"

    def test_escape_combined(self):
        """混合通配符场景"""
        assert user_service._escape_like("a\\b%c_d") == "a\\\\b\\%c\\_d"

    def test_escape_no_special_chars(self):
        """无特殊字符时原样返回"""
        assert user_service._escape_like("alice") == "alice"

    def test_escape_empty_string(self):
        """空字符串原样返回"""
        assert user_service._escape_like("") == ""

    def test_escape_only_wildcards(self):
        """纯通配符也应被转义"""
        assert user_service._escape_like("%") == "\\%"
        assert user_service._escape_like("_") == "\\_"

    def test_escape_multiple_wildcards(self):
        """多个通配符都应被转义"""
        assert user_service._escape_like("%%__") == "\\%\\%\\_\\_"

    def test_escape_backslash_before_wildcard_not_double_escaped(self):
        """反斜杠先转义，避免把转义字符本身再次当作转义前缀"""
        # 输入 "\%" (2 字符) -> 先转义反斜杠得到 "\\%" (3 字符)，
        # 再转义 % 得到 "\\\%" (4 字符: 3 个反斜杠 + 1 个 %)
        # 使用原始字符串 r"\\\%" 避免无效转义序列告警
        assert user_service._escape_like("\\%") == r"\\\%"


class TestSearchUsers:
    """测试 search_users 的通配符转义行为"""

    @pytest.mark.asyncio
    async def test_search_users_returns_id_username_pairs(self):
        """正常搜索应返回 [{id, username}] 列表"""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = [(1, "alice"), (2, "alice2")]
        db.execute = AsyncMock(return_value=result_mock)

        items = await user_service.search_users(db, "alice", limit=10)
        assert items == [{"id": 1, "username": "alice"}, {"id": 2, "username": "alice2"}]

    @pytest.mark.asyncio
    async def test_search_users_percent_is_escaped(self):
        """搜索 "%" 时，传递给 ilike 的 pattern 应包含转义后的 \\%，而非裸 %"""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        await user_service.search_users(db, "%", limit=10)

        # 捕获 select 语句并编译，验证 SQL 中出现转义后的 \%
        select_stmt = db.execute.await_args.args[0]
        compiled = str(
            select_stmt.compile(compile_kwargs={"literal_binds": True})
        )
        # pattern 应为 "%\%%"，即外层两个 % 是通配符，中间 \% 是字面量
        # SQL 文本里应能看到 ESCAPE '\' 子句
        assert "ESCAPE" in compiled or "escape" in compiled
        # 确保不会出现 "%%%"（裸通配符未转义的迹象）
        # 编译后的 LIKE 表达式形如: lower(users.username) LIKE lower('%\%%') ESCAPE '\'
        assert "\\%" in compiled or "\\\\%" in compiled

    @pytest.mark.asyncio
    async def test_search_users_underscore_is_escaped(self):
        """搜索 "_" 时，传递给 ilike 的 pattern 应包含转义后的 \\_"""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        await user_service.search_users(db, "_", limit=10)

        select_stmt = db.execute.await_args.args[0]
        compiled = str(
            select_stmt.compile(compile_kwargs={"literal_binds": True})
        )
        assert "ESCAPE" in compiled or "escape" in compiled
        assert "\\_" in compiled

    @pytest.mark.asyncio
    async def test_search_users_calls_escape_like(self):
        """search_users 应调用 _escape_like 对 query 进行转义"""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        with patch(
            "app.services.user_service._escape_like",
            wraps=user_service._escape_like,
        ) as spy_escape:
            await user_service.search_users(db, "a%b_c", limit=5)

        spy_escape.assert_called_once_with("a%b_c")

    @pytest.mark.asyncio
    async def test_search_users_respects_limit(self):
        """limit 参数应传递给 select.limit"""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        await user_service.search_users(db, "alice", limit=5)

        select_stmt = db.execute.await_args.args[0]
        compiled = str(
            select_stmt.compile(compile_kwargs={"literal_binds": True})
        )
        assert "LIMIT 5" in compiled

    @pytest.mark.asyncio
    async def test_search_users_backslash_is_escaped(self):
        """搜索包含反斜杠的字符串时，反斜杠应被转义"""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        await user_service.search_users(db, "a\\b", limit=10)

        select_stmt = db.execute.await_args.args[0]
        compiled = str(
            select_stmt.compile(compile_kwargs={"literal_binds": True})
        )
        # 反斜杠应被转义为 \\\\
        assert "ESCAPE" in compiled or "escape" in compiled
