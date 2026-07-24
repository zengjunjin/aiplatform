"""Tests for KB collaborator permission enforcement (IDOR fix).

验证 read/write/admin 三级权限分层, 确保 read 权限协作者无法越权
删除知识库/修改文档/管理协作者。

对应 spec: harden-and-optimize-platform-2026-07 Task 1。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import ForbiddenError, NotFoundError
from app.services import kb_service


def _make_kb(kb_id=1, owner_id=10, collaborators=None):
    """构造一个 KB mock, collaborators 形如 [{"user_id": int, "permission": str}]。"""
    kb = MagicMock()
    kb.id = kb_id
    kb.owner_id = owner_id
    kb.collaborators = collaborators or []
    return kb


def _make_db(kb):
    """构造 mock AsyncSession, execute 返回包含 kb 的 result。"""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = kb
    db.execute.return_value = result
    return db


class TestHasPermission:
    def test_read_satisfies_read(self):
        assert kb_service._has_permission("read", "read") is True

    def test_write_satisfies_read(self):
        assert kb_service._has_permission("write", "read") is True

    def test_admin_satisfies_read(self):
        assert kb_service._has_permission("admin", "read") is True

    def test_read_not_satisfies_write(self):
        assert kb_service._has_permission("read", "write") is False

    def test_write_satisfies_write(self):
        assert kb_service._has_permission("write", "write") is True

    def test_admin_satisfies_write(self):
        assert kb_service._has_permission("admin", "write") is True

    def test_read_not_satisfies_admin(self):
        assert kb_service._has_permission("read", "admin") is False

    def test_write_not_satisfies_admin(self):
        assert kb_service._has_permission("write", "admin") is False

    def test_admin_satisfies_admin(self):
        assert kb_service._has_permission("admin", "admin") is True


class TestGetKbForRead:
    @pytest.mark.asyncio
    async def test_owner_can_read(self):
        kb = _make_kb(owner_id=10)
        db = _make_db(kb)
        result = await kb_service.get_kb_for_read(1, 10, db)
        assert result is kb

    @pytest.mark.asyncio
    async def test_read_collaborator_can_read(self):
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "read"}])
        db = _make_db(kb)
        result = await kb_service.get_kb_for_read(1, 20, db)
        assert result is kb

    @pytest.mark.asyncio
    async def test_non_collaborator_denied(self):
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "read"}])
        db = _make_db(kb)
        with pytest.raises(ForbiddenError) as exc:
            await kb_service.get_kb_for_read(1, 999, db)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_not_found(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result
        with pytest.raises(NotFoundError):
            await kb_service.get_kb_for_read(1, 10, db)


class TestGetKbForWrite:
    @pytest.mark.asyncio
    async def test_owner_can_write(self):
        kb = _make_kb(owner_id=10)
        db = _make_db(kb)
        result = await kb_service.get_kb_for_write(1, 10, db)
        assert result is kb

    @pytest.mark.asyncio
    async def test_write_collaborator_can_write(self):
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "write"}])
        db = _make_db(kb)
        result = await kb_service.get_kb_for_write(1, 20, db)
        assert result is kb

    @pytest.mark.asyncio
    async def test_admin_collaborator_can_write(self):
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "admin"}])
        db = _make_db(kb)
        result = await kb_service.get_kb_for_write(1, 20, db)
        assert result is kb

    @pytest.mark.asyncio
    async def test_read_collaborator_denied(self):
        """IDOR 修复核心: read 协作者不能写。"""
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "read"}])
        db = _make_db(kb)
        with pytest.raises(ForbiddenError) as exc:
            await kb_service.get_kb_for_write(1, 20, db)
        assert exc.value.status_code == 403


class TestGetKbForAdmin:
    @pytest.mark.asyncio
    async def test_owner_can_admin(self):
        kb = _make_kb(owner_id=10)
        db = _make_db(kb)
        result = await kb_service.get_kb_for_admin(1, 10, db)
        assert result is kb

    @pytest.mark.asyncio
    async def test_admin_collaborator_can_admin(self):
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "admin"}])
        db = _make_db(kb)
        result = await kb_service.get_kb_for_admin(1, 20, db)
        assert result is kb

    @pytest.mark.asyncio
    async def test_read_collaborator_denied(self):
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "read"}])
        db = _make_db(kb)
        with pytest.raises(ForbiddenError) as exc:
            await kb_service.get_kb_for_admin(1, 20, db)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_write_collaborator_denied(self):
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "write"}])
        db = _make_db(kb)
        with pytest.raises(ForbiddenError) as exc:
            await kb_service.get_kb_for_admin(1, 20, db)
        assert exc.value.status_code == 403


class TestGetKbAlias:
    @pytest.mark.asyncio
    async def test_get_kb_is_read_alias(self):
        """get_kb 保持向后兼容, 等价于 get_kb_for_read。"""
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "read"}])
        db = _make_db(kb)
        # read 协作者可以通过 get_kb 读取 (向后兼容)
        result = await kb_service.get_kb(1, 20, db)
        assert result is kb


class TestDeleteKbPermission:
    @pytest.mark.asyncio
    async def test_read_collaborator_cannot_delete(self):
        """IDOR 修复核心: read 协作者调用 delete_kb → 403 ForbiddenError。"""
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "read"}])
        db = _make_db(kb)
        with pytest.raises(ForbiddenError) as exc:
            await kb_service.delete_kb(1, 20, db)
        assert exc.value.status_code == 403
        # 确保未执行任何删除操作 (权限校验在 DB 操作之前)
        assert db.delete.await_count == 0

    @pytest.mark.asyncio
    async def test_write_collaborator_cannot_delete(self):
        """write 协作者不能删除知识库 (仅 owner 可删)。"""
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "write"}])
        db = _make_db(kb)
        with pytest.raises(ForbiddenError) as exc:
            await kb_service.delete_kb(1, 20, db)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_collaborator_cannot_delete(self):
        """admin 协作者也不能删除知识库 (仅 owner 可删, spec cdp-full-coverage-v2-2026-07-24)。

        此前实现调用 get_kb_for_admin 允许 admin 协作者删除，违反 spec 设计，
        已修正为 owner-only 校验。本用例防止回归。
        """
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "admin"}])
        db = _make_db(kb)
        with pytest.raises(ForbiddenError) as exc:
            await kb_service.delete_kb(1, 20, db)
        assert exc.value.status_code == 403
        assert db.delete.await_count == 0

    @pytest.mark.asyncio
    async def test_non_collaborator_cannot_delete(self):
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "admin"}])
        db = _make_db(kb)
        with pytest.raises(ForbiddenError) as exc:
            await kb_service.delete_kb(1, 999, db)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_owner_can_delete(self):
        """owner 可以删除自己的知识库。"""
        kb = _make_kb(owner_id=10, collaborators=[])
        db = _make_db(kb)
        # owner 调用 delete_kb 不应抛异常
        await kb_service.delete_kb(1, 10, db)
        assert db.delete.await_count == 1


class TestUpdateKbPermission:
    @pytest.mark.asyncio
    async def test_read_collaborator_cannot_update(self):
        """read 协作者不能修改知识库 (需 write 权限)。"""
        from app.schemas.kb import KBUpdate

        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "read"}])
        db = _make_db(kb)
        with pytest.raises(ForbiddenError) as exc:
            await kb_service.update_kb(1, KBUpdate(name="hacked"), 20, db)
        assert exc.value.status_code == 403


class TestCollaboratorManagementPermission:
    @pytest.mark.asyncio
    async def test_read_collaborator_cannot_add_collaborator(self):
        """read 协作者不能添加协作者 (需 admin 权限)。"""
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "read"}])
        db = _make_db(kb)
        with pytest.raises(ForbiddenError) as exc:
            await kb_service.add_collaborator(1, 20, 30, "write", db)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_write_collaborator_cannot_remove_collaborator(self):
        """write 协作者不能移除协作者 (需 admin 权限)。"""
        kb = _make_kb(owner_id=10, collaborators=[{"user_id": 20, "permission": "write"}])
        db = _make_db(kb)
        with pytest.raises(ForbiddenError) as exc:
            await kb_service.remove_collaborator(1, 20, 30, db)
        assert exc.value.status_code == 403
