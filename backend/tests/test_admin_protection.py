"""Tests for admin self-protection logic in user_service.

Verifies that an admin cannot disable themselves or change their own role,
which would otherwise lead to lockout.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AppException
from app.services import user_service


@pytest.fixture
def fake_db():
    """Mock AsyncSession - 实际查询走 scalar_one_or_none() 返回 None，
    我们只需要验证在查询前的 admin_id 检查就会抛出异常。"""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    return db


class TestAdminSelfProtection:
    """admin 不能修改自己的角色 / 禁用自己，避免锁死系统。"""

    @pytest.mark.asyncio
    async def test_admin_cannot_modify_own_role(self, fake_db):
        """admin 修改自己角色 → 抛 AppException(400)"""
        admin_id = 1
        with pytest.raises(AppException) as exc_info:
            await user_service.update_role(
                user_id=admin_id, role="user", db=fake_db, admin_id=admin_id
            )
        assert exc_info.value.status_code == 400
        assert "own role" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_admin_cannot_disable_own_account(self, fake_db):
        """admin 禁用自己 → 抛 AppException(400)"""
        admin_id = 1
        with pytest.raises(AppException) as exc_info:
            await user_service.update_status(
                user_id=admin_id, is_active=False, db=fake_db, admin_id=admin_id
            )
        assert exc_info.value.status_code == 400
        assert "own account" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_admin_cannot_disable_self_even_when_active_true(self, fake_db):
        """即使 is_active=True（看似无害），admin 也不应操作自己账户状态"""
        admin_id = 1
        with pytest.raises(AppException):
            await user_service.update_status(
                user_id=admin_id, is_active=True, db=fake_db, admin_id=admin_id
            )

    @pytest.mark.asyncio
    async def test_admin_can_modify_other_user_role(self, fake_db):
        """admin 修改其他用户角色 → 不抛异常（db.execute 被调用）"""
        # 构造一个返回 user 的 mock
        fake_user = MagicMock()
        fake_user.role = "user"
        fake_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: fake_user))
        # 不应抛异常
        result = await user_service.update_role(user_id=2, role="admin", db=fake_db, admin_id=1)
        assert result is fake_user
        assert fake_user.role == "admin"
        fake_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_admin_can_disable_other_user(self, fake_db):
        """admin 禁用其他用户 → 不抛异常"""
        fake_user = MagicMock()
        fake_user.is_active = True
        fake_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: fake_user))
        result = await user_service.update_status(
            user_id=2, is_active=False, db=fake_db, admin_id=1
        )
        assert result is fake_user
        assert fake_user.is_active is False
        fake_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_role_nonexistent_user_raises_not_found(self, fake_db):
        """admin 修改不存在的用户 → NotFoundError（admin_id != user_id，越过自我保护检查）"""
        from app.core.exceptions import NotFoundError

        # db.execute 默认返回 None
        with pytest.raises(NotFoundError):
            await user_service.update_role(user_id=999, role="admin", db=fake_db, admin_id=1)

    @pytest.mark.asyncio
    async def test_update_status_nonexistent_user_raises_not_found(self, fake_db):
        """admin 禁用不存在的用户 → NotFoundError"""
        from app.core.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            await user_service.update_status(user_id=999, is_active=False, db=fake_db, admin_id=1)
