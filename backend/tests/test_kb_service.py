"""Tests for app.services.kb_service

覆盖场景:
- 协作者 JSONB 增删改
- 权限校验（read/write/admin 三种角色）
- 级联删除（顺序 + 事件发布）
- owner 不可自降权限
- owner 不可自移除
- 协作者自移除边界
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.db.user import User
from app.schemas.kb import KBCreate, KBUpdate
from app.services import kb_service


def _make_kb(
    kb_id=1,
    owner_id=10,
    name="test-kb",
    description="desc",
    collaborators=None,
    doc_count=0,
    chunk_count=0,
):
    """构造 KB mock。collaborators 形如 [{"user_id": int, "permission": str}]。"""
    kb = MagicMock()
    kb.id = kb_id
    kb.owner_id = owner_id
    kb.name = name
    kb.description = description
    kb.collaborators = collaborators if collaborators is not None else []
    kb.doc_count = doc_count
    kb.chunk_count = chunk_count
    kb.created_at = MagicMock()
    kb.updated_at = MagicMock()
    return kb


def _make_user(user_id=1, username="tester"):
    """构造 User mock。"""
    u = MagicMock(spec=User)
    u.id = user_id
    u.username = username
    return u


def _make_db_with_kb(kb):
    """构造 db mock，execute 返回该 kb。"""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: kb))
    return db


# ========== 协作者 JSONB 增删改 ==========


class TestAddCollaborator:
    """add_collaborator 的 JSONB 操作。"""

    @pytest.mark.asyncio
    async def test_add_collaborator_success(self):
        """成功添加协作者到 JSONB 数组。"""
        kb = _make_kb(owner_id=10, collaborators=[])
        target_user = _make_user(user_id=20, username="collaborator")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=lambda: kb),  # get_kb_for_admin
                MagicMock(scalar_one_or_none=lambda: target_user),  # 查询 target_user
            ]
        )

        with patch("app.services.kb_service.log_audit", new=AsyncMock()):
            result = await kb_service.add_collaborator(1, 10, 20, "write", db)

        assert result == {"user_id": 20, "username": "collaborator", "permission": "write"}
        assert {"user_id": 20, "permission": "write"} in kb.collaborators
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_collaborator_update_existing_permission(self):
        """已存在的协作者：更新权限（先移除旧条目再添加新条目）。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "read"}],
        )
        target_user = _make_user(user_id=20, username="collaborator")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=lambda: kb),
                MagicMock(scalar_one_or_none=lambda: target_user),
            ]
        )

        with patch("app.services.kb_service.log_audit", new=AsyncMock()):
            await kb_service.add_collaborator(1, 10, 20, "admin", db)

        # 应只有一个条目，权限更新为 admin
        assert len(kb.collaborators) == 1
        assert kb.collaborators[0] == {"user_id": 20, "permission": "admin"}

    @pytest.mark.asyncio
    async def test_add_collaborator_cannot_add_self(self):
        """owner 不能添加自己为协作者（防止自降权限）。"""
        kb = _make_kb(owner_id=10, collaborators=[])
        db = _make_db_with_kb(kb)

        with pytest.raises(ForbiddenError):
            await kb_service.add_collaborator(1, 10, 10, "read", db)

    @pytest.mark.asyncio
    async def test_add_collaborator_cannot_add_owner(self):
        """不能将 owner 添加为协作者（防止自降权限）。"""
        kb = _make_kb(owner_id=10, collaborators=[])
        owner_user = _make_user(user_id=10, username="owner")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=lambda: kb),
                MagicMock(scalar_one_or_none=lambda: owner_user),
            ]
        )

        with pytest.raises(ForbiddenError):
            await kb_service.add_collaborator(1, 20, 10, "admin", db)

    @pytest.mark.asyncio
    async def test_add_collaborator_target_user_not_found(self):
        """目标用户不存在 → NotFoundError。"""
        kb = _make_kb(owner_id=10, collaborators=[])
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=lambda: kb),
                MagicMock(scalar_one_or_none=lambda: None),
            ]
        )

        with pytest.raises(NotFoundError):
            await kb_service.add_collaborator(1, 10, 999, "read", db)

    @pytest.mark.asyncio
    async def test_add_collaborator_read_perm_denied(self):
        """read 协作者不能添加协作者（需 admin 权限）。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "read"}],
        )
        db = _make_db_with_kb(kb)

        with pytest.raises(ForbiddenError):
            await kb_service.add_collaborator(1, 20, 30, "write", db)


class TestRemoveCollaborator:
    """remove_collaborator 的 JSONB 操作。"""

    @pytest.mark.asyncio
    async def test_remove_collaborator_success(self):
        """成功从 JSONB 数组移除协作者。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[
                {"user_id": 20, "permission": "write"},
                {"user_id": 30, "permission": "read"},
            ],
        )
        db = _make_db_with_kb(kb)

        with patch("app.services.kb_service.log_audit", new=AsyncMock()):
            await kb_service.remove_collaborator(1, 10, 20, db)

        # 应只剩 user 30
        assert len(kb.collaborators) == 1
        assert kb.collaborators[0]["user_id"] == 30
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_remove_collaborator_nonexistent_idempotent(self):
        """移除不存在的协作者 → 幂等，不报错。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "write"}],
        )
        db = _make_db_with_kb(kb)

        with patch("app.services.kb_service.log_audit", new=AsyncMock()):
            await kb_service.remove_collaborator(1, 10, 999, db)

        # 列表不变
        assert len(kb.collaborators) == 1
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_remove_collaborator_owner_self_removal_noop(self):
        """owner 不可自移除：owner 不在 collaborators 列表中，调用为 no-op。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "write"}],
        )
        db = _make_db_with_kb(kb)

        with patch("app.services.kb_service.log_audit", new=AsyncMock()):
            # owner 调用 remove_collaborator(target=owner_id)
            await kb_service.remove_collaborator(1, 10, 10, db)

        # 列表不变（owner 本来就不在列表中）
        assert len(kb.collaborators) == 1
        assert kb.collaborators[0]["user_id"] == 20

    @pytest.mark.asyncio
    async def test_remove_collaborator_admin_self_removal_boundary(self):
        """协作者自移除边界：admin 协作者可自移除（移除后失去访问权限）。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[
                {"user_id": 20, "permission": "admin"},
                {"user_id": 30, "permission": "read"},
            ],
        )
        db = _make_db_with_kb(kb)

        with patch("app.services.kb_service.log_audit", new=AsyncMock()):
            # admin 协作者(20) 移除自己
            await kb_service.remove_collaborator(1, 20, 20, db)

        # user 20 应被移除
        assert len(kb.collaborators) == 1
        assert kb.collaborators[0]["user_id"] == 30

    @pytest.mark.asyncio
    async def test_remove_collaborator_read_perm_denied(self):
        """read 协作者不能移除协作者（需 admin 权限）。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "read"}],
        )
        db = _make_db_with_kb(kb)

        with pytest.raises(ForbiddenError):
            await kb_service.remove_collaborator(1, 20, 30, db)

    @pytest.mark.asyncio
    async def test_remove_collaborator_write_perm_denied(self):
        """write 协作者不能移除协作者（需 admin 权限）。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "write"}],
        )
        db = _make_db_with_kb(kb)

        with pytest.raises(ForbiddenError):
            await kb_service.remove_collaborator(1, 20, 30, db)


class TestGetCollaborators:
    """get_collaborators 的 JSONB 读取与用户名富化。"""

    @pytest.mark.asyncio
    async def test_get_collaborators_enriched_with_usernames(self):
        """返回的协作者列表应包含 username（批量查询）。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[
                {"user_id": 20, "permission": "write"},
                {"user_id": 30, "permission": "read"},
            ],
        )
        user20 = _make_user(user_id=20, username="alice")
        user30 = _make_user(user_id=30, username="bob")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=lambda: kb),  # get_kb_for_read
                MagicMock(  # 批量查询 users
                    scalars=MagicMock(return_value=MagicMock(all=lambda: [user20, user30]))
                ),
            ]
        )

        result = await kb_service.get_collaborators(1, 10, db)

        assert len(result) == 2
        assert result[0] == {"user_id": 20, "username": "alice", "permission": "write"}
        assert result[1] == {"user_id": 30, "username": "bob", "permission": "read"}

    @pytest.mark.asyncio
    async def test_get_collaborators_missing_user_fallback(self):
        """用户不存在时使用 User#{id} 占位。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 999, "permission": "read"}],
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=lambda: kb),
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: []))),
            ]
        )

        result = await kb_service.get_collaborators(1, 10, db)
        assert len(result) == 1
        assert result[0]["username"] == "User#999"

    @pytest.mark.asyncio
    async def test_get_collaborators_empty_list(self):
        """无协作者 → 空列表。"""
        kb = _make_kb(owner_id=10, collaborators=[])
        db = _make_db_with_kb(kb)

        result = await kb_service.get_collaborators(1, 10, db)
        assert result == []


# ========== 权限校验（read/write/admin 三种角色） ==========


class TestPermissionEnforcement:
    """三种角色的权限校验（功能层）。"""

    @pytest.mark.asyncio
    async def test_read_collaborator_can_read(self):
        """read 协作者可通过 get_kb_for_read。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "read"}],
        )
        db = _make_db_with_kb(kb)
        result = await kb_service.get_kb_for_read(1, 20, db)
        assert result is kb

    @pytest.mark.asyncio
    async def test_read_collaborator_cannot_write(self):
        """read 协作者不能通过 get_kb_for_write。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "read"}],
        )
        db = _make_db_with_kb(kb)
        with pytest.raises(ForbiddenError):
            await kb_service.get_kb_for_write(1, 20, db)

    @pytest.mark.asyncio
    async def test_write_collaborator_can_write(self):
        """write 协作者可通过 get_kb_for_write。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "write"}],
        )
        db = _make_db_with_kb(kb)
        result = await kb_service.get_kb_for_write(1, 20, db)
        assert result is kb

    @pytest.mark.asyncio
    async def test_write_collaborator_cannot_admin(self):
        """write 协作者不能通过 get_kb_for_admin。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "write"}],
        )
        db = _make_db_with_kb(kb)
        with pytest.raises(ForbiddenError):
            await kb_service.get_kb_for_admin(1, 20, db)

    @pytest.mark.asyncio
    async def test_admin_collaborator_can_admin(self):
        """admin 协作者可通过 get_kb_for_admin。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "admin"}],
        )
        db = _make_db_with_kb(kb)
        result = await kb_service.get_kb_for_admin(1, 20, db)
        assert result is kb

    @pytest.mark.asyncio
    async def test_admin_collaborator_can_write(self):
        """admin 协作者可通过 get_kb_for_write（权限向下兼容）。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "admin"}],
        )
        db = _make_db_with_kb(kb)
        result = await kb_service.get_kb_for_write(1, 20, db)
        assert result is kb

    @pytest.mark.asyncio
    async def test_owner_has_all_permissions(self):
        """owner 拥有所有权限（read/write/admin）。"""
        kb = _make_kb(owner_id=10, collaborators=[])
        db = _make_db_with_kb(kb)
        assert await kb_service.get_kb_for_read(1, 10, db) is kb
        assert await kb_service.get_kb_for_write(1, 10, db) is kb
        assert await kb_service.get_kb_for_admin(1, 10, db) is kb

    @pytest.mark.asyncio
    async def test_non_collaborator_denied(self):
        """非协作者/非 owner → ForbiddenError。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "admin"}],
        )
        db = _make_db_with_kb(kb)
        with pytest.raises(ForbiddenError):
            await kb_service.get_kb_for_read(1, 999, db)

    @pytest.mark.asyncio
    async def test_kb_not_found_raises(self):
        """KB 不存在 → NotFoundError。"""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        with pytest.raises(NotFoundError):
            await kb_service.get_kb_for_read(1, 10, db)


# ========== 级联删除 ==========


class TestDeleteKbCascade:
    """delete_kb 的级联清理与事件发布。"""

    @pytest.mark.asyncio
    async def test_delete_kb_cascade_deletes_all_relations(self):
        """级联删除：ChatSession → DocumentChunk → Document → KB 全部删除。"""
        kb = _make_kb(owner_id=10)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: kb))
        db.scalar = AsyncMock(side_effect=[5, 10])  # doc_count=5, chunk_count=10

        with (
            patch("app.services.kb_service.EventBus.publish", new=AsyncMock()),
            patch("app.services.kb_service.log_audit", new=AsyncMock()),
            patch("app.services.kb_service.get_redis", return_value=None),
        ):
            await kb_service.delete_kb(1, 10, db)

        # 4 次 execute：1 次 select KB + 3 次 delete（ChatSession/DocumentChunk/Document）
        assert db.execute.await_count == 4
        db.delete.assert_awaited_once_with(kb)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_kb_publishes_kb_deleted_event(self):
        """删除 KB 后发布 KB_DELETED 事件（含 doc_count/chunk_count）。"""
        kb = _make_kb(owner_id=10)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: kb))
        db.scalar = AsyncMock(side_effect=[3, 7])

        with (
            patch("app.services.kb_service.EventBus.publish", new=AsyncMock()) as mock_publish,
            patch("app.services.kb_service.log_audit", new=AsyncMock()),
            patch("app.services.kb_service.get_redis", return_value=None),
        ):
            await kb_service.delete_kb(1, 10, db)

        mock_publish.assert_awaited_once()
        event_args = mock_publish.await_args.args
        assert event_args[0] == kb_service.EventBus.KB_DELETED
        assert event_args[1]["kb_id"] == 1
        assert event_args[1]["doc_count"] == 3
        assert event_args[1]["chunk_count"] == 7

    @pytest.mark.asyncio
    async def test_delete_kb_event_failure_falls_back_to_redis_queue(self):
        """EventBus.publish 失败时，kb_id 写入 Redis 补偿队列。"""
        kb = _make_kb(owner_id=10)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: kb))
        db.scalar = AsyncMock(side_effect=[0, 0])
        redis_mock = MagicMock()
        redis_mock.lpush = AsyncMock()

        with (
            patch(
                "app.services.kb_service.EventBus.publish",
                new=AsyncMock(side_effect=Exception("boom")),
            ),
            patch("app.services.kb_service.log_audit", new=AsyncMock()),
            patch("app.services.kb_service.get_redis", return_value=redis_mock),
        ):
            await kb_service.delete_kb(1, 10, db)

        redis_mock.lpush.assert_awaited_once_with("kb:cleanup:pending", "1")

    @pytest.mark.asyncio
    async def test_delete_kb_not_found_raises(self):
        """KB 不存在 → NotFoundError。"""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        with pytest.raises(NotFoundError):
            await kb_service.delete_kb(1, 10, db)

    @pytest.mark.asyncio
    async def test_delete_kb_admin_collaborator_denied(self):
        """admin 协作者不能删除 KB（仅 owner）。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "admin"}],
        )
        db = _make_db_with_kb(kb)

        with pytest.raises(ForbiddenError):
            await kb_service.delete_kb(1, 20, db)
        db.delete.assert_not_awaited()


# ========== KB CRUD ==========


class TestCreateKb:
    @pytest.mark.asyncio
    async def test_create_kb_success(self):
        """成功创建知识库。"""
        req = KBCreate(name="new-kb", description="desc")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        async def fake_refresh(obj, *args, **kwargs):
            obj.id = 99

        db.refresh = AsyncMock(side_effect=fake_refresh)

        result = await kb_service.create_kb(req, user_id=10, db=db)
        assert result.id == 99
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_kb_name_conflict_raises(self):
        """同名知识库已存在 → ConflictError。"""
        existing = _make_kb(kb_id=1, owner_id=10, name="dup")
        req = KBCreate(name="dup", description="desc")
        db = _make_db_with_kb(existing)

        with pytest.raises(ConflictError):
            await kb_service.create_kb(req, user_id=10, db=db)


class TestUpdateKb:
    @pytest.mark.asyncio
    async def test_update_kb_name(self):
        """更新知识库名称。"""
        kb = _make_kb(owner_id=10, name="old")
        db = _make_db_with_kb(kb)
        req = KBUpdate(name="new-name", description=None)

        with patch("app.services.kb_service.log_audit", new=AsyncMock()):
            result = await kb_service.update_kb(1, req, 10, db)
        assert result.name == "new-name"

    @pytest.mark.asyncio
    async def test_update_kb_description(self):
        """更新知识库描述。"""
        kb = _make_kb(owner_id=10, description="old")
        db = _make_db_with_kb(kb)
        req = KBUpdate(name=None, description="new-desc")

        with patch("app.services.kb_service.log_audit", new=AsyncMock()):
            result = await kb_service.update_kb(1, req, 10, db)
        assert result.description == "new-desc"


# ========== Owner 不可自降权限/自移除 综合边界 ==========


class TestOwnerSelfManagementBoundary:
    """owner 权限边界：不可自降权限、不可自移除。"""

    @pytest.mark.asyncio
    async def test_owner_cannot_add_self_as_collaborator(self):
        """owner 不能添加自己为协作者（防止自降权限）。"""
        kb = _make_kb(owner_id=10, collaborators=[])
        db = _make_db_with_kb(kb)

        with pytest.raises(ForbiddenError):
            await kb_service.add_collaborator(1, 10, 10, "read", db)

    @pytest.mark.asyncio
    async def test_owner_cannot_be_added_as_collaborator_by_admin(self):
        """admin 协作者也不能将 owner 添加为协作者。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "admin"}],
        )
        owner_user = _make_user(user_id=10, username="owner")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=lambda: kb),
                MagicMock(scalar_one_or_none=lambda: owner_user),
            ]
        )

        with pytest.raises(ForbiddenError):
            await kb_service.add_collaborator(1, 20, 10, "admin", db)

    @pytest.mark.asyncio
    async def test_owner_self_removal_is_noop(self):
        """owner 调用 remove_collaborator(target=owner) → no-op（不在列表中）。"""
        kb = _make_kb(
            owner_id=10,
            collaborators=[{"user_id": 20, "permission": "write"}],
        )
        db = _make_db_with_kb(kb)

        with patch("app.services.kb_service.log_audit", new=AsyncMock()):
            await kb_service.remove_collaborator(1, 10, 10, db)

        # 列表不变（owner 不在 collaborators 中）
        assert len(kb.collaborators) == 1
