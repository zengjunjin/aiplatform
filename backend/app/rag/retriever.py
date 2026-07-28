"""Hybrid retrieval: BM25 + vector + RRF fusion."""

import asyncio
import hashlib
import json
import time
from collections import OrderedDict

from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)
from sqlalchemy.exc import (
    DisconnectionError,
    InterfaceError,
    OperationalError,
)
from sqlalchemy.exc import (
    TimeoutError as SATimeoutError,
)

from app.config import settings
from app.core.metrics import RAG_RETRIEVAL_LATENCY, RAG_RETRIEVAL_TOTAL
from app.models.factory import ModelFactory
from app.rag.bm25 import bm25_store
from app.redis_client import get_redis


class HybridRetriever:
    """BM25 + vector retrieval + RRF fusion."""

    def __init__(self):
        self._qdrant_client: QdrantClient | None = None
        self._embedding = None
        # chunks 元数据缓存: kb_id -> list[dict], 避免每次检索都全量加载
        # 使用 OrderedDict 实现 LRU，避免无界增长导致内存爆炸
        self._chunks_cache: OrderedDict[int, list[dict]] = OrderedDict()
        # singleflight locks: 每个 kb_id 独立锁，确保 miss 时只加载一次
        # asyncio.Lock 在单线程 asyncio 中可安全 lazy init（无 await 间隙）
        # 使用 OrderedDict 实现 LRU，KB 数量多时淘汰最久未用的锁，防内存泄漏
        self._chunks_locks: OrderedDict[int, asyncio.Lock] = OrderedDict()

    def _get_chunks_lock(self, kb_id: int) -> asyncio.Lock:
        """获取指定 kb 的 chunks 加载锁（singleflight 模式，LRU 限制大小）。

        多个并发请求 miss 时，只允许第一个加载，其他等待结果。
        asyncio 单线程模型下，dict 读写无 await 间隙，可避免竞争。

        LRU 策略：锁字典超过 settings.RETRIEVER_LOCKS_MAX_SIZE 时淘汰最久未访问
        的锁。正被持有的锁跳过淘汰（保留 singleflight 语义），极端情况下字典
        可能短暂超限，待锁释放后自然回落。
        """
        if kb_id in self._chunks_locks:
            # 命中：更新访问顺序（LRU）
            self._chunks_locks.move_to_end(kb_id)
        else:
            self._chunks_locks[kb_id] = asyncio.Lock()
            # LRU 淘汰：最久未访问且未被持有的锁被移除
            if len(self._chunks_locks) > settings.RETRIEVER_LOCKS_MAX_SIZE:
                oldest_lock = next(iter(self._chunks_locks.values()))
                if not oldest_lock.locked():
                    self._chunks_locks.popitem(last=False)
        return self._chunks_locks[kb_id]

    @property
    def qdrant(self):
        if self._qdrant_client is None:
            self._qdrant_client = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
            )
        return self._qdrant_client

    @property
    def embedding(self):
        if self._embedding is None:
            self._embedding = ModelFactory.create_embedding()
        return self._embedding

    def _collection_name(self, kb_id: int) -> str:
        return f"chunks_kb_{kb_id}"

    async def _ensure_collection(self, kb_id: int):
        """Ensure collection exists, create if not (async, 不阻塞事件循环)."""
        name = self._collection_name(kb_id)
        try:
            await asyncio.to_thread(self.qdrant.get_collection, name)
        except Exception as e:
            logger.debug(f"Collection '{name}' not found, creating: {e}")
            await asyncio.to_thread(
                self.qdrant.create_collection,
                collection_name=name,
                vectors_config=VectorParams(
                    size=settings.EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            )

    async def retrieve(
        self,
        query: str,
        kb_id: int,
        top_k: int = 10,
        filters: dict | None = None,
        alpha: float | None = None,
    ) -> list[dict]:
        """Run hybrid retrieval and return fused top-k chunks.

        filters: 可选的元数据过滤条件，例如
            {"doc_id": 123, "file_type": "pdf", "source_page": 3, "heading": "..."}
            filters=None 或空 dict 时不过滤（行为与原来完全一致）。
            字段映射：source_page -> Qdrant payload "page"。
            向量检索通过 Qdrant Filter 下推过滤；BM25 检索在内存中过滤。

        alpha: BM25/向量加权融合权重 [0,1]。None 时走 RRF 融合（默认，向后兼容）；
               1.0 纯向量检索，0.0 纯 BM25 检索，0.5 等权加权。
               优先级：参数 > KB 配置（Task 2.8）> 全局 settings.RETRIEVAL_ALPHA；
               当前未传 alpha 即走 RRF，全局/KB 覆盖链路由 Task 2.8 接入。
        """
        RAG_RETRIEVAL_TOTAL.labels(kb_id=str(kb_id)).inc()
        total_start = time.perf_counter()
        # 先获取 BM25 所需的 chunks 元数据（缓存命中时 O(1)），
        # bm25_store.search 依赖该数据，需在并行前就绪
        chunks_for_bm25 = await self._get_chunks_for_bm25(kb_id)
        # 构建 Qdrant Filter（filters 为空时返回 None，不过滤）
        qdrant_filter = self._build_qdrant_filter(filters)
        # 并行执行 vector + BM25 检索，缩短端到端延迟
        # 异常处理：_vector_search 内部已 try/except 返回 []；
        # bm25_store.search 异常向上传播（与原串行行为一致）
        vec_t0 = time.perf_counter()
        bm25_t0 = time.perf_counter()
        vec_results, bm25_results = await asyncio.gather(
            self._vector_search(query, kb_id, top_k * 2, qdrant_filter=qdrant_filter),
            bm25_store.search(kb_id, query, top_k * 2, chunks=chunks_for_bm25),
        )
        # BM25 内存过滤（filters 为空时直接返回原结果，无额外开销）
        bm25_results = self._filter_bm25_results(bm25_results, filters)
        RAG_RETRIEVAL_LATENCY.labels(stage="vector").observe(time.perf_counter() - vec_t0)
        RAG_RETRIEVAL_LATENCY.labels(stage="bm25").observe(time.perf_counter() - bm25_t0)
        rrf_t0 = time.perf_counter()
        if alpha is None:
            # 默认走 RRF 融合，保持向后兼容（避免破坏现有测试）
            merged = self._rrf_fuse(vec_results, bm25_results)
        else:
            # alpha 显式传入：加权融合替代 RRF（alpha=1.0 纯向量，0.0 纯 BM25）
            merged = self._weighted_fuse(vec_results, bm25_results, alpha)
        RAG_RETRIEVAL_LATENCY.labels(stage="rrf").observe(time.perf_counter() - rrf_t0)
        RAG_RETRIEVAL_LATENCY.labels(stage="total").observe(time.perf_counter() - total_start)
        return merged[:top_k]

    async def _get_chunks_for_bm25(self, kb_id: int) -> list[dict]:
        """获取 KB 的所有 chunks 元数据（带缓存 + singleflight）。

        首次调用从 DB 加载并缓存，后续直接返回缓存。
        通过 invalidate_chunks_cache 在文档增删时主动失效。
        使用 LRU 策略限制缓存大小，超限 KB 不缓存以防内存爆炸。

        singleflight 模式：多个并发请求 miss 时，只允许第一个加载，
        其他请求等待 per-kb_id 锁，结果共享。
        """
        # Fast path: cache hit（无锁读取，asyncio 单线程无竞争）
        if kb_id in self._chunks_cache:
            # 命中缓存：更新访问顺序（LRU）
            self._chunks_cache.move_to_end(kb_id)
            return self._chunks_cache[kb_id]

        # Slow path: 持有 per-kb_id 锁，防止并发重复加载
        kb_lock = self._get_chunks_lock(kb_id)
        async with kb_lock:
            # Double-check：等待锁期间可能已被其他请求加载
            if kb_id in self._chunks_cache:
                self._chunks_cache.move_to_end(kb_id)
                return self._chunks_cache[kb_id]
            chunks = await self._load_chunks_for_bm25(kb_id)
            # 空列表不缓存：DB 瞬时故障返回 [] 时让下次请求重试，避免永久缓存空结果
            if not chunks:
                logger.warning("KB {} loaded empty chunks, skip cache to allow retry", kb_id)
                return chunks
            # 单个 KB chunks 数量超限：返回数据供本次使用，但不写入缓存
            if len(chunks) > settings.BM25_CACHE_MAX_CHUNKS_PER_KB:
                logger.warning(
                    "KB {} has {} chunks exceeding limit {}, skipping cache",
                    kb_id,
                    len(chunks),
                    settings.BM25_CACHE_MAX_CHUNKS_PER_KB,
                )
                return chunks
            self._chunks_cache[kb_id] = chunks
            # LRU 淘汰：缓存条目数超过上限时移除最久未访问的 KB
            if len(self._chunks_cache) > settings.BM25_CACHE_MAX_KB:
                self._chunks_cache.popitem(last=False)
            return chunks

    def invalidate_chunks_cache(self, kb_id: int):
        """文档增删后失效该 KB 的 chunks 缓存。

        注意：只清理 cache，不清理 singleflight 锁。
        原因：正在加载的协程持有的锁对象若被从 _chunks_locks 移除，
        新请求会创建新锁导致 singleflight 失效、重复加载。
        锁有 LRU 自然淘汰，不会内存泄漏。
        """
        self._chunks_cache.pop(kb_id, None)

    async def _load_chunks_for_bm25(self, kb_id: int) -> list[dict]:
        """Load all chunks of a KB from DB for BM25 search."""
        try:
            from sqlalchemy import select

            from app.database import async_session
            from app.db.document import Document
            from app.db.document_chunk import DocumentChunk

            async with async_session() as session:
                result = await session.execute(
                    select(
                        DocumentChunk.id,
                        DocumentChunk.doc_id,
                        DocumentChunk.content,
                        DocumentChunk.chunk_index,
                    )
                    .join(Document, DocumentChunk.doc_id == Document.id)
                    .where(Document.kb_id == kb_id)
                    .order_by(DocumentChunk.id)
                )
                rows = result.all()
                return [
                    {
                        "chunk_id": r[0],
                        "doc_id": r[1],
                        "content": r[2],
                        "chunk_index": r[3],
                    }
                    for r in rows
                ]
        except Exception as e:
            # Task 29: 区分连接异常（致命，logger.error）与数据异常（可降级，logger.warning）。
            # 返回值不变（均返回空列表），仅调整日志级别以便运维定位。
            if isinstance(
                e,
                OperationalError
                | InterfaceError
                | DisconnectionError
                | SATimeoutError
                | ConnectionError
                | OSError
                | asyncio.TimeoutError,
            ):
                logger.error("_load_chunks_for_bm25 connection error: {}", e)
            else:
                logger.warning("_load_chunks_for_bm25 data error (degraded): {}", e)
            return []

    async def _get_cached_query_embedding(self, query: str, model_name: str) -> list[float]:
        """获取 query embedding，带 Redis 缓存（TTL 300s）。

        缓存 key 包含 model_name，避免不同 embedding 模型向量混淆。
        Redis 不可用或异常时 fallback 到直接计算，不影响检索。
        """
        cache_key = f"emb:{model_name}:" f"{hashlib.sha256(query.encode('utf-8')).hexdigest()}"
        # 命中：直接反序列化返回
        try:
            redis = get_redis()
            if redis is not None:
                cached = await redis.get(cache_key)
                if cached is not None:
                    return json.loads(cached)
        except Exception as e:
            logger.warning("query embedding cache read failed, fallback to compute: {}", e)

        # 未命中或 Redis 不可用：调 embedding 计算
        query_vec = await self.embedding.embed([query])
        vector = query_vec[0]

        # 写回缓存（失败仅告警，不影响结果）
        try:
            redis = get_redis()
            if redis is not None:
                await redis.setex(cache_key, 300, json.dumps(vector))
        except Exception as e:
            logger.warning("query embedding cache write failed: {}", e)

        return vector

    # filter key -> Qdrant payload key 的映射。
    # source_page 对应 payload 中的 "page" 字段（见 add_chunks payload 结构）。
    # heading 当前 payload 中不存在，预留以备 Task 3.2 扩展。
    _FILTER_KEY_MAP = {
        "doc_id": "doc_id",
        "file_type": "file_type",
        "source_page": "page",
        "heading": "heading",
    }

    def _build_qdrant_filter(self, filters: dict) -> Filter | None:
        """根据 filters dict 构建 Qdrant Filter 对象。

        输入示例: {"doc_id": 123, "file_type": "pdf", "source_page": 3}
        输出: Filter(must=[FieldCondition(...), ...]) 或 None

        - 多个条件以 AND（must）组合。
        - filters=None 或空 dict 时返回 None（不过滤，行为与原来一致）。
        - 未识别的 key 原样作为 payload key 使用（兼容未来扩展字段）。
        """
        if not filters:
            return None
        conditions = []
        for filter_key, value in filters.items():
            payload_key = self._FILTER_KEY_MAP.get(filter_key, filter_key)
            conditions.append(
                FieldCondition(
                    key=payload_key,
                    match=MatchValue(value=value),
                )
            )
        if not conditions:
            return None
        return Filter(must=conditions)

    def _filter_bm25_results(self, results: list[dict], filters: dict) -> list[dict]:
        """对 BM25 返回结果按 metadata 做内存过滤。

        BM25 返回的 chunk 是 flat dict，元数据字段直接 inline
        （doc_id / file_type / page 等，取决于 chunks 加载来源）。

        - filters=None 或空 dict 时直接返回原结果（无额外开销）。
        - 字段映射与 _build_qdrant_filter 一致（source_page -> page）。
        - 若 chunk 缺少被过滤的字段，跳过该条件（保留 chunk，兼容旧数据）。
          这样在 Task 3.2 落地 metadata 前，filter 逻辑已就绪而不误剔旧数据。
        """
        if not filters:
            return results
        filtered = []
        for chunk in results:
            keep = True
            for filter_key, value in filters.items():
                payload_key = self._FILTER_KEY_MAP.get(filter_key, filter_key)
                if payload_key not in chunk:
                    # chunk 无该 metadata 字段，跳过过滤（兼容旧数据）
                    continue
                if chunk.get(payload_key) != value:
                    keep = False
                    break
            if keep:
                filtered.append(chunk)
        return filtered

    async def _vector_search(
        self, query: str, kb_id: int, top_k: int, qdrant_filter: Filter | None = None
    ) -> list[dict]:
        try:
            # 获取 embedding 模型名（兼容 CachedEmbeddingProvider 包装）
            emb = self.embedding
            model_name = (
                getattr(emb, "model", None)
                or getattr(getattr(emb, "inner", None), "model", None)
                or "unknown"
            )
            query_vec = await self._get_cached_query_embedding(query, model_name)
            await self._ensure_collection(kb_id)
            # Bug 2: qdrant-client >= 1.10 removed .search(); use .query_points().
            # query_filter=None 时 Qdrant 不过滤，行为与原来一致。
            response = await asyncio.to_thread(
                self.qdrant.query_points,
                collection_name=self._collection_name(kb_id),
                query=query_vec,
                query_filter=qdrant_filter,
                limit=top_k,
                with_payload=True,
            )
            chunks = []
            for point in response.points:
                payload = point.payload or {}
                # Task 13: 过滤低于 score 阈值的 chunks，避免低质量上下文进入 prompt
                if point.score is not None and point.score < settings.RETRIEVAL_SCORE_THRESHOLD:
                    continue
                chunks.append(
                    {
                        "chunk_id": payload.get("chunk_id", point.id),
                        "doc_id": payload.get("doc_id"),
                        "kb_id": payload.get("kb_id", kb_id),
                        "filename": payload.get("filename", ""),
                        "content": payload.get("content", ""),
                        "page": payload.get("page"),
                        "score": point.score,
                        "source": "vector",
                    }
                )
            return chunks
        except Exception as e:
            # Task 29: 区分连接异常（致命，logger.error）与数据异常（可降级，logger.warning）。
            # 返回值不变（均返回空列表），仅调整日志级别以便运维定位。
            if isinstance(
                e,
                ConnectionError | OSError | asyncio.TimeoutError | ResponseHandlingException,
            ):
                logger.error("vector search connection error: {}", e)
            else:
                logger.warning("vector search data error (degraded): {}", e)
            return []

    async def add_chunks(self, kb_id: int, chunks: list[dict], vectors: list[list[float]]):
        """Add chunks to Qdrant collection."""
        await self._ensure_collection(kb_id)
        points = []
        for i, (chunk, vec) in enumerate(zip(chunks, vectors, strict=False)):
            point_id = chunk.get("chunk_id") or chunk.get("id") or i + 1
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vec,
                    payload={
                        "chunk_id": point_id,
                        "doc_id": chunk.get("doc_id"),
                        "kb_id": kb_id,
                        "filename": chunk.get("filename", ""),
                        "content": chunk.get("content", ""),
                        "chunk_index": chunk.get("chunk_index", i),
                        "file_type": chunk.get("file_type", ""),
                        "page": chunk.get("page"),
                    },
                )
            )
        await asyncio.to_thread(
            self.qdrant.upsert,
            collection_name=self._collection_name(kb_id),
            points=points,
        )
        # 失效 chunks 缓存，下次检索会重新加载
        self.invalidate_chunks_cache(kb_id)

    def delete_by_doc_id(self, kb_id: int, doc_id: int):
        """Delete all chunks for a document."""
        try:
            self.qdrant.delete(
                collection_name=self._collection_name(kb_id),
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="doc_id",
                            match=MatchValue(value=doc_id),
                        ),
                    ],
                ),
            )
        except Exception as e:
            logger.warning("delete_by_doc_id failed: {}", e)
        # 失效 chunks 缓存
        self.invalidate_chunks_cache(kb_id)

    def delete_collection(self, kb_id: int):
        """Delete entire collection for a knowledge base."""
        try:
            self.qdrant.delete_collection(self._collection_name(kb_id))
        except Exception as e:
            logger.warning("delete_collection failed: {}", e)
        # 失效 chunks 缓存
        self.invalidate_chunks_cache(kb_id)

    async def close(self) -> None:
        """Close Qdrant client and clear in-memory caches.

        Called during application shutdown to gracefully release connections.
        Embedding provider is closed separately by ModelFactory.close_all().
        """
        if self._qdrant_client is not None:
            try:
                await asyncio.to_thread(self._qdrant_client.close)
            except Exception as e:
                logger.warning("Error closing Qdrant client: {}", e)
            self._qdrant_client = None
        # Clear in-memory caches
        self._chunks_cache.clear()
        self._chunks_locks.clear()
        # Embedding provider is managed by ModelFactory.close_all() in main.py
        self._embedding = None

    def _rrf_fuse(
        self, vec_results: list[dict], bm25_results: list[dict], k: int = settings.RRF_K
    ) -> list[dict]:
        """Reciprocal Rank Fusion.

        Both vec_results and bm25_results are lists of dicts with 'chunk_id' key.
        Score = sum of 1/(k + rank + 1) for each list.
        """
        rrf_scores = {}
        chunk_map = {}

        # Vector results
        for rank, r in enumerate(vec_results):
            cid = r["chunk_id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0) + 1 / (k + rank + 1)
            if cid not in chunk_map:
                chunk_map[cid] = dict(r)

        # BM25 results (now dicts, not tuples)
        for rank, r in enumerate(bm25_results):
            cid = r.get("chunk_id")
            if cid is None:
                continue
            rrf_scores[cid] = rrf_scores.get(cid, 0) + 1 / (k + rank + 1)
            if cid not in chunk_map:
                chunk_map[cid] = {
                    "chunk_id": cid,
                    "doc_id": r.get("doc_id"),
                    "filename": r.get("filename", ""),
                    "content": r.get("content", ""),
                    "page": r.get("page"),
                    "score": r.get("score", 0),
                    "source": "bm25",
                }

        sorted_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)
        result = []
        for cid in sorted_ids:
            chunk = dict(chunk_map.get(cid, {"chunk_id": cid}))
            chunk["rrf_score"] = rrf_scores[cid]
            result.append(chunk)
        return result

    @staticmethod
    def _normalize(scores: dict) -> dict:
        """min-max 归一化到 [0, 1]。

        边界：空 dict 返回空；单元素 dict（或所有值相等）返回 {id: 1.0}，
        避免 max==min 时除零。
        """
        if not scores:
            return {}
        vals = list(scores.values())
        vmin, vmax = min(vals), max(vals)
        if vmax == vmin:
            return {k: 1.0 for k in scores}
        return {k: (v - vmin) / (vmax - vmin) for k, v in scores.items()}

    def _weighted_fuse(
        self, vec_results: list[dict], bm25_results: list[dict], alpha: float
    ) -> list[dict]:
        """加权融合：final = alpha * norm(vec_score) + (1-alpha) * norm(bm25_score)。

        alpha=1.0 纯向量检索（BM25 权重为 0），alpha=0.0 纯 BM25（向量权重为 0）。
        score 先按各自来源 min-max 归一化到 [0,1]，再加权求和。
        """
        chunk_map = {}
        vec_scores: dict = {}
        for r in vec_results:
            cid = r["chunk_id"]
            vec_scores[cid] = r.get("score", 0.0)
            if cid not in chunk_map:
                chunk_map[cid] = dict(r)

        bm25_scores: dict = {}
        for r in bm25_results:
            cid = r.get("chunk_id")
            if cid is None:
                continue
            bm25_scores[cid] = r.get("score", 0.0)
            if cid not in chunk_map:
                chunk_map[cid] = {
                    "chunk_id": cid,
                    "doc_id": r.get("doc_id"),
                    "filename": r.get("filename", ""),
                    "content": r.get("content", ""),
                    "page": r.get("page"),
                    "score": r.get("score", 0),
                    "source": "bm25",
                }

        vec_norm = self._normalize(vec_scores)
        bm25_norm = self._normalize(bm25_scores)

        final_scores = {}
        for cid in chunk_map:
            final_scores[cid] = alpha * vec_norm.get(cid, 0.0) + (1 - alpha) * bm25_norm.get(
                cid, 0.0
            )

        sorted_ids = sorted(final_scores, key=final_scores.get, reverse=True)
        result = []
        for cid in sorted_ids:
            chunk = dict(chunk_map.get(cid, {"chunk_id": cid}))
            chunk["fused_score"] = final_scores[cid]
            result.append(chunk)
        return result


retriever = HybridRetriever()
