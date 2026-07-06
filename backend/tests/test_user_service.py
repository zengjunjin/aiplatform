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
