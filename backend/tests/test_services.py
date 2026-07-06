"""Tests for app.services.kb_service and app.services.document_service

使用 mock AsyncSession 测试业务逻辑，不依赖真实 PostgreSQL。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services import kb_service, document_service
from app.core.exceptions import NotFoundError, ForbiddenError, AppException
from app.db.knowledge_base import KnowledgeBase
from app.db.document import Document


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
        req = MagicMock()
        req.name = "my kb"
        req.description = "desc"
        db = AsyncMock()

        async def fake_refresh(obj, *args, **kwargs):
            obj.id = 99
        db.refresh = AsyncMock(side_effect=fake_refresh)

        result = await kb_service.create_kb(req, user_id=1, db=db)
        assert result.name == "my kb"
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
        # 第一次 execute: count → scalar_one() = 2
        # 第二次 execute: select → scalars().all() = [kb1, kb2]
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = kbs
        db.execute = AsyncMock(side_effect=[count_result, list_result])

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
        kb = _make_kb()
        db = _mock_db_with_kb(kb)
        # mock 各清理步骤
        with patch("app.rag.retriever.retriever.delete_collection", new=AsyncMock()) as mock_qdrant, \
             patch("app.rag.bm25.bm25_store.delete", new=AsyncMock()) as mock_bm25, \
             patch("app.utils.storage.delete_kb_dir") as mock_storage:
            await kb_service.delete_kb(kb_id=1, user_id=1, db=db)
        mock_qdrant.assert_awaited_once_with(1)
        mock_bm25.assert_awaited_once_with(1)
        mock_storage.assert_called_once_with(1)
        db.delete.assert_awaited_once_with(kb)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_kb_continues_on_qdrant_failure(self):
        """Qdrant 删除失败 → 继续删除其他资源"""
        kb = _make_kb()
        db = _mock_db_with_kb(kb)
        with patch("app.rag.retriever.retriever.delete_collection", new=AsyncMock(side_effect=Exception("qdrant down"))), \
             patch("app.rag.bm25.bm25_store.delete", new=AsyncMock()) as mock_bm25, \
             patch("app.utils.storage.delete_kb_dir"):
            # 不应抛异常
            await kb_service.delete_kb(kb_id=1, user_id=1, db=db)
        # BM25 仍被清理
        mock_bm25.assert_awaited_once()


class TestGetKbStats:
    @pytest.mark.asyncio
    async def test_get_kb_stats_returns_counts(self):
        kb = _make_kb()
        docs = [_make_doc(file_size=100), _make_doc(doc_id=11, file_size=200)]
        chunks = [MagicMock(), MagicMock(), MagicMock()]

        db = AsyncMock()
        # get_kb 内部 execute
        # stats: doc execute, chunk execute
        kb_result = MagicMock()
        kb_result.scalar_one_or_none.return_value = kb
        doc_result = MagicMock()
        doc_result.scalars.return_value.all.return_value = docs
        chunk_result = MagicMock()
        chunk_result.scalars.return_value.all.return_value = chunks
        db.execute = AsyncMock(side_effect=[kb_result, doc_result, chunk_result])

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
        async def fake_refresh(obj, *args, **kwargs):
            obj.id = 10
        db = AsyncMock()
        db.refresh = AsyncMock(side_effect=fake_refresh)

        result = await document_service.upload_document(
            kb_id=1, user_id=1, filename="a.md",
            file_path="/tmp/a.md", file_type="md", file_size=100, db=db,
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
                doc_id=10, req=req, user_id=1, db=db,
            )
        assert result.filename == "new.md"
        db.commit.assert_awaited_once()


class TestReparseDocument:
    @pytest.mark.asyncio
    async def test_reparse_done_status_allowed(self):
        """status=done → 允许重解析"""
        doc = _make_doc(status="done")
        with patch.object(document_service, "get_document", new=AsyncMock(return_value=doc)):
            with patch("app.tasks.document_task.parse_document_task") as mock_task:
                db = AsyncMock()
                result = await document_service.reparse_document(doc_id=10, user_id=1, db=db)
        assert result.status == "pending"
        mock_task.delay.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_reparse_failed_status_allowed(self):
        """status=failed → 允许重解析"""
        doc = _make_doc(status="failed")
        with patch.object(document_service, "get_document", new=AsyncMock(return_value=doc)):
            with patch("app.tasks.document_task.parse_document_task"):
                db = AsyncMock()
                await document_service.reparse_document(doc_id=10, user_id=1, db=db)

    @pytest.mark.asyncio
    async def test_reparse_parsing_status_rejected(self):
        """status=parsing → 409 拒绝"""
        doc = _make_doc(status="parsing")
        with patch.object(document_service, "get_document", new=AsyncMock(return_value=doc)):
            db = AsyncMock()
            with pytest.raises(AppException) as exc_info:
                await document_service.reparse_document(doc_id=10, user_id=1, db=db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_reparse_chunking_status_rejected(self):
        doc = _make_doc(status="chunking")
        with patch.object(document_service, "get_document", new=AsyncMock(return_value=doc)):
            db = AsyncMock()
            with pytest.raises(AppException) as exc_info:
                await document_service.reparse_document(doc_id=10, user_id=1, db=db)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_reparse_embedding_status_rejected(self):
        doc = _make_doc(status="embedding")
        with patch.object(document_service, "get_document", new=AsyncMock(return_value=doc)):
            db = AsyncMock()
            with pytest.raises(AppException) as exc_info:
                await document_service.reparse_document(doc_id=10, user_id=1, db=db)
        assert exc_info.value.status_code == 409


class TestDeleteDocument:
    @pytest.mark.asyncio
    async def test_delete_document_calls_all_cleanup(self):
        doc = _make_doc(doc_id=10, kb_id=1)
        with patch.object(document_service, "get_document", new=AsyncMock(return_value=doc)):
            with patch("app.rag.retriever.retriever.delete_by_doc_id", new=AsyncMock()) as mock_qdrant, \
                 patch("app.rag.bm25.bm25_store.remove_document", new=AsyncMock()) as mock_bm25, \
                 patch.object(document_service, "get_kb_dir") as mock_kb_dir, \
                 patch.object(document_service, "delete_file") as mock_delete_file:
                # mock kb_dir.iterdir()
                fake_file = MagicMock()
                fake_file.name = "10_abc.md"
                mock_kb_dir.return_value.iterdir.return_value = [fake_file]
                db = AsyncMock()
                await document_service.delete_document(doc_id=10, user_id=1, db=db)
        mock_qdrant.assert_awaited_once_with(1, 10)
        mock_bm25.assert_awaited_once_with(1, 10)
        mock_delete_file.assert_called_once()
        db.delete.assert_awaited_once_with(doc)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_document_continues_on_qdrant_failure(self):
        """Qdrant 删除失败 → 继续删除其他"""
        doc = _make_doc(doc_id=10, kb_id=1)
        with patch.object(document_service, "get_document", new=AsyncMock(return_value=doc)):
            with patch("app.rag.retriever.retriever.delete_by_doc_id", new=AsyncMock(side_effect=Exception("qdrant down"))), \
                 patch("app.rag.bm25.bm25_store.remove_document", new=AsyncMock()) as mock_bm25, \
                 patch.object(document_service, "get_kb_dir"), \
                 patch.object(document_service, "delete_file"):
                db = AsyncMock()
                # 不应抛
                await document_service.delete_document(doc_id=10, user_id=1, db=db)
        mock_bm25.assert_awaited_once()  # BM25 仍被清理
