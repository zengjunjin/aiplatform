"""Celery task: parse -> chunk -> embed -> store.

Uses synchronous SQLAlchemy session (psycopg2) for Celery worker.
Embeddings fetched via sync HTTP requests.
Progress tracked via Redis (doc:progress:{doc_id}).
"""
import json
import logging
import requests
import redis as redis_sync
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.tasks.celery_app import celery_app
from app.config import settings
from app.rag.retriever import retriever
from app.db.sync_session import get_sync_session
from app.db.document import Document
from app.db.document_chunk import DocumentChunk
from app.parsers import get_parser
from app.parsers.chunker import chunker

logger = logging.getLogger(__name__)


def _get_redis_sync():
    """Get sync Redis client for progress tracking."""
    try:
        return redis_sync.from_url(settings.redis_url, decode_responses=True)
    except Exception:
        return None


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
        session.commit()
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
    finally:
        session.close()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout, requests.HTTPError)),
    reraise=True,
)
def _embed_single_text(text: str) -> list[float]:
    """Call Ollama embeddings API synchronously with retry."""
    url = f"{settings.OLLAMA_HOST}/api/embeddings"
    resp = requests.post(
        url,
        json={"model": settings.EMBEDDING_MODEL, "prompt": text},
        timeout=120,
    )
    if resp.status_code >= 500 or resp.status_code == 429:
        resp.raise_for_status()
    resp.raise_for_status()
    return resp.json()["embedding"]


def _embed_texts_sync(texts: list[str]) -> list[list[float]]:
    """Call Ollama embeddings API synchronously with per-text retry."""
    results = []
    for text in texts:
        embedding = _embed_single_text(text)
        results.append(embedding)
    return results


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

    import asyncio
    # 问题: Celery worker 线程可能已有事件循环, asyncio.run() 会创建新循环导致冲突
    # 解决方案: 创建独立的新事件循环, 确保不受影响
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        async def _add():
            await retriever.add_chunks(kb_id, chunks, vectors)
        loop.run_until_complete(_add())
    finally:
        loop.close()

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
        return {"doc_id": doc_id, "chunk_count": len(chunks), "status": "done"}
    except Exception as e:
        if self.request.retries >= self.max_retries:
            _update_progress(doc_id, "failed", 100, error=str(e))
        raise self.retry(exc=e, countdown=2 ** self.request.retries)