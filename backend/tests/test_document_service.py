"""Tests for app.services.document_service.upload_document (Task 13).

覆盖完整上传流程的业务路径：
  - 正常路径（KB 权限 + 数量 + 文件名 + 扩展名 + hash + Celery delay）
  - KB 权限不足
  - 文档数量超限
  - 无效文件名（路径穿越 / 空名）
  - 不支持的扩展名
  - IntegrityError（临时 hash 冲突）
  - hash 重复（save_upload_file 后发现 existing）
  - save_upload_file ValueError（文件过大）
  - save_upload_file ValueError（不支持的类型）
  - 其他异常 → INTERNAL_ERROR
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import AppException, ConflictError, ValidationError
from app.services import document_service


def _make_user(user_id=1):
    u = MagicMock()
    u.id = user_id
    return u


def _make_file(filename="test.md"):
    f = MagicMock()
    f.filename = filename
    return f


def _make_db(doc_count=0, existing_doc=None, commit_side_effect=None):
    """构造 mock db：count 查询返回 doc_count，existing 查询返回 existing_doc。"""
    db = AsyncMock()
    # count_result.scalar_one() → doc_count
    count_result = MagicMock()
    count_result.scalar_one.return_value = doc_count
    # existing_result.scalar_one_or_none() → existing_doc (or None)
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = existing_doc
    db.execute = AsyncMock(side_effect=[count_result, existing_result])
    if commit_side_effect:
        db.commit = AsyncMock(side_effect=commit_side_effect)
    # db.refresh 默认设置 doc.id
    async def fake_refresh(obj, *args, **kwargs):
        obj.id = 99
    db.refresh = AsyncMock(side_effect=fake_refresh)
    return db


@pytest.fixture
def patch_save_upload_file():
    """patch save_upload_file 返回 (path, type, size, hash)。"""
    with patch("app.services.document_service.save_upload_file",
               return_value=("/tmp/test.md", "md", 100, "abc123")) as m:
        yield m


@pytest.fixture
def patch_delete_file():
    with patch("app.services.document_service.delete_file") as m:
        yield m


@pytest.fixture
def patch_parse_task():
    """patch Celery parse_document_task.delay 返回 mock task。"""
    fake_task = MagicMock()
    fake_task.id = "task-uuid"
    with patch("app.tasks.document_task.parse_document_task.delay",
               return_value=fake_task) as m:
        yield m


class TestUploadDocumentNormal:
    @pytest.mark.asyncio
    async def test_normal_upload_returns_doc_and_task(
        self, patch_save_upload_file, patch_parse_task
    ):
        """正常路径：返回 (doc, task)，doc 元数据被正确更新。"""
        from app.services import document_service

        user = _make_user()
        file = _make_file("test.md")
        db = _make_db(doc_count=0, existing_doc=None)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            doc, task = await document_service.upload_document(file, 1, user, db)

        assert doc.id == 99
        assert doc.file_path == "/tmp/test.md"
        assert doc.file_type == "md"
        assert doc.file_size == 100
        assert doc.file_hash == "abc123"
        assert doc.status == "pending"
        assert task.id == "task-uuid"
        patch_parse_task.assert_called_once_with(99)


class TestUploadDocumentPermission:
    @pytest.mark.asyncio
    async def test_kb_permission_failure_propagates(self):
        """KB 权限不足时应抛出原异常，不继续后续逻辑。"""
        from app.services import document_service

        user = _make_user()
        file = _make_file("test.md")
        db = _make_db()

        with patch("app.services.kb_service.get_kb_for_write",
                   new=AsyncMock(side_effect=PermissionError("forbidden"))):
            with pytest.raises(PermissionError):
                await document_service.upload_document(file, 1, user, db)


class TestUploadDocumentCountLimit:
    @pytest.mark.asyncio
    async def test_doc_count_exceeded_raises_app_exception(self):
        """文档数量超限时抛出 AppException(DOC_LIMIT_EXCEEDED)。"""
        from app.services import document_service

        user = _make_user()
        file = _make_file("test.md")
        # doc_count = MAX_DOCUMENTS_PER_KB (默认 100)
        from app.config import settings
        db = _make_db(doc_count=settings.MAX_DOCUMENTS_PER_KB)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(AppException) as exc_info:
                await document_service.upload_document(file, 1, user, db)

        assert exc_info.value.status_code == 400


class TestUploadDocumentFilename:
    @pytest.mark.asyncio
    async def test_empty_filename_raises_validation_error(self):
        """空文件名应抛出 ValidationError。"""
        from app.services import document_service

        user = _make_user()
        file = _make_file(filename="")
        db = _make_db(doc_count=0)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(ValidationError):
                await document_service.upload_document(file, 1, user, db)

    @pytest.mark.asyncio
    async def test_path_traversal_filename_raises_validation_error(self):
        """含 '..' 的文件名（basename 后仍保留 '..'）应抛出 ValidationError。"""
        from app.services import document_service

        user = _make_user()
        # os.path.basename("..hidden") = "..hidden"（仍含 ".."），触发 ValidationError
        file = _make_file(filename="..hidden")
        db = _make_db(doc_count=0)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(ValidationError):
                await document_service.upload_document(file, 1, user, db)


class TestUploadDocumentExt:
    @pytest.mark.asyncio
    async def test_unsupported_extension_raises_app_exception(self):
        """不支持的扩展名应抛出 AppException(UNSUPPORTED_FILE_TYPE)。"""
        from app.services import document_service

        user = _make_user()
        file = _make_file("test.exe")  # .exe 不在 ALLOWED_EXT
        db = _make_db(doc_count=0)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(AppException) as exc_info:
                await document_service.upload_document(file, 1, user, db)

        assert exc_info.value.status_code == 400


class TestUploadDocumentIntegrityError:
    @pytest.mark.asyncio
    async def test_temp_hash_integrity_error_raises_internal_error(self):
        """第一次 commit 抛 IntegrityError 时应抛出 AppException(INTERNAL_ERROR)。"""
        from sqlalchemy.exc import IntegrityError as SAIntegrityError

        from app.services import document_service

        user = _make_user()
        file = _make_file("test.md")
        # 第一次 commit 抛 IntegrityError
        db = _make_db(
            doc_count=0,
            existing_doc=None,
            commit_side_effect=[SAIntegrityError("stmt", "params", Exception("orig")), None],
        )

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(AppException) as exc_info:
                await document_service.upload_document(file, 1, user, db)

        assert exc_info.value.status_code == 500


class TestUploadDocumentHashConflict:
    @pytest.mark.asyncio
    async def test_existing_hash_conflict_raises_conflict_error(
        self, patch_save_upload_file, patch_delete_file
    ):
        """save_upload_file 后发现 existing doc 应抛出 ConflictError 并清理。"""
        from app.services import document_service

        user = _make_user()
        file = _make_file("test.md")
        existing_doc = MagicMock()
        existing_doc.id = 50
        db = _make_db(doc_count=0, existing_doc=existing_doc)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(ConflictError):
                await document_service.upload_document(file, 1, user, db)

        # 应该删除已保存的文件
        patch_delete_file.assert_called_once_with("/tmp/test.md")


class TestUploadDocumentSaveFileError:
    @pytest.mark.asyncio
    async def test_save_upload_file_too_large_raises_file_too_large(self, patch_delete_file):
        """save_upload_file ValueError 含 'too large' 应抛出 AppException(FILE_TOO_LARGE)。"""
        from app.services import document_service

        user = _make_user()
        file = _make_file("test.md")
        db = _make_db(doc_count=0, existing_doc=None)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()), \
             patch("app.services.document_service.save_upload_file",
                   side_effect=ValueError("File too large: 100MB > 20MB")):
            with pytest.raises(AppException) as exc_info:
                await document_service.upload_document(file, 1, user, db)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_save_upload_file_unsupported_type_raises_app_exception(self, patch_delete_file):
        """save_upload_file ValueError 含 'Unsupported' 应抛出 AppException(UNSUPPORTED_FILE_TYPE)。"""
        from app.services import document_service

        user = _make_user()
        file = _make_file("test.md")
        db = _make_db(doc_count=0, existing_doc=None)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()), \
             patch("app.services.document_service.save_upload_file",
                   side_effect=ValueError("Unsupported file type (magic mismatch)")):
            with pytest.raises(AppException) as exc_info:
                await document_service.upload_document(file, 1, user, db)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_save_upload_file_generic_error_raises_internal_error(self, patch_delete_file):
        """save_upload_file 其他异常应抛出 AppException(INTERNAL_ERROR)。"""
        from app.services import document_service

        user = _make_user()
        file = _make_file("test.md")
        db = _make_db(doc_count=0, existing_doc=None)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()), \
             patch("app.services.document_service.save_upload_file",
                   side_effect=RuntimeError("disk full")):
            with pytest.raises(AppException) as exc_info:
                await document_service.upload_document(file, 1, user, db)

        assert exc_info.value.status_code == 500
