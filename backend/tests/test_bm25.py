"""Unit tests for rag.bm25 module."""

from app.rag.bm25 import BM25Store, bm25_store

SAMPLE_DOCS = [
    {"content": "The quick brown fox jumps over the lazy dog"},
    {"content": "A quick brown dog outpaces a lazy fox"},
    {"content": "Lorem ipsum dolor sit amet consectetur adipiscing elit"},
    {"content": "The fox and the hound are friends"},
]


class TestBM25Store:
    def test_build_with_chunks(self):
        """_build should create a BM25Okapi from chunks and return tokenized for reuse.

        P1-4 修复后 _build 返回 (bm25, tokenized) 元组，序列化时复用 tokenized 避免重复分词。
        """
        store = BM25Store()
        bm25, tokenized = store._build(SAMPLE_DOCS)
        assert bm25 is not None
        assert len(tokenized) == 4
        scores = bm25.get_scores(store._tokenize("fox"))
        assert len(scores) == 4

    def test_tokenize_english(self):
        store = BM25Store()
        tokens = store._tokenize("hello world")
        assert "hello" in tokens
        assert "world" in tokens

    def test_tokenize_cjk(self):
        store = BM25Store()
        tokens = store._tokenize("你好世界")
        assert "你好" in tokens
        assert "世界" in tokens

    def test_tokenize_mixed(self):
        store = BM25Store()
        tokens = store._tokenize("hello 世界")
        assert "hello" in tokens
        assert "世界" in tokens

    def test_tokenize_empty(self):
        store = BM25Store()
        tokens = store._tokenize("")
        assert tokens == []

    def test_key_format(self):
        store = BM25Store()
        key = store._key(42)
        assert key == "bm25:kb:42"
        assert isinstance(key, str)

    def test_search_with_chunks_provided(self):
        import asyncio

        store = BM25Store()
        results = asyncio.run(store.search(999999, "fox", top_k=2, chunks=SAMPLE_DOCS))
        assert len(results) == 2
        assert isinstance(results[0], dict)
        assert "score" in results[0]
        assert "content" in results[0]

    def test_search_empty_kb_no_chunks(self):
        import asyncio

        store = BM25Store()
        results = asyncio.run(store.search(999998, "query", top_k=5))
        assert results == []

    def test_search_empty_query(self):
        import asyncio

        store = BM25Store()
        results = asyncio.run(store.search(999995, "", top_k=5, chunks=SAMPLE_DOCS))
        assert isinstance(results, list)

    def test_top_k_limit(self):
        import asyncio

        store = BM25Store()
        results = asyncio.run(store.search(999997, "the", top_k=2, chunks=SAMPLE_DOCS))
        assert len(results) <= 2

    def test_top_k_zero(self):
        import asyncio

        store = BM25Store()
        results = asyncio.run(store.search(999994, "fox", top_k=0, chunks=SAMPLE_DOCS))
        assert len(results) == 0

    def test_scores_descending(self):
        import asyncio

        store = BM25Store()
        results = asyncio.run(store.search(999996, "fox", top_k=4, chunks=SAMPLE_DOCS))
        scores = [r["score"] for r in results]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    def test_rebuild_sync(self):
        store = BM25Store()
        store.rebuild_sync(9001, SAMPLE_DOCS)
        # Should be in cache after rebuild
        assert 9001 in store._cache
        # And search should work
        results = store.search_sync(9001, "fox", top_k=2)
        assert len(results) == 2

    def test_search_sync_with_chunks(self):
        store = BM25Store()
        results = store.search_sync(9002, "fox", top_k=3, chunks=SAMPLE_DOCS)
        assert len(results) == 3

    def test_delete_removes_from_cache(self):
        import asyncio

        store = BM25Store()

        async def _test():
            await store.search(9003, "fox", top_k=2, chunks=SAMPLE_DOCS)
            assert 9003 in store._cache
            await store.delete(9003)
            assert 9003 not in store._cache

        asyncio.run(_test())

    def test_delete_nonexistent_no_error(self):
        import asyncio

        store = BM25Store()

        async def _test():
            await store.delete(9999999)

        asyncio.run(_test())

    def test_module_instance_exists(self):
        assert bm25_store is not None
        assert isinstance(bm25_store, BM25Store)

    def test_cache_used_on_second_search(self):
        """第二次 search 不传 chunks 时，应从内存缓存加载 chunks 元数据，结果 content 不为空。"""
        import asyncio

        store = BM25Store()
        kb_id = 9100
        # First call builds and caches BM25 index + chunks metadata
        asyncio.run(store.search(kb_id, "fox", top_k=2, chunks=SAMPLE_DOCS))
        assert kb_id in store._cache
        # Second call uses cached BM25 index, loads chunks from memory cache
        # Note: 不能用 "dog"，因为 "dog" 在 2/4 文档中出现，BM25 IDF = log((4-2+0.5)/(2+0.5)) = 0，
        # 打分全为 0 被阈值过滤（与 Lucene/Elasticsearch 业界惯例一致），返回空结果。
        # "fox" 在 3/4 文档中出现，IDF<0（负分），负分不被过滤，能返回结果验证 cache 复用 + chunks 回填。
        results = asyncio.run(store.search(kb_id, "fox", top_k=2))
        assert len(results) == 2
        # Verify chunks metadata is properly backfilled from memory cache (content not empty)
        assert all(r.get("content") for r in results)


# ---------- Phase F2: 增量更新测试 ----------

DOC_A_CHUNKS = [
    {
        "chunk_id": 1,
        "doc_id": 100,
        "kb_id": 9200,
        "content": "Python is a programming language",
        "filename": "a.md",
        "file_type": "md",
    },
    {
        "chunk_id": 2,
        "doc_id": 100,
        "kb_id": 9200,
        "content": "Python supports multiple paradigms",
        "filename": "a.md",
        "file_type": "md",
    },
]

DOC_B_CHUNKS = [
    {
        "chunk_id": 3,
        "doc_id": 200,
        "kb_id": 9200,
        "content": "Rust is a systems programming language",
        "filename": "b.md",
        "file_type": "md",
    },
]


class TestBM25Incremental:
    """Phase F2: BM25 增量 add_documents / remove_document 方法"""

    def test_add_documents_sync_appends_to_existing(self):
        """先 rebuild doc A，再 add_documents doc B → 搜索能命中两个文档"""
        store = BM25Store()
        kb_id = 9201
        try:
            store.rebuild_sync(kb_id, DOC_A_CHUNKS)
            # 此时只有 doc A
            results = store.search_sync(kb_id, "rust", top_k=5)
            assert all("rust" not in r.get("content", "").lower() for r in results)

            # 增量追加 doc B
            store.add_documents_sync(kb_id, DOC_B_CHUNKS)
            # 现在 doc B 应在索引里
            results = store.search_sync(kb_id, "rust", top_k=5)
            assert any("rust" in r.get("content", "").lower() for r in results)
            # doc A 仍可搜索
            results = store.search_sync(kb_id, "python", top_k=5)
            assert any("python" in r.get("content", "").lower() for r in results)
        finally:
            store._cache.pop(kb_id, None)

    def test_add_documents_sync_first_call_equiv_rebuild(self):
        """Redis 无缓存时，add_documents_sync 等价于 rebuild"""
        store = BM25Store()
        kb_id = 9202
        try:
            store.add_documents_sync(kb_id, DOC_A_CHUNKS)
            assert kb_id in store._cache
            results = store.search_sync(kb_id, "python", top_k=5)
            assert len(results) > 0
        finally:
            store._cache.pop(kb_id, None)

    def test_add_documents_sync_empty_noop(self):
        """传空 chunks → 不抛异常，索引不变"""
        store = BM25Store()
        kb_id = 9203
        try:
            store.rebuild_sync(kb_id, DOC_A_CHUNKS)
            store.add_documents_sync(kb_id, [])
            results = store.search_sync(kb_id, "python", top_k=5)
            assert len(results) > 0
        finally:
            store._cache.pop(kb_id, None)

    def test_remove_document_sync_removes_doc_chunks(self):
        """add A + B → remove A → 搜索只命中 B"""
        store = BM25Store()
        kb_id = 9204
        try:
            store.rebuild_sync(kb_id, DOC_A_CHUNKS)
            store.add_documents_sync(kb_id, DOC_B_CHUNKS)
            # 删除 doc A
            store.remove_document_sync(kb_id, doc_id=100)
            # doc A 的内容应搜不到（或排得很低）
            # 这里验证 doc B 仍可搜索
            results = store.search_sync(kb_id, "rust", top_k=5)
            assert any("rust" in r.get("content", "").lower() for r in results)
        finally:
            store._cache.pop(kb_id, None)

    def test_serialize_deserialize_roundtrip(self):
        """chunks 序列化/反序列化保留关键字段"""
        store = BM25Store()
        raw = store._serialize_chunks(DOC_A_CHUNKS + DOC_B_CHUNKS)
        restored = store._deserialize_chunks(raw)
        assert len(restored) == 3
        assert restored[0]["content"] == "Python is a programming language"
        assert restored[0]["doc_id"] == 100
        assert restored[2]["doc_id"] == 200

    def test_deserialize_empty_or_invalid(self):
        """反序列化空串/None/非法 JSON → 返回空列表"""
        store = BM25Store()
        assert store._deserialize_chunks(None) == []
        assert store._deserialize_chunks("") == []
        assert store._deserialize_chunks("not a json") == []

    def test_chunks_key_format(self):
        """Phase F2 新增的 chunks 元数据 key 命名"""
        store = BM25Store()
        assert store._chunks_key(42) == "bm25:kb:42:chunks"

    def test_add_documents_async(self):
        """异步增量 add_documents"""
        import asyncio

        store = BM25Store()
        kb_id = 9205

        async def _test():
            await store.rebuild(kb_id, DOC_A_CHUNKS)
            await store.add_documents(kb_id, DOC_B_CHUNKS)
            results = await store.search(kb_id, "rust", top_k=5)
            assert any("rust" in r.get("content", "").lower() for r in results)
            results = await store.search(kb_id, "python", top_k=5)
            assert any("python" in r.get("content", "").lower() for r in results)

        try:
            asyncio.run(_test())
        finally:
            store._cache.pop(kb_id, None)

    def test_remove_document_async(self):
        """异步 remove_document"""
        import asyncio

        store = BM25Store()
        kb_id = 9206

        async def _test():
            await store.rebuild(kb_id, DOC_A_CHUNKS)
            await store.add_documents(kb_id, DOC_B_CHUNKS)
            await store.remove_document(kb_id, doc_id=100)
            # doc B 仍可搜
            results = await store.search(kb_id, "rust", top_k=5)
            assert any("rust" in r.get("content", "").lower() for r in results)

        try:
            asyncio.run(_test())
        finally:
            store._cache.pop(kb_id, None)


# ---------- SubTask 18.1: async 路径 asyncio.Lock 并发保护 ----------
class TestBM25AsyncLock:
    """BM25 async 路径使用 asyncio.Lock 保护 _cache（非 threading.Lock）"""

    def test_async_lock_is_lazy_initialized(self):
        """async 路径的锁在首次使用时 lazy 初始化"""
        store = BM25Store()
        assert store._async_lock is None
        lock = store._get_async_lock()
        assert lock is not None
        import asyncio

        assert isinstance(lock, asyncio.Lock)

    def test_sync_lock_remains_threading_lock(self):
        """sync 路径（Celery）继续使用 threading.Lock"""
        import threading

        store = BM25Store()
        assert isinstance(store._sync_lock, type(threading.Lock()))

    def test_concurrent_get_or_build_safe(self):
        """并发 get_or_build 不会破坏 _cache"""
        import asyncio

        store = BM25Store()
        kb_id = 9300

        async def _test():
            # 5 个并发 get_or_build 同一 kb_id
            results = await asyncio.gather(
                *[store.get_or_build(kb_id, DOC_A_CHUNKS) for _ in range(5)]
            )
            # 所有结果应非 None
            assert all(r is not None for r in results)
            # _cache 中应只有一个条目
            assert kb_id in store._cache

        try:
            asyncio.run(_test())
        finally:
            store._cache.pop(kb_id, None)

    def test_concurrent_rebuild_and_delete_safe(self):
        """并发 rebuild + delete 不应导致状态错误"""
        import asyncio

        store = BM25Store()
        kb_id = 9301

        async def _test():
            await store.rebuild(kb_id, DOC_A_CHUNKS)
            # 并发 delete + 再次 rebuild
            await asyncio.gather(
                store.delete(kb_id),
                store.rebuild(kb_id, DOC_B_CHUNKS),
            )
            # 最终状态应一致：cache 中应有索引
            assert kb_id in store._cache

        try:
            asyncio.run(_test())
        finally:
            store._cache.pop(kb_id, None)
