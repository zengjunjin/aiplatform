"""Tests for app.tasks.document_task

重点测试 _embed_single_text (retry 逻辑) 和 _update_progress 等纯函数，
parse_document_task 主流程通过 mock 测试。
"""
import pytest
import json
from unittest.mock import MagicMock, patch, AsyncMock
from app.tasks import document_task


class TestGetRedisSync:
    def test_get_redis_sync_returns_client(self):
        with patch("app.tasks.document_task.redis_sync.from_url") as mock_from_url:
            mock_client = MagicMock()
            mock_from_url.return_value = mock_client
            result = document_task._get_redis_sync()
            assert result is mock_client

    def test_get_redis_sync_returns_none_on_error(self):
        with patch("app.tasks.document_task.redis_sync.from_url", side_effect=Exception("no redis")):
            result = document_task._get_redis_sync()
            assert result is None


class TestUpdateProgress:
    def test_update_progress_skips_missing_doc(self):
        """doc 不存在 → 直接返回，不写 Redis"""
        session = MagicMock()
        session.get.return_value = None
        with patch("app.tasks.document_task.get_sync_session", return_value=session):
            with patch("app.tasks.document_task._get_redis_sync") as mock_redis:
                document_task._update_progress(doc_id=999, status="done", progress=100)
        mock_redis.assert_not_called()

    def test_update_progress_updates_doc_and_redis(self):
        """doc 存在 → 更新 PG + Redis"""
        doc = MagicMock()
        doc.status = "pending"
        session = MagicMock()
        session.get.return_value = doc
        redis_mock = MagicMock()

        with patch("app.tasks.document_task.get_sync_session", return_value=session):
            with patch("app.tasks.document_task._get_redis_sync", return_value=redis_mock):
                document_task._update_progress(
                    doc_id=1, status="parsing", progress=10, chunk_count=5,
                )
        assert doc.status == "parsing"
        assert doc.chunk_count == 5
        session.commit.assert_called_once()
        redis_mock.setex.assert_called_once()
        # 验证 Redis key 和 data
        args = redis_mock.setex.call_args
        key, ttl, value = args[0]
        assert key == "doc:progress:1"
        assert ttl == 3600
        data = json.loads(value)
        assert data["status"] == "parsing"
        assert data["progress"] == 10
        assert data["chunk_count"] == 5

    def test_update_progress_with_error_message(self):
        doc = MagicMock()
        session = MagicMock()
        session.get.return_value = doc
        redis_mock = MagicMock()

        with patch("app.tasks.document_task.get_sync_session", return_value=session):
            with patch("app.tasks.document_task._get_redis_sync", return_value=redis_mock):
                document_task._update_progress(
                    doc_id=1, status="failed", progress=100, error="parse error",
                )
        assert doc.error_message == "parse error"
        data = json.loads(redis_mock.setex.call_args[0][2])
        assert data["error_message"] == "parse error"

    def test_update_progress_no_redis_skips_redis(self):
        """Redis 不可用 → 仅更新 PG，不抛异常"""
        doc = MagicMock()
        session = MagicMock()
        session.get.return_value = doc

        with patch("app.tasks.document_task.get_sync_session", return_value=session):
            with patch("app.tasks.document_task._get_redis_sync", return_value=None):
                # 不应抛异常
                document_task._update_progress(doc_id=1, status="done", progress=100)


class TestCleanupOldChunks:
    def test_cleanup_old_chunks_deletes_from_pg_and_qdrant(self):
        session = MagicMock()
        redis_mock = MagicMock()

        with patch("app.tasks.document_task.get_sync_session", return_value=session):
            with patch("app.tasks.document_task.retriever") as mock_retriever:
                document_task._cleanup_old_chunks(doc_id=10, kb_id=1)
        # PG 删除
        session.execute.assert_called_once()
        session.commit.assert_called_once()
        # Qdrant 删除
        mock_retriever.delete_by_doc_id.assert_called_once_with(1, 10)

    def test_cleanup_old_chunks_continues_on_qdrant_failure(self):
        """Qdrant 删除失败 → 不影响 PG 清理"""
        session = MagicMock()
        with patch("app.tasks.document_task.get_sync_session", return_value=session):
            with patch("app.tasks.document_task.retriever") as mock_retriever:
                mock_retriever.delete_by_doc_id.side_effect = Exception("qdrant down")
                # 不应抛异常
                document_task._cleanup_old_chunks(doc_id=10, kb_id=1)
        session.commit.assert_called_once()  # PG 仍提交


class TestEmbedSingleText:
    def test_embed_single_text_success(self):
        """正常调用 Ollama embeddings API"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
        mock_resp.raise_for_status = MagicMock()

        with patch("app.tasks.document_task.requests.post", return_value=mock_resp):
            result = document_task._embed_single_text("hello")
        assert result == [0.1, 0.2, 0.3]

    def test_embed_single_text_calls_correct_url(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"embedding": []}
        mock_resp.raise_for_status = MagicMock()

        with patch("app.tasks.document_task.requests.post", return_value=mock_resp) as mock_post:
            with patch("app.tasks.document_task.settings") as mock_settings:
                mock_settings.OLLAMA_HOST = "http://ollama:11434"
                mock_settings.EMBEDDING_MODEL = "nomic-embed-text"
                document_task._embed_single_text("hi")
                args = mock_post.call_args
                assert args[0][0] == "http://ollama:11434/api/embeddings"
                assert args[1]["json"]["model"] == "nomic-embed-text"
                assert args[1]["json"]["prompt"] == "hi"


class TestEmbedTextsSync:
    def test_embed_texts_sync_empty_list(self):
        """空文本列表 → 空向量列表"""
        result = document_task._embed_texts_sync([])
        assert result == []

    def test_embed_texts_sync_multiple_texts(self):
        """多个文本 → 逐个调用 _embed_single_text"""
        with patch.object(document_task, "_embed_single_text") as mock_embed:
            mock_embed.side_effect = [[0.1], [0.2], [0.3]]
            result = document_task._embed_texts_sync(["a", "b", "c"])
        assert result == [[0.1], [0.2], [0.3]]
        assert mock_embed.call_count == 3


class TestEmbedAndStore:
    def test_embed_and_store_empty_chunks_returns_early(self):
        """chunks 为空 → 直接返回，不调用 embed/store"""
        # 不应抛异常
        document_task._embed_and_store(doc_id=1, chunks=[])


class TestParseDocumentTask:
    """parse_document_task 是 celery bind=True task，签名 (self, doc_id)。
    通过 task 对象调用时，celery 自动绑定 task instance 为 self，
    所以调用方式是 parse_document_task(doc_id)，但需要先 push request context。
    简化测试：直接用 .apply() 或 mock task stack。
    """

    def _invoke_task(self, doc_id, retries=0, max_retries=3):
        """辅助：在 mock request context 下调用 task 主体。"""
        task_obj = document_task.parse_document_task
        # push 一个 mock request 到 task stack
        from celery import current_app
        request_mock = MagicMock()
        request_mock.retries = retries
        task_obj.push_request(retries=retries)
        try:
            return task_obj.run(doc_id)
        finally:
            task_obj.pop_request()

    def test_parse_document_task_success(self):
        """完整流程：parse → chunk → embed → store → done"""
        chunks = [
            {"chunk_id": 1, "doc_id": 10, "kb_id": 1, "content": "hello", "filename": "a.md", "file_type": "md"},
        ]
        task_obj = document_task.parse_document_task
        task_obj.push_request(retries=0)

        try:
            with patch.object(document_task, "_update_progress") as mock_progress, \
                 patch.object(document_task, "_parse_and_chunk", return_value=chunks) as mock_parse, \
                 patch.object(document_task, "_embed_and_store") as mock_embed:
                result = task_obj.run(10)

            assert result["doc_id"] == 10
            assert result["chunk_count"] == 1
            assert result["status"] == "done"
            progress_calls = [c.args[1] for c in mock_progress.call_args_list]
            assert progress_calls == ["parsing", "chunking", "embedding", "done"]
            mock_parse.assert_called_once_with(10)
            mock_embed.assert_called_once_with(10, chunks)
        finally:
            task_obj.pop_request()

    def test_parse_document_task_retries_on_exception(self):
        """异常 → 调用 self.retry"""
        task_obj = document_task.parse_document_task
        task_obj.push_request(retries=0)
        # mock retry 方法
        with patch.object(task_obj, "retry", side_effect=Exception("retry scheduled")) as mock_retry:
            with patch.object(document_task, "_update_progress"), \
                 patch.object(document_task, "_parse_and_chunk", side_effect=Exception("parse failed")):
                with pytest.raises(Exception, match="retry scheduled"):
                    task_obj.run(10)
            mock_retry.assert_called_once()
        task_obj.pop_request()

    def test_parse_document_task_marks_failed_on_max_retries(self):
        """达到 max_retries → 标记 failed 后再 retry"""
        task_obj = document_task.parse_document_task
        # max_retries 默认是 3，push_request retries=3 时 >= max_retries
        task_obj.push_request(retries=3)
        try:
            with patch.object(task_obj, "retry", side_effect=Exception("retry")) as mock_retry:
                with patch.object(document_task, "_update_progress") as mock_progress, \
                     patch.object(document_task, "_parse_and_chunk", side_effect=Exception("parse failed")):
                    with pytest.raises(Exception):
                        task_obj.run(10)
                # 应有 failed 状态的 progress 更新
                failed_calls = [c for c in mock_progress.call_args_list if c.args[1] == "failed"]
                assert len(failed_calls) == 1
                assert "parse failed" in str(failed_calls[0].kwargs.get("error", ""))
                mock_retry.assert_called_once()
        finally:
            task_obj.pop_request()
