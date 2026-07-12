"""Celery task: parse -> chunk -> embed -> store.

Uses synchronous SQLAlchemy session (psycopg2) for Celery worker.
Embeddings fetched via concurrent async HTTP requests (aiohttp).
Progress tracked via Redis (doc:progress:{doc_id}).
"""
import json
import logging
import asyncio
import redis as redis_sync

from app.tasks.celery_app import celery_app
from app.config import settings
from app.rag.retriever import retriever
from app.db.sync_session import get_sync_session
from app.db.document import Document
from app.db.document_chunk import DocumentChunk
from app.parsers import get_parser
from app.parsers.chunker import chunker

logger = logging.getLogger(__name__)

# 模块级 Redis 连接单例（Celery worker 线程安全, 复用连接池避免泄漏）
_redis_sync_client: redis_sync.Redis | None = None


def _get_redis_sync():
    """Get sync Redis client for progress tracking (module-level singleton)."""
    global _redis_sync_client
    if _redis_sync_client is None:
        try:
            client = redis_sync.from_url(settings.redis_url, decode_responses=True)
            client.ping()
            _redis_sync_client = client
        except Exception:
            return None
    return _redis_sync_client


def _update_progress(doc_id: int, status: str, progress: int,
                     chunk_count: int = 0, error: str | None = None):
    """Update progress in both PG and Redis."""
    session = get_sync_session()
    try:
        doc = session.get(Document, doc_id)
        if not doc:
            return
        doc.status = status
        if chunk_count:
            doc.chunk_count = chunk_count
        if error:
            doc.error_message = error
        try:
            session.commit()
        except Exception:
            session.rollback()
            raise
    finally:
        session.close()

    r = _get_redis_sync()
    if r:
        data = {
            "status": status,
            "progress": progress,
            "chunk_count": chunk_count,
            "error_message": error or "",
        }
        r.setex(f"doc:progress:{doc_id}", 3600, json.dumps(data))


def _cleanup_old_chunks(doc_id: int, kb_id: int):
    """Delete old chunks (PG + Qdrant) before re-parsing."""
    session = get_sync_session()
    try:
        from sqlalchemy import delete
        session.execute(
            delete(DocumentChunk).where(DocumentChunk.doc_id == doc_id)
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    try:
        retriever.delete_by_doc_id(kb_id, doc_id)
    except Exception as e:
        logger.warning("Qdrant cleanup failed: %s", e)


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
        for i, c in enumerate(chunks):
            chunk = DocumentChunk(
                doc_id=doc_id,
                kb_id=doc.kb_id,
                chunk_index=i,
                content=c["content"],
                char_count=c["char_count"],
                            )
            session.add(chunk)
            chunk_records.append(c)
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
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def _embed_texts_async(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts concurrently via aiohttp with semaphore."""
    import aiohttp
    sem = asyncio.Semaphore(settings.EMBEDDING_CONCURRENCY)

    async def _embed_one(session, text):
        async with sem:
            async with session.post(
                f"{settings.OLLAMA_HOST}/api/embeddings",
                json={"model": settings.EMBEDDING_MODEL, "prompt": text},
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["embedding"]

    async with aiohttp.ClientSession() as session:
        tasks = [_embed_one(session, t) for t in texts]
        return await asyncio.gather(*tasks)


def _embed_texts_sync(texts: list[str]) -> list[list[float]]:
    """Run concurrent embedding in a dedicated event loop (Celery worker context)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_embed_texts_async(texts))
    finally:
        loop.close()


def _embed_and_store(doc_id: int, chunks: list[dict]):
    """Embed all chunks and store in Qdrant + rebuild BM25 index.

    Bug 8: After retriever.add_chunks succeeds, backfill vector_id
    into document_chunks so we can trace PG row -> Qdrant point.
    Uses sync psycopg2 session (we are inside the Celery worker).
    """
    if not chunks:
        return

    texts = [c["content"] for c in chunks]
    vectors = _embed_texts_sync(texts)

    kb_id = chunks[0]["kb_id"]

    # 问题: Celery worker 线程可能已有事件循环, asyncio.run() 会创建新循环导致冲突
    # 解决方案: 创建独立的新事件循环, 确保不受影响, 完成后恢复旧循环
    try:
        old_loop = asyncio.get_event_loop()
    except RuntimeError:
        old_loop = None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        async def _add():
            await retriever.add_chunks(kb_id, chunks, vectors)
        loop.run_until_complete(_add())
    finally:
        loop.close()
        if old_loop is not None:
            asyncio.set_event_loop(old_loop)

    session = get_sync_session()
    try:
        from sqlalchemy import text as sa_text
        for chunk in chunks:
            chunk_id = chunk.get("chunk_id")
            if chunk_id is None:
                continue
            point_id = str(chunk_id)
            session.execute(
                sa_text(
                    "UPDATE document_chunks SET vector_id = :vid WHERE id = :cid"
                ),
                {"vid": point_id, "cid": chunk_id},
            )
        session.commit()
    except Exception as e:
        logger.warning("backfill vector_id failed: %s", e)
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        session.close()

    try:
        # Phase F2: 增量追加新文档 chunks 到 BM25 索引（而非全量 rebuild）
        # 避免覆盖 kb 中其他文档的索引数据
        from app.rag.bm25 import bm25_store
        bm25_store.add_documents_sync(kb_id, chunks)
    except Exception as e:
        logger.warning("BM25 incremental update failed: %s", e)


@celery_app.task(bind=True, max_retries=3,
                 name="app.tasks.document_task.parse_document")
def parse_document_task(self, doc_id: int):
    """Parse -> chunk -> embed -> store. Tracks progress via Redis.
    
    Retry with exponential backoff: 1s, 2s, 4s.
    Only retries on transient errors (network, 5xx, etc.).
    """
    try:
        _update_progress(doc_id, "parsing", 10)
        chunks = _parse_and_chunk(doc_id)

        _update_progress(doc_id, "chunking", 30, chunk_count=len(chunks))

        _update_progress(doc_id, "embedding", 60, chunk_count=len(chunks))
        _embed_and_store(doc_id, chunks)

        _update_progress(doc_id, "done", 100, chunk_count=len(chunks))

        # 发布 DOCUMENT_PARSED 事件
        try:
            try:
                old_loop = asyncio.get_event_loop()
            except RuntimeError:
                old_loop = None
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def _publish():
                    from app.core.events import EventBus
                    await EventBus.init()
                    session = get_sync_session()
                    try:
                        doc = session.get(Document, doc_id)
                        uploader_id = doc.uploader_id if doc else None
                    finally:
                        session.close()
                    await EventBus.publish(EventBus.DOCUMENT_PARSED, {
                        "doc_id": doc_id,
                        "filename": doc.filename if doc else "",
                        "kb_id": doc.kb_id if doc else None,
                        "uploader_id": uploader_id,
                        "chunk_count": len(chunks),
                    })
                    await EventBus.close()
                loop.run_until_complete(_publish())
            finally:
                loop.close()
                if old_loop is not None:
                    asyncio.set_event_loop(old_loop)
        except Exception as e:
            logger.warning("Failed to publish DOCUMENT_PARSED event: %s", e)

        return {"doc_id": doc_id, "chunk_count": len(chunks), "status": "done"}
    except Exception as e:
        retry_count = self.request.retries
        if retry_count >= self.max_retries:
            _update_progress(doc_id, "failed", 100, error=str(e))
        else:
            # 更新进度为 retrying, 让前端知道正在重试
            _update_progress(doc_id, "retrying", 50, error=f"重试 {retry_count + 1}/{self.max_retries}: {str(e)[:200]}")
        raise self.retry(exc=e, countdown=2 ** retry_count)