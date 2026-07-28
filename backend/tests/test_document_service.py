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

扩展覆盖 (T11):
  - _on_kb_deleted / register_event_handlers
  - create_document_record
  - upload_document Celery 派发失败分支
  - _save_file_and_verify_hash IntegrityError on second commit / ValidationError fallback
  - list_documents / get_document / get_document_for_write / update_document
  - delete_document (含 qdrant/bm25/file 清理分支)
  - reparse_document (并发 / rowcount=0 / 正常)
  - get_progress (缓存命中 / 未命中 / 读取失败)
  - preview_document (无 parser / 解析失败 / 正常分页)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AppException, ConflictError, NotFoundError, ValidationError
from app.services import document_service


def _make_file(filename="test.md"):
    f = MagicMock()
    f.filename = filename
    return f


@pytest.fixture
def patch_save_upload_file():
    """patch save_upload_file 返回 (path, type, size, hash)。"""
    with patch(
        "app.services.document_service.save_upload_file",
        return_value=("/tmp/test.md", "md", 100, "abc123"),
    ) as m:
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
    with patch("app.tasks.document_task.parse_document_task.delay", return_value=fake_task) as m:
        yield m


class TestUploadDocumentNormal:
    @pytest.mark.asyncio
    async def test_normal_upload_returns_doc_and_task(
        self, make_user, make_db, patch_save_upload_file, patch_parse_task
    ):
        """正常路径：返回 (doc, task)，doc 元数据被正确更新。"""

        user = make_user()
        file = _make_file("test.md")
        db = make_db(doc_count=0, existing_doc=None)

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
    async def test_kb_permission_failure_propagates(self, make_user, make_db):
        """KB 权限不足时应抛出原异常，不继续后续逻辑。"""

        user = make_user()
        file = _make_file("test.md")
        db = make_db()

        with patch(
            "app.services.kb_service.get_kb_for_write",
            new=AsyncMock(side_effect=PermissionError("forbidden")),
        ):
            with pytest.raises(PermissionError):
                await document_service.upload_document(file, 1, user, db)


class TestUploadDocumentCountLimit:
    @pytest.mark.asyncio
    async def test_doc_count_exceeded_raises_app_exception(self, make_user, make_db):
        """文档数量超限时抛出 AppException(DOC_LIMIT_EXCEEDED)。"""

        user = make_user()
        file = _make_file("test.md")
        # doc_count = MAX_DOCUMENTS_PER_KB (默认 100)
        from app.config import settings

        db = make_db(doc_count=settings.MAX_DOCUMENTS_PER_KB)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(AppException) as exc_info:
                await document_service.upload_document(file, 1, user, db)

        assert exc_info.value.status_code == 400


class TestUploadDocumentFilename:
    @pytest.mark.asyncio
    async def test_empty_filename_raises_validation_error(self, make_user, make_db):
        """空文件名应抛出 ValidationError。"""

        user = make_user()
        file = _make_file(filename="")
        db = make_db(doc_count=0)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(ValidationError):
                await document_service.upload_document(file, 1, user, db)

    @pytest.mark.asyncio
    async def test_path_traversal_filename_raises_validation_error(self, make_user, make_db):
        """含 '..' 的文件名（basename 后仍保留 '..'）应抛出 ValidationError。"""

        user = make_user()
        # os.path.basename("..hidden") = "..hidden"（仍含 ".."），触发 ValidationError
        file = _make_file(filename="..hidden")
        db = make_db(doc_count=0)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(ValidationError):
                await document_service.upload_document(file, 1, user, db)


class TestUploadDocumentExt:
    @pytest.mark.asyncio
    async def test_unsupported_extension_raises_app_exception(self, make_user, make_db):
        """不支持的扩展名应抛出 AppException(UNSUPPORTED_FILE_TYPE)。"""

        user = make_user()
        file = _make_file("test.exe")  # .exe 不在 ALLOWED_EXT
        db = make_db(doc_count=0)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(AppException) as exc_info:
                await document_service.upload_document(file, 1, user, db)

        assert exc_info.value.status_code == 400


class TestUploadDocumentIntegrityError:
    @pytest.mark.asyncio
    async def test_temp_hash_integrity_error_raises_internal_error(self, make_user, make_db):
        """第一次 commit 抛 IntegrityError 时应抛出 AppException(INTERNAL_ERROR)。"""
        from sqlalchemy.exc import IntegrityError as SAIntegrityError

        user = make_user()
        file = _make_file("test.md")
        # 第一次 commit 抛 IntegrityError
        db = make_db(
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
        self, make_user, make_db, patch_save_upload_file, patch_delete_file
    ):
        """save_upload_file 后发现 existing doc 应抛出 ConflictError 并清理。"""

        user = make_user()
        file = _make_file("test.md")
        existing_doc = MagicMock()
        existing_doc.id = 50
        db = make_db(doc_count=0, existing_doc=existing_doc)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(ConflictError):
                await document_service.upload_document(file, 1, user, db)

        # 应该删除已保存的文件
        patch_delete_file.assert_called_once_with("/tmp/test.md")


class TestUploadDocumentSaveFileError:
    @pytest.mark.asyncio
    async def test_save_upload_file_too_large_raises_file_too_large(
        self, make_user, make_db, patch_delete_file
    ):
        """save_upload_file ValueError 含 'too large' 应抛出 AppException(FILE_TOO_LARGE)。"""

        user = make_user()
        file = _make_file("test.md")
        db = make_db(doc_count=0, existing_doc=None)

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.services.document_service.save_upload_file",
                side_effect=ValueError("File too large: 100MB > 20MB"),
            ),
        ):
            with pytest.raises(AppException) as exc_info:
                await document_service.upload_document(file, 1, user, db)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_save_upload_file_unsupported_type_raises_app_exception(
        self, make_user, make_db, patch_delete_file
    ):
        """save_upload_file ValueError 含 'Unsupported' 应抛出 AppException(UNSUPPORTED_FILE_TYPE)。"""

        user = make_user()
        file = _make_file("test.md")
        db = make_db(doc_count=0, existing_doc=None)

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.services.document_service.save_upload_file",
                side_effect=ValueError("Unsupported file type (magic mismatch)"),
            ),
        ):
            with pytest.raises(AppException) as exc_info:
                await document_service.upload_document(file, 1, user, db)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_save_upload_file_generic_error_raises_internal_error(
        self, make_user, make_db, patch_delete_file
    ):
        """save_upload_file 其他异常应抛出 AppException(INTERNAL_ERROR)。"""

        user = make_user()
        file = _make_file("test.md")
        db = make_db(doc_count=0, existing_doc=None)

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.services.document_service.save_upload_file",
                side_effect=RuntimeError("disk full"),
            ),
        ):
            with pytest.raises(AppException) as exc_info:
                await document_service.upload_document(file, 1, user, db)

        assert exc_info.value.status_code == 500


# ============================================================
# T11 扩展测试：覆盖 _on_kb_deleted / register_event_handlers /
# create_document_record / list_documents / get_document /
# get_document_for_write / update_document / delete_document /
# reparse_document / get_progress / preview_document /
# upload_document Celery 派发失败 / _save_file_and_verify_hash 边界
# ============================================================


# ---------- _on_kb_deleted ----------


class TestOnKbDeleted:
    @pytest.mark.asyncio
    async def test_no_kb_id_returns_early(self):
        """payload 无 kb_id 时直接返回，不触发任何外部清理。"""
        with (
            patch("app.rag.retriever.retriever") as mock_retriever,
            patch("app.rag.bm25.bm25_store") as mock_bm25,
        ):
            await document_service._on_kb_deleted({})

        mock_retriever.delete_collection.assert_not_called()
        mock_bm25.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_kb_id_none_returns_early(self):
        with (
            patch("app.rag.retriever.retriever") as mock_retriever,
            patch("app.rag.bm25.bm25_store") as mock_bm25,
        ):
            await document_service._on_kb_deleted({"kb_id": None})

        mock_retriever.delete_collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_cleanups_succeed(self):
        """所有清理成功执行（best-effort）。"""
        fake_retriever = MagicMock()
        fake_bm25 = AsyncMock()
        fake_storage = MagicMock()

        with (
            patch("app.rag.retriever.retriever", fake_retriever),
            patch("app.rag.bm25.bm25_store", fake_bm25),
            patch("app.utils.storage.delete_kb_dir", fake_storage.delete_kb_dir),
        ):
            await document_service._on_kb_deleted({"kb_id": 7})

        # asyncio.to_thread 调用 retriever.delete_collection
        fake_retriever.delete_collection.assert_called_once_with(7)
        fake_bm25.delete.assert_awaited_once_with(7)
        fake_storage.delete_kb_dir.assert_called_once_with(7)

    @pytest.mark.asyncio
    async def test_qdrant_failure_does_not_block_others(self):
        """Qdrant 删除失败不阻塞 BM25 / 存储清理。"""
        fake_retriever = MagicMock()
        fake_retriever.delete_collection.side_effect = RuntimeError("qdrant down")
        fake_bm25 = AsyncMock()

        with (
            patch("app.rag.retriever.retriever", fake_retriever),
            patch("app.rag.bm25.bm25_store", fake_bm25),
            patch("app.utils.storage.delete_kb_dir") as mock_delete_dir,
        ):
            await document_service._on_kb_deleted({"kb_id": 7})

        fake_bm25.delete.assert_awaited_once_with(7)
        mock_delete_dir.assert_called_once_with(7)

    @pytest.mark.asyncio
    async def test_bm25_failure_does_not_block_storage(self):
        fake_retriever = MagicMock()
        fake_bm25 = AsyncMock()
        fake_bm25.delete.side_effect = RuntimeError("redis down")

        with (
            patch("app.rag.retriever.retriever", fake_retriever),
            patch("app.rag.bm25.bm25_store", fake_bm25),
            patch("app.utils.storage.delete_kb_dir") as mock_delete_dir,
        ):
            await document_service._on_kb_deleted({"kb_id": 7})

        fake_retriever.delete_collection.assert_called_once_with(7)
        mock_delete_dir.assert_called_once_with(7)

    @pytest.mark.asyncio
    async def test_storage_failure_swallowed(self):
        fake_retriever = MagicMock()
        fake_bm25 = AsyncMock()

        with (
            patch("app.rag.retriever.retriever", fake_retriever),
            patch("app.rag.bm25.bm25_store", fake_bm25),
            patch("app.utils.storage.delete_kb_dir", side_effect=OSError("disk error")),
        ):
            # 不应抛出异常
            await document_service._on_kb_deleted({"kb_id": 7})

        fake_retriever.delete_collection.assert_called_once_with(7)
        fake_bm25.delete.assert_awaited_once_with(7)


# ---------- register_event_handlers ----------


class TestRegisterEventHandlers:
    def test_registers_kb_deleted_handler(self):
        """注册 KB_DELETED 事件订阅者。"""
        with patch.object(
            document_service.EventBus, "subscribe_sync"
        ) as mock_subscribe:
            document_service.register_event_handlers()

        mock_subscribe.assert_called_once()
        args = mock_subscribe.call_args.args
        assert args[0] == document_service.EventBus.KB_DELETED
        assert args[1] == document_service._on_kb_deleted


# ---------- create_document_record ----------


class TestCreateDocumentRecord:
    @pytest.mark.asyncio
    async def test_normal_creates_and_commits(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        doc = await document_service.create_document_record(
            kb_id=1,
            user_id=2,
            filename="test.md",
            file_path="/tmp/test.md",
            file_type="md",
            file_size=100,
            db=db,
        )

        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(doc)
        assert doc.kb_id == 1
        assert doc.uploader_id == 2
        assert doc.filename == "test.md"
        assert doc.file_path == "/tmp/test.md"
        assert doc.file_type == "md"
        assert doc.file_size == 100
        assert doc.status == "pending"
        assert doc.chunk_count == 0


# ---------- upload_document: Celery 派发失败 ----------


class TestUploadDocumentCeleryDispatchFailure:
    @pytest.mark.asyncio
    async def test_celery_dispatch_failure_marks_doc_failed_and_reraises(
        self, make_user, make_db, patch_save_upload_file
    ):
        """Celery 派发失败：doc 标记为 failed，commit 成功后重新抛出原异常。"""
        user = make_user()
        file = _make_file("test.md")
        # commit_side_effect: 第一次（创建 doc）成功；后续 commit 不抛异常
        db = make_db(doc_count=0, existing_doc=None)

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.tasks.document_task.parse_document_task.delay",
                side_effect=RuntimeError("celery down"),
            ),
            patch(
                "app.db.knowledge_base.KnowledgeBase"
            ),  # 防止 KB doc_count+1 触发实际查询
        ):
            with pytest.raises(RuntimeError, match="celery down"):
                await document_service.upload_document(file, 1, user, db)

    @pytest.mark.asyncio
    async def test_celery_dispatch_failure_with_commit_error_rolls_back(
        self, make_user, make_db, patch_save_upload_file
    ):
        """Celery 派发失败且 commit 也失败时执行 rollback，仍重新抛出原异常。"""
        user = make_user()
        file = _make_file("test.md")
        # commit_side_effect:
        # 1) _create_doc_record commit 成功
        # 2) _save_file_and_verify_hash 第一次 commit 成功
        # 3) Celery 失败后 commit (标记 failed) 抛错 -> rollback
        db = make_db(
            doc_count=0,
            existing_doc=None,
            commit_side_effect=[None, None, RuntimeError("commit failed")],
        )

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.tasks.document_task.parse_document_task.delay",
                side_effect=RuntimeError("celery down"),
            ),
            patch("app.db.knowledge_base.KnowledgeBase"),
        ):
            with pytest.raises(RuntimeError, match="celery down"):
                await document_service.upload_document(file, 1, user, db)

        db.rollback.assert_awaited()


# ---------- _save_file_and_verify_hash: IntegrityError on second commit ----------


class TestSaveFileHashIntegrityErrorOnCommit:
    @pytest.mark.asyncio
    async def test_second_commit_integrity_error_raises_conflict(
        self, make_user, make_db, patch_delete_file
    ):
        """第二次 commit 抛 IntegrityError 时应清理文件并抛 ConflictError。"""
        from sqlalchemy.exc import IntegrityError as SAIntegrityError

        user = make_user()
        file = _make_file("test.md")
        # commit_side_effect:
        # 1) _create_doc_record commit 成功
        # 2) _save_file_and_verify_hash 第二次 commit 抛 IntegrityError
        # 3) IntegrityError 处理分支中的清理 commit (delete doc) 成功
        db = make_db(
            doc_count=0,
            existing_doc=None,
            commit_side_effect=[
                None,
                SAIntegrityError("stmt", "params", Exception("orig")),
                None,
            ],
        )

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.services.document_service.save_upload_file",
                return_value=("/tmp/test.md", "md", 100, "abc123"),
            ),
        ):
            with pytest.raises(ConflictError):
                await document_service.upload_document(file, 1, user, db)

        patch_delete_file.assert_called_once_with("/tmp/test.md")


# ---------- _save_file_and_verify_hash: ValueError fallback to ValidationError ----------


class TestSaveFileValueErrorFallback:
    @pytest.mark.asyncio
    async def test_value_error_unmatched_message_raises_validation_error(
        self, make_user, make_db, patch_delete_file
    ):
        """ValueError 不匹配 too large / Unsupported 时回退到 ValidationError。"""
        user = make_user()
        file = _make_file("test.md")
        db = make_db(doc_count=0, existing_doc=None)

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.services.document_service.save_upload_file",
                side_effect=ValueError("some other validation error"),
            ),
        ):
            with pytest.raises(ValidationError):
                await document_service.upload_document(file, 1, user, db)


# ---------- list_documents ----------


class TestListDocuments:
    @pytest.mark.asyncio
    async def test_list_without_kb_filter(self):
        """无 kb_id 过滤：单次 execute + scalar 调用。"""
        docs = [MagicMock(id=1), MagicMock(id=2)]
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = docs
        db.execute = AsyncMock(return_value=result_mock)
        db.scalar = AsyncMock(return_value=2)

        docs_ret, total = await document_service.list_documents(user_id=1, db=db)

        assert docs_ret == docs
        assert total == 2

    @pytest.mark.asyncio
    async def test_list_with_kb_filter(self):
        """有 kb_id 过滤：先 kb_service.get_kb_for_read 校验，再过滤查询。"""
        docs = [MagicMock(id=1)]
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = docs
        db.execute = AsyncMock(return_value=result_mock)
        db.scalar = AsyncMock(return_value=1)

        with patch(
            "app.services.kb_service.get_kb_for_read", new=AsyncMock()
        ) as mock_read:
            docs_ret, total = await document_service.list_documents(
                user_id=1, db=db, kb_id=5
            )

        mock_read.assert_awaited_once_with(5, 1, db)
        assert docs_ret == docs
        assert total == 1

    @pytest.mark.asyncio
    async def test_list_empty_with_none_total(self):
        """db.scalar 返回 None 时 total 应降级为 0。"""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)
        db.scalar = AsyncMock(return_value=None)

        docs_ret, total = await document_service.list_documents(user_id=1, db=db)

        assert docs_ret == []
        assert total == 0


# ---------- get_document ----------


class TestGetDocument:
    @pytest.mark.asyncio
    async def test_doc_found(self):
        doc = MagicMock(id=10, kb_id=5)
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=result_mock)

        with patch(
            "app.services.kb_service.get_kb_for_read", new=AsyncMock()
        ) as mock_read:
            got = await document_service.get_document(10, 1, db)

        assert got is doc
        mock_read.assert_awaited_once_with(5, 1, db)

    @pytest.mark.asyncio
    async def test_doc_not_found_raises(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(NotFoundError):
            await document_service.get_document(999, 1, db)


# ---------- get_document_for_write ----------


class TestGetDocumentForWrite:
    @pytest.mark.asyncio
    async def test_doc_found(self):
        doc = MagicMock(id=10, kb_id=5)
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=result_mock)

        with patch(
            "app.services.kb_service.get_kb_for_write", new=AsyncMock()
        ) as mock_write:
            got = await document_service.get_document_for_write(10, 1, db)

        assert got is doc
        mock_write.assert_awaited_once_with(5, 1, db)

    @pytest.mark.asyncio
    async def test_doc_not_found_raises(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(NotFoundError):
            await document_service.get_document_for_write(999, 1, db)


# ---------- update_document ----------


class TestUpdateDocument:
    @pytest.mark.asyncio
    async def test_update_title(self):
        doc = MagicMock(id=10, kb_id=5, filename="old.md")
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        req = MagicMock()
        req.title = "new-name.md"

        with patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()):
            ret = await document_service.update_document(10, req, 1, db)

        assert ret is doc
        assert doc.filename == "new-name.md"
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(doc)

    @pytest.mark.asyncio
    async def test_update_with_none_title_keeps_filename(self):
        doc = MagicMock(id=10, kb_id=5, filename="keep.md")
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=result_mock)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        req = MagicMock()
        req.title = None

        with patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()):
            ret = await document_service.update_document(10, req, 1, db)

        assert ret is doc
        assert doc.filename == "keep.md"


# ---------- delete_document ----------


def _make_doc_for_delete(doc_id=10, kb_id=5, chunk_count=3):
    doc = MagicMock()
    doc.id = doc_id
    doc.kb_id = kb_id
    doc.filename = "test.md"
    doc.chunk_count = chunk_count
    return doc


class TestDeleteDocument:
    @pytest.mark.asyncio
    async def test_normal_delete_with_kb_update(self):
        """正常删除：含 KB doc_count/chunk_count 更新与审计日志。"""
        doc = _make_doc_for_delete(doc_id=10, kb_id=5, chunk_count=3)
        db = AsyncMock()
        # get_document_for_write 内 db.execute
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)
        db.commit = AsyncMock()
        db.delete = AsyncMock()

        kb = MagicMock()
        db.get = AsyncMock(return_value=kb)

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.services.document_service.log_audit", new=AsyncMock()
            ) as mock_audit,
            patch("app.rag.retriever.retriever") as mock_retriever,
            patch("app.rag.bm25.bm25_store", new=AsyncMock()) as mock_bm25,
            patch(
                "app.services.document_service.get_kb_dir"
            ) as mock_get_kb_dir,
        ):
            mock_get_kb_dir.return_value.iterdir.return_value = []
            await document_service.delete_document(10, 1, db)

        # 删除 chunks + 软删 doc + KB 更新 + audit 后续清理
        assert db.commit.await_count >= 2
        # KB 应被加载并更新（doc_count / chunk_count）
        db.get.assert_awaited()
        # 审计日志
        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.call_args.kwargs
        assert audit_kwargs["action"] == "DOCUMENT_DELETE"
        assert audit_kwargs["user_id"] == 1
        # Qdrant / BM25 清理
        mock_retriever.delete_by_doc_id.assert_called_once_with(5, 10)
        mock_bm25.remove_document.assert_awaited_once_with(5, 10)

    @pytest.mark.asyncio
    async def test_doc_not_found_raises(self):
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=doc_result)

        with pytest.raises(NotFoundError):
            await document_service.delete_document(999, 1, db)

    @pytest.mark.asyncio
    async def test_qdrant_failure_does_not_break_delete(self):
        """Qdrant 删除失败不阻塞后续清理流程。"""
        doc = _make_doc_for_delete(doc_id=10, kb_id=5, chunk_count=0)
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)
        db.commit = AsyncMock()
        db.get = AsyncMock(return_value=None)  # 无 KB

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch("app.services.document_service.log_audit", new=AsyncMock()),
            patch(
                "app.rag.retriever.retriever"
            ) as mock_retriever_mod,
            patch("app.rag.bm25.bm25_store", new=AsyncMock()) as mock_bm25,
            patch(
                "app.services.document_service.get_kb_dir"
            ) as mock_get_kb_dir,
        ):
            mock_retriever_mod.delete_by_doc_id.side_effect = RuntimeError("qdrant down")
            mock_get_kb_dir.return_value.iterdir.return_value = []
            # 不应抛异常
            await document_service.delete_document(10, 1, db)

        mock_retriever_mod.delete_by_doc_id.assert_called_once_with(5, 10)
        mock_bm25.remove_document.assert_awaited_once_with(5, 10)

    @pytest.mark.asyncio
    async def test_bm25_failure_does_not_break_delete(self):
        """BM25 删除失败不阻塞存储清理。"""
        doc = _make_doc_for_delete(doc_id=10, kb_id=5, chunk_count=0)
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)
        db.commit = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch("app.services.document_service.log_audit", new=AsyncMock()),
            patch("app.rag.retriever.retriever"),
            patch(
                "app.rag.bm25.bm25_store", new=AsyncMock()
            ) as mock_bm25,
            patch(
                "app.services.document_service.get_kb_dir"
            ) as mock_get_kb_dir,
        ):
            mock_bm25.remove_document.side_effect = RuntimeError("redis down")
            mock_get_kb_dir.return_value.iterdir.return_value = []
            await document_service.delete_document(10, 1, db)

        mock_bm25.remove_document.assert_awaited_once_with(5, 10)

    @pytest.mark.asyncio
    async def test_file_delete_with_matching_prefix(self):
        """存储清理：删除匹配 "{doc.id}_" 前缀的文件。"""
        doc = _make_doc_for_delete(doc_id=10, kb_id=5, chunk_count=0)
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)
        db.commit = AsyncMock()
        db.get = AsyncMock(return_value=None)

        # 模拟文件列表：含匹配/不匹配项
        f_match = MagicMock()
        f_match.name = "10_test.md"
        f_other_doc = MagicMock()
        f_other_doc.name = "100_other.md"  # 不应被删（前缀不匹配）
        f_unrelated = MagicMock()
        f_unrelated.name = "summary.md"

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch("app.services.document_service.log_audit", new=AsyncMock()),
            patch("app.rag.retriever.retriever"),
            patch("app.rag.bm25.bm25_store", new=AsyncMock()),
            patch(
                "app.services.document_service.get_kb_dir"
            ) as mock_get_kb_dir,
            patch(
                "app.services.document_service.delete_file"
            ) as mock_delete_file,
        ):
            mock_get_kb_dir.return_value.iterdir.return_value = [
                f_match,
                f_other_doc,
                f_unrelated,
            ]
            await document_service.delete_document(10, 1, db)

        # 只删除 10_test.md
        mock_delete_file.assert_called_once_with(str(f_match))

    @pytest.mark.asyncio
    async def test_file_delete_failure_swallowed(self):
        """存储清理失败不影响删除流程（已 soft-delete）。"""
        doc = _make_doc_for_delete(doc_id=10, kb_id=5, chunk_count=0)
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)
        db.commit = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch("app.services.document_service.log_audit", new=AsyncMock()),
            patch("app.rag.retriever.retriever"),
            patch("app.rag.bm25.bm25_store", new=AsyncMock()),
            patch(
                "app.services.document_service.get_kb_dir",
                side_effect=OSError("storage error"),
            ),
        ):
            # 不应抛出异常
            await document_service.delete_document(10, 1, db)


# ---------- reparse_document ----------


class TestReparseDocument:
    @pytest.mark.asyncio
    async def test_already_parsing_raises_conflict(self):
        doc = MagicMock(id=10, kb_id=5, status="parsing")
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(ConflictError):
                await document_service.reparse_document(10, 1, db)

    @pytest.mark.asyncio
    async def test_chunking_status_raises_conflict(self):
        doc = MagicMock(id=10, kb_id=5, status="chunking")
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(ConflictError):
                await document_service.reparse_document(10, 1, db)

    @pytest.mark.asyncio
    async def test_embedding_status_raises_conflict(self):
        doc = MagicMock(id=10, kb_id=5, status="embedding")
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(ConflictError):
                await document_service.reparse_document(10, 1, db)

    @pytest.mark.asyncio
    async def test_rowcount_zero_raises_conflict(self):
        """乐观锁：UPDATE rowcount=0 表示状态已被并发修改。"""
        doc = MagicMock(id=10, kb_id=5, status="done")
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        update_result = MagicMock()
        update_result.rowcount = 0
        db.execute = AsyncMock(side_effect=[doc_result, update_result])
        db.commit = AsyncMock()

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(ConflictError) as exc_info:
                await document_service.reparse_document(10, 1, db)

        # ConflictError.message 含 "status changed"（AppException 不传 message 到 super().__init__，
        # 因此 str(exc) 为空，需通过 .message 属性验证）
        assert "status changed" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_normal_reparse_with_kb_chunk_count_update(self):
        """正常 reparse：含 KB chunk_count 扣减。"""
        doc = MagicMock(id=10, kb_id=5, status="done", chunk_count=3)
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=[doc_result, update_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        kb = MagicMock()
        db.get = AsyncMock(return_value=kb)

        fake_task = MagicMock()
        fake_task.id = "task-uuid"

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.tasks.document_task.parse_document_task.delay",
                return_value=fake_task,
            ) as mock_delay,
        ):
            ret_doc, ret_task = await document_service.reparse_document(10, 1, db)

        assert ret_doc is doc
        assert ret_task is fake_task
        assert doc.status == "pending"
        assert doc.error_message is None
        mock_delay.assert_called_once_with(10)
        # KB chunk_count 扣减 commit
        db.get.assert_awaited()
        # 至少两次 commit: reparse + KB 更新
        assert db.commit.await_count >= 2

    @pytest.mark.asyncio
    async def test_normal_reparse_without_kb(self):
        """KB 不存在时跳过 chunk_count 扣减。"""
        doc = MagicMock(id=10, kb_id=5, status="done", chunk_count=3)
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=[doc_result, update_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.get = AsyncMock(return_value=None)  # KB 不存在

        fake_task = MagicMock()

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.tasks.document_task.parse_document_task.delay",
                return_value=fake_task,
            ),
        ):
            ret_doc, _ = await document_service.reparse_document(10, 1, db)

        assert ret_doc.status == "pending"

    @pytest.mark.asyncio
    async def test_normal_reparse_with_zero_chunk_count_skips_kb_update(self):
        """doc.chunk_count 为 0 时跳过 KB chunk_count 扣减（不调用第二次 commit）。"""
        doc = MagicMock(id=10, kb_id=5, status="done", chunk_count=0)
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=[doc_result, update_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        # 即使返回 kb，由于 doc.chunk_count=0，if kb and doc.chunk_count 为 False，
        # 不会进入 kb.chunk_count 更新分支
        kb = MagicMock()
        db.get = AsyncMock(return_value=kb)

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.tasks.document_task.parse_document_task.delay",
                return_value=MagicMock(),
            ),
        ):
            await document_service.reparse_document(10, 1, db)

        # db.get 仍会被调用（无条件），但 kb.chunk_count 未被赋值（chunk_count=0 跳过更新）
        # 只有一次 commit（reparse 自身），没有第二次 commit（KB 更新分支未进入）
        assert db.commit.await_count == 1
        # kb.chunk_count 不应被赋值
        assert not hasattr(kb.chunk_count, "_mock_children") or not kb.chunk_count._mock_children

    # ---------- Task 11: force 参数（P1-API-07）----------

    @pytest.mark.asyncio
    async def test_force_skips_parsing_status_check(self):
        """force=True 时 status='parsing' 不再抛 ConflictError，正常执行 reparse。"""
        doc = MagicMock(id=10, kb_id=5, status="parsing", chunk_count=2)
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        update_result = MagicMock()
        update_result.rowcount = 1  # force 分支不检查 rowcount，但提供值以防空引用
        db.execute = AsyncMock(side_effect=[doc_result, update_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.get = AsyncMock(return_value=None)  # KB 不存在，跳过 chunk_count 扣减

        fake_task = MagicMock()
        fake_task.id = "task-force"

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.tasks.document_task.parse_document_task.delay",
                return_value=fake_task,
            ) as mock_delay,
        ):
            ret_doc, ret_task = await document_service.reparse_document(
                10, 1, db, force=True
            )

        assert ret_doc is doc
        assert ret_task is fake_task
        assert doc.status == "pending"
        assert doc.error_message is None
        mock_delay.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_force_skips_chunking_status_check(self):
        """force=True 时 status='chunking' 不再抛 ConflictError。"""
        doc = MagicMock(id=10, kb_id=5, status="chunking", chunk_count=0)
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=[doc_result, update_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.get = AsyncMock(return_value=None)

        fake_task = MagicMock()

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.tasks.document_task.parse_document_task.delay",
                return_value=fake_task,
            ),
        ):
            ret_doc, _ = await document_service.reparse_document(10, 1, db, force=True)

        assert ret_doc.status == "pending"

    @pytest.mark.asyncio
    async def test_force_skips_embedding_status_check(self):
        """force=True 时 status='embedding' 不再抛 ConflictError。"""
        doc = MagicMock(id=10, kb_id=5, status="embedding", chunk_count=0)
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=[doc_result, update_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.tasks.document_task.parse_document_task.delay",
                return_value=MagicMock(),
            ),
        ):
            ret_doc, _ = await document_service.reparse_document(10, 1, db, force=True)

        assert ret_doc.status == "pending"

    @pytest.mark.asyncio
    async def test_force_update_omits_status_condition(self):
        """force=True 时 UPDATE WHERE 子句只含 doc_id，不含 status 条件（跳过乐观锁）。"""
        doc = MagicMock(id=10, kb_id=5, status="parsing", chunk_count=0)
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(side_effect=[doc_result, update_result])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.get = AsyncMock(return_value=None)

        with (
            patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()),
            patch(
                "app.tasks.document_task.parse_document_task.delay",
                return_value=MagicMock(),
            ),
        ):
            await document_service.reparse_document(10, 1, db, force=True)

        # 第二次 execute 是 UPDATE 语句
        update_stmt = db.execute.await_args_list[1].args[0]
        compiled = str(update_stmt.compile(compile_kwargs={"literal_binds": True}))
        # WHERE 子句应只含 doc_id=10，不含 status 条件
        assert "status" not in compiled.lower().split("where")[-1]
        assert "documents.id = 10" in compiled or "documents.id = 10" in compiled.replace("\n", " ")

    @pytest.mark.asyncio
    async def test_force_false_still_rejects_parsing(self):
        """force=False（默认）时 status='parsing' 仍抛 ConflictError。"""
        doc = MagicMock(id=10, kb_id=5, status="parsing")
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(ConflictError):
                await document_service.reparse_document(10, 1, db, force=False)

    @pytest.mark.asyncio
    async def test_force_default_value_is_false(self):
        """不传 force 时默认为 False，仍执行状态检查。"""
        doc = MagicMock(id=10, kb_id=5, status="parsing")
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        with patch("app.services.kb_service.get_kb_for_write", new=AsyncMock()):
            with pytest.raises(ConflictError):
                await document_service.reparse_document(10, 1, db)


# ---------- get_progress ----------


class TestGetProgress:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_data(self):
        """Redis 命中缓存时直接返回，跳过 DB 查询。"""
        cached = {"status": "done", "progress": 100, "chunk_count": 5, "error_message": None}
        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(return_value='{"status":"done","progress":100}')

        doc = MagicMock(id=10, kb_id=5, status="done", chunk_count=5, error_message=None)
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        with (
            patch("app.redis_client.get_redis", return_value=fake_redis),
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
            patch("json.loads", return_value=cached),
        ):
            result = await document_service.get_progress(10, 1, db)

        assert result == cached
        # DB 不应被调用
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cache_miss_falls_back_to_db(self):
        """Redis 未命中时降级为 DB 查询。"""
        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(return_value=None)

        doc = MagicMock(id=10, kb_id=5, status="done", chunk_count=5, error_message=None)
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        with (
            patch("app.redis_client.get_redis", return_value=fake_redis),
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
        ):
            result = await document_service.get_progress(10, 1, db)

        assert result["status"] == "done"
        assert result["progress"] == 100
        assert result["chunk_count"] == 5
        assert result["error_message"] is None

    @pytest.mark.asyncio
    async def test_cache_read_error_falls_back_to_db(self):
        """Redis 读取异常时不阻塞，降级为 DB 查询。"""
        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(side_effect=RuntimeError("redis down"))

        doc = MagicMock(id=10, kb_id=5, status="parsing", chunk_count=2, error_message=None)
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        with (
            patch("app.redis_client.get_redis", return_value=fake_redis),
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
        ):
            result = await document_service.get_progress(10, 1, db)

        assert result["status"] == "parsing"
        assert result["progress"] == 10  # STATUS_PROGRESS["parsing"] = 10

    @pytest.mark.asyncio
    async def test_no_redis_client_falls_back_to_db(self):
        """get_redis 返回 None 时降级为 DB 查询。"""
        doc = MagicMock(id=10, kb_id=5, status="failed", chunk_count=0, error_message="boom")
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        with (
            patch("app.redis_client.get_redis", return_value=None),
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
        ):
            result = await document_service.get_progress(10, 1, db)

        assert result["status"] == "failed"
        assert result["progress"] == 100
        assert result["error_message"] == "boom"


# ---------- preview_document ----------


class TestPreviewDocument:
    @pytest.mark.asyncio
    async def test_unsupported_file_type_raises_app_exception(self):
        """无对应 parser 时抛 AppException(UNSUPPORTED_FILE_TYPE)。"""
        doc = MagicMock(id=10, kb_id=5, file_path="/tmp/x.exe", file_type="exe")
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
            patch("app.parsers.get_parser", return_value=None),
        ):
            with pytest.raises(AppException) as exc_info:
                await document_service.preview_document(10, 1, db)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_parse_failure_raises_doc_parse_failed(self):
        """parser.parse 抛异常时抛 AppException(DOC_PARSE_FAILED)。"""
        doc = MagicMock(id=10, kb_id=5, file_path="/tmp/x.md", file_type="md")
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        fake_parser = MagicMock()
        fake_parser.parse.side_effect = RuntimeError("parse error")

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
            patch("app.parsers.get_parser", return_value=fake_parser),
        ):
            with pytest.raises(AppException) as exc_info:
                await document_service.preview_document(10, 1, db)

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_normal_preview_first_page(self):
        """正常预览：第一页返回正确分页数据。"""
        raw_text = "line1\nline2\nline3\nline4\nline5"
        doc = MagicMock(
            id=10,
            kb_id=5,
            filename="test.md",
            file_type="md",
            file_path="/tmp/test.md",
        )
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        fake_parser = MagicMock()
        fake_parser.parse.return_value = raw_text

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
            patch("app.parsers.get_parser", return_value=fake_parser),
        ):
            result = await document_service.preview_document(
                10, 1, db, page=1, page_size=2
            )

        assert result["filename"] == "test.md"
        assert result["file_type"] == "md"
        assert result["content"] == "line1\nline2"
        assert result["page"] == 1
        assert result["page_size"] == 2
        assert result["total_lines"] == 5
        assert result["total_pages"] == 3  # ceil(5/2)

    @pytest.mark.asyncio
    async def test_normal_preview_second_page(self):
        """分页：第二页内容正确。"""
        raw_text = "line1\nline2\nline3\nline4\nline5"
        doc = MagicMock(
            id=10, kb_id=5, filename="t.md", file_type="md", file_path="/tmp/t.md"
        )
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        fake_parser = MagicMock()
        fake_parser.parse.return_value = raw_text

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
            patch("app.parsers.get_parser", return_value=fake_parser),
        ):
            result = await document_service.preview_document(
                10, 1, db, page=2, page_size=2
            )

        assert result["content"] == "line3\nline4"
        assert result["page"] == 2

    @pytest.mark.asyncio
    async def test_page_clamped_to_total_pages(self):
        """page 超出 total_pages 时被钳制为 total_pages。"""
        raw_text = "line1\nline2\nline3"
        doc = MagicMock(
            id=10, kb_id=5, filename="t.md", file_type="md", file_path="/tmp/t.md"
        )
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        fake_parser = MagicMock()
        fake_parser.parse.return_value = raw_text

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
            patch("app.parsers.get_parser", return_value=fake_parser),
        ):
            result = await document_service.preview_document(
                10, 1, db, page=99, page_size=2
            )

        # total_pages = ceil(3/2) = 2; page=99 应被钳制为 2
        assert result["page"] == 2
        assert result["total_pages"] == 2

    @pytest.mark.asyncio
    async def test_page_below_one_clamped_to_one(self):
        """page < 1 时被钳制为 1。"""
        raw_text = "line1\nline2"
        doc = MagicMock(
            id=10, kb_id=5, filename="t.md", file_type="md", file_path="/tmp/t.md"
        )
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        fake_parser = MagicMock()
        fake_parser.parse.return_value = raw_text

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
            patch("app.parsers.get_parser", return_value=fake_parser),
        ):
            result = await document_service.preview_document(
                10, 1, db, page=0, page_size=2
            )

        assert result["page"] == 1

    @pytest.mark.asyncio
    async def test_empty_file_returns_single_page(self):
        """空文件：total_pages=1，content 为空字符串。"""
        doc = MagicMock(
            id=10, kb_id=5, filename="t.md", file_type="md", file_path="/tmp/t.md"
        )
        db = AsyncMock()
        doc_result = MagicMock()
        doc_result.scalar_one_or_none.return_value = doc
        db.execute = AsyncMock(return_value=doc_result)

        fake_parser = MagicMock()
        fake_parser.parse.return_value = ""

        with (
            patch("app.services.kb_service.get_kb_for_read", new=AsyncMock()),
            patch("app.parsers.get_parser", return_value=fake_parser),
        ):
            result = await document_service.preview_document(10, 1, db)

        # "" .split("\n") = [""], total_lines=1, total_pages=1
        assert result["total_lines"] == 1
        assert result["total_pages"] == 1
        assert result["content"] == ""
