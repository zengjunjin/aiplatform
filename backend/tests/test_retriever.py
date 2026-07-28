"""Tests for app.rag.retriever.HybridRetriever

重点测试 _rrf_fuse（纯算法，无 IO）和边界情况，
vector_search / _load_chunks_for_bm25 通过 mock 测试。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
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
        assert result[0]["rrf_score"] == pytest.approx(1 / 61, rel=1e-3)

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
        expected = 1 / 61 + 1 / 61  # 两个 rank 0
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
        assert result[0]["rrf_score"] == pytest.approx(1 / 61, rel=1e-6)

    def test_rrf_fuse_custom_k(self):
        r = HybridRetriever()
        vec = [{"chunk_id": 1, "content": "a", "score": 0.9}]
        result = r._rrf_fuse(vec, [], k=100)
        # rank 0, k=100: 1/(100+0+1) = 1/101
        assert result[0]["rrf_score"] == pytest.approx(1 / 101, rel=1e-6)


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

        with (
            patch.object(r, "_vector_search", AsyncMock(return_value=vec_results)),
            patch.object(r, "_load_chunks_for_bm25", AsyncMock(return_value=[])),
            patch("app.rag.retriever.bm25_store") as mock_bm25,
        ):
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

        with (
            patch.object(r, "_vector_search", AsyncMock(return_value=vec)),
            patch.object(r, "_load_chunks_for_bm25", AsyncMock(return_value=[])),
            patch("app.rag.retriever.bm25_store") as mock_bm25,
        ):
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

        async def fake_vec_search(query, kb_id, top_k, qdrant_filter=None):
            captured_top_k_vec.append(top_k)
            return []

        async def fake_bm25_search(kb_id, query, top_k, chunks=None):
            captured_top_k_bm25.append(top_k)
            return []

        with (
            patch.object(r, "_vector_search", side_effect=fake_vec_search),
            patch.object(r, "_load_chunks_for_bm25", AsyncMock(return_value=[])),
            patch("app.rag.retriever.bm25_store") as mock_bm25,
        ):
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
            results = await asyncio.gather(*[r._get_chunks_for_bm25(kb_id=999) for _ in range(5)])

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
    async def test_invalidate_clears_cache_only(self):
        """invalidate_chunks_cache 只清理 cache，不清理 singleflight 锁

        修复（v0.4.0）：invalidate 不再清理锁。
        原因：正在加载的协程持有的锁对象若被移除，新请求会创建新锁
        导致 singleflight 失效、重复加载。锁有 LRU 自然淘汰，不会内存泄漏。
        """
        r = HybridRetriever()

        async def fake_load(kb_id):
            return [{"chunk_id": 1, "content": "test"}]

        with patch.object(r, "_load_chunks_for_bm25", side_effect=fake_load):
            await r._get_chunks_for_bm25(kb_id=777)

        assert 777 in r._chunks_locks
        r.invalidate_chunks_cache(777)
        # 锁不被清理（修复 v0.4.0：避免 singleflight 失效）
        assert 777 in r._chunks_locks
        # 但 cache 被清理
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


# ---------- 阶段 5: _chunks_locks LRU 淘汰行为 ----------
class TestChunksLocksLRU:
    """retriever._chunks_locks OrderedDict LRU 淘汰策略覆盖。

    覆盖 spec 阶段 5 验收点：
      - KB 数量超过 RETRIEVER_LOCKS_MAX_SIZE 时最久未用的锁被淘汰
      - 正被持有的锁跳过淘汰（保留 singleflight 语义）
      - 命中时通过 move_to_end 更新访问顺序
    """

    def test_locks_evict_oldest_when_exceed_max_size(self, monkeypatch):
        """KB 数量超过 max_size 时最久未访问的锁被淘汰。"""
        monkeypatch.setattr("app.rag.retriever.settings.RETRIEVER_LOCKS_MAX_SIZE", 3)
        r = HybridRetriever()

        # 顺序插入 4 个 KB 的锁（max_size=3 → 第 4 个触发淘汰）
        r._get_chunks_lock(1)
        r._get_chunks_lock(2)
        r._get_chunks_lock(3)
        r._get_chunks_lock(4)  # 触发淘汰 kb_id=1

        assert len(r._chunks_locks) == 3
        # 最久未用的 kb_id=1 应被淘汰
        assert 1 not in r._chunks_locks
        # 最近访问的 kb_id=2,3,4 应保留
        assert 2 in r._chunks_locks
        assert 3 in r._chunks_locks
        assert 4 in r._chunks_locks

    def test_access_updates_lru_order(self, monkeypatch):
        """命中已存在的 kb_id 时通过 move_to_end 更新访问顺序，避免被错误淘汰。"""
        monkeypatch.setattr("app.rag.retriever.settings.RETRIEVER_LOCKS_MAX_SIZE", 3)
        r = HybridRetriever()

        r._get_chunks_lock(1)
        r._get_chunks_lock(2)
        r._get_chunks_lock(3)
        # 重新访问 kb_id=1，使其成为最近访问
        r._get_chunks_lock(1)
        # 插入第 4 个，应淘汰最久未用的 kb_id=2（而非 kb_id=1）
        r._get_chunks_lock(4)

        assert len(r._chunks_locks) == 3
        assert 2 not in r._chunks_locks  # 最久未用的被淘汰
        assert 1 in r._chunks_locks  # 最近访问的保留
        assert 3 in r._chunks_locks
        assert 4 in r._chunks_locks

    def test_held_lock_not_evicted(self, monkeypatch):
        """正被持有的锁跳过淘汰，避免破坏 singleflight 语义。

        极端情况下字典可能短暂超限，待锁释放后自然回落。
        """
        monkeypatch.setattr("app.rag.retriever.settings.RETRIEVER_LOCKS_MAX_SIZE", 3)
        r = HybridRetriever()

        r._get_chunks_lock(1)
        r._get_chunks_lock(2)
        r._get_chunks_lock(3)
        # 持有 kb_id=1 的锁（模拟 singleflight 加载中）
        r._chunks_locks[1] = MagicMock()
        r._chunks_locks[1].locked.return_value = True

        # 插入第 4 个，因 kb_id=1 被持有无法淘汰，字典短暂超限到 4
        r._get_chunks_lock(4)

        # kb_id=1 被持有未淘汰，字典短暂超限
        assert 1 in r._chunks_locks
        assert 4 in r._chunks_locks
        # 字典大小为 4（短暂超限，待锁释放后自然回落）
        assert len(r._chunks_locks) == 4

    def test_released_lock_evicted_on_next_access(self, monkeypatch):
        """锁释放后，下一次新插入会淘汰该被释放的最久未用锁。

        spec: 极端情况下字典可能短暂超限，待锁释放后"自然回落"。
        产品代码每次插入新锁时只淘汰 1 个最久未用的锁（不循环淘汰），
        因此字典大小不会立即回到 max_size，但被持有的锁一旦释放，
        下次插入会优先淘汰它。
        """
        monkeypatch.setattr("app.rag.retriever.settings.RETRIEVER_LOCKS_MAX_SIZE", 3)
        r = HybridRetriever()

        r._get_chunks_lock(1)
        r._get_chunks_lock(2)
        r._get_chunks_lock(3)

        # 持有 kb_id=1 → 插入 4 时不淘汰 1
        held_lock = MagicMock()
        held_lock.locked.return_value = True
        r._chunks_locks[1] = held_lock
        r._get_chunks_lock(4)
        assert 1 in r._chunks_locks  # 被持有未淘汰

        # 释放 kb_id=1 → 下一次新插入会淘汰 kb_id=1
        held_lock.locked.return_value = False
        r._get_chunks_lock(5)
        assert 1 not in r._chunks_locks  # 释放后被淘汰
        assert 5 in r._chunks_locks


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
        fake_qdrant.query_points = MagicMock(
            return_value=MagicMock(points=[high_score_point, low_score_point])
        )
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


# ---------- _load_chunks_for_bm25: DB 加载 + 异常分支 (205-250) ----------
class TestLoadChunksForBM25:
    """覆盖 _load_chunks_for_bm25 的 DB 加载成功路径与异常分类日志"""

    @pytest.mark.asyncio
    async def test_load_chunks_success(self):
        """正常 DB 查询 → 返回 chunks 列表"""
        r = HybridRetriever()
        fake_rows = [(1, 100, "content1", 0), (2, 100, "content2", 1)]

        mock_result = MagicMock()
        mock_result.all.return_value = fake_rows
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None
        mock_async_session = MagicMock(return_value=mock_cm)

        with patch("app.database.async_session", mock_async_session):
            result = await r._load_chunks_for_bm25(kb_id=1)

        assert len(result) == 2
        assert result[0] == {
            "chunk_id": 1,
            "doc_id": 100,
            "content": "content1",
            "chunk_index": 0,
        }
        assert result[1]["chunk_index"] == 1

    @pytest.mark.asyncio
    async def test_load_chunks_empty(self):
        """DB 返回空 → 空列表"""
        r = HybridRetriever()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None
        mock_async_session = MagicMock(return_value=mock_cm)

        with patch("app.database.async_session", mock_async_session):
            result = await r._load_chunks_for_bm25(kb_id=1)

        assert result == []

    @pytest.mark.asyncio
    async def test_load_chunks_connection_error_logged_as_error(self):
        """OperationalError → logger.error + 返回空列表"""
        from sqlalchemy.exc import OperationalError

        r = HybridRetriever()
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=OperationalError("stmt", {}, Exception("orig"))
        )

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None
        mock_async_session = MagicMock(return_value=mock_cm)

        with (
            patch("app.database.async_session", mock_async_session),
            patch("app.rag.retriever.logger") as mock_logger,
        ):
            result = await r._load_chunks_for_bm25(kb_id=1)

        assert result == []
        mock_logger.error.assert_called_once()
        mock_logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_chunks_data_error_logged_as_warning(self):
        """非连接异常（如 ValueError）→ logger.warning + 返回空列表"""
        r = HybridRetriever()
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=ValueError("bad data"))

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None
        mock_async_session = MagicMock(return_value=mock_cm)

        with (
            patch("app.database.async_session", mock_async_session),
            patch("app.rag.retriever.logger") as mock_logger,
        ):
            result = await r._load_chunks_for_bm25(kb_id=1)

        assert result == []
        mock_logger.warning.assert_called_once()
        mock_logger.error.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_chunks_oserror_logged_as_error(self):
        """OSError → logger.error（属于连接异常分支）"""
        r = HybridRetriever()
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=OSError("net error"))

        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_session
        mock_cm.__aexit__.return_value = None
        mock_async_session = MagicMock(return_value=mock_cm)

        with (
            patch("app.database.async_session", mock_async_session),
            patch("app.rag.retriever.logger") as mock_logger,
        ):
            result = await r._load_chunks_for_bm25(kb_id=1)

        assert result == []
        mock_logger.error.assert_called_once()


# ---------- _build_qdrant_filter (305-316) ----------
class TestBuildQdrantFilter:
    def test_none_filters_returns_none(self):
        r = HybridRetriever()
        assert r._build_qdrant_filter(None) is None

    def test_empty_filters_returns_none(self):
        r = HybridRetriever()
        assert r._build_qdrant_filter({}) is None

    def test_doc_id_filter(self):
        r = HybridRetriever()
        f = r._build_qdrant_filter({"doc_id": 123})
        assert f is not None
        assert len(f.must) == 1
        assert f.must[0].key == "doc_id"
        assert f.must[0].match.value == 123

    def test_source_page_maps_to_page(self):
        """source_page → payload key 'page'"""
        r = HybridRetriever()
        f = r._build_qdrant_filter({"source_page": 3})
        assert f.must[0].key == "page"
        assert f.must[0].match.value == 3

    def test_file_type_filter(self):
        r = HybridRetriever()
        f = r._build_qdrant_filter({"file_type": "pdf"})
        assert f.must[0].key == "file_type"
        assert f.must[0].match.value == "pdf"

    def test_unknown_key_used_as_is(self):
        """未识别的 key 原样作为 payload key"""
        r = HybridRetriever()
        f = r._build_qdrant_filter({"custom_field": "val"})
        assert f.must[0].key == "custom_field"

    def test_multiple_filters_combined_with_and(self):
        """多条件以 must(AND) 组合"""
        r = HybridRetriever()
        f = r._build_qdrant_filter(
            {"doc_id": 1, "file_type": "pdf", "source_page": 3, "heading": "x"}
        )
        assert len(f.must) == 4
        keys = {c.key for c in f.must}
        assert keys == {"doc_id", "file_type", "page", "heading"}

    def test_truthy_filters_with_empty_items_returns_none(self):
        """filters 真值但 items() 为空 → 返回 None（防御性边界）"""

        class EmptyItemsObj:
            def __bool__(self):
                return True

            def items(self):
                return []

        r = HybridRetriever()
        assert r._build_qdrant_filter(EmptyItemsObj()) is None


# ---------- _filter_bm25_results (331-344) ----------
class TestFilterBM25Results:
    def test_none_filters_returns_original(self):
        r = HybridRetriever()
        results = [{"chunk_id": 1}]
        assert r._filter_bm25_results(results, None) is results

    def test_empty_filters_returns_original(self):
        r = HybridRetriever()
        results = [{"chunk_id": 1}]
        assert r._filter_bm25_results(results, {}) is results

    def test_filters_by_doc_id(self):
        r = HybridRetriever()
        results = [
            {"chunk_id": 1, "doc_id": 100},
            {"chunk_id": 2, "doc_id": 200},
        ]
        filtered = r._filter_bm25_results(results, {"doc_id": 100})
        assert len(filtered) == 1
        assert filtered[0]["chunk_id"] == 1

    def test_filters_by_source_page_maps_to_page(self):
        """source_page → page 字段"""
        r = HybridRetriever()
        results = [
            {"chunk_id": 1, "page": 3},
            {"chunk_id": 2, "page": 5},
        ]
        filtered = r._filter_bm25_results(results, {"source_page": 3})
        assert len(filtered) == 1
        assert filtered[0]["chunk_id"] == 1

    def test_chunk_missing_filter_field_is_kept(self):
        """chunk 缺少被过滤字段 → 保留（兼容旧数据）"""
        r = HybridRetriever()
        results = [
            {"chunk_id": 1},  # 无 doc_id
            {"chunk_id": 2, "doc_id": 100},
        ]
        filtered = r._filter_bm25_results(results, {"doc_id": 100})
        assert len(filtered) == 2  # 1 保留（跳过）+ 2 保留（匹配）

    def test_multiple_filters_all_must_match(self):
        """多条件 AND：所有条件需满足"""
        r = HybridRetriever()
        results = [
            {"chunk_id": 1, "doc_id": 100, "file_type": "pdf"},
            {"chunk_id": 2, "doc_id": 100, "file_type": "md"},  # file_type 不匹配
            {"chunk_id": 3, "doc_id": 200, "file_type": "pdf"},  # doc_id 不匹配
        ]
        filtered = r._filter_bm25_results(results, {"doc_id": 100, "file_type": "pdf"})
        assert len(filtered) == 1
        assert filtered[0]["chunk_id"] == 1

    def test_all_filtered_out(self):
        r = HybridRetriever()
        results = [{"chunk_id": 1, "doc_id": 999}]
        filtered = r._filter_bm25_results(results, {"doc_id": 100})
        assert filtered == []


# ---------- _normalize (508-514) ----------
class TestNormalize:
    def test_empty_dict(self):
        r = HybridRetriever()
        assert r._normalize({}) == {}

    def test_single_element(self):
        """单元素 → 1.0（避免除零）"""
        r = HybridRetriever()
        result = r._normalize({1: 5.0})
        assert result == {1: 1.0}

    def test_all_equal_values(self):
        """所有值相等 → 全 1.0"""
        r = HybridRetriever()
        result = r._normalize({1: 5.0, 2: 5.0, 3: 5.0})
        assert result == {1: 1.0, 2: 1.0, 3: 1.0}

    def test_min_max_normalization(self):
        r = HybridRetriever()
        result = r._normalize({1: 0.0, 2: 5.0, 3: 10.0})
        assert result[1] == pytest.approx(0.0)
        assert result[2] == pytest.approx(0.5)
        assert result[3] == pytest.approx(1.0)

    def test_negative_values(self):
        """BM25 可能有负分"""
        r = HybridRetriever()
        result = r._normalize({1: -2.0, 2: 0.0, 3: 2.0})
        assert result[1] == pytest.approx(0.0)
        assert result[2] == pytest.approx(0.5)
        assert result[3] == pytest.approx(1.0)


# ---------- _weighted_fuse (524-564) ----------
class TestWeightedFuse:
    def test_empty_inputs(self):
        r = HybridRetriever()
        assert r._weighted_fuse([], [], alpha=0.5) == []

    def test_only_vector_results(self):
        r = HybridRetriever()
        vec = [{"chunk_id": 1, "score": 0.9}, {"chunk_id": 2, "score": 0.5}]
        result = r._weighted_fuse(vec, [], alpha=1.0)
        assert len(result) == 2
        assert result[0]["chunk_id"] == 1  # 更高分排前
        assert "fused_score" in result[0]

    def test_only_bm25_results(self):
        r = HybridRetriever()
        bm25 = [{"chunk_id": 1, "score": 5.0, "content": "x"}]
        result = r._weighted_fuse([], bm25, alpha=0.0)
        assert len(result) == 1
        assert result[0]["chunk_id"] == 1
        assert result[0]["source"] == "bm25"

    def test_overlapping_chunk_ids(self):
        """vec 和 bm25 命中相同 chunk → 加权融合"""
        r = HybridRetriever()
        vec = [{"chunk_id": 1, "score": 0.9}]
        bm25 = [{"chunk_id": 1, "score": 5.0}]
        result = r._weighted_fuse(vec, bm25, alpha=0.5)
        assert len(result) == 1
        # 两个都归一化为 1.0（单元素），fused = 0.5*1 + 0.5*1 = 1.0
        assert result[0]["fused_score"] == pytest.approx(1.0)

    def test_bm25_missing_chunk_id_skipped(self):
        """bm25 结果无 chunk_id → 跳过"""
        r = HybridRetriever()
        bm25 = [
            {"content": "no id", "score": 1.0},
            {"chunk_id": 5, "content": "with id", "score": 2.0},
        ]
        result = r._weighted_fuse([], bm25, alpha=0.0)
        assert len(result) == 1
        assert result[0]["chunk_id"] == 5

    def test_alpha_one_pure_vector(self):
        """alpha=1.0 → 纯向量，bm25 不影响排序"""
        r = HybridRetriever()
        vec = [{"chunk_id": 1, "score": 0.9}, {"chunk_id": 2, "score": 0.1}]
        bm25 = [{"chunk_id": 2, "score": 100.0}]  # bm25 高分但 alpha=1 忽略
        result = r._weighted_fuse(vec, bm25, alpha=1.0)
        assert result[0]["chunk_id"] == 1  # vec 高分排前

    def test_alpha_zero_pure_bm25(self):
        """alpha=0.0 → 纯 BM25"""
        r = HybridRetriever()
        vec = [{"chunk_id": 1, "score": 100.0}]  # vec 高分但 alpha=0 忽略
        bm25 = [{"chunk_id": 2, "score": 5.0}, {"chunk_id": 3, "score": 1.0}]
        result = r._weighted_fuse(vec, bm25, alpha=0.0)
        assert result[0]["chunk_id"] == 2  # bm25 高分排前

    def test_preserves_vector_metadata(self):
        """weighted_fuse 保留 vec 路径 metadata"""
        r = HybridRetriever()
        vec = [{"chunk_id": 1, "filename": "doc.md", "page": 3, "score": 0.9}]
        result = r._weighted_fuse(vec, [], alpha=1.0)
        assert result[0]["filename"] == "doc.md"
        assert result[0]["page"] == 3


# ---------- retrieve with alpha (153) ----------
class TestRetrieveWithAlpha:
    @pytest.mark.asyncio
    async def test_retrieve_with_alpha_calls_weighted_fuse(self):
        """alpha 显式传入 → 走 _weighted_fuse 而非 RRF"""
        r = HybridRetriever()
        vec_results = [{"chunk_id": 1, "content": "a", "score": 0.9}]
        bm25_results = [{"chunk_id": 2, "content": "b", "score": 5.0}]

        with (
            patch.object(r, "_vector_search", AsyncMock(return_value=vec_results)),
            patch.object(r, "_load_chunks_for_bm25", AsyncMock(return_value=[])),
            patch("app.rag.retriever.bm25_store") as mock_bm25,
            patch.object(r, "_weighted_fuse") as mock_weighted,
            patch.object(r, "_rrf_fuse") as mock_rrf,
            patch("app.rag.retriever.RAG_RETRIEVAL_TOTAL"),
        ):
            mock_bm25.search = AsyncMock(return_value=bm25_results)
            mock_weighted.return_value = [{"chunk_id": 1, "fused_score": 1.0}]
            result = await r.retrieve("query", kb_id=1, top_k=5, alpha=0.5)

        mock_weighted.assert_called_once()
        mock_rrf.assert_not_called()
        assert result == [{"chunk_id": 1, "fused_score": 1.0}]

    @pytest.mark.asyncio
    async def test_retrieve_with_alpha_none_calls_rrf(self):
        """alpha=None → 走 _rrf_fuse（默认）"""
        r = HybridRetriever()

        with (
            patch.object(r, "_vector_search", AsyncMock(return_value=[])),
            patch.object(r, "_load_chunks_for_bm25", AsyncMock(return_value=[])),
            patch("app.rag.retriever.bm25_store") as mock_bm25,
            patch.object(r, "_weighted_fuse") as mock_weighted,
            patch.object(r, "_rrf_fuse") as mock_rrf,
            patch("app.rag.retriever.RAG_RETRIEVAL_TOTAL"),
        ):
            mock_bm25.search = AsyncMock(return_value=[])
            mock_rrf.return_value = []
            await r.retrieve("query", kb_id=1, top_k=5)  # alpha 默认 None

        mock_rrf.assert_called_once()
        mock_weighted.assert_not_called()

    @pytest.mark.asyncio
    async def test_retrieve_with_filters_passes_qdrant_filter(self):
        """retrieve 传入 filters → _vector_search 收到 Qdrant Filter"""
        r = HybridRetriever()
        captured_filter = []

        async def fake_vec(query, kb_id, top_k, qdrant_filter=None):
            captured_filter.append(qdrant_filter)
            return []

        with (
            patch.object(r, "_vector_search", side_effect=fake_vec),
            patch.object(r, "_load_chunks_for_bm25", AsyncMock(return_value=[])),
            patch("app.rag.retriever.bm25_store") as mock_bm25,
            patch("app.rag.retriever.RAG_RETRIEVAL_TOTAL"),
        ):
            mock_bm25.search = AsyncMock(return_value=[])
            await r.retrieve("query", kb_id=1, top_k=5, filters={"doc_id": 100})

        assert captured_filter[0] is not None
        assert captured_filter[0].must[0].key == "doc_id"

    @pytest.mark.asyncio
    async def test_retrieve_with_filters_filters_bm25_results(self):
        """retrieve 传入 filters → BM25 结果在内存中过滤"""
        r = HybridRetriever()
        bm25_results = [
            {"chunk_id": 1, "doc_id": 100, "content": "a", "score": 5.0},
            {"chunk_id": 2, "doc_id": 200, "content": "b", "score": 4.0},
        ]

        with (
            patch.object(r, "_vector_search", AsyncMock(return_value=[])),
            patch.object(r, "_load_chunks_for_bm25", AsyncMock(return_value=[])),
            patch("app.rag.retriever.bm25_store") as mock_bm25,
            patch("app.rag.retriever.RAG_RETRIEVAL_TOTAL"),
        ):
            mock_bm25.search = AsyncMock(return_value=bm25_results)
            result = await r.retrieve("query", kb_id=1, top_k=5, filters={"doc_id": 100})

        # doc_id=200 的 bm25 结果被过滤
        chunk_ids = {c["chunk_id"] for c in result}
        assert 2 not in chunk_ids
        assert 1 in chunk_ids


# ---------- _get_cached_query_embedding (263-267, 277-279) ----------
class TestGetCachedQueryEmbedding:
    @pytest.mark.asyncio
    async def test_redis_cache_hit(self):
        """Redis 命中 → 直接返回缓存，不计算 embedding"""
        r = HybridRetriever()
        fake_embedding = MagicMock()
        fake_embedding.embed = AsyncMock(return_value=[[0.1, 0.2]])
        r._embedding = fake_embedding

        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(return_value='[0.5, 0.6]')

        with patch("app.rag.retriever.get_redis", return_value=fake_redis):
            result = await r._get_cached_query_embedding("query", "model")

        assert result == [0.5, 0.6]
        fake_embedding.embed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_redis_cache_miss_computes_and_writes(self):
        """Redis 未命中 → 计算 embedding + 写回缓存"""
        r = HybridRetriever()
        fake_embedding = MagicMock()
        fake_embedding.embed = AsyncMock(return_value=[[0.1, 0.2]])
        r._embedding = fake_embedding

        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(return_value=None)
        fake_redis.setex = AsyncMock()

        with patch("app.rag.retriever.get_redis", return_value=fake_redis):
            result = await r._get_cached_query_embedding("query", "model")

        assert result == [0.1, 0.2]
        fake_embedding.embed.assert_awaited_once()
        fake_redis.setex.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_redis_none_falls_back_to_compute(self):
        """Redis 不可用（None）→ 直接计算，不写缓存"""
        r = HybridRetriever()
        fake_embedding = MagicMock()
        fake_embedding.embed = AsyncMock(return_value=[[0.1, 0.2]])
        r._embedding = fake_embedding

        with patch("app.rag.retriever.get_redis", return_value=None):
            result = await r._get_cached_query_embedding("query", "model")

        assert result == [0.1, 0.2]
        fake_embedding.embed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_redis_read_exception_falls_back_to_compute(self):
        """Redis 读异常 → fallback 计算"""
        r = HybridRetriever()
        fake_embedding = MagicMock()
        fake_embedding.embed = AsyncMock(return_value=[[0.1, 0.2]])
        r._embedding = fake_embedding

        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(side_effect=Exception("redis down"))
        fake_redis.setex = AsyncMock()

        with (
            patch("app.rag.retriever.get_redis", return_value=fake_redis),
            patch("app.rag.retriever.logger") as mock_logger,
        ):
            result = await r._get_cached_query_embedding("query", "model")

        assert result == [0.1, 0.2]
        fake_embedding.embed.assert_awaited_once()
        mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_redis_write_exception_does_not_raise(self):
        """Redis 写异常 → 不抛出，返回计算结果"""
        r = HybridRetriever()
        fake_embedding = MagicMock()
        fake_embedding.embed = AsyncMock(return_value=[[0.1, 0.2]])
        r._embedding = fake_embedding

        fake_redis = AsyncMock()
        fake_redis.get = AsyncMock(return_value=None)
        fake_redis.setex = AsyncMock(side_effect=Exception("write failed"))

        with (
            patch("app.rag.retriever.get_redis", return_value=fake_redis),
            patch("app.rag.retriever.logger") as mock_logger,
        ):
            result = await r._get_cached_query_embedding("query", "model")

        assert result == [0.1, 0.2]
        mock_logger.warning.assert_called()


# ---------- _ensure_collection (92-97) ----------
class TestEnsureCollection:
    @pytest.mark.asyncio
    async def test_creates_collection_when_not_found(self):
        """collection 不存在 → 创建"""
        r = HybridRetriever()
        fake_qdrant = MagicMock()
        fake_qdrant.get_collection = MagicMock(side_effect=Exception("not found"))
        fake_qdrant.create_collection = MagicMock()
        r._qdrant_client = fake_qdrant

        await r._ensure_collection(kb_id=1)

        fake_qdrant.create_collection.assert_called_once()
        # 验证创建参数
        args = fake_qdrant.create_collection.call_args
        assert args.kwargs["collection_name"] == "chunks_kb_1"
        assert args.kwargs["vectors_config"].size == settings.EMBEDDING_DIM

    @pytest.mark.asyncio
    async def test_skips_create_when_collection_exists(self):
        """collection 已存在 → 不创建"""
        r = HybridRetriever()
        fake_qdrant = MagicMock()
        fake_qdrant.get_collection = MagicMock(return_value=MagicMock())
        fake_qdrant.create_collection = MagicMock()
        r._qdrant_client = fake_qdrant

        await r._ensure_collection(kb_id=1)

        fake_qdrant.get_collection.assert_called_once_with("chunks_kb_1")
        fake_qdrant.create_collection.assert_not_called()


# ---------- qdrant / embedding property lazy init (75, 84) ----------
class TestLazyInit:
    def test_qdrant_lazy_init(self):
        """qdrant property 首次访问创建 QdrantClient"""
        r = HybridRetriever()
        assert r._qdrant_client is None
        with patch("app.rag.retriever.QdrantClient") as mock_qdrant_cls:
            _ = r.qdrant
            mock_qdrant_cls.assert_called_once()

    def test_qdrant_cached_after_first_access(self):
        r = HybridRetriever()
        with patch("app.rag.retriever.QdrantClient") as mock_qdrant_cls:
            _ = r.qdrant
            _ = r.qdrant
            assert mock_qdrant_cls.call_count == 1

    def test_embedding_lazy_init(self):
        """embedding property 首次访问通过 ModelFactory 创建"""
        r = HybridRetriever()
        assert r._embedding is None
        with patch("app.rag.retriever.ModelFactory") as mock_factory:
            mock_factory.create_embedding.return_value = "fake_embedding"
            emb = r.embedding
            assert emb == "fake_embedding"
            mock_factory.create_embedding.assert_called_once()

    def test_embedding_cached_after_first_access(self):
        r = HybridRetriever()
        with patch("app.rag.retriever.ModelFactory") as mock_factory:
            mock_factory.create_embedding.return_value = "fake"
            _ = r.embedding
            _ = r.embedding
            assert mock_factory.create_embedding.call_count == 1


# ---------- vector search 连接异常分支 (395) ----------
class TestVectorSearchConnectionErrors:
    @pytest.mark.asyncio
    async def test_connection_error_logged_as_error(self):
        """ConnectionError → logger.error"""
        r = HybridRetriever()
        r._embedding = MagicMock()
        fake_qdrant = MagicMock()
        fake_qdrant.query_points = MagicMock(side_effect=ConnectionError("refused"))
        r._qdrant_client = fake_qdrant

        with (
            patch.object(r, "_ensure_collection"),
            patch.object(
                r, "_get_cached_query_embedding", AsyncMock(return_value=[0.1, 0.2])
            ),
            patch("app.rag.retriever.logger") as mock_logger,
        ):
            result = await r._vector_search("query", kb_id=1, top_k=5)

        assert result == []
        mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_oserror_logged_as_error(self):
        r = HybridRetriever()
        r._embedding = MagicMock()
        fake_qdrant = MagicMock()
        fake_qdrant.query_points = MagicMock(side_effect=OSError("net"))
        r._qdrant_client = fake_qdrant

        with (
            patch.object(r, "_ensure_collection"),
            patch.object(
                r, "_get_cached_query_embedding", AsyncMock(return_value=[0.1, 0.2])
            ),
            patch("app.rag.retriever.logger") as mock_logger,
        ):
            result = await r._vector_search("query", kb_id=1, top_k=5)

        assert result == []
        mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_response_handling_exception_logged_as_error(self):
        """ResponseHandlingException → logger.error"""
        from qdrant_client.http.exceptions import ResponseHandlingException

        r = HybridRetriever()
        r._embedding = MagicMock()
        fake_qdrant = MagicMock()
        fake_qdrant.query_points = MagicMock(
            side_effect=ResponseHandlingException("timeout")
        )
        r._qdrant_client = fake_qdrant

        with (
            patch.object(r, "_ensure_collection"),
            patch.object(
                r, "_get_cached_query_embedding", AsyncMock(return_value=[0.1, 0.2])
            ),
            patch("app.rag.retriever.logger") as mock_logger,
        ):
            result = await r._vector_search("query", kb_id=1, top_k=5)

        assert result == []
        mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_generic_exception_logged_as_warning(self):
        """非连接异常 → logger.warning"""
        r = HybridRetriever()
        r._embedding = MagicMock()
        fake_qdrant = MagicMock()
        fake_qdrant.query_points = MagicMock(side_effect=ValueError("bad data"))
        r._qdrant_client = fake_qdrant

        with (
            patch.object(r, "_ensure_collection"),
            patch.object(
                r, "_get_cached_query_embedding", AsyncMock(return_value=[0.1, 0.2])
            ),
            patch("app.rag.retriever.logger") as mock_logger,
        ):
            result = await r._vector_search("query", kb_id=1, top_k=5)

        assert result == []
        mock_logger.warning.assert_called_once()
        mock_logger.error.assert_not_called()


# ---------- _chunks_cache LRU + 大 KB 跳过缓存 (184-190, 194) ----------
class TestChunksCacheLRU:
    @pytest.mark.asyncio
    async def test_chunks_exceeding_max_chunks_per_kb_not_cached(self, monkeypatch):
        """chunks 数量超 BM25_CACHE_MAX_CHUNKS_PER_KB → 返回但不缓存"""
        monkeypatch.setattr("app.rag.retriever.settings.BM25_CACHE_MAX_CHUNKS_PER_KB", 5)
        r = HybridRetriever()
        big_chunks = [{"chunk_id": i, "content": f"c{i}"} for i in range(10)]

        async def fake_load(kb_id):
            return big_chunks

        with (
            patch.object(r, "_load_chunks_for_bm25", side_effect=fake_load),
            patch("app.rag.retriever.logger") as mock_logger,
        ):
            result = await r._get_chunks_for_bm25(kb_id=1)

        assert result == big_chunks  # 返回数据
        assert 1 not in r._chunks_cache  # 但不缓存
        mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_chunks_cache_evicts_oldest_when_exceed_max_kbs(self, monkeypatch):
        """缓存 KB 数超过 BM25_CACHE_MAX_KB → LRU 淘汰最久未访问"""
        monkeypatch.setattr("app.rag.retriever.settings.BM25_CACHE_MAX_KB", 2)
        r = HybridRetriever()

        async def fake_load(kb_id):
            return [{"chunk_id": 1, "content": f"kb{kb_id}"}]

        with patch.object(r, "_load_chunks_for_bm25", side_effect=fake_load):
            await r._get_chunks_for_bm25(kb_id=1)
            await r._get_chunks_for_bm25(kb_id=2)
            await r._get_chunks_for_bm25(kb_id=3)  # 触发淘汰 kb_id=1

        assert 1 not in r._chunks_cache  # 最久未访问被淘汰
        assert 2 in r._chunks_cache
        assert 3 in r._chunks_cache
        assert len(r._chunks_cache) == 2

    @pytest.mark.asyncio
    async def test_cache_hit_updates_lru_order(self, monkeypatch):
        """缓存命中时 move_to_end 更新访问顺序"""
        monkeypatch.setattr("app.rag.retriever.settings.BM25_CACHE_MAX_KB", 2)
        r = HybridRetriever()

        async def fake_load(kb_id):
            return [{"chunk_id": 1, "content": f"kb{kb_id}"}]

        with patch.object(r, "_load_chunks_for_bm25", side_effect=fake_load):
            await r._get_chunks_for_bm25(kb_id=1)
            await r._get_chunks_for_bm25(kb_id=2)
            # 重新访问 kb_id=1，使其成为最近访问
            await r._get_chunks_for_bm25(kb_id=1)
            # 插入 kb_id=3，应淘汰 kb_id=2（最久未访问）
            await r._get_chunks_for_bm25(kb_id=3)

        assert 1 in r._chunks_cache  # 最近访问的保留
        assert 2 not in r._chunks_cache  # 最久未访问的被淘汰
        assert 3 in r._chunks_cache

    @pytest.mark.asyncio
    async def test_double_check_cache_hit_inside_lock(self):
        """slow path 锁内 double-check：等待锁期间缓存被填充 → 不加载"""
        r = HybridRetriever()
        load_count = 0

        async def fake_load(kb_id):
            nonlocal load_count
            load_count += 1
            return [{"chunk_id": 1, "content": "loaded"}]

        # 自定义锁：acquire 时模拟另一个请求已填充缓存
        class CustomLock:
            async def __aenter__(self):
                r._chunks_cache[999] = [{"chunk_id": 1, "content": "filled by other"}]
                return self

            async def __aexit__(self, *args):
                pass

            def locked(self):
                return False

        with (
            patch.object(r, "_load_chunks_for_bm25", side_effect=fake_load),
            patch.object(r, "_get_chunks_lock", return_value=CustomLock()),
        ):
            result = await r._get_chunks_for_bm25(kb_id=999)

        # double-check 命中，不调用 _load_chunks_for_bm25
        assert load_count == 0
        assert result[0]["content"] == "filled by other"
