"""Celery task: parse -> chunk -> embed -> store.

Uses synchronous SQLAlchemy session (psycopg2) for Celery worker.
Embeddings via ModelFactory.create_embedding() (with Redis cache layer
when EMBEDDING_CACHE_ENABLED=True). Concurrency & retries handled inside
the embedding provider.
Progress tracked via Redis (doc:progress:{doc_id}).
"""

import asyncio
import json

import redis as redis_sync
from loguru import logger

from app.config import settings
from app.db.document import Document
from app.db.document_chunk import DocumentChunk
from app.db.sync_session import get_sync_session
from app.parsers import get_parser
from app.parsers.chunker import chunker
from app.rag.retriever import retriever
from app.tasks.celery_app import celery_app

# 模块级 Redis 连接单例（Celery worker 线程安全, 复用连接池避免泄漏）
_redis_sync_client: redis_sync.Redis | None = None


def _get_redis_sync() -> redis_sync.Redis | None:
    """Get sync Redis client for progress tracking (module-level singleton)."""
    global _redis_sync_client
    if _redis_sync_client is None:
        try:
            client = redis_sync.from_url(settings.redis_url, decode_responses=True)
            client.ping()
            _redis_sync_client = client
        except Exception as e:
            logger.debug(f"Redis sync client init failed: {e}")
            return None
    return _redis_sync_client


def _update_progress(
    doc_id: int, status: str, progress: int, chunk_count: int = 0, error: str | None = None
) -> None:
    """Update progress in both PG and Redis."""
    session = get_sync_session()
    try:
        doc = session.get(Document, doc_id)
        if not doc:
            return
        doc.status = status
        if chunk_count:
            doc.chunk_count = chunk_count
        # 显式覆盖 error_message：error=None 时清空历史错误信息（如重试成功后 done 状态）
        doc.error_message = error
        try:
            session.commit()
        except Exception as e:
            logger.debug(f"Update progress commit failed: {e}")
            if session.is_active:
                session.rollback()
            raise
        # Task 17: Redis 写入移到 session.close() 之前，避免 session 已关闭时进度丢失
        # Redis 写入失败不影响主流程（DB 已 commit）
        try:
            r = _get_redis_sync()
            if r:
                data = {
                    "status": status,
                    "progress": progress,
                    "chunk_count": chunk_count,
                    "error_message": error or "",
                }
                # Task 40: 进度缓存 TTL 迁移到 config.py
                r.setex(
                    f"doc:progress:{doc_id}",
                    settings.DOC_PROGRESS_CACHE_TTL,
                    json.dumps(data),
                )
        except Exception as e:
            logger.warning(f"Redis progress write failed: {e}")
    finally:
        session.close()


def _get_document_status(doc_id: int) -> str | None:
    """Fetch current document status for idempotency check (Task 34).

    Returns None if document not found.
    单独抽出便于在测试中 mock，避免触发真实 DB 会话。
    """
    session = get_sync_session()
    try:
        doc = session.get(Document, doc_id)
        return doc.status if doc else None
    finally:
        session.close()


def _cleanup_old_chunks(doc_id: int, kb_id: int) -> None:
    """Delete old chunks (PG + Qdrant) before re-parsing."""
    session = get_sync_session()
    try:
        from sqlalchemy import delete

        session.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc_id))
        session.commit()
    except Exception as e:
        logger.debug(f"Cleanup old chunks failed: {e}")
        if session.is_active:
            session.rollback()
        raise
    finally:
        session.close()

    try:
        retriever.delete_by_doc_id(kb_id, doc_id)
    except Exception as e:
        logger.warning(f"Qdrant cleanup failed: {e}")


def _parse_and_chunk(doc_id: int) -> list[dict]:
    """Parse the file and split into chunks. Persist chunks to PG."""
    session = get_sync_session()
    try:
        doc = session.get(Document, doc_id)
        if not doc:
            raise ValueError(f"Document {doc_id} not found")

        _cleanup_old_chunks(doc_id, doc.kb_id)

        parser = get_parser(doc.file_path)
        if not parser:
            raise ValueError(f"Unsupported file type: {doc.file_type}")

        text = parser.parse(doc.file_path)
        chunks = chunker.chunk(text)

        chunk_records = []
        chunk_objs = []
        for i, c in enumerate(chunks):
            chunk = DocumentChunk(
                doc_id=doc_id,
                kb_id=doc.kb_id,
                chunk_index=i,
                content=c["content"],
                char_count=c["char_count"],
            )
            chunk_objs.append(chunk)
            chunk_records.append(c)
        session.add_all(chunk_objs)
        session.commit()

        from sqlalchemy import select

        result = session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.doc_id == doc_id)
            .order_by(DocumentChunk.chunk_index)
        )
        db_chunks = result.scalars().all()
        for i, dc in enumerate(db_chunks):
            chunk_records[i]["chunk_id"] = dc.id
            chunk_records[i]["doc_id"] = doc.id
            chunk_records[i]["kb_id"] = doc.kb_id
            chunk_records[i]["filename"] = doc.filename
            chunk_records[i]["file_type"] = doc.file_type

        return chunk_records
    except Exception as e:
        logger.debug(f"Parse and chunk failed: {e}")
        if session.is_active:
            session.rollback()
        raise
    finally:
        session.close()


async def _embed_texts_async(texts: list[str]) -> list[list[float]]:
    """Embed texts via ModelFactory (with Redis cache layer if enabled).

    并发控制 (Semaphore) 与重试由 OllamaEmbeddingProvider.embed 内部处理；
    若 EMBEDDING_CACHE_ENABLED=True，CachedEmbeddingProvider 在外层加 Redis 缓存。

    注意：Celery 通过 _embed_texts_sync 每次创建新 event loop。
    CachedEmbeddingProvider 是单例，其 async Redis 连接绑定到创建时的 loop，
    跨 loop 复用会触发 "Event loop is closed"。因此每次调用前重置连接，
    强制在当前 loop 中重建连接。缓存未启用时无 reset_connection 方法，跳过。
    """
    from app.models.factory import ModelFactory

    embedding = ModelFactory.create_embedding()
    # Task 35: 通过公开方法 reset_connection() 重置连接，避免访问私有属性 _redis
    if hasattr(embedding, "reset_connection"):
        embedding.reset_connection()
    return await embedding.embed(texts)


def _embed_and_store(doc_id: int, chunks: list[dict]) -> None:
    """Embed all chunks and store in Qdrant + rebuild BM25 index.

    Bug 8: After retriever.add_chunks succeeds, backfill vector_id
    into document_chunks so we can trace PG row -> Qdrant point.
    Uses sync psycopg2 session (we are inside the Celery worker).
    """
    if not chunks:
        return

    texts = [c["content"] for c in chunks]
    kb_id = chunks[0]["kb_id"]

    # 单一事件循环完成 embedding + Qdrant 写入（避免创建多个事件循环）
    loop = asyncio.new_event_loop()
    try:
        vectors = loop.run_until_complete(_embed_texts_async(texts))

        async def _add():
            await retriever.add_chunks(kb_id, chunks, vectors)

        loop.run_until_complete(_add())
    finally:
        loop.close()

    session = get_sync_session()
    try:
        from sqlalchemy import update as sa_update

        for chunk in chunks:
            chunk_id = chunk.get("chunk_id")
            if chunk_id is None:
                continue
            point_id = str(chunk_id)
            session.execute(
                sa_update(DocumentChunk)
                .where(DocumentChunk.id == chunk_id)
                .values(vector_id=point_id)
            )
        session.commit()
    except Exception as e:
        logger.warning(f"backfill vector_id failed: {e}")
        if session.is_active:
            try:
                session.rollback()
            except Exception as re:
                logger.debug(f"Rollback after backfill failure failed: {re}")
    finally:
        session.close()

    try:
        # Phase F2: 增量追加新文档 chunks 到 BM25 索引（而非全量 rebuild）
        # 避免覆盖 kb 中其他文档的索引数据
        from app.rag.bm25 import bm25_store

        bm25_store.add_documents_sync(kb_id, chunks)
    except Exception as e:
        logger.warning(f"BM25 incremental update failed: {e}")


@celery_app.task(
    bind=True,
    max_retries=settings.TASK_MAX_RETRIES_PARSING,
    name="app.tasks.document_task.parse_document",
)
def parse_document_task(self, doc_id: int) -> dict | None:
    """Parse -> chunk -> embed -> store. Tracks progress via Redis.

    Retry with exponential backoff: 1s, 2s, 4s.
    Only retries on transient errors (network, 5xx, etc.).

    幂等性 (Task 34): task_acks_late=True 启用后, Celery 可能在 worker
    崩溃/重启时重新投递任务。通过检查 doc.status 跳过已完成 (done) 或
    正在处理 (parsing) 的文档, 避免重复解析。failed/pending 状态不跳过,
    允许用户重试失败的文档。
    """
    # === 幂等性检查 (Task 34) + TOCTOU 修复 (Task 4) ===
    # 乐观锁：原子地检查状态并设为 parsing，消除 SELECT-then-UPDATE 的 TOCTOU 竞态。
    # 原实现先用 _get_document_status SELECT 再判断，与后续 _update_progress(parsing)
    # 之间存在窗口期，可能被其他 worker 抢占导致重复解析。
    # 现使用单条 UPDATE...RETURNING：仅当 status NOT IN (done, parsing) 时改为 parsing。
    # done: 已完成，跳过；parsing: 其他 worker 正在处理，跳过；
    # failed/pending/retrying/chunking/embedding: 允许继续（支持失败重试 & acks_late 重投递）。
    from sqlalchemy import update as sa_update

    session = get_sync_session()
    try:
        result = session.execute(
            sa_update(Document)
            .where(
                Document.id == doc_id,
                ~Document.status.in_(["done", "parsing"]),
            )
            .values(status="parsing")
            .returning(Document)
        )
        doc = result.scalar_one_or_none()
        session.commit()
    except Exception as e:
        logger.debug(f"Idempotency claim failed: {e}")
        if session.is_active:
            session.rollback()
        raise
    finally:
        session.close()

    if doc is None:
        # 文档不存在，或状态为 done/parsing（已被其他 worker 抢占）
        current_status = _get_document_status(doc_id)
        if current_status is None:
            logger.warning(f"Document {doc_id} not found, skipping (idempotent)")
        elif current_status == "done":
            logger.info(f"Document {doc_id} already done, skipping (idempotent)")
        else:
            logger.warning(
                f"Document {doc_id} is being parsed by another worker, skipping (idempotent)"
            )
        return
    # === 幂等性检查结束 ===

    try:
        _update_progress(doc_id, "parsing", 10)
        chunks = _parse_and_chunk(doc_id)

        _update_progress(doc_id, "chunking", 30, chunk_count=len(chunks))

        _update_progress(doc_id, "embedding", 60, chunk_count=len(chunks))
        _embed_and_store(doc_id, chunks)

        _update_progress(doc_id, "done", 100, chunk_count=len(chunks))

        # 发布 DOCUMENT_PARSED 事件
        # Bug 11: EventBus 已在 worker_process_init 中初始化, 此处仅 publish,
        # 不再每次 init/close, 避免 Redis 连接与 listener task 泄漏。
        # 复用 worker 进程级事件循环 (EventBus._redis 绑定到该 loop)。
        try:
            loop = None
            created_loop = False
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError("event loop closed")
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                created_loop = True

            async def _publish():
                from app.core.events import EventBus

                session = get_sync_session()
                try:
                    doc = session.get(Document, doc_id)
                    uploader_id = doc.uploader_id if doc else None
                    filename = doc.filename if doc else ""
                    kb_id = doc.kb_id if doc else None
                finally:
                    session.close()
                await EventBus.publish(
                    EventBus.DOCUMENT_PARSED,
                    {
                        "doc_id": doc_id,
                        "filename": filename,
                        "kb_id": kb_id,
                        "uploader_id": uploader_id,
                        "chunk_count": len(chunks),
                    },
                )

            try:
                loop.run_until_complete(_publish())
            finally:
                # Task 14: 确保新建的事件循环一定被关闭，避免 loop 泄漏
                if created_loop and loop is not None:
                    loop.close()
        except Exception as e:
            logger.warning(f"Failed to publish DOCUMENT_PARSED event: {e}")

        # Phase 5 / H49: 业务指标 - 文档解析成功计数
        from app.core.metrics import DOC_PARSE_SUCCESS_TOTAL

        DOC_PARSE_SUCCESS_TOTAL.inc()
        return {"doc_id": doc_id, "chunk_count": len(chunks), "status": "done"}
    except Exception as e:
        logger.exception(f"Document parse failed for doc_id={doc_id}")
        # Phase 5 / H49: 业务指标 - 文档解析失败计数
        from app.core.metrics import DOC_PARSE_FAILURE_TOTAL

        DOC_PARSE_FAILURE_TOTAL.labels(failure_reason=type(e).__name__).inc()
        retry_count = self.request.retries
        if retry_count >= self.max_retries:
            _update_progress(doc_id, "failed", 100, error="文档解析失败，请重试或联系管理员")
        else:
            # 更新进度为 retrying, 让前端知道正在重试
            _update_progress(
                doc_id, "retrying", 50, error=f"正在重试 {retry_count + 1}/{self.max_retries}"
            )
        raise self.retry(exc=e, countdown=2**retry_count) from e
