"""Hybrid retrieval: BM25 + vector + RRF fusion."""
import asyncio
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
    TimeoutError as SATimeoutError,
)

from app.config import settings
from app.core.metrics import RAG_RETRIEVAL_LATENCY, RAG_RETRIEVAL_TOTAL
from app.models.factory import ModelFactory
from app.rag.bm25 import bm25_store


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
        self._chunks_locks: dict[int, asyncio.Lock] = {}

    def _get_chunks_lock(self, kb_id: int) -> asyncio.Lock:
        """获取指定 kb 的 chunks 加载锁（singleflight 模式）。

        多个并发请求 miss 时，只允许第一个加载，其他等待结果。
        asyncio 单线程模型下，dict 读写无 await 间隙，可避免竞争。
        """
        if kb_id not in self._chunks_locks:
            self._chunks_locks[kb_id] = asyncio.Lock()
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
        except Exception:
            await asyncio.to_thread(
                self.qdrant.create_collection,
                collection_name=name,
                vectors_config=VectorParams(
                    size=settings.EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            )

    async def retrieve(self, query: str, kb_id: int,
                       top_k: int = 10) -> list[dict]:
        """Run hybrid retrieval and return fused top-k chunks."""
        RAG_RETRIEVAL_TOTAL.labels(kb_id=str(kb_id)).inc()
        total_start = time.perf_counter()
        # 先获取 BM25 所需的 chunks 元数据（缓存命中时 O(1)），
        # bm25_store.search 依赖该数据，需在并行前就绪
        chunks_for_bm25 = await self._get_chunks_for_bm25(kb_id)
        # 并行执行 vector + BM25 检索，缩短端到端延迟
        # 异常处理：_vector_search 内部已 try/except 返回 []；
        # bm25_store.search 异常向上传播（与原串行行为一致）
        vec_t0 = time.perf_counter()
        bm25_t0 = time.perf_counter()
        vec_results, bm25_results = await asyncio.gather(
            self._vector_search(query, kb_id, top_k * 2),
            bm25_store.search(kb_id, query, top_k * 2, chunks=chunks_for_bm25),
        )
        RAG_RETRIEVAL_LATENCY.labels(stage="vector").observe(time.perf_counter() - vec_t0)
        RAG_RETRIEVAL_LATENCY.labels(stage="bm25").observe(time.perf_counter() - bm25_t0)
        rrf_t0 = time.perf_counter()
        merged = self._rrf_fuse(vec_results, bm25_results)
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
            # 单个 KB chunks 数量超限：返回数据供本次使用，但不写入缓存
            if len(chunks) > settings.BM25_CACHE_MAX_CHUNKS_PER_KB:
                logger.warning(
                    "KB {} has {} chunks exceeding limit {}, skipping cache",
                    kb_id, len(chunks), settings.BM25_CACHE_MAX_CHUNKS_PER_KB,
                )
                return chunks
            self._chunks_cache[kb_id] = chunks
            # LRU 淘汰：缓存条目数超过上限时移除最久未访问的 KB
            if len(self._chunks_cache) > settings.BM25_CACHE_MAX_KB:
                self._chunks_cache.popitem(last=False)
            return chunks

    def invalidate_chunks_cache(self, kb_id: int):
        """文档增删后失效该 KB 的 chunks 缓存。"""
        self._chunks_cache.pop(kb_id, None)
        # 清理 singleflight 锁，避免内存泄漏
        self._chunks_locks.pop(kb_id, None)

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
                (
                    OperationalError,
                    InterfaceError,
                    DisconnectionError,
                    SATimeoutError,
                    ConnectionError,
                    OSError,
                    asyncio.TimeoutError,
                ),
            ):
                logger.error("_load_chunks_for_bm25 connection error: {}", e)
            else:
                logger.warning("_load_chunks_for_bm25 data error (degraded): {}", e)
            return []

    async def _vector_search(self, query: str, kb_id: int,
                             top_k: int) -> list[dict]:
        try:
            query_vec = await self.embedding.embed([query])
            await self._ensure_collection(kb_id)
            # Bug 2: qdrant-client >= 1.10 removed .search(); use .query_points().
            response = await asyncio.to_thread(
                self.qdrant.query_points,
                collection_name=self._collection_name(kb_id),
                query=query_vec[0],
                limit=top_k,
                with_payload=True,
            )
            chunks = []
            for point in response.points:
                payload = point.payload or {}
                # Task 13: 过滤低于 score 阈值的 chunks，避免低质量上下文进入 prompt
                if point.score is not None and point.score < settings.RETRIEVAL_SCORE_THRESHOLD:
                    continue
                chunks.append({
                    "chunk_id": payload.get("chunk_id", point.id),
                    "doc_id": payload.get("doc_id"),
                    "kb_id": payload.get("kb_id", kb_id),
                    "filename": payload.get("filename", ""),
                    "content": payload.get("content", ""),
                    "page": payload.get("page"),
                    "score": point.score,
                    "source": "vector",
                })
            return chunks
        except Exception as e:
            # Task 29: 区分连接异常（致命，logger.error）与数据异常（可降级，logger.warning）。
            # 返回值不变（均返回空列表），仅调整日志级别以便运维定位。
            if isinstance(
                e,
                (
                    ConnectionError,
                    OSError,
                    asyncio.TimeoutError,
                    ResponseHandlingException,
                ),
            ):
                logger.error("vector search connection error: {}", e)
            else:
                logger.warning("vector search data error (degraded): {}", e)
            return []

    async def add_chunks(self, kb_id: int, chunks: list[dict], vectors: list[list[float]]):
        """Add chunks to Qdrant collection."""
        await self._ensure_collection(kb_id)
        points = []
        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            point_id = chunk.get("chunk_id") or chunk.get("id") or i + 1
            points.append(PointStruct(
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
            ))
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

    def _rrf_fuse(self, vec_results: list[dict],
                  bm25_results: list[dict], k: int = settings.RRF_K) -> list[dict]:
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


retriever = HybridRetriever()
