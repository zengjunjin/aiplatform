"""BM25 keyword retrieval store.

Provides BOTH async methods (for FastAPI handlers) and sync methods
(for Celery tasks). The sync methods use a synchronous Redis client
so they work inside Celery's sync worker without an event loop.

增量更新（Phase F2）：
- 在 Redis 维护 `bm25:kb:{kb_id}:chunks` list 存该 kb 的全部 chunks 元数据
- `add_documents` / `add_documents_sync` 增量追加新 chunks 后重建 BM25Okapi 索引
- `remove_document` / `remove_document_sync` 删除指定 doc 的 chunks 后重建
- `delete` 清空整个 kb 的索引和 chunks 元数据

注意：rank-bm25 的 BM25Okapi 不支持原地增量更新，必须重建索引，
但通过 Redis 缓存 chunks 元数据，调用方只需传入"新增/删除"的 chunks，
无需自行加载整个 kb 的 chunks 列表。
"""
import json
import pickle
from typing import Optional
from rank_bm25 import BM25Okapi
import redis as redis_sync_lib
import redis.asyncio as redis_async_lib
from app.config import settings


class BM25Store:
    """BM25 index manager, cached per knowledge base."""

    def __init__(self):
        self._cache = {}  # in-memory cache
        self._sync_redis: Optional[redis_sync_lib.Redis] = None
        self._async_redis: Optional[redis_async_lib.Redis] = None

    def _key(self, kb_id: int) -> str:
        """BM25 索引（pickle 后 hex）的 Redis key。"""
        return f"bm25:kb:{kb_id}"

    def _chunks_key(self, kb_id: int) -> str:
        """BM25 chunks 元数据列表的 Redis key（JSON list）。"""
        return f"bm25:kb:{kb_id}:chunks"

    # ---------- sync Redis accessor ----------
    def _get_sync_redis(self) -> Optional[redis_sync_lib.Redis]:
        if self._sync_redis is None:
            try:
                self._sync_redis = redis_sync_lib.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                self._sync_redis.ping()
            except Exception:
                self._sync_redis = None
        return self._sync_redis

    # ---------- async Redis accessor ----------
    async def _get_async_redis(self):
        if self._async_redis is None:
            try:
                self._async_redis = redis_async_lib.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                await self._async_redis.ping()
            except Exception:
                self._async_redis = None
        return self._async_redis

    # ---------- building / tokenizing ----------
    def _build(self, chunks: list[dict]) -> BM25Okapi:
        tokenized = [self._tokenize(c["content"]) for c in chunks]
        return BM25Okapi(tokenized)

    def _tokenize(self, text: str) -> list[str]:
        """Simple tokenizer: split by whitespace + per-char for CJK."""
        tokens = list(text.split())
        for ch in text:
            if "\u4e00" <= ch <= "\u9fff":
                tokens.append(ch)
        return tokens

    def _serialize_chunks(self, chunks: list[dict]) -> str:
        """chunks list -> JSON string（用于 Redis 持久化）。
        仅保留必要字段，避免 pickle 跨版本问题。"""
        slim = []
        for c in chunks:
            slim.append({
                "chunk_id": c.get("chunk_id"),
                "doc_id": c.get("doc_id"),
                "kb_id": c.get("kb_id"),
                "content": c.get("content", ""),
                "filename": c.get("filename", ""),
                "file_type": c.get("file_type", ""),
            })
        return json.dumps(slim, ensure_ascii=False)

    def _deserialize_chunks(self, raw: str | None) -> list[dict]:
        if not raw:
            return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

    # ---------- async API (FastAPI handlers) ----------
    async def get_or_build(self, kb_id: int, chunks: list[dict] | None = None) -> Optional[BM25Okapi]:
        if kb_id in self._cache:
            return self._cache[kb_id]

        redis = await self._get_async_redis()
        if redis:
            raw = await redis.get(self._key(kb_id))
            if raw:
                bm25 = pickle.loads(bytes.fromhex(raw))
                self._cache[kb_id] = bm25
                return bm25

        if chunks:
            bm25 = self._build(chunks)
            self._cache[kb_id] = bm25
            if redis:
                await redis.set(self._key(kb_id), pickle.dumps(bm25).hex(), ex=86400)
            return bm25
        return None

    async def search(self, kb_id: int, query: str, top_k: int = 20,
                     chunks: list[dict] | None = None) -> list[dict]:
        """Search BM25 index, return list of {chunk_id, score, content, ...}.

        chunks 参数用于结果回填（chunk_id/doc_id/filename 等元数据）。
        若未传入 chunks，则尝试从 Redis 加载已缓存的 chunks 元数据；
        若 in-memory cache 已命中 BM25 索引，则直接使用（避免重建索引）。
        """
        # 优先使用 in-memory cache 命中的 BM25 索引
        bm25 = self._cache.get(kb_id)
        if bm25 is None:
            # cache 未命中，尝试从 Redis 加载 chunks 元数据以构建索引
            if chunks is None:
                redis = await self._get_async_redis()
                if redis:
                    chunks = self._deserialize_chunks(await redis.get(self._chunks_key(kb_id)))
            bm25 = await self.get_or_build(kb_id, chunks)
        if not bm25:
            return []
        # cache 命中但未传 chunks 时，尝试加载 chunks 元数据用于结果回填
        # （用于回填 chunk_id/doc_id/filename 等；失败则退化为空 content）
        if chunks is None:
            try:
                redis = await self._get_async_redis()
                if redis:
                    chunks = self._deserialize_chunks(await redis.get(self._chunks_key(kb_id)))
            except Exception:
                chunks = None
        tokens = self._tokenize(query)
        scores = bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        # Return dicts with chunk_id mapped from the original chunks list
        results = []
        for idx, score in ranked:
            if chunks and idx < len(chunks):
                chunk = dict(chunks[idx])
                chunk["score"] = float(score)
                chunk["source"] = "bm25"
                results.append(chunk)
            else:
                results.append({
                    "chunk_id": idx,
                    "score": float(score),
                    "content": "",
                    "source": "bm25",
                })
        return results

    async def rebuild(self, kb_id: int, chunks: list[dict]):
        """全量重建 BM25 索引，并缓存 chunks 元数据。"""
        bm25 = self._build(chunks)
        self._cache[kb_id] = bm25
        redis = await self._get_async_redis()
        if redis:
            await redis.set(self._key(kb_id), pickle.dumps(bm25).hex(), ex=86400)
            await redis.set(self._chunks_key(kb_id), self._serialize_chunks(chunks), ex=86400)

    async def add_documents(self, kb_id: int, new_chunks: list[dict]):
        """增量追加新文档 chunks，重建 BM25 索引。

        从 Redis 读取已缓存的 chunks 列表，追加新 chunks，重建索引。
        若 Redis 中无缓存（首次或被清空），则等价于 rebuild。
        """
        if not new_chunks:
            return
        redis = await self._get_async_redis()
        existing: list[dict] = []
        if redis:
            existing = self._deserialize_chunks(await redis.get(self._chunks_key(kb_id)))
        all_chunks = existing + new_chunks
        await self.rebuild(kb_id, all_chunks)

    async def remove_document(self, kb_id: int, doc_id: int):
        """删除指定文档的所有 chunks，重建 BM25 索引。"""
        redis = await self._get_async_redis()
        if not redis:
            return
        existing = self._deserialize_chunks(await redis.get(self._chunks_key(kb_id)))
        remaining = [c for c in existing if c.get("doc_id") != doc_id]
        await self.rebuild(kb_id, remaining)

    async def delete(self, kb_id: int):
        """清空整个 kb 的 BM25 索引和 chunks 元数据。"""
        self._cache.pop(kb_id, None)
        redis = await self._get_async_redis()
        if redis:
            await redis.delete(self._key(kb_id), self._chunks_key(kb_id))

    # ---------- sync API (Celery tasks) ----------
    def rebuild_sync(self, kb_id: int, chunks: list[dict]):
        """全量重建 BM25 索引，并缓存 chunks 元数据（sync 版本）。"""
        bm25 = self._build(chunks)
        self._cache[kb_id] = bm25
        redis = self._get_sync_redis()
        if redis:
            redis.set(self._key(kb_id), pickle.dumps(bm25).hex(), ex=86400)
            redis.set(self._chunks_key(kb_id), self._serialize_chunks(chunks), ex=86400)

    def add_documents_sync(self, kb_id: int, new_chunks: list[dict]):
        """增量追加新文档 chunks，重建 BM25 索引（sync 版本）。

        从 Redis 读取已缓存的 chunks 列表，追加新 chunks，重建索引。
        若 Redis 中无缓存（首次或被清空），则等价于 rebuild_sync。

        使用场景：Celery worker 解析新文档后，只需传入该文档的 chunks，
        无需加载整个 kb 的 chunks 列表，BM25 索引会自动合并。
        """
        if not new_chunks:
            return
        redis = self._get_sync_redis()
        existing: list[dict] = []
        if redis:
            existing = self._deserialize_chunks(redis.get(self._chunks_key(kb_id)))
        all_chunks = existing + new_chunks
        self.rebuild_sync(kb_id, all_chunks)

    def remove_document_sync(self, kb_id: int, doc_id: int):
        """删除指定文档的所有 chunks，重建 BM25 索引（sync 版本）。"""
        redis = self._get_sync_redis()
        if not redis:
            return
        existing = self._deserialize_chunks(redis.get(self._chunks_key(kb_id)))
        remaining = [c for c in existing if c.get("doc_id") != doc_id]
        self.rebuild_sync(kb_id, remaining)

    def search_sync(self, kb_id: int, query: str, top_k: int = 20,
                    chunks: list[dict] | None = None) -> list[dict]:
        """Sync search, return list of {chunk_id, score, content, ...}.

        若未传入 chunks，则尝试从 Redis 加载已缓存的 chunks 元数据。
        """
        if chunks is None:
            redis = self._get_sync_redis()
            if redis:
                chunks = self._deserialize_chunks(redis.get(self._chunks_key(kb_id)))

        if kb_id in self._cache:
            bm25 = self._cache[kb_id]
        else:
            redis = self._get_sync_redis()
            bm25 = None
            if redis:
                raw = redis.get(self._key(kb_id))
                if raw:
                    bm25 = pickle.loads(bytes.fromhex(raw))
                    self._cache[kb_id] = bm25
            if bm25 is None and chunks:
                bm25 = self._build(chunks)
                self._cache[kb_id] = bm25
                if redis:
                    redis.set(self._key(kb_id), pickle.dumps(bm25).hex(), ex=86400)
        if not bm25:
            return []
        tokens = self._tokenize(query)
        scores = bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        results = []
        for idx, score in ranked:
            if chunks and idx < len(chunks):
                chunk = dict(chunks[idx])
                chunk["score"] = float(score)
                chunk["source"] = "bm25"
                results.append(chunk)
            else:
                results.append({
                    "chunk_id": idx,
                    "score": float(score),
                    "content": "",
                    "source": "bm25",
                })
        return results


bm25_store = BM25Store()
