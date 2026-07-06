import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from app.db.document import Document
from app.db.document_chunk import DocumentChunk
from app.core.exceptions import NotFoundError, ForbiddenError
from app.schemas.document import DocumentUpdate
from app.utils.storage import delete_file, get_kb_dir

logger = logging.getLogger(__name__)


async def upload_document(
    kb_id: int,
    user_id: int,
    filename: str,
    file_path: str,
    file_type: str,
    file_size: int,
    db: AsyncSession,
) -> Document:
    doc = Document(
        kb_id=kb_id,
        filename=filename,
        file_path=file_path,
        file_type=file_type,
        file_size=file_size,
        status="pending",
        chunk_count=0,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


async def list_documents(
    user_id: int, db: AsyncSession, kb_id: int | None = None, page: int = 1, page_size: int = 20
):
    from app.db.knowledge_base import KnowledgeBase
    query = select(Document).join(KnowledgeBase, Document.kb_id == KnowledgeBase.id).where(KnowledgeBase.owner_id == user_id)
    if kb_id is not None:
        from app.services.kb_service import get_kb
        await get_kb(kb_id, user_id, db)
        query = query.where(Document.kb_id == kb_id)
    result = await db.execute(
        query
        .offset((page - 1) * page_size)
        .limit(page_size)
        .order_by(Document.created_at.desc())
    )
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    return result.scalars().all(), total or 0


async def get_document(doc_id: int, user_id: int, db: AsyncSession) -> Document:
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("Document not found")
    from app.services.kb_service import get_kb
    await get_kb(doc.kb_id, user_id, db)
    return doc


async def update_document(
    doc_id: int, req: DocumentUpdate, user_id: int, db: AsyncSession
) -> Document:
    doc = await get_document(doc_id, user_id, db)
    if req.title is not None:
        doc.filename = req.title
    await db.commit()
    await db.refresh(doc)
    return doc


async def delete_document(doc_id: int, user_id: int, db: AsyncSession):
    """Delete document with full cascade cleanup.

    1. Delete Qdrant vectors for this document
    2. Update/remove from BM25 index
    3. Delete file from storage
    4. Delete document chunks from DB
    5. Delete document record
    """
    doc = await get_document(doc_id, user_id, db)

    # 1. Delete Qdrant vectors (delete_by_doc_id is sync, do NOT await)
    try:
        from app.rag.retriever import retriever
        retriever.delete_by_doc_id(doc.kb_id, doc.id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Qdrant doc delete failed: %s", e)

    # 2. BM25: 删除该文档在 BM25 索引中的 chunks（增量更新）
    try:
        from app.rag.bm25 import bm25_store
        await bm25_store.remove_document(doc.kb_id, doc.id)
    except Exception as e:
        logger.warning("BM25 remove_document failed: %s", e)

    # 3. Delete file from storage (delete ALL matching files, not just first)
    try:
        kb_dir = get_kb_dir(doc.kb_id)
        for f in kb_dir.iterdir():
            if f.name.startswith(f"{doc.id}_"):
                delete_file(str(f))
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("File delete failed: %s", e)

    # 4. Delete document chunks
    try:
        await db.execute(
            delete(DocumentChunk).where(DocumentChunk.doc_id == doc.id)
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Chunks delete failed: %s", e)

    # 5. Delete document record
    await db.delete(doc)
    await db.commit()


async def reparse_document(doc_id: int, user_id: int, db: AsyncSession) -> Document:
    doc = await get_document(doc_id, user_id, db)
    if doc.status in ("parsing", "chunking", "embedding"):
        from app.core.exceptions import ConflictError
        raise ConflictError(message="Document is already being processed")
    doc.status = "pending"
    doc.error_message = None
    await db.commit()
    from app.tasks.document_task import parse_document_task
    parse_document_task.delay(doc.id)
    await db.refresh(doc)
    return doc
