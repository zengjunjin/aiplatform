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

安全：使用 JSON 序列化 tokenized 语料替代 pickle，避免反序列化 RCE 风险。
"""

import asyncio
import json
import threading
from collections import OrderedDict

import redis as redis_sync_lib
import redis.asyncio as redis_async_lib
from loguru import logger
from rank_bm25 import BM25Okapi

from app.config import settings


class BM25Store:
    """BM25 index manager, cached per knowledge base."""

    def __init__(self):
        # in-memory cache: OrderedDict 实现 LRU，避免多租户长期运行 OOM
        self._cache: OrderedDict[int, BM25Okapi] = OrderedDict()
        self._cache_max = 16  # LRU 上限，与项目其他缓存上限一致
        # chunks 元数据内存缓存：kb_id -> list[dict]。
        # 作为 Redis 的 fallback：Redis 不可用或未命中时，从内存读取 chunks 元数据，
        # 避免 search 时 chunks=None 导致结果 content 为空。
        # rebuild/add_documents/remove_document 时同步更新此缓存。
        self._chunks_meta_cache: OrderedDict[int, list[dict]] = OrderedDict()
        self._sync_redis: redis_sync_lib.Redis | None = None
        self._async_redis: redis_async_lib.Redis | None = None
        self._sync_lock = threading.Lock()  # sync API (Celery) 使用 threading.Lock
        self._async_lock: asyncio.Lock | None = None  # async API 使用 asyncio.Lock（lazy init）

    # ---------- chunks 元数据内存缓存（Redis fallback）----------
    def _set_chunks_meta(self, kb_id: int, chunks: list[dict]) -> None:
        """写入 chunks 元数据到内存缓存（LRU 淘汰）。"""
        self._chunks_meta_cache[kb_id] = chunks
        self._chunks_meta_cache.move_to_end(kb_id)
        if len(self._chunks_meta_cache) > self._cache_max:
            self._chunks_meta_cache.popitem(last=False)

    def _get_chunks_meta(self, kb_id: int) -> list[dict] | None:
        """从内存缓存读取 chunks 元数据（命中时更新 LRU 顺序）。"""
        if kb_id in self._chunks_meta_cache:
            self._chunks_meta_cache.move_to_end(kb_id)
            return self._chunks_meta_cache[kb_id]
        return None

    def _pop_chunks_meta(self, kb_id: int) -> None:
        """从内存缓存移除 chunks 元数据。"""
        self._chunks_meta_cache.pop(kb_id, None)

    def _get_async_lock(self) -> asyncio.Lock:
        """获取 async 路径的并发锁（lazy init，避免跨事件循环绑定问题）。

        sync API (Celery tasks) 继续使用 _sync_lock (threading.Lock)，
        async wrappers (get_or_build/search/rebuild) 使用此 asyncio.Lock。
        """
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    def _key(self, kb_id: int) -> str:
        """BM25 索引（JSON 序列化的 tokenized 语料）的 Redis key。"""
        return f"bm25:kb:{kb_id}"

    def _chunks_key(self, kb_id: int) -> str:
        """BM25 chunks 元数据列表的 Redis key（JSON list）。"""
        return f"bm25:kb:{kb_id}:chunks"

    # ---------- sync Redis accessor ----------
    def _get_sync_redis(self) -> redis_sync_lib.Redis | None:
        if self._sync_redis is not None:
            return self._sync_redis
        with self._sync_lock:
            # 双重检查: 锁内再次确认未初始化
            if self._sync_redis is not None:
                return self._sync_redis
            try:
                self._sync_redis = redis_sync_lib.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                self._sync_redis.ping()
            except Exception as e:
                logger.debug(f"BM25 sync redis init failed: {e}")
                self._sync_redis = None
        return self._sync_redis

    # ---------- async Redis accessor ----------
    async def _get_async_redis(self):
        # 健康检查：若缓存的连接绑定到已关闭的 event loop（如 asyncio.run 后再次调用），
        # ping 会抛 "Event loop is closed"，此时重置连接后重新创建。
        if self._async_redis is not None:
            try:
                await self._async_redis.ping()
            except Exception as e:
                # 健康检查失败（如 event loop 已关闭/网络中断），关闭旧连接后重置
                logger.debug(f"BM25 async redis ping failed, resetting: {e}")
                old = self._async_redis
                self._async_redis = None
                try:
                    await old.aclose()
                except Exception:
                    pass
        if self._async_redis is None:
            try:
                self._async_redis = redis_async_lib.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                await self._async_redis.ping()
            except Exception as e:
                logger.debug(f"BM25 async redis init failed: {e}")
                self._async_redis = None
        return self._async_redis

    # ---------- building / tokenizing ----------
    def _build(self, chunks: list[dict]) -> tuple[BM25Okapi, list[list[str]]]:
        """分词 + 构建 BM25Okapi 索引，返回 (bm25, tokenized) 供序列化复用。"""
        tokenized = [self._tokenize(c["content"]) for c in chunks]
        return BM25Okapi(tokenized), tokenized

    def _tokenize(self, text: str) -> list[str]:
        """分词 + 大小写归一化。

        英文搜索需大小写不敏感（"rust" 应匹配 "Rust"），
        故对输入做 .lower() 后再分词。中文不受影响。
        """
        import jieba

        tokens = list(jieba.cut(text.lower()))
        return tokens

    def _serialize_index(self, tokenized: list[list[str]]) -> str:
        """将已分词的语料序列化为 JSON（替代 pickle, 避免 RCE 风险）。

        注意：参数是已分词的 tokenized 列表，不再重复分词（P1-4 修复）。
        """
        return json.dumps(tokenized, ensure_ascii=False)

    def _deserialize_index(self, raw: str | None) -> BM25Okapi | None:
        """从 JSON 反序列化并重建 BM25Okapi 索引。"""
        if not raw:
            return None
        try:
            tokenized = json.loads(raw)
            if not isinstance(tokenized, list):
                return None
            return BM25Okapi(tokenized)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def _serialize_chunks(self, chunks: list[dict]) -> str:
        """chunks list -> JSON string（用于 Redis 持久化）。
        仅保留必要字段，避免跨版本问题。"""
        slim = []
        for c in chunks:
            slim.append(
                {
                    "chunk_id": c.get("chunk_id"),
                    "doc_id": c.get("doc_id"),
                    "kb_id": c.get("kb_id"),
                    "content": c.get("content", ""),
                    "filename": c.get("filename", ""),
                    "file_type": c.get("file_type", ""),
                }
            )
        return json.dumps(slim, ensure_ascii=False)

    def _deserialize_chunks(self, raw: str | None) -> list[dict]:
        if not raw:
            return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

    # ---------- shared CPU core (打分 + 排序 + 结果构建) ----------
    def _search_core(
        self,
        bm25: BM25Okapi,
        chunks: list[dict] | None,
        query: str,
        top_k: int,
    ) -> list[dict]:
        """纯 CPU 函数：tokenize + BM25 打分 + 排序 + 结果回填。

        sync/async 路径共用，调用方负责 IO 层（Redis 读取 / cache 检查）
        与锁（sync=threading.Lock / async=asyncio.Lock）。
        """
        tokens = self._tokenize(query)
        scores = bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:top_k]
        results = []
        for idx, score in ranked:
            # score 阈值过滤：完全未匹配（score==0）或正分但低于阈值的 chunk 不进入 RRF 融合。
            # 注意：BM25Okapi 的 idf 可为负（当词在大部分文档中出现，区分性低），
            # 负分仍表示"词匹配了"，应保留进入 RRF 融合，不应被阈值过滤。
            # 因此过滤条件为 0 <= score < threshold，负分放行。
            if 0 <= score < settings.BM25_SCORE_THRESHOLD:
                continue
            if chunks and idx < len(chunks):
                chunk = dict(chunks[idx])
                chunk["score"] = float(score)
                chunk["source"] = "bm25"
                results.append(chunk)
            else:
                results.append(
                    {
                        "chunk_id": idx,
                        "score": float(score),
                        "content": "",
                        "source": "bm25",
                    }
                )
        return results

    # ---------- async API (FastAPI handlers) ----------
    async def get_or_build(self, kb_id: int, chunks: list[dict] | None = None) -> BM25Okapi | None:
        # cache 命中检查受锁保护，避免与并发 rebuild/delete 竞争
        async with self._get_async_lock():
            if kb_id in self._cache:
                self._cache.move_to_end(kb_id)  # LRU: 更新访问顺序
                return self._cache[kb_id]

        redis = await self._get_async_redis()
        if redis:
            raw = await redis.get(self._key(kb_id))
            if raw:
                # CPU: BM25Okapi 重建，offload 到线程池避免阻塞事件循环
                bm25 = await asyncio.to_thread(self._deserialize_index, raw)
                if bm25:
                    async with self._get_async_lock():
                        self._cache[kb_id] = bm25
                        if len(self._cache) > self._cache_max:
                            self._cache.popitem(last=False)
                    # 同步 chunks 元数据到内存缓存：后续 search 不传 chunks 时，
                    # 需要从内存缓存加载 chunks 用于结果回填。
                    # 若 chunks 参数已传（调用方提供最新数据），优先用 chunks；
                    # 否则从 Redis 加载 chunks 元数据。
                    if chunks:
                        self._set_chunks_meta(kb_id, chunks)
                    else:
                        chunks_raw = await redis.get(self._chunks_key(kb_id))
                        if chunks_raw:
                            chunks_meta = self._deserialize_chunks(chunks_raw)
                            if chunks_meta:
                                self._set_chunks_meta(kb_id, chunks_meta)
                    return bm25

        if chunks:
            # CPU: jieba 分词 + BM25Okapi 构建
            bm25 = await asyncio.to_thread(self._build, chunks)
            async with self._get_async_lock():
                self._cache[kb_id] = bm25
                if len(self._cache) > self._cache_max:
                    self._cache.popitem(last=False)
            # 同步写入内存级 chunks 元数据缓存（Redis fallback）
            self._set_chunks_meta(kb_id, chunks)
            if redis:
                # CPU: jieba 分词 + JSON 序列化
                serialized = await asyncio.to_thread(self._serialize_index, chunks)
                await redis.set(self._key(kb_id), serialized, ex=settings.BM25_INDEX_TTL)
                await redis.set(
                    self._chunks_key(kb_id),
                    self._serialize_chunks(chunks),
                    ex=settings.BM25_INDEX_TTL,
                )
            return bm25
        return None

    async def search(
        self, kb_id: int, query: str, top_k: int = 20, chunks: list[dict] | None = None
    ) -> list[dict]:
        """Search BM25 index, return list of {chunk_id, score, content, ...}.

        chunks 参数用于结果回填（chunk_id/doc_id/filename 等元数据）。
        若未传入 chunks，则尝试从 Redis 加载已缓存的 chunks 元数据；
        若 in-memory cache 已命中 BM25 索引，则直接使用（避免重建索引）。
        """
        # 优先使用 in-memory cache 命中的 BM25 索引
        if kb_id in self._cache:
            bm25 = self._cache[kb_id]
            self._cache.move_to_end(kb_id)  # LRU: 更新访问顺序
        else:
            bm25 = None
        if bm25 is None:
            # cache 未命中，尝试从 Redis 加载 chunks 元数据以构建索引
            if chunks is None:
                redis = await self._get_async_redis()
                if redis:
                    chunks = self._deserialize_chunks(await redis.get(self._chunks_key(kb_id)))
                # Redis 未命中或不可用（返回 None 或 []）：fallback 到内存缓存
                # 注意：_deserialize_chunks 对 None/空串返回 []，需用 `not chunks` 判断
                if not chunks:
                    chunks = self._get_chunks_meta(kb_id)
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
            except Exception as e:
                logger.debug(f"BM25 chunks cache read failed, fallback to None: {e}")
                chunks = None
            # Redis 未命中或不可用（返回 None 或 []）：fallback 到内存缓存
            if not chunks:
                chunks = self._get_chunks_meta(kb_id)
        # CPU: jieba 分词 + BM25 打分 + 排序 + 结果回填，offload 到线程池避免阻塞事件循环
        return await asyncio.to_thread(self._search_core, bm25, chunks, query, top_k)

    async def rebuild(self, kb_id: int, chunks: list[dict]):
        """全量重建 BM25 索引，并缓存 chunks 元数据。"""
        # CPU: jieba 分词 + BM25Okapi 构建，offload 到线程池避免阻塞事件循环
        # _build 返回 (bm25, tokenized)，序列化时复用 tokenized 避免重复分词（P1-4 修复）
        bm25, tokenized = await asyncio.to_thread(self._build, chunks)
        async with self._get_async_lock():
            self._cache[kb_id] = bm25
            if len(self._cache) > self._cache_max:
                self._cache.popitem(last=False)
        # 同步写入内存级 chunks 元数据缓存（Redis fallback）
        self._set_chunks_meta(kb_id, chunks)
        redis = await self._get_async_redis()
        if redis:
            # 复用 _build 已分词的 tokenized，不再重复分词
            serialized_index = await asyncio.to_thread(self._serialize_index, tokenized)
            await redis.set(self._key(kb_id), serialized_index, ex=settings.BM25_INDEX_TTL)
            await redis.set(
                self._chunks_key(kb_id), self._serialize_chunks(chunks), ex=settings.BM25_INDEX_TTL
            )

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
        # Redis 未命中或不可用：fallback 到内存缓存
        if not existing:
            existing = self._get_chunks_meta(kb_id) or []
        all_chunks = existing + new_chunks
        await self.rebuild(kb_id, all_chunks)

    async def remove_document(self, kb_id: int, doc_id: int):
        """删除指定文档的所有 chunks，重建 BM25 索引。"""
        redis = await self._get_async_redis()
        existing: list[dict] = []
        if redis:
            existing = self._deserialize_chunks(await redis.get(self._chunks_key(kb_id)))
        # Redis 未命中或不可用：fallback 到内存缓存
        if not existing:
            existing = self._get_chunks_meta(kb_id) or []
        remaining = [c for c in existing if c.get("doc_id") != doc_id]
        await self.rebuild(kb_id, remaining)

    async def delete(self, kb_id: int):
        """清空整个 kb 的 BM25 索引和 chunks 元数据。"""
        async with self._get_async_lock():
            self._cache.pop(kb_id, None)
        # 同步清理内存级 chunks 元数据缓存
        self._pop_chunks_meta(kb_id)
        redis = await self._get_async_redis()
        if redis:
            await redis.delete(self._key(kb_id), self._chunks_key(kb_id))

    # ---------- sync API (Celery tasks) ----------
    def rebuild_sync(self, kb_id: int, chunks: list[dict]):
        """全量重建 BM25 索引，并缓存 chunks 元数据（sync 版本）。"""
        bm25, tokenized = self._build(chunks)
        self._cache[kb_id] = bm25
        if len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)
        # 同步写入内存级 chunks 元数据缓存（Redis fallback）
        self._set_chunks_meta(kb_id, chunks)
        redis = self._get_sync_redis()
        if redis:
            redis.set(self._key(kb_id), self._serialize_index(tokenized), ex=settings.BM25_INDEX_TTL)
            redis.set(
                self._chunks_key(kb_id), self._serialize_chunks(chunks), ex=settings.BM25_INDEX_TTL
            )

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
        # Redis 未命中或不可用：fallback 到内存缓存
        if not existing:
            existing = self._get_chunks_meta(kb_id) or []
        all_chunks = existing + new_chunks
        self.rebuild_sync(kb_id, all_chunks)

    def remove_document_sync(self, kb_id: int, doc_id: int):
        """删除指定文档的所有 chunks，重建 BM25 索引（sync 版本）。"""
        redis = self._get_sync_redis()
        existing: list[dict] = []
        if redis:
            existing = self._deserialize_chunks(redis.get(self._chunks_key(kb_id)))
        # Redis 未命中或不可用：fallback 到内存缓存
        if not existing:
            existing = self._get_chunks_meta(kb_id) or []
        remaining = [c for c in existing if c.get("doc_id") != doc_id]
        self.rebuild_sync(kb_id, remaining)

    def search_sync(
        self, kb_id: int, query: str, top_k: int = 20, chunks: list[dict] | None = None
    ) -> list[dict]:
        """Sync search, return list of {chunk_id, score, content, ...}.

        若未传入 chunks，则尝试从 Redis 加载已缓存的 chunks 元数据；
        Redis 不可用时 fallback 到内存级 chunks 元数据缓存。
        """
        if chunks is None:
            redis = self._get_sync_redis()
            if redis:
                chunks = self._deserialize_chunks(redis.get(self._chunks_key(kb_id)))
            # Redis 未命中或不可用（返回 None 或 []）：fallback 到内存缓存
            # 注意：_deserialize_chunks 对 None/空串返回 []，需用 `not chunks` 判断
            if not chunks:
                chunks = self._get_chunks_meta(kb_id)

        if kb_id in self._cache:
            bm25 = self._cache[kb_id]
            self._cache.move_to_end(kb_id)  # LRU: 更新访问顺序
        else:
            redis = self._get_sync_redis()
            bm25 = None
            if redis:
                raw = redis.get(self._key(kb_id))
                if raw:
                    bm25 = self._deserialize_index(raw)
                    if bm25:
                        self._cache[kb_id] = bm25
                        if len(self._cache) > self._cache_max:
                            self._cache.popitem(last=False)
            if bm25 is None and chunks:
                bm25, tokenized = self._build(chunks)
                self._cache[kb_id] = bm25
                if len(self._cache) > self._cache_max:
                    self._cache.popitem(last=False)
                # 同步写入内存级 chunks 元数据缓存（Redis fallback）
                self._set_chunks_meta(kb_id, chunks)
                if redis:
                    redis.set(
                        self._key(kb_id), self._serialize_index(tokenized), ex=settings.BM25_INDEX_TTL
                    )
                    redis.set(
                        self._chunks_key(kb_id),
                        self._serialize_chunks(chunks),
                        ex=settings.BM25_INDEX_TTL,
                    )
        if not bm25:
            return []
        return self._search_core(bm25, chunks, query, top_k)

    async def close(self) -> None:
        """Close Redis connections and clear in-memory caches.

        Called during application shutdown to gracefully release resources.
        """
        if self._async_redis is not None:
            try:
                await self._async_redis.aclose()
            except Exception as e:
                logger.warning(f"Error closing BM25 async Redis: {e}")
            self._async_redis = None
        if self._sync_redis is not None:
            try:
                self._sync_redis.close()
            except Exception as e:
                logger.warning(f"Error closing BM25 sync Redis: {e}")
            self._sync_redis = None
        # Clear in-memory caches
        self._cache.clear()
        self._chunks_meta_cache.clear()


bm25_store = BM25Store()
