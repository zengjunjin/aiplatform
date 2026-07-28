"""Tests for app.services.user_service"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException, NotFoundError
from app.services import user_service


class TestListUsers:
    @pytest.mark.asyncio
    async def test_list_users_returns_paginated(self, make_user):
        """返回 (items, total)"""
        db = AsyncMock()
        # 第一次 execute 返回 count
        count_result = MagicMock()
        count_result.scalar_one.return_value = 5
        # 第二次 execute 返回 users
        users = [make_user(user_id=1), make_user(user_id=2)]
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = users

        db.execute = AsyncMock(side_effect=[count_result, users_result])

        items, total = await user_service.list_users(db, page=1, page_size=20)
        assert total == 5
        assert len(items) == 2
        assert items == users


class TestListUsersKeywordSearch:
    """Task 12: list_users keyword 搜索功能（P1-API-08）"""

    @pytest.mark.asyncio
    async def test_keyword_none_no_filter(self, make_user):
        """keyword=None 时不过滤，等价于原 list_users 行为。"""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 3
        users = [make_user(user_id=1), make_user(user_id=2)]
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = users

        db.execute = AsyncMock(side_effect=[count_result, users_result])

        items, total = await user_service.list_users(db, page=1, page_size=20, keyword=None)
        assert total == 3
        assert items == users
        # 两次 execute：count + list
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_keyword_applies_username_email_filter(self, make_user):
        """keyword 非空时，count 与 list 查询都应包含 WHERE 过滤条件。"""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        users = [make_user(user_id=2, username="alice")]
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = users

        db.execute = AsyncMock(side_effect=[count_result, users_result])

        items, total = await user_service.list_users(
            db, page=1, page_size=20, keyword="alice"
        )
        assert total == 1
        assert items == users

        # 验证 count 查询含 ilike 过滤
        count_stmt = db.execute.await_args_list[0].args[0]
        count_compiled = str(count_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "alice" in count_compiled
        assert "ESCAPE" in count_compiled or "escape" in count_compiled

        # 验证 list 查询含 ilike 过滤
        list_stmt = db.execute.await_args_list[1].args[0]
        list_compiled = str(list_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "alice" in list_compiled
        assert "ESCAPE" in list_compiled or "escape" in list_compiled

    @pytest.mark.asyncio
    async def test_keyword_search_both_username_and_email(self):
        """keyword 过滤条件应同时覆盖 username 和 email 字段（OR）。"""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[count_result, users_result])

        await user_service.list_users(db, page=1, page_size=20, keyword="test")

        # 编译 count 查询，验证 OR 条件含 username 和 email
        count_stmt = db.execute.await_args_list[0].args[0]
        compiled = str(count_stmt.compile(compile_kwargs={"literal_binds": True}))
        compiled_lower = compiled.lower()
        # 应包含 username 和 email 字段
        assert "username" in compiled_lower
        assert "email" in compiled_lower
        # 应包含 OR（ilike 用 OR 连接）
        assert " or " in compiled_lower or "or (" in compiled_lower

    @pytest.mark.asyncio
    async def test_keyword_percent_is_escaped(self):
        """keyword 含 % 时应被 _escape_like 转义，避免通配符注入。"""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[count_result, users_result])

        await user_service.list_users(db, page=1, page_size=20, keyword="%")

        count_stmt = db.execute.await_args_list[0].args[0]
        compiled = str(count_stmt.compile(compile_kwargs={"literal_binds": True}))
        # 应含转义后的 \%（字面量），ESCAPE 子句
        assert "ESCAPE" in compiled or "escape" in compiled
        assert "\\%" in compiled or "\\\\%" in compiled

    @pytest.mark.asyncio
    async def test_keyword_underscore_is_escaped(self):
        """keyword 含 _ 时应被 _escape_like 转义。"""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[count_result, users_result])

        await user_service.list_users(db, page=1, page_size=20, keyword="_")

        count_stmt = db.execute.await_args_list[0].args[0]
        compiled = str(count_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "ESCAPE" in compiled or "escape" in compiled
        assert "\\_" in compiled

    @pytest.mark.asyncio
    async def test_keyword_calls_escape_like(self):
        """list_users 应调用 _escape_like 对 keyword 进行转义。"""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[count_result, users_result])

        with patch(
            "app.services.user_service._escape_like",
            wraps=user_service._escape_like,
        ) as spy_escape:
            await user_service.list_users(db, page=1, page_size=20, keyword="a%b_c")

        spy_escape.assert_called_once_with("a%b_c")

    @pytest.mark.asyncio
    async def test_keyword_empty_string_no_filter(self, make_user):
        """keyword='' 空字符串时 falsy，不过滤（与 keyword=None 一致）。"""
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        users = [make_user(user_id=1), make_user(user_id=2)]
        users_result = MagicMock()
        users_result.scalars.return_value.all.return_value = users

        db.execute = AsyncMock(side_effect=[count_result, users_result])

        items, total = await user_service.list_users(db, page=1, page_size=20, keyword="")
        assert total == 2
        assert items == users
        # 空字符串 falsy，不应调用 _escape_like
        # 验证 count 查询不含 WHERE ilike
        count_stmt = db.execute.await_args_list[0].args[0]
        compiled = str(count_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "ilike" not in compiled.lower()


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
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        with pytest.raises(NotFoundError):
            await user_service.update_role(99, "admin", db, admin_id=1)

    @pytest.mark.asyncio
    async def test_update_role_success(self, make_user):
        """成功修改角色"""
        target = make_user(user_id=2, role="user")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: target))
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
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        with pytest.raises(NotFoundError):
            await user_service.update_status(99, False, db, admin_id=1)

    @pytest.mark.asyncio
    async def test_update_status_success(self, make_user):
        """成功禁用用户"""
        target = make_user(user_id=2, is_active=True)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: target))
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
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        with pytest.raises(NotFoundError):
            await user_service.change_password(99, "old", "NewPwd123!", db)

    @pytest.mark.asyncio
    async def test_change_password_wrong_old_raises(self, make_user):
        """旧密码错误 → AppException"""
        user = make_user(user_id=1, password_hash="hash")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))
        with patch("app.services.user_service.verify_password", return_value=False):
            with pytest.raises(AppException):
                await user_service.change_password(1, "wrongold", "NewPwd123!", db)

    @pytest.mark.asyncio
    async def test_change_password_success(self, make_user):
        """成功修改密码"""
        user = make_user(user_id=1, password_hash="old_hash")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))
        with (
            patch("app.services.user_service.verify_password", return_value=True),
            patch("app.services.user_service.hash_password", return_value="new_hash") as mock_hash,
            patch("app.services.auth_service.validate_password_strength") as mock_validate,
        ):
            await user_service.change_password(1, "OldPwd123!", "NewPwd123!", db)
        # 验证 hash + commit 被调用
        mock_validate.assert_called_once_with("NewPwd123!")
        mock_hash.assert_called_once_with("NewPwd123!")
        assert user.password_hash == "new_hash"
        db.commit.assert_awaited_once()


class TestCacheInvalidation:
    """用户信息缓存失效 - Task 32 SubTask 32.2。"""

    @pytest.mark.asyncio
    async def test_update_role_invalidates_cache(self, make_user):
        """update_role 成功后应删除 user:{id} 缓存"""
        target = make_user(user_id=2, role="user")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: target))
        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock()
        with patch("app.services.user_service.get_redis", return_value=redis_mock):
            await user_service.update_role(2, "admin", db, admin_id=1)
        redis_mock.delete.assert_awaited_once_with("user:2")

    @pytest.mark.asyncio
    async def test_update_status_invalidates_cache(self, make_user):
        """update_status 成功后应删除 user:{id} 缓存"""
        target = make_user(user_id=2, is_active=True)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: target))
        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock()
        with patch("app.services.user_service.get_redis", return_value=redis_mock):
            await user_service.update_status(2, False, db, admin_id=1)
        redis_mock.delete.assert_awaited_once_with("user:2")

    @pytest.mark.asyncio
    async def test_change_password_invalidates_cache(self, make_user):
        """change_password 成功后应删除 user:{id} 缓存"""
        user = make_user(user_id=1, password_hash="old_hash")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))
        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock()
        with (
            patch("app.services.user_service.verify_password", return_value=True),
            patch("app.services.user_service.hash_password", return_value="new_hash"),
            patch("app.services.auth_service.validate_password_strength"),
            patch("app.services.user_service.get_redis", return_value=redis_mock),
        ):
            await user_service.change_password(1, "OldPwd123!", "NewPwd123!", db)
        redis_mock.delete.assert_awaited_once_with("user:1")

    @pytest.mark.asyncio
    async def test_update_role_cache_failure_does_not_raise(self, make_user):
        """缓存删除失败不应影响主流程"""
        target = make_user(user_id=2, role="user")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: target))
        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock(side_effect=Exception("Redis down"))
        with patch("app.services.user_service.get_redis", return_value=redis_mock):
            # 不应抛异常
            result = await user_service.update_role(2, "admin", db, admin_id=1)
        assert result is target
        assert target.role == "admin"

    @pytest.mark.asyncio
    async def test_update_status_cache_failure_does_not_raise(self, make_user):
        """缓存删除失败不应影响主流程"""
        target = make_user(user_id=2, is_active=True)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: target))
        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock(side_effect=Exception("Redis down"))
        with patch("app.services.user_service.get_redis", return_value=redis_mock):
            result = await user_service.update_status(2, False, db, admin_id=1)
        assert result is target
        assert target.is_active is False

    @pytest.mark.asyncio
    async def test_change_password_cache_failure_does_not_raise(self, make_user):
        """缓存删除失败不应影响主流程"""
        user = make_user(user_id=1, password_hash="old_hash")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))
        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock(side_effect=Exception("Redis down"))
        with (
            patch("app.services.user_service.verify_password", return_value=True),
            patch("app.services.user_service.hash_password", return_value="new_hash"),
            patch("app.services.auth_service.validate_password_strength"),
            patch("app.services.user_service.get_redis", return_value=redis_mock),
        ):
            # 不应抛异常
            await user_service.change_password(1, "OldPwd123!", "NewPwd123!", db)
        assert user.password_hash == "new_hash"

    @pytest.mark.asyncio
    async def test_update_role_redis_unavailable_no_error(self, make_user):
        """Redis 不可用时不报错（get_redis 返回 None）"""
        target = make_user(user_id=2, role="user")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: target))
        with patch("app.services.user_service.get_redis", return_value=None):
            result = await user_service.update_role(2, "admin", db, admin_id=1)
        assert result is target
        assert target.role == "admin"

    @pytest.mark.asyncio
    async def test_update_status_redis_unavailable_no_error(self, make_user):
        """Redis 不可用时不报错（get_redis 返回 None）"""
        target = make_user(user_id=2, is_active=True)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: target))
        with patch("app.services.user_service.get_redis", return_value=None):
            result = await user_service.update_status(2, False, db, admin_id=1)
        assert result is target
        assert target.is_active is False

    @pytest.mark.asyncio
    async def test_change_password_redis_unavailable_no_error(self, make_user):
        """Redis 不可用时不报错（get_redis 返回 None）"""
        user = make_user(user_id=1, password_hash="old_hash")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))
        with (
            patch("app.services.user_service.verify_password", return_value=True),
            patch("app.services.user_service.hash_password", return_value="new_hash"),
            patch("app.services.auth_service.validate_password_strength"),
            patch("app.services.user_service.get_redis", return_value=None),
        ):
            await user_service.change_password(1, "OldPwd123!", "NewPwd123!", db)
        assert user.password_hash == "new_hash"

    @pytest.mark.asyncio
    async def test_update_role_not_found_does_not_invalidate_cache(self):
        """用户不存在时不应调用缓存删除（提前 raise）"""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
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
        compiled = str(select_stmt.compile(compile_kwargs={"literal_binds": True}))
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
        compiled = str(select_stmt.compile(compile_kwargs={"literal_binds": True}))
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
        compiled = str(select_stmt.compile(compile_kwargs={"literal_binds": True}))
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
        compiled = str(select_stmt.compile(compile_kwargs={"literal_binds": True}))
        # 反斜杠应被转义为 \\\\
        assert "ESCAPE" in compiled or "escape" in compiled
