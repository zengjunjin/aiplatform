"""Tests for app.rag.retriever.HybridRetriever

重点测试 _rrf_fuse（纯算法，无 IO）和边界情况，
vector_search / _load_chunks_for_bm25 通过 mock 测试。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.rag.retriever import HybridRetriever, retriever


class TestCollectionName:
    def test_collection_name_format(self):
        r = HybridRetriever()
        assert r._collection_name(42) == "chunks_kb_42"

    def test_collection_name_zero(self):
        r = HybridRetriever()
        assert r._collection_name(0) == "chunks_kb_0"


class TestRRFFusion:
    def test_rrf_fuse_empty_inputs(self):
        r = HybridRetriever()
        assert r._rrf_fuse([], []) == []

    def test_rrf_fuse_only_vector_results(self):
        r = HybridRetriever()
        vec = [
            {"chunk_id": 1, "content": "a", "score": 0.9},
            {"chunk_id": 2, "content": "b", "score": 0.8},
        ]
        result = r._rrf_fuse(vec, [])
        assert len(result) == 2
        assert result[0]["chunk_id"] == 1  # rank 0 → 最高分
        assert result[0]["rrf_score"] > result[1]["rrf_score"]
        # rrf_score = 1/(60+0+1) ≈ 0.0164
        assert result[0]["rrf_score"] == pytest.approx(1/61, rel=1e-3)

    def test_rrf_fuse_only_bm25_results(self):
        r = HybridRetriever()
        bm25 = [
            {"chunk_id": 10, "content": "x", "score": 5.0, "doc_id": 1, "filename": "a.md"},
            {"chunk_id": 20, "content": "y", "score": 4.0, "doc_id": 2, "filename": "b.md"},
        ]
        result = r._rrf_fuse([], bm25)
        assert len(result) == 2
        assert result[0]["chunk_id"] == 10
        assert result[0]["source"] == "bm25"  # 来自 bm25 路径

    def test_rrf_fuse_both_sources_overlapping_chunk_ids(self):
        """vec 和 bm25 命中相同 chunk → rrf_score 叠加"""
        r = HybridRetriever()
        vec = [
            {"chunk_id": 1, "content": "a", "score": 0.9},  # rank 0
        ]
        bm25 = [
            {"chunk_id": 1, "content": "a", "score": 5.0},  # rank 0
            {"chunk_id": 2, "content": "b", "score": 3.0},
        ]
        result = r._rrf_fuse(vec, bm25)
        # chunk_id 1 在两个 list 都排 rank 0 → 分数最高
        assert result[0]["chunk_id"] == 1
        expected = 1/61 + 1/61  # 两个 rank 0
        assert result[0]["rrf_score"] == pytest.approx(expected, rel=1e-3)
        assert result[1]["chunk_id"] == 2

    def test_rrf_fuse_bm25_missing_chunk_id_skipped(self):
        """bm25 结果无 chunk_id 字段 → 跳过"""
        r = HybridRetriever()
        bm25 = [
            {"content": "no id", "score": 1.0},  # 无 chunk_id
            {"chunk_id": 5, "content": "with id", "score": 2.0},
        ]
        result = r._rrf_fuse([], bm25)
        assert len(result) == 1
        assert result[0]["chunk_id"] == 5

    def test_rrf_fuse_preserves_vector_metadata(self):
        """rrf 结果保留 vec 路径的 metadata（filename 等）"""
        r = HybridRetriever()
        vec = [{"chunk_id": 1, "content": "a", "filename": "doc.md", "page": 3, "score": 0.9}]
        result = r._rrf_fuse(vec, [])
        assert result[0]["filename"] == "doc.md"
        assert result[0]["page"] == 3

    def test_rrf_fuse_default_k_is_60(self):
        """默认 k=60，影响分数计算"""
        r = HybridRetriever()
        vec = [{"chunk_id": 1, "content": "a", "score": 0.9}]
        result = r._rrf_fuse(vec, [])
        # rank 0, k=60: 1/(60+0+1) = 1/61
        assert result[0]["rrf_score"] == pytest.approx(1/61, rel=1e-6)

    def test_rrf_fuse_custom_k(self):
        r = HybridRetriever()
        vec = [{"chunk_id": 1, "content": "a", "score": 0.9}]
        result = r._rrf_fuse(vec, [], k=100)
        # rank 0, k=100: 1/(100+0+1) = 1/101
        assert result[0]["rrf_score"] == pytest.approx(1/101, rel=1e-6)


class TestRetrieverSingleton:
    def test_retriever_singleton_exists(self):
        assert isinstance(retriever, HybridRetriever)


class TestRetrieveWithMocks:
    @pytest.mark.asyncio
    async def test_retrieve_fuses_vec_and_bm25(self):
        """retrieve 调用 _vector_search + bm25_store.search + _rrf_fuse"""
        r = HybridRetriever()
        vec_results = [{"chunk_id": 1, "content": "a", "score": 0.9}]
        bm25_results = [{"chunk_id": 2, "content": "b", "score": 5.0}]

        with patch.object(r, "_vector_search", AsyncMock(return_value=vec_results)), \
             patch.object(r, "_load_chunks_for_bm25", AsyncMock(return_value=[])), \
             patch("app.rag.retriever.bm25_store") as mock_bm25:
            mock_bm25.search = AsyncMock(return_value=bm25_results)
            with patch("app.rag.retriever.RAG_RETRIEVAL_TOTAL"):
                result = await r.retrieve("query", kb_id=1, top_k=5)

        # 两个结果都被融合
        assert len(result) == 2
        chunk_ids = {c["chunk_id"] for c in result}
        assert chunk_ids == {1, 2}

    @pytest.mark.asyncio
    async def test_retrieve_top_k_limits_results(self):
        """retrieve 返回的结果数不超过 top_k"""
        r = HybridRetriever()
        vec = [{"chunk_id": i, "content": f"a{i}", "score": 0.9} for i in range(10)]
        bm25 = [{"chunk_id": i, "content": f"b{i}", "score": 5.0} for i in range(10)]

        with patch.object(r, "_vector_search", AsyncMock(return_value=vec)), \
             patch.object(r, "_load_chunks_for_bm25", AsyncMock(return_value=[])), \
             patch("app.rag.retriever.bm25_store") as mock_bm25:
            mock_bm25.search = AsyncMock(return_value=bm25)
            with patch("app.rag.retriever.RAG_RETRIEVAL_TOTAL"):
                result = await r.retrieve("query", kb_id=1, top_k=3)
        assert len(result) <= 3

    @pytest.mark.asyncio
    async def test_retrieve_requests_2x_top_k_from_each_source(self):
        """retrieve 向 vector_search 和 bm25 各请求 top_k*2 个结果"""
        r = HybridRetriever()
        captured_top_k_vec = []
        captured_top_k_bm25 = []

        async def fake_vec_search(query, kb_id, top_k):
            captured_top_k_vec.append(top_k)
            return []

        async def fake_bm25_search(kb_id, query, top_k, chunks=None):
            captured_top_k_bm25.append(top_k)
            return []

        with patch.object(r, "_vector_search", side_effect=fake_vec_search), \
             patch.object(r, "_load_chunks_for_bm25", AsyncMock(return_value=[])), \
             patch("app.rag.retriever.bm25_store") as mock_bm25:
            mock_bm25.search = fake_bm25_search
            with patch("app.rag.retriever.RAG_RETRIEVAL_TOTAL"):
                await r.retrieve("query", kb_id=1, top_k=5)
        assert captured_top_k_vec == [10]  # 5 * 2
        assert captured_top_k_bm25 == [10]


# ---------- SubTask 18.2: _chunks_cache singleflight 模式 ----------
class TestChunksCacheSingleflight:
    """retriever._chunks_cache miss-then-load 路径 singleflight 保护"""

    @pytest.mark.asyncio
    async def test_concurrent_misses_only_load_once(self):
        """多个并发请求 miss 时，_load_chunks_for_bm25 只应被调用一次"""
        import asyncio
        r = HybridRetriever()
        load_count = 0

        async def fake_load(kb_id):
            nonlocal load_count
            load_count += 1
            await asyncio.sleep(0.05)  # 模拟 DB 加载耗时
            return [{"chunk_id": 1, "doc_id": 100, "content": "test"}]

        with patch.object(r, "_load_chunks_for_bm25", side_effect=fake_load):
            # 5 个并发请求
            results = await asyncio.gather(
                *[r._get_chunks_for_bm25(kb_id=999) for _ in range(5)]
            )

        # 只应加载一次（singleflight）
        assert load_count == 1, f"Expected 1 load, got {load_count}"
        # 所有请求都应得到相同结果
        assert all(len(res) == 1 for res in results)
        assert all(res[0]["content"] == "test" for res in results)

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_load(self):
        """缓存命中时不调用 _load_chunks_for_bm25"""
        r = HybridRetriever()
        load_count = 0

        async def fake_load(kb_id):
            nonlocal load_count
            load_count += 1
            return [{"chunk_id": 1, "content": "cached"}]

        with patch.object(r, "_load_chunks_for_bm25", side_effect=fake_load):
            # 第一次：miss，加载
            await r._get_chunks_for_bm25(kb_id=888)
            assert load_count == 1
            # 第二次：hit，不加载
            await r._get_chunks_for_bm25(kb_id=888)
            assert load_count == 1

    @pytest.mark.asyncio
    async def test_different_kb_ids_load_independently(self):
        """不同 kb_id 的加载互不影响"""
        import asyncio
        r = HybridRetriever()
        loaded_kbs = []

        async def fake_load(kb_id):
            loaded_kbs.append(kb_id)
            await asyncio.sleep(0.01)
            return [{"chunk_id": 1, "content": f"kb{kb_id}"}]

        with patch.object(r, "_load_chunks_for_bm25", side_effect=fake_load):
            await asyncio.gather(
                r._get_chunks_for_bm25(kb_id=100),
                r._get_chunks_for_bm25(kb_id=200),
            )

        assert sorted(loaded_kbs) == [100, 200]

    @pytest.mark.asyncio
    async def test_invalidate_clears_lock(self):
        """invalidate_chunks_cache 应清理 singleflight 锁"""
        r = HybridRetriever()

        async def fake_load(kb_id):
            return [{"chunk_id": 1, "content": "test"}]

        with patch.object(r, "_load_chunks_for_bm25", side_effect=fake_load):
            await r._get_chunks_for_bm25(kb_id=777)

        assert 777 in r._chunks_locks
        r.invalidate_chunks_cache(777)
        assert 777 not in r._chunks_locks
        assert 777 not in r._chunks_cache

    @pytest.mark.asyncio
    async def test_concurrent_load_and_invalidate_safe(self):
        """并发加载 + invalidate 不应导致状态错误"""
        import asyncio
        r = HybridRetriever()
        load_count = 0

        async def fake_load(kb_id):
            nonlocal load_count
            load_count += 1
            await asyncio.sleep(0.02)
            return [{"chunk_id": 1, "content": "test"}]

        async def invalidate():
            await asyncio.sleep(0.01)  # 让加载先开始
            r.invalidate_chunks_cache(666)

        with patch.object(r, "_load_chunks_for_bm25", side_effect=fake_load):
            # 并发：加载 + invalidate
            await asyncio.gather(
                r._get_chunks_for_bm25(kb_id=666),
                r._get_chunks_for_bm25(kb_id=666),
                invalidate(),
            )
        # 不应抛出异常，最终状态应一致
        assert load_count >= 1


class TestVectorSearchErrorHandling:
    @pytest.mark.asyncio
    async def test_vector_search_returns_empty_on_error(self):
        """_vector_search 内部异常 → 返回空列表（不抛出）"""
        r = HybridRetriever()
        # embedding 是 property，访问时返回 _embedding。直接 patch _embedding 私有属性
        fake_embedding = MagicMock()
        fake_embedding.embed = AsyncMock(side_effect=Exception("ollama down"))
        r._embedding = fake_embedding
        result = await r._vector_search("query", kb_id=1, top_k=5)
        assert result == []


class TestVectorSearchScoreThreshold:
    """Task 13: 检索结果 score 阈值过滤"""

    @pytest.mark.asyncio
    async def test_low_score_chunks_filtered_out(self):
        """score < RETRIEVAL_SCORE_THRESHOLD 的 chunks 被过滤"""
        from app.config import settings

        r = HybridRetriever()
        fake_embedding = MagicMock()
        fake_embedding.embed = AsyncMock(return_value=[[0.1, 0.2]])
        r._embedding = fake_embedding

        # Mock qdrant.query_points 返回混合分数结果
        high_score_point = MagicMock()
        high_score_point.id = 1
        high_score_point.score = 0.9
        high_score_point.payload = {"chunk_id": 1, "content": "high score chunk"}

        low_score_point = MagicMock()
        low_score_point.id = 2
        low_score_point.score = 0.1  # 低于阈值 0.3
        low_score_point.payload = {"chunk_id": 2, "content": "low score chunk"}

        fake_qdrant = MagicMock()
        fake_qdrant.query_points = MagicMock(return_value=MagicMock(points=[high_score_point, low_score_point]))
        r._qdrant_client = fake_qdrant

        with patch.object(r, "_ensure_collection"):
            result = await r._vector_search("query", kb_id=1, top_k=10)

        # 低分 chunk 应被过滤
        assert len(result) == 1
        assert result[0]["chunk_id"] == 1
        assert result[0]["score"] == 0.9

    @pytest.mark.asyncio
    async def test_all_chunks_below_threshold_returns_empty(self):
        """所有 chunks 都低于阈值 → 返回空列表"""
        r = HybridRetriever()
        fake_embedding = MagicMock()
        fake_embedding.embed = AsyncMock(return_value=[[0.1, 0.2]])
        r._embedding = fake_embedding

        low_score_point = MagicMock()
        low_score_point.id = 1
        low_score_point.score = 0.05  # 远低于阈值
        low_score_point.payload = {"chunk_id": 1, "content": "low score"}

        fake_qdrant = MagicMock()
        fake_qdrant.query_points = MagicMock(return_value=MagicMock(points=[low_score_point]))
        r._qdrant_client = fake_qdrant

        with patch.object(r, "_ensure_collection"):
            result = await r._vector_search("query", kb_id=1, top_k=10)

        assert result == []

    @pytest.mark.asyncio
    async def test_none_score_not_filtered(self):
        """score 为 None 的 chunk 不被过滤（保留兼容性）"""
        r = HybridRetriever()
        fake_embedding = MagicMock()
        fake_embedding.embed = AsyncMock(return_value=[[0.1, 0.2]])
        r._embedding = fake_embedding

        none_score_point = MagicMock()
        none_score_point.id = 1
        none_score_point.score = None
        none_score_point.payload = {"chunk_id": 1, "content": "no score"}

        fake_qdrant = MagicMock()
        fake_qdrant.query_points = MagicMock(return_value=MagicMock(points=[none_score_point]))
        r._qdrant_client = fake_qdrant

        with patch.object(r, "_ensure_collection"):
            result = await r._vector_search("query", kb_id=1, top_k=10)

        assert len(result) == 1


class TestDeleteByDocId:
    def test_delete_by_doc_id_handles_exception(self):
        """delete_by_doc_id 内部异常 → 不抛出（仅打印 warning）"""
        r = HybridRetriever()
        fake_qdrant = MagicMock()
        fake_qdrant.delete.side_effect = Exception("qdrant down")
        r._qdrant_client = fake_qdrant
        # 不应抛异常
        r.delete_by_doc_id(kb_id=1, doc_id=10)
        fake_qdrant.delete.assert_called_once()

    def test_delete_by_doc_id_calls_qdrant_delete(self):
        """正常情况调用 qdrant.delete 带 Filter"""
        r = HybridRetriever()
        fake_qdrant = MagicMock()
        r._qdrant_client = fake_qdrant
        r.delete_by_doc_id(kb_id=1, doc_id=10)
        fake_qdrant.delete.assert_called_once()
        # 验证 points_selector 参数
        args = fake_qdrant.delete.call_args
        assert "points_selector" in args.kwargs or len(args.args) >= 2


class TestDeleteCollection:
    def test_delete_collection_handles_exception(self):
        r = HybridRetriever()
        fake_qdrant = MagicMock()
        fake_qdrant.delete_collection.side_effect = Exception("not found")
        r._qdrant_client = fake_qdrant
        r.delete_collection(kb_id=1)  # 不抛
        fake_qdrant.delete_collection.assert_called_once_with("chunks_kb_1")

    def test_delete_collection_calls_qdrant(self):
        r = HybridRetriever()
        fake_qdrant = MagicMock()
        r._qdrant_client = fake_qdrant
        r.delete_collection(kb_id=42)
        fake_qdrant.delete_collection.assert_called_once_with("chunks_kb_42")


class TestAddChunks:
    @pytest.mark.asyncio
    async def test_add_chunks_ensures_collection_then_upserts(self):
        r = HybridRetriever()
        chunks = [
            {"chunk_id": 1, "content": "a", "doc_id": 10, "filename": "x.md", "file_type": "md"},
        ]
        vectors = [[0.1, 0.2, 0.3]]

        with patch.object(r, "_ensure_collection") as mock_ensure:
            fake_qdrant = MagicMock()
            r._qdrant_client = fake_qdrant
            await r.add_chunks(kb_id=1, chunks=chunks, vectors=vectors)
            mock_ensure.assert_called_once_with(1)
            fake_qdrant.upsert.assert_called_once()
            # 验证 PointStruct 包含正确 payload
            args = fake_qdrant.upsert.call_args
            points = args.kwargs.get("points") or args.args[1]
            assert len(points) == 1
            assert points[0].id == 1
            assert points[0].payload["content"] == "a"
            assert points[0].payload["kb_id"] == 1

    @pytest.mark.asyncio
    async def test_add_chunks_uses_id_or_index_as_point_id(self):
        """chunk 无 chunk_id → 用 id 字段或索引+1"""
        r = HybridRetriever()
        chunks = [
            {"id": 100, "content": "a"},
            {"content": "b"},  # 无 id/chunk_id → 用 i+1 = 2
        ]
        vectors = [[0.1], [0.2]]

        with patch.object(r, "_ensure_collection"):
            fake_qdrant = MagicMock()
            r._qdrant_client = fake_qdrant
            await r.add_chunks(kb_id=1, chunks=chunks, vectors=vectors)
            args = fake_qdrant.upsert.call_args
            points = args.kwargs.get("points") or args.args[1]
            assert points[0].id == 100
            assert points[1].id == 2  # i+1
