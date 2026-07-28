"""Tests for uncovered parts of app.tasks.document_task: _parse_and_chunk + _embed_and_store."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks import document_task


def _patch_bm25():
    """Helper: bm25_store 在 _embed_and_store 内部 `from app.rag.bm25 import bm25_store`
    延迟导入，所以 patch app.rag.bm25.bm25_store 才能在 import 时生效。"""
    return patch("app.rag.bm25.bm25_store")


def _run_async(coro):
    """替换 asyncio.run：在新 event loop 中真正运行 coroutine。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestParseAndChunk:
    def test_parse_and_chunk_doc_not_found_raises(self):
        """doc 不存在 → ValueError"""
        session = MagicMock()
        session.get.return_value = None
        with patch("app.tasks.document_task.get_sync_session", return_value=session):
            with pytest.raises(ValueError, match="not found"):
                document_task._parse_and_chunk(999)
        session.close.assert_called_once()

    def test_parse_and_chunk_unsupported_file_type_raises(self):
        """parser 为 None → ValueError"""
        doc = MagicMock()
        doc.id = 1
        doc.kb_id = 1
        doc.file_path = "/tmp/file.unknown"
        doc.file_type = "unknown"
        session = MagicMock()
        session.get.return_value = doc

        with patch("app.tasks.document_task.get_sync_session", return_value=session):
            with patch("app.tasks.document_task._cleanup_old_chunks"):
                with patch("app.tasks.document_task.get_parser", return_value=None):
                    with pytest.raises(ValueError, match="Unsupported file type"):
                        document_task._parse_and_chunk(1)
        session.close.assert_called_once()

    def test_parse_and_chunk_success(self):
        """完整流程：parse → chunk → 写入 PG → 读取并填充 chunk_id"""
        doc = MagicMock()
        doc.id = 10
        doc.kb_id = 1
        doc.file_path = "/tmp/test.md"
        doc.file_type = "md"
        doc.filename = "test.md"

        # chunks from parser
        chunks_from_parser = [
            {"content": "hello", "char_count": 5},
            {"content": "world", "char_count": 5},
        ]

        # 模拟 db_chunks（提交后查询出来的）
        db_chunk1 = MagicMock()
        db_chunk1.id = 101
        db_chunk2 = MagicMock()
        db_chunk2.id = 102
        db_chunks = [db_chunk1, db_chunk2]

        session = MagicMock()
        session.get.return_value = doc
        # session.execute 在 select chunks 时返回 db_chunks
        select_result = MagicMock()
        select_result.scalars.return_value.all.return_value = db_chunks
        session.execute = MagicMock(return_value=select_result)

        parser_mock = MagicMock()
        parser_mock.parse.return_value = "hello world"

        with patch("app.tasks.document_task.get_sync_session", return_value=session):
            with patch("app.tasks.document_task._cleanup_old_chunks"):
                with patch("app.tasks.document_task.get_parser", return_value=parser_mock):
                    with patch("app.tasks.document_task.chunker") as mock_chunker:
                        mock_chunker.chunk.return_value = chunks_from_parser
                        result = document_task._parse_and_chunk(10)

        assert len(result) == 2
        # 应填充 chunk_id, doc_id, kb_id, filename, file_type
        assert result[0]["chunk_id"] == 101
        assert result[0]["doc_id"] == 10
        assert result[0]["kb_id"] == 1
        assert result[0]["filename"] == "test.md"
        assert result[0]["file_type"] == "md"
        assert result[1]["chunk_id"] == 102
        # 应 add_all 1 次（批量插入 2 个 DocumentChunk）并 commit
        assert session.add_all.call_count == 1
        assert len(session.add_all.call_args[0][0]) == 2
        session.commit.assert_called_once()
        session.close.assert_called_once()


class TestEmbedAndStore:
    def test_embed_and_store_calls_retriever_and_backfills(self):
        """_embed_and_store 完整流程：embed → add_chunks → backfill vector_id → BM25 增量"""
        chunks = [
            {
                "chunk_id": 101,
                "doc_id": 10,
                "kb_id": 1,
                "content": "hello",
                "filename": "a.md",
                "file_type": "md",
            },
            {
                "chunk_id": 102,
                "doc_id": 10,
                "kb_id": 1,
                "content": "world",
                "filename": "a.md",
                "file_type": "md",
            },
        ]
        vectors = [[0.1, 0.2], [0.3, 0.4]]

        session = MagicMock()

        with patch("app.tasks.document_task._embed_texts_async", new=AsyncMock(return_value=vectors)):
            with patch("app.tasks.document_task.retriever") as mock_retriever:
                mock_retriever.add_chunks = AsyncMock()
                with patch("app.tasks.document_task.get_sync_session", return_value=session):
                    with _patch_bm25() as mock_bm25:
                        mock_bm25.add_documents_sync = MagicMock()
                        with patch("asyncio.run", side_effect=_run_async):
                            document_task._embed_and_store(10, chunks)

        # retriever.add_chunks 应被调用
        mock_retriever.add_chunks.assert_awaited_once()
        # vector_id backfill SQL 应执行 2 次
        assert session.execute.call_count == 2
        session.commit.assert_called_once()
        # BM25 增量更新应被调用
        mock_bm25.add_documents_sync.assert_called_once_with(1, chunks)

    def test_embed_and_store_continues_on_backfill_failure(self):
        """backfill vector_id 失败 → rollback，但不抛异常"""
        chunks = [
            {
                "chunk_id": 101,
                "doc_id": 10,
                "kb_id": 1,
                "content": "hello",
                "filename": "a.md",
                "file_type": "md",
            },
        ]

        session = MagicMock()
        session.execute.side_effect = Exception("DB error")

        with patch("app.tasks.document_task._embed_texts_async", new=AsyncMock(return_value=[[0.1]])):
            with patch("app.tasks.document_task.retriever") as mock_retriever:
                mock_retriever.add_chunks = AsyncMock()
                with patch("app.tasks.document_task.get_sync_session", return_value=session):
                    with _patch_bm25():
                        with patch("asyncio.run", side_effect=_run_async):
                            # 不应抛异常
                            document_task._embed_and_store(10, chunks)
        # rollback 应被调用
        session.rollback.assert_called_once()

    def test_embed_and_store_continues_on_bm25_failure(self):
        """BM25 增量失败 → 不抛异常"""
        chunks = [
            {
                "chunk_id": 101,
                "doc_id": 10,
                "kb_id": 1,
                "content": "hello",
                "filename": "a.md",
                "file_type": "md",
            },
        ]

        session = MagicMock()

        with patch("app.tasks.document_task._embed_texts_async", new=AsyncMock(return_value=[[0.1]])):
            with patch("app.tasks.document_task.retriever") as mock_retriever:
                mock_retriever.add_chunks = AsyncMock()
                with patch("app.tasks.document_task.get_sync_session", return_value=session):
                    with _patch_bm25() as mock_bm25:
                        mock_bm25.add_documents_sync = MagicMock(side_effect=Exception("BM25 down"))
                        with patch("asyncio.run", side_effect=_run_async):
                            # 不应抛异常
                            document_task._embed_and_store(10, chunks)
        # vector_id backfill 仍执行
        session.execute.assert_called_once()
        session.commit.assert_called_once()

    def test_embed_and_store_skips_chunks_without_chunk_id(self):
        """chunk 无 chunk_id → 跳过 backfill 但仍 add_chunks"""
        chunks = [
            {"content": "hello", "kb_id": 1, "doc_id": 10, "filename": "a.md", "file_type": "md"},
        ]

        session = MagicMock()

        with patch("app.tasks.document_task._embed_texts_async", new=AsyncMock(return_value=[[0.1]])):
            with patch("app.tasks.document_task.retriever") as mock_retriever:
                mock_retriever.add_chunks = AsyncMock()
                with patch("app.tasks.document_task.get_sync_session", return_value=session):
                    with _patch_bm25():
                        with patch("asyncio.run", side_effect=_run_async):
                            document_task._embed_and_store(10, chunks)
        # 没有 chunk_id，不执行 UPDATE SQL
        session.execute.assert_not_called()
