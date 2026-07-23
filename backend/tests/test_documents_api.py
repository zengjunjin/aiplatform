"""Tests for app.api.v1.documents (Document API endpoints)"""
import pytest
import os
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import UploadFile
from app.api.v1 import documents
from app.core.exceptions import AppException, ValidationError, ConflictError
from app.core.errors import ErrorCode
from app.db.document import Document


@pytest.fixture
def user():
    u = MagicMock()
    u.id = 1
    return u


@pytest.fixture
def db():
    return AsyncMock()


def _make_doc(doc_id=10, kb_id=1, status="done", filename="a.md", file_hash="abc",
              error_message=None):
    doc = MagicMock(spec=Document)
    doc.id = doc_id
    doc.kb_id = kb_id
    doc.filename = filename
    doc.file_path = "/tmp/a.md"
    doc.file_type = "md"
    doc.file_size = 100
    doc.file_hash = file_hash
    doc.status = status
    doc.chunk_count = 5
    doc.error_message = error_message
    doc.uploader_id = 1
    doc.created_at = MagicMock()
    doc.created_at.isoformat.return_value = "2026-01-01T00:00:00"
    doc.updated_at = MagicMock()
    doc.updated_at.isoformat.return_value = "2026-01-01T00:00:00"
    return doc


class TestListDocuments:
    @pytest.mark.asyncio
    async def test_list_documents_returns_paginated(self, user, db, request_mock):
        docs = [_make_doc(doc_id=1), _make_doc(doc_id=2)]
        with patch("app.services.document_service.list_documents", new=AsyncMock(
            return_value=(docs, 2)
        )):
            result = await documents.list_documents(
                request=request_mock, kb_id=1, page=1, page_size=20, user=user, db=db
            )
        assert result["data"]["total"] == 2
        assert len(result["data"]["items"]) == 2


class TestGetDocument:
    @pytest.mark.asyncio
    async def test_get_document_returns_doc(self, user, db, request_mock):
        doc = _make_doc(doc_id=10)
        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            result = await documents.get_document(doc_id=10, request=request_mock, user=user, db=db)
        assert result["data"]["id"] == 10


class TestGetProgress:
    @pytest.mark.asyncio
    async def test_get_progress_from_redis_cache(self, user, db, request_mock):
        """Redis 有进度缓存 → 返回缓存值"""
        doc = _make_doc(doc_id=10, status="embedding")
        cached = '{"status": "embedding", "progress": 60, "chunk_count": 5, "error_message": ""}'
        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(return_value=cached)

        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            with patch("app.redis_client.get_redis", new=AsyncMock(return_value=redis_mock)):
                result = await documents.get_progress(doc_id=10, request=request_mock, user=user, db=db)
        assert result["data"]["progress"] == 60
        assert result["data"]["status"] == "embedding"

    @pytest.mark.asyncio
    async def test_get_progress_no_cache_returns_status_map(self, user, db, request_mock):
        """Redis 无缓存 → 根据 doc.status 返回估算进度"""
        doc = _make_doc(doc_id=10, status="done")
        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            with patch("app.redis_client.get_redis", new=AsyncMock(return_value=None)):
                result = await documents.get_progress(doc_id=10, request=request_mock, user=user, db=db)
        assert result["data"]["progress"] == 100
        assert result["data"]["status"] == "done"

    @pytest.mark.asyncio
    async def test_get_progress_pending_status(self, user, db, request_mock):
        doc = _make_doc(doc_id=10, status="pending")
        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            with patch("app.redis_client.get_redis", new=AsyncMock(return_value=None)):
                result = await documents.get_progress(doc_id=10, request=request_mock, user=user, db=db)
        assert result["data"]["progress"] == 0

    @pytest.mark.asyncio
    async def test_get_progress_failed_status(self, user, db, request_mock):
        doc = _make_doc(doc_id=10, status="failed", error_message="parse error")
        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            with patch("app.redis_client.get_redis", new=AsyncMock(return_value=None)):
                result = await documents.get_progress(doc_id=10, request=request_mock, user=user, db=db)
        assert result["data"]["progress"] == 100
        assert result["data"]["error_message"] == "parse error"


class TestDeleteDocument:
    @pytest.mark.asyncio
    async def test_delete_document_calls_service(self, user, db, request_mock):
        doc = _make_doc(doc_id=10, status="done")
        with patch("app.services.document_service.get_document_for_write", new=AsyncMock(return_value=doc)), \
             patch("app.services.document_service.delete_document", new=AsyncMock()) as mock_del:
            result = await documents.delete_document(doc_id=10, request=request_mock, user=user, db=db)
        mock_del.assert_awaited_once_with(10, 1, db)
        assert "message" in result


class TestReparseDocument:
    """Task 5: reparse 通过 document_service.reparse_document 原子锁防止并发重复触发"""

    @pytest.mark.asyncio
    async def test_reparse_done_status_allowed(self, user, db, request_mock):
        """status=done → 允许 reparse, 返回 (doc, task)"""
        doc = _make_doc(doc_id=10, status="done")
        fake_task = MagicMock(id="task-123")
        with patch("app.services.document_service.reparse_document",
                   new=AsyncMock(return_value=(doc, fake_task))) as mock_reparse:
            result = await documents.reparse_document(doc_id=10, request=request_mock, user=user, db=db)
        mock_reparse.assert_awaited_once_with(10, 1, db)
        assert result["data"]["document_id"] == 10
        assert result["data"]["task_id"] == "task-123"

    @pytest.mark.asyncio
    async def test_reparse_failed_status_allowed(self, user, db, request_mock):
        """status=failed → 允许 reparse"""
        doc = _make_doc(doc_id=10, status="failed")
        fake_task = MagicMock(id="task-456")
        with patch("app.services.document_service.reparse_document",
                   new=AsyncMock(return_value=(doc, fake_task))):
            result = await documents.reparse_document(doc_id=10, request=request_mock, user=user, db=db)
        assert result["data"]["task_id"] == "task-456"

    @pytest.mark.asyncio
    async def test_reparse_parsing_status_rejected_via_service(self, user, db, request_mock):
        """status=parsing → service 抛 ConflictError, 端点透传"""
        from app.core.exceptions import ConflictError
        with patch("app.services.document_service.reparse_document",
                   new=AsyncMock(side_effect=ConflictError(message="Document is already being processed"))):
            with pytest.raises(ConflictError):
                await documents.reparse_document(doc_id=10, request=request_mock, user=user, db=db)

    @pytest.mark.asyncio
    async def test_reparse_concurrent_trigger_raises_conflict(self, user, db, request_mock):
        """Task 5 SubTask 5.2: 并发触发 reparse (乐观锁 rowcount=0) → ConflictError, 不重复入队"""
        from app.core.exceptions import ConflictError
        with patch("app.services.document_service.reparse_document",
                   new=AsyncMock(side_effect=ConflictError(message="Document status changed, please retry"))):
            with pytest.raises(ConflictError) as exc_info:
                await documents.reparse_document(doc_id=10, request=request_mock, user=user, db=db)
        # ConflictError 应携带 409 status_code, 表明并发冲突被正确识别
        assert exc_info.value.status_code == 409
        # message 应被设置 (即使 str() 不返回 message, exc_info.value.message 应存在)
        assert exc_info.value.message is not None


class TestUploadDocument:
    """upload_document 路由层测试。

    Task 13: 业务逻辑已下沉到 document_service.upload_document，
    路由仅做参数绑定 + 调用 service。业务逻辑测试见 test_document_service.py。
    """

    @pytest.mark.asyncio
    async def test_upload_returns_pending_and_task_id(self, user, db, request_mock):
        """路由调用 service 并返回 {document_id, status=pending, task_id}。"""
        file = MagicMock(spec=UploadFile)
        file.filename = "newdoc.md"

        fake_doc = MagicMock()
        fake_doc.id = 99
        fake_doc.filename = "newdoc.md"
        fake_task = MagicMock()
        fake_task.id = "task-uuid"

        with patch("app.services.document_service.upload_document",
                   new=AsyncMock(return_value=(fake_doc, fake_task))) as mock_service:
            result = await documents.upload_document(
                request=request_mock, file=file, kb_id=1, user=user, db=db
            )

        mock_service.assert_awaited_once_with(file, 1, user, db)
        assert result["data"]["document_id"] == 99
        assert result["data"]["status"] == "pending"
        assert result["data"]["task_id"] == "task-uuid"

    @pytest.mark.asyncio
    async def test_upload_propagates_service_exception(self, user, db, request_mock):
        """service 抛出的异常应原样传播（不包装）。"""
        file = MagicMock(spec=UploadFile)
        file.filename = "doc.md"

        with patch("app.services.document_service.upload_document",
                   new=AsyncMock(side_effect=ConflictError(message="dup"))):
            with pytest.raises(ConflictError):
                await documents.upload_document(
                    request=request_mock, file=file, kb_id=1, user=user, db=db
                )
