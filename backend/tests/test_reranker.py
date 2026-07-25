"""Tests for app.rag.reranker.Reranker"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.reranker import Reranker


@pytest.fixture
def fake_provider():
    p = MagicMock()
    p.rerank = AsyncMock(return_value=[])
    return p


class TestReranker:
    @pytest.mark.asyncio
    async def test_rerank_empty_chunks_returns_empty(self, fake_provider):
        """空 chunks → 直接返回空列表，不调用 provider"""
        r = Reranker()
        r._provider = fake_provider
        result = await r.rerank("query", [], top_k=5)
        assert result == []
        fake_provider.rerank.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rerank_returns_chunks_with_rerank_score(self, fake_provider):
        """provider 返回 [(idx, score), ...]，reranker 映射回原 chunk 并添加 rerank_score"""
        chunks = [
            {"chunk_id": 1, "content": "doc A"},
            {"chunk_id": 2, "content": "doc B"},
            {"chunk_id": 3, "content": "doc C"},
        ]
        # provider 返回：chunk 2 得分最高，chunk 0 次之
        fake_provider.rerank = AsyncMock(return_value=[(2, 0.95), (0, 0.80)])
        r = Reranker()
        r._provider = fake_provider

        result = await r.rerank("query", chunks, top_k=2)
        assert len(result) == 2
        assert result[0]["chunk_id"] == 3  # idx 2 → chunk_id 3
        assert result[0]["rerank_score"] == pytest.approx(0.95)
        assert result[1]["chunk_id"] == 1  # idx 0 → chunk_id 1
        assert result[1]["rerank_score"] == pytest.approx(0.80)
        # 验证传给 provider 的 documents 是 content 列表
        args = fake_provider.rerank.await_args
        docs = args[0][1]
        assert docs == ["doc A", "doc B", "doc C"]
        assert args[1] == {"top_k": 2} or args[0][2] == 2

    @pytest.mark.asyncio
    async def test_rerank_skips_out_of_range_idx(self, fake_provider):
        """provider 返回的 idx 越界 → 跳过"""
        chunks = [{"chunk_id": 1, "content": "only one"}]
        fake_provider.rerank = AsyncMock(return_value=[(0, 0.9), (5, 0.5)])
        r = Reranker()
        r._provider = fake_provider

        result = await r.rerank("query", chunks, top_k=5)
        assert len(result) == 1
        assert result[0]["chunk_id"] == 1

    @pytest.mark.asyncio
    async def test_rerank_preserves_original_chunk_fields(self, fake_provider):
        """rerank 返回的 chunk 保留原 chunk 的所有字段"""
        chunks = [
            {
                "chunk_id": 7,
                "doc_id": 100,
                "kb_id": 5,
                "content": "text",
                "filename": "a.md",
                "file_type": "md",
            }
        ]
        fake_provider.rerank = AsyncMock(return_value=[(0, 0.99)])
        r = Reranker()
        r._provider = fake_provider

        result = await r.rerank("query", chunks, top_k=1)
        assert result[0]["doc_id"] == 100
        assert result[0]["kb_id"] == 5
        assert result[0]["filename"] == "a.md"
        assert result[0]["file_type"] == "md"
        assert result[0]["rerank_score"] == 0.99

    def test_provider_lazy_initialization(self):
        """provider 属性首次访问时通过 ModelFactory 创建"""
        r = Reranker()
        assert r._provider is None
        with patch("app.rag.reranker.ModelFactory") as mock_factory:
            mock_factory.create_reranker.return_value = "fake_provider"
            p = r.provider
            assert p == "fake_provider"
            mock_factory.create_reranker.assert_called_once()
            # 第二次访问不重新创建
            _ = r.provider
            mock_factory.create_reranker.assert_called_once()

    def test_provider_cached_after_first_access(self):
        """provider 创建后被缓存"""
        r = Reranker()
        with patch("app.rag.reranker.ModelFactory") as mock_factory:
            mock_factory.create_reranker.return_value = "fake"
            _ = r.provider
            _ = r.provider
            _ = r.provider
        assert mock_factory.create_reranker.call_count == 1


@pytest.fixture
def reranker_singleton():
    """重置单例，避免影响其他测试"""
    from app.rag.reranker import reranker

    saved = reranker._provider
    reranker._provider = None
    yield reranker
    reranker._provider = saved


def test_reranker_singleton_exists():
    """reranker 单例已导出"""
    from app.rag.reranker import reranker

    assert isinstance(reranker, Reranker)


class TestRerankerContentExtraction:
    """rerank 提取 content 字段时的边界情况"""

    @pytest.mark.asyncio
    async def test_chunk_without_content_uses_empty_string(self, fake_provider):
        """chunk 无 content 字段 → 传给 provider 空字符串"""
        chunks = [{"chunk_id": 1}]  # 无 content
        fake_provider.rerank = AsyncMock(return_value=[(0, 0.5)])
        r = Reranker()
        r._provider = fake_provider

        result = await r.rerank("query", chunks, top_k=1)
        args = fake_provider.rerank.await_args
        docs = args[0][1]
        assert docs == [""]
        assert len(result) == 1
