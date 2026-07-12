"""Tests for app.api.v1.documents (Document API endpoints)"""
import pytest
import os
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import UploadFile
from starlette.requests import Request
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


@pytest.fixture
def request_mock():
    """真实的 starlette Request，limiter 装饰器需要"""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/documents/upload",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 8000),
    }
    return Request(scope)


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
    async def test_list_documents_returns_paginated(self, user, db):
        docs = [_make_doc(doc_id=1), _make_doc(doc_id=2)]
        with patch("app.services.document_service.list_documents", new=AsyncMock(
            return_value=(docs, 2)
        )):
            result = await documents.list_documents(
                kb_id=1, page=1, page_size=20, user=user, db=db
            )
        assert result["data"]["total"] == 2
        assert len(result["data"]["items"]) == 2


class TestGetDocument:
    @pytest.mark.asyncio
    async def test_get_document_returns_doc(self, user, db):
        doc = _make_doc(doc_id=10)
        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            result = await documents.get_document(doc_id=10, user=user, db=db)
        assert result["data"]["id"] == 10


class TestGetProgress:
    @pytest.mark.asyncio
    async def test_get_progress_from_redis_cache(self, user, db):
        """Redis 有进度缓存 → 返回缓存值"""
        doc = _make_doc(doc_id=10, status="embedding")
        cached = '{"status": "embedding", "progress": 60, "chunk_count": 5, "error_message": ""}'
        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(return_value=cached)

        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            with patch("app.redis_client.get_redis", new=AsyncMock(return_value=redis_mock)):
                result = await documents.get_progress(doc_id=10, user=user, db=db)
        assert result["data"]["progress"] == 60
        assert result["data"]["status"] == "embedding"

    @pytest.mark.asyncio
    async def test_get_progress_no_cache_returns_status_map(self, user, db):
        """Redis 无缓存 → 根据 doc.status 返回估算进度"""
        doc = _make_doc(doc_id=10, status="done")
        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            with patch("app.redis_client.get_redis", new=AsyncMock(return_value=None)):
                result = await documents.get_progress(doc_id=10, user=user, db=db)
        assert result["data"]["progress"] == 100
        assert result["data"]["status"] == "done"

    @pytest.mark.asyncio
    async def test_get_progress_pending_status(self, user, db):
        doc = _make_doc(doc_id=10, status="pending")
        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            with patch("app.redis_client.get_redis", new=AsyncMock(return_value=None)):
                result = await documents.get_progress(doc_id=10, user=user, db=db)
        assert result["data"]["progress"] == 0

    @pytest.mark.asyncio
    async def test_get_progress_failed_status(self, user, db):
        doc = _make_doc(doc_id=10, status="failed", error_message="parse error")
        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            with patch("app.redis_client.get_redis", new=AsyncMock(return_value=None)):
                result = await documents.get_progress(doc_id=10, user=user, db=db)
        assert result["data"]["progress"] == 100
        assert result["data"]["error_message"] == "parse error"


class TestDeleteDocument:
    @pytest.mark.asyncio
    async def test_delete_document_calls_service(self, user, db):
        doc = _make_doc(doc_id=10, status="done")
        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)), \
             patch("app.services.document_service.delete_document", new=AsyncMock()) as mock_del:
            result = await documents.delete_document(doc_id=10, user=user, db=db)
        mock_del.assert_awaited_once_with(10, 1, db)
        assert "message" in result


class TestReparseDocument:
    @pytest.mark.asyncio
    async def test_reparse_done_status_allowed(self, user, db):
        """status=done → 允许 reparse"""
        doc = _make_doc(doc_id=10, status="done")
        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            with patch("app.tasks.document_task.parse_document_task") as mock_task:
                mock_task.delay.return_value = MagicMock(id="task-123")
                result = await documents.reparse_document(doc_id=10, user=user, db=db)
        assert doc.status == "parsing"
        assert result["data"]["task_id"] == "task-123"

    @pytest.mark.asyncio
    async def test_reparse_failed_status_allowed(self, user, db):
        doc = _make_doc(doc_id=10, status="failed")
        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            with patch("app.tasks.document_task.parse_document_task"):
                await documents.reparse_document(doc_id=10, user=user, db=db)
        assert doc.status == "parsing"

    @pytest.mark.asyncio
    async def test_reparse_parsing_status_rejected(self, user, db):
        doc = _make_doc(doc_id=10, status="parsing")
        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            with pytest.raises(ConflictError):
                await documents.reparse_document(doc_id=10, user=user, db=db)

    @pytest.mark.asyncio
    async def test_reparse_chunking_status_rejected(self, user, db):
        doc = _make_doc(doc_id=10, status="chunking")
        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            with pytest.raises(ConflictError):
                await documents.reparse_document(doc_id=10, user=user, db=db)

    @pytest.mark.asyncio
    async def test_reparse_embedding_status_rejected(self, user, db):
        doc = _make_doc(doc_id=10, status="embedding")
        with patch("app.services.document_service.get_document", new=AsyncMock(return_value=doc)):
            with pytest.raises(ConflictError):
                await documents.reparse_document(doc_id=10, user=user, db=db)


class TestUploadDocument:
    """upload_document 有 @limiter.limit 装饰器，需要真实 Request"""

    @pytest.mark.asyncio
    async def test_upload_doc_limit_exceeded(self, user, db, request_mock):
        """文档数超限 → AppException（在文件名校验之前，所以不需要 file）"""
        file = MagicMock(spec=UploadFile)
        file.filename = "doc.md"

        with patch("app.services.kb_service.get_kb", new=AsyncMock()):
            db.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: 100))
            with patch("app.config.settings") as mock_settings:
                mock_settings.MAX_DOCUMENTS_PER_KB = 100
                with pytest.raises(AppException) as exc_info:
                    await documents.upload_document(
                        request=request_mock, file=file, kb_id=1, user=user, db=db
                    )
        assert exc_info.value.code == ErrorCode.DOC_LIMIT_EXCEEDED

    @pytest.mark.asyncio
    async def test_upload_invalid_filename_rejected(self, user, db, request_mock):
        """filename 包含 '..' → ValidationError"""
        file = MagicMock(spec=UploadFile)
        file.filename = "doc..md"

        with patch("app.services.kb_service.get_kb", new=AsyncMock()):
            db.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: 0))
            with patch("app.config.settings") as mock_settings:
                mock_settings.MAX_DOCUMENTS_PER_KB = 100
                with pytest.raises(ValidationError):
                    await documents.upload_document(
                        request=request_mock, file=file, kb_id=1, user=user, db=db
                    )

    @pytest.mark.asyncio
    async def test_upload_unsupported_extension_rejected(self, user, db, request_mock):
        """不在 ALLOWED_EXT 中 → AppException(UNSUPPORTED_FILE_TYPE)"""
        file = MagicMock(spec=UploadFile)
        file.filename = "doc.exe"

        with patch("app.services.kb_service.get_kb", new=AsyncMock()):
            db.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: 0))
            with patch("app.config.settings") as mock_settings:
                mock_settings.MAX_DOCUMENTS_PER_KB = 100
                with patch("app.api.v1.documents.ALLOWED_EXT", [".md", ".txt"]):
                    with pytest.raises(AppException) as exc_info:
                        await documents.upload_document(
                            request=request_mock, file=file, kb_id=1, user=user, db=db
                        )
        assert exc_info.value.code == ErrorCode.UNSUPPORTED_FILE_TYPE

    @pytest.mark.asyncio
    async def test_upload_successful_path(self, user, db, request_mock):
        """完整成功的上传路径：valid file + hash 不重复 + task.delay"""
        file = MagicMock(spec=UploadFile)
        file.filename = "newdoc.md"

        # 模拟 db 操作
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one=lambda: 0,            # 当前 doc count
            scalar_one_or_none=lambda: None,  # hash 不重复
        ))
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()

        with patch("app.services.kb_service.get_kb", new=AsyncMock()):
            with patch("app.config.settings") as mock_settings:
                mock_settings.MAX_DOCUMENTS_PER_KB = 100
                mock_settings.MAX_FILE_SIZE_MB = 50
                with patch("app.api.v1.documents.ALLOWED_EXT", [".md"]):
                    with patch("app.api.v1.documents.save_upload_file",
                               return_value=("/tmp/newdoc.md", "md", 100, "hash123")):
                        with patch("app.tasks.document_task.parse_document_task") as mock_task:
                            mock_task.delay.return_value = MagicMock(id="task-1")
                            result = await documents.upload_document(
                                request=request_mock, file=file, kb_id=1, user=user, db=db
                            )
        assert result["data"]["status"] == "pending"
        assert result["data"]["task_id"] == "task-1"

    @pytest.mark.asyncio
    async def test_upload_duplicate_hash_raises_conflict(self, user, db, request_mock):
        """hash 重复 → ConflictError"""
        file = MagicMock(spec=UploadFile)
        file.filename = "dup.md"

        existing_doc = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one=lambda: 0,
            scalar_one_or_none=lambda: existing_doc,  # 已存在
        ))
        db.commit = AsyncMock()
        db.delete = AsyncMock()

        with patch("app.services.kb_service.get_kb", new=AsyncMock()):
            with patch("app.config.settings") as mock_settings:
                mock_settings.MAX_DOCUMENTS_PER_KB = 100
                with patch("app.api.v1.documents.ALLOWED_EXT", [".md"]):
                    with patch("app.api.v1.documents.save_upload_file",
                               return_value=("/tmp/dup.md", "md", 100, "hash456")):
                        with patch("app.api.v1.documents.delete_file") as mock_del_file:
                            with pytest.raises(ConflictError):
                                await documents.upload_document(
                                    request=request_mock, file=file, kb_id=1,
                                    user=user, db=db
                                )
        # 重复时应删除已保存的文件
        mock_del_file.assert_called_once_with("/tmp/dup.md")

    @pytest.mark.asyncio
    async def test_upload_save_raises_value_error_too_large(self, user, db, request_mock):
        """save_upload_file 抛 ValueError 'too large' → AppException(FILE_TOO_LARGE)"""
        file = MagicMock(spec=UploadFile)
        file.filename = "big.md"

        db.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: 0))
        db.commit = AsyncMock()
        db.delete = AsyncMock()

        with patch("app.services.kb_service.get_kb", new=AsyncMock()):
            with patch("app.config.settings") as mock_settings:
                mock_settings.MAX_DOCUMENTS_PER_KB = 100
                mock_settings.MAX_FILE_SIZE_MB = 50
                with patch("app.api.v1.documents.ALLOWED_EXT", [".md"]):
                    with patch("app.api.v1.documents.save_upload_file",
                               side_effect=ValueError("File too large")):
                        with pytest.raises(AppException) as exc_info:
                            await documents.upload_document(
                                request=request_mock, file=file, kb_id=1,
                                user=user, db=db
                            )
        assert exc_info.value.code == ErrorCode.FILE_TOO_LARGE

    @pytest.mark.asyncio
    async def test_upload_save_raises_value_error_unsupported(self, user, db, request_mock):
        """save_upload_file 抛 ValueError 'Unsupported' → AppException(UNSUPPORTED_FILE_TYPE)"""
        file = MagicMock(spec=UploadFile)
        file.filename = "weird.md"

        db.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: 0))
        db.commit = AsyncMock()
        db.delete = AsyncMock()

        with patch("app.services.kb_service.get_kb", new=AsyncMock()):
            with patch("app.config.settings") as mock_settings:
                mock_settings.MAX_DOCUMENTS_PER_KB = 100
                with patch("app.api.v1.documents.ALLOWED_EXT", [".md"]):
                    with patch("app.api.v1.documents.save_upload_file",
                               side_effect=ValueError("Unsupported magic")):
                        with pytest.raises(AppException) as exc_info:
                            await documents.upload_document(
                                request=request_mock, file=file, kb_id=1,
                                user=user, db=db
                            )
        assert exc_info.value.code == ErrorCode.UNSUPPORTED_FILE_TYPE

    @pytest.mark.asyncio
    async def test_upload_save_raises_other_value_error(self, user, db, request_mock):
        """save_upload_file 抛其他 ValueError → ValidationError"""
        file = MagicMock(spec=UploadFile)
        file.filename = "doc.md"

        db.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: 0))
        db.commit = AsyncMock()
        db.delete = AsyncMock()

        with patch("app.services.kb_service.get_kb", new=AsyncMock()):
            with patch("app.config.settings") as mock_settings:
                mock_settings.MAX_DOCUMENTS_PER_KB = 100
                with patch("app.api.v1.documents.ALLOWED_EXT", [".md"]):
                    with patch("app.api.v1.documents.save_upload_file",
                               side_effect=ValueError("some other reason")):
                        with pytest.raises(ValidationError):
                            await documents.upload_document(
                                request=request_mock, file=file, kb_id=1,
                                user=user, db=db
                            )

    @pytest.mark.asyncio
    async def test_upload_save_raises_unexpected_exception(self, user, db, request_mock):
        """save_upload_file 抛非 ValueError 异常 → AppException(INTERNAL_ERROR)"""
        file = MagicMock(spec=UploadFile)
        file.filename = "doc.md"

        db.execute = AsyncMock(return_value=MagicMock(scalar_one=lambda: 0))
        db.commit = AsyncMock()
        db.delete = AsyncMock()

        with patch("app.services.kb_service.get_kb", new=AsyncMock()):
            with patch("app.config.settings") as mock_settings:
                mock_settings.MAX_DOCUMENTS_PER_KB = 100
                with patch("app.api.v1.documents.ALLOWED_EXT", [".md"]):
                    with patch("app.api.v1.documents.save_upload_file",
                               side_effect=RuntimeError("disk full")):
                        with pytest.raises(AppException) as exc_info:
                            await documents.upload_document(
                                request=request_mock, file=file, kb_id=1,
                                user=user, db=db
                            )
        assert exc_info.value.code == ErrorCode.INTERNAL_ERROR
