"""Tests for app.services.kb_service and app.services.document_service

使用 mock AsyncSession 测试业务逻辑，不依赖真实 PostgreSQL。
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException, ForbiddenError, NotFoundError
from app.db.document import Document
from app.db.knowledge_base import KnowledgeBase
from app.services import document_service, kb_service

# ---------- kb_service 测试 ----------


def _make_kb(kb_id=1, owner_id=1, name="kb1"):
    kb = MagicMock(spec=KnowledgeBase)
    kb.id = kb_id
    kb.owner_id = owner_id
    kb.name = name
    kb.description = "desc"
    kb.created_at = MagicMock()
    kb.created_at.isoformat.return_value = "2026-01-01T00:00:00"
    kb.updated_at = MagicMock()
    kb.updated_at.isoformat.return_value = "2026-01-01T00:00:00"
    return kb


def _make_doc(doc_id=10, kb_id=1, filename="a.md", file_size=100, status="done"):
    doc = MagicMock(spec=Document)
    doc.id = doc_id
    doc.kb_id = kb_id
    doc.filename = filename
    doc.file_path = "/tmp/a.md"
    doc.file_type = "md"
    doc.file_size = file_size
    doc.status = status
    doc.chunk_count = 5
    doc.error_message = None
    return doc


def _mock_db_with_kb(kb):
    """mock db：execute 返回带 scalar_one_or_none 的结果"""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: kb))
    return db


class TestCreateKb:
    @pytest.mark.asyncio
    async def test_create_kb_success(self):
        test_name = f"test_kb_{int(time.time() * 1000)}"
        req = MagicMock()
        req.name = test_name
        req.description = "desc"
        db = AsyncMock()

        # Mock the duplicate name check: db.execute returns scalar_one_or_none() = None
        mock_check_result = MagicMock()
        mock_check_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_check_result

        async def fake_refresh(obj, *args, **kwargs):
            obj.id = 99

        db.refresh = AsyncMock(side_effect=fake_refresh)

        result = await kb_service.create_kb(req, user_id=1, db=db)
        assert result.name == test_name
        assert result.id == 99
        db.add.assert_called_once()
        db.commit.assert_awaited_once()


class TestGetKb:
    @pytest.mark.asyncio
    async def test_get_kb_success(self):
        kb = _make_kb(kb_id=5, owner_id=1)
        db = _mock_db_with_kb(kb)
        result = await kb_service.get_kb(kb_id=5, user_id=1, db=db)
        assert result.id == 5

    @pytest.mark.asyncio
    async def test_get_kb_not_found_raises(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        with pytest.raises(NotFoundError):
            await kb_service.get_kb(kb_id=999, user_id=1, db=db)

    @pytest.mark.asyncio
    async def test_get_kb_wrong_owner_raises_forbidden(self):
        kb = _make_kb(owner_id=2)  # 别人的 kb
        db = _mock_db_with_kb(kb)
        with pytest.raises(ForbiddenError):
            await kb_service.get_kb(kb_id=1, user_id=1, db=db)


class TestListKbs:
    @pytest.mark.asyncio
    async def test_list_kbs_returns_items_and_total(self):
        kbs = [_make_kb(kb_id=1), _make_kb(kb_id=2)]
        db = AsyncMock()
        # db.scalar 用于 count 查询
        db.scalar = AsyncMock(return_value=2)
        # db.execute 用于 data 查询 → scalars().all() = [kb1, kb2]
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = kbs
        db.execute = AsyncMock(return_value=list_result)

        items, total = await kb_service.list_kbs(user_id=1, db=db, page=1, page_size=20)
        assert total == 2
        assert len(items) == 2


class TestUpdateKb:
    @pytest.mark.asyncio
    async def test_update_kb_only_name(self):
        kb = _make_kb(name="old")
        db = _mock_db_with_kb(kb)
        req = MagicMock()
        req.name = "new name"
        req.description = None  # 不更新
        result = await kb_service.update_kb(kb_id=1, req=req, user_id=1, db=db)
        assert result.name == "new name"
        # description 不变
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_kb_only_description(self):
        kb = _make_kb()
        kb.description = "old desc"
        db = _mock_db_with_kb(kb)
        req = MagicMock()
        req.name = None
        req.description = "new desc"
        result = await kb_service.update_kb(kb_id=1, req=req, user_id=1, db=db)
        assert result.description == "new desc"


class TestDeleteKb:
    @pytest.mark.asyncio
    async def test_delete_kb_calls_all_cleanup_steps(self):
        """Task 29: delete_kb 发布 KB_DELETED 事件，外部资源清理由订阅者处理。"""
        from app.core.events import EventBus

        kb = _make_kb()
        db = AsyncMock()
        # get_kb_for_read → execute(scalar_one_or_none)；后续 delete 语句 → execute
        kb_result = MagicMock()
        kb_result.scalar_one_or_none.return_value = kb
        db.execute = AsyncMock(return_value=kb_result)
        # doc_count / chunk_count 统计
        db.scalar = AsyncMock(side_effect=[2, 5])

        with (
            patch("app.services.kb_service.EventBus.publish", new=AsyncMock()) as mock_publish,
            patch("app.services.kb_service.log_audit", new=AsyncMock()),
        ):
            await kb_service.delete_kb(kb_id=1, user_id=1, db=db)
        # 验证发布 KB_DELETED 事件（外部清理由 document_service 订阅者处理）
        mock_publish.assert_awaited_once()
        args, _ = mock_publish.call_args
        assert args[0] == EventBus.KB_DELETED
        assert args[1]["kb_id"] == 1
        assert args[1]["doc_count"] == 2
        assert args[1]["chunk_count"] == 5
        db.delete.assert_awaited_once_with(kb)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_kb_continues_on_qdrant_failure(self):
        """Task 29: _on_kb_deleted 容错 — Qdrant 删除失败仍清理 BM25/storage。"""
        with (
            patch(
                "app.rag.retriever.retriever.delete_collection",
                new=MagicMock(side_effect=Exception("qdrant down")),
            ),
            patch("app.rag.bm25.bm25_store.delete", new=AsyncMock()) as mock_bm25,
            patch("app.utils.storage.delete_kb_dir") as mock_storage,
        ):
            # _on_kb_deleted 不应抛异常，Qdrant 失败后继续清理其他资源
            await document_service._on_kb_deleted({"kb_id": 1, "doc_count": 0, "chunk_count": 0})
        # BM25 和 storage 仍被清理
        mock_bm25.assert_awaited_once_with(1)
        mock_storage.assert_called_once_with(1)


class TestGetKbStats:
    @pytest.mark.asyncio
    async def test_get_kb_stats_returns_counts(self):
        kb = _make_kb()

        db = AsyncMock()
        # get_kb 内部 execute: scalar_one_or_none
        # get_kb_stats: db.execute → doc_stats.one(); db.scalar → chunk_count
        kb_result = MagicMock()
        kb_result.scalar_one_or_none.return_value = kb
        doc_stats_result = MagicMock()
        doc_stats_result.one.return_value = MagicMock(doc_count=2, total_size=300)
        db.execute = AsyncMock(side_effect=[kb_result, doc_stats_result])
        db.scalar = AsyncMock(return_value=3)

        stats = await kb_service.get_kb_stats(kb_id=1, user_id=1, db=db)
        assert stats["doc_count"] == 2
        assert stats["chunk_count"] == 3
        assert stats["total_size"] == 300
        assert stats["name"] == "kb1"
        assert stats["id"] == 1


# ---------- document_service 测试 ----------


class TestUploadDocument:
    @pytest.mark.asyncio
    async def test_upload_document_creates_record(self):
        """Task 13: 旧 upload_document 重命名为 create_document_record（低层 API）。

        新的 upload_document(file, kb_id, user, db) 完整业务封装在 test_document_service.py 中测试。
        """

        async def fake_refresh(obj, *args, **kwargs):
            obj.id = 10

        db = AsyncMock()
        db.refresh = AsyncMock(side_effect=fake_refresh)

        result = await document_service.create_document_record(
            kb_id=1,
            user_id=1,
            filename="a.md",
            file_path="/tmp/a.md",
            file_type="md",
            file_size=100,
            db=db,
        )
        assert result.id == 10
        assert result.filename == "a.md"
        assert result.status == "pending"
        assert result.chunk_count == 0
        db.add.assert_called_once()
        db.commit.assert_awaited_once()


class TestGetDocument:
    @pytest.mark.asyncio
    async def test_get_document_success(self):
        doc = _make_doc(doc_id=10, kb_id=1)
        kb = _make_kb(kb_id=1, owner_id=1)
        db = AsyncMock()
        # 第一次 execute: doc → scalar_one_or_none
        # get_kb 内部 execute: kb → scalar_one_or_none
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        kb_result = MagicMock()
        kb_result.scalar_one_or_none.return_value = kb
        db.execute = AsyncMock(side_effect=[doc_result, kb_result])

        result = await document_service.get_document(doc_id=10, user_id=1, db=db)
        assert result.id == 10

    @pytest.mark.asyncio
    async def test_get_document_not_found(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        with pytest.raises(NotFoundError):
            await document_service.get_document(doc_id=999, user_id=1, db=db)


class TestUpdateDocument:
    @pytest.mark.asyncio
    async def test_update_document_title(self):
        doc = _make_doc(filename="old.md")
        req = MagicMock()
        req.title = "new.md"
        with patch.object(document_service, "get_document", new=AsyncMock(return_value=doc)):
            db = AsyncMock()
            result = await document_service.update_document(
                doc_id=10,
                req=req,
                user_id=1,
                db=db,
            )
        assert result.filename == "new.md"
        db.commit.assert_awaited_once()


class TestReparseDocument:
    @pytest.mark.asyncio
    async def test_reparse_done_status_allowed(self):
        """status=done → 允许重解析, 返回 (doc, task) 元组"""
        doc = _make_doc(status="done")
        with patch.object(
            document_service, "get_document_for_write", new=AsyncMock(return_value=doc)
        ):
            with patch("app.tasks.document_task.parse_document_task") as mock_task:
                db = AsyncMock()
                # Mock sa_update result: rowcount=1 表示更新成功
                mock_result = MagicMock(rowcount=1)
                db.execute = AsyncMock(return_value=mock_result)
                # Mock kb with concrete doc_count/chunk_count for max() arithmetic
                mock_kb = MagicMock()
                mock_kb.doc_count = 5
                mock_kb.chunk_count = 100
                db.get = AsyncMock(return_value=mock_kb)
                result = await document_service.reparse_document(doc_id=10, user_id=1, db=db)
        # 新契约: 返回 tuple (doc, task)
        assert isinstance(result, tuple)
        returned_doc, _ = result
        assert returned_doc.status == "pending"
        mock_task.delay.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_reparse_failed_status_allowed(self):
        """status=failed → 允许重解析"""
        doc = _make_doc(status="failed")
        with patch.object(
            document_service, "get_document_for_write", new=AsyncMock(return_value=doc)
        ):
            with patch("app.tasks.document_task.parse_document_task"):
                db = AsyncMock()
                mock_result = MagicMock(rowcount=1)
                db.execute = AsyncMock(return_value=mock_result)
                # Mock kb with concrete doc_count/chunk_count for max() arithmetic
                mock_kb = MagicMock()
                mock_kb.doc_count = 5
                mock_kb.chunk_count = 100
                db.get = AsyncMock(return_value=mock_kb)
                result = await document_service.reparse_document(doc_id=10, user_id=1, db=db)
        # 返回 tuple (doc, task)
        assert isinstance(result, tuple)
        assert result[0].status == "pending"

    @pytest.mark.asyncio
    async def test_reparse_parsing_status_rejected(self):
        """status=parsing → 409 拒绝"""
        doc = _make_doc(status="parsing")
        with patch.object(
            document_service, "get_document_for_write", new=AsyncMock(return_value=doc)
        ):
            db = AsyncMock()
            with pytest.raises(AppException) as exc_info:
                await document_service.reparse_document(doc_id=10, user_id=1, db=db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_reparse_chunking_status_rejected(self):
        doc = _make_doc(status="chunking")
        with patch.object(
            document_service, "get_document_for_write", new=AsyncMock(return_value=doc)
        ):
            db = AsyncMock()
            with pytest.raises(AppException) as exc_info:
                await document_service.reparse_document(doc_id=10, user_id=1, db=db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_reparse_embedding_status_rejected(self):
        doc = _make_doc(status="embedding")
        with patch.object(
            document_service, "get_document_for_write", new=AsyncMock(return_value=doc)
        ):
            db = AsyncMock()
            with pytest.raises(AppException) as exc_info:
                await document_service.reparse_document(doc_id=10, user_id=1, db=db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_reparse_concurrent_trigger_raises_conflict(self):
        """Task 5 SubTask 5.2: 乐观锁 rowcount=0 (并发触发) → ConflictError, 不重复入队"""
        doc = _make_doc(status="done")
        with patch.object(
            document_service, "get_document_for_write", new=AsyncMock(return_value=doc)
        ):
            with patch("app.tasks.document_task.parse_document_task") as mock_task:
                db = AsyncMock()
                # sa_update 返回 rowcount=0 表示状态已被并发请求修改
                mock_result = MagicMock(rowcount=0)
                db.execute = AsyncMock(return_value=mock_result)
                with pytest.raises(AppException) as exc_info:
                    await document_service.reparse_document(doc_id=10, user_id=1, db=db)
        assert exc_info.value.status_code == 409
        # 并发冲突时不应入队 task
        mock_task.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_reparse_returns_tuple_of_doc_and_task(self):
        """Task 5: reparse_document 返回 (doc, task) 元组"""
        doc = _make_doc(status="done")
        fake_task = MagicMock(id="task-xyz")
        with patch.object(
            document_service, "get_document_for_write", new=AsyncMock(return_value=doc)
        ):
            with patch("app.tasks.document_task.parse_document_task") as mock_task:
                mock_task.delay.return_value = fake_task
                db = AsyncMock()
                mock_result = MagicMock(rowcount=1)
                db.execute = AsyncMock(return_value=mock_result)
                # Mock kb with concrete doc_count/chunk_count for max() arithmetic
                mock_kb = MagicMock()
                mock_kb.doc_count = 5
                mock_kb.chunk_count = 100
                db.get = AsyncMock(return_value=mock_kb)
                result = await document_service.reparse_document(doc_id=10, user_id=1, db=db)
        # 应返回 tuple (doc, task)
        assert isinstance(result, tuple)
        assert len(result) == 2
        returned_doc, returned_task = result
        assert returned_doc.status == "pending"
        assert returned_task.id == "task-xyz"


class TestDeleteDocument:
    @pytest.mark.asyncio
    async def test_delete_document_calls_all_cleanup(self):
        doc = _make_doc(doc_id=10, kb_id=1)
        with patch.object(
            document_service, "get_document_for_write", new=AsyncMock(return_value=doc)
        ):
            with (
                patch("app.rag.retriever.retriever.delete_by_doc_id") as mock_qdrant,
                patch("app.rag.bm25.bm25_store.remove_document", new=AsyncMock()) as mock_bm25,
                patch.object(document_service, "get_kb_dir") as mock_kb_dir,
                patch.object(document_service, "delete_file") as mock_delete_file,
            ):
                # mock kb_dir.iterdir()
                fake_file = MagicMock()
                fake_file.name = "10_abc.md"
                mock_kb_dir.return_value.iterdir.return_value = [fake_file]
                db = AsyncMock()
                # Mock kb with concrete doc_count/chunk_count for max() arithmetic
                mock_kb = MagicMock()
                mock_kb.doc_count = 5
                mock_kb.chunk_count = 100
                db.get = AsyncMock(return_value=mock_kb)
                await document_service.delete_document(doc_id=10, user_id=1, db=db)
        mock_qdrant.assert_called_once_with(1, 10)
        mock_bm25.assert_awaited_once_with(1, 10)
        mock_delete_file.assert_called_once()
        # 软删除: doc.deleted_at is set, doc.status == "deleted"
        assert doc.deleted_at is not None
        assert doc.status == "deleted"
        db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_delete_document_continues_on_qdrant_failure(self):
        """Qdrant 删除失败 → 继续删除其他"""
        doc = _make_doc(doc_id=10, kb_id=1)
        with patch.object(
            document_service, "get_document_for_write", new=AsyncMock(return_value=doc)
        ):
            with (
                patch(
                    "app.rag.retriever.retriever.delete_by_doc_id",
                    side_effect=Exception("qdrant down"),
                ),
                patch("app.rag.bm25.bm25_store.remove_document", new=AsyncMock()) as mock_bm25,
                patch.object(document_service, "get_kb_dir"),
                patch.object(document_service, "delete_file"),
            ):
                db = AsyncMock()
                # Mock kb with concrete doc_count/chunk_count for max() arithmetic
                mock_kb = MagicMock()
                mock_kb.doc_count = 5
                mock_kb.chunk_count = 100
                db.get = AsyncMock(return_value=mock_kb)
                # 不应抛
                await document_service.delete_document(doc_id=10, user_id=1, db=db)
        mock_bm25.assert_awaited_once()  # BM25 仍被清理
