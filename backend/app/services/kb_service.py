from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from app.db.knowledge_base import KnowledgeBase
from app.db.document import Document
from app.db.document_chunk import DocumentChunk
from app.db.chat_session import ChatSession
from app.core.exceptions import NotFoundError, ForbiddenError
from app.schemas.kb import KBCreate, KBUpdate


async def create_kb(req: KBCreate, user_id: int, db: AsyncSession) -> KnowledgeBase:
    kb = KnowledgeBase(name=req.name, description=req.description, owner_id=user_id)
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


async def list_kbs(user_id: int, db: AsyncSession, page: int = 1, page_size: int = 20):
    count_result = await db.execute(
        select(func.count()).select_from(KnowledgeBase).where(KnowledgeBase.owner_id == user_id)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.owner_id == user_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .order_by(KnowledgeBase.updated_at.desc())
    )
    items = result.scalars().all()
    return items, total


async def get_kb(kb_id: int, user_id: int, db: AsyncSession) -> KnowledgeBase:
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("Knowledge base not found")
    if kb.owner_id != user_id:
        raise ForbiddenError("Access denied")
    return kb


async def update_kb(kb_id: int, req: KBUpdate, user_id: int, db: AsyncSession) -> KnowledgeBase:
    kb = await get_kb(kb_id, user_id, db)
    if req.name is not None:
        kb.name = req.name
    if req.description is not None:
        kb.description = req.description
    await db.commit()
    await db.refresh(kb)
    return kb


async def delete_kb(kb_id: int, user_id: int, db: AsyncSession):
    """Delete knowledge base with full cascade cleanup.

    Order of operations:
    1. Delete Qdrant collection (vectors)
    2. Delete BM25 index from Redis
    3. Delete file storage directory
    4. Delete chat sessions linked to this KB
    5. Delete document chunks
    6. Delete documents
    7. Delete knowledge base
    """
    kb = await get_kb(kb_id, user_id, db)

    # 1. Delete Qdrant collection (delete_collection is sync, do NOT await)
    try:
        from app.rag.retriever import retriever
        retriever.delete_collection(kb_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Qdrant collection delete failed: %s", e)

    # 2. Delete BM25 index from Redis
    try:
        from app.rag.bm25 import bm25_store
        await bm25_store.delete(kb_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("BM25 index delete failed: %s", e)

    # 3. Delete file storage directory
    try:
        from app.utils.storage import delete_kb_dir
        delete_kb_dir(kb_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Storage dir delete failed: %s", e)

    # 4. Delete chat sessions linked to this KB
    try:
        await db.execute(
            delete(ChatSession).where(ChatSession.kb_id == kb_id)
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Chat sessions delete failed: %s", e)

    # 5. Delete document chunks
    try:
        await db.execute(
            delete(DocumentChunk).where(DocumentChunk.kb_id == kb_id)
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Chunks delete failed: %s", e)

    # 6. Delete documents
    try:
        await db.execute(
            delete(Document).where(Document.kb_id == kb_id)
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Documents delete failed: %s", e)

    # 7. Delete knowledge base
    await db.delete(kb)
    await db.commit()


async def get_kb_stats(kb_id: int, user_id: int, db: AsyncSession) -> dict:
    """Get KB statistics: doc count, chunk count, total size (using SQL aggregation)."""
    kb = await get_kb(kb_id, user_id, db)

    # Use SQL aggregation instead of loading all rows into memory
    doc_stats = await db.execute(
        select(
            func.count(Document.id).label("doc_count"),
            func.coalesce(func.sum(Document.file_size), 0).label("total_size"),
        ).where(Document.kb_id == kb_id)
    )
    doc_row = doc_stats.one()

    chunk_count = await db.scalar(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.kb_id == kb_id)
    )

    return {
        "id": kb.id,
        "name": kb.name,
        "description": kb.description,
        "doc_count": doc_row.doc_count or 0,
        "chunk_count": chunk_count or 0,
        "total_size": int(doc_row.total_size or 0),
        "created_at": kb.created_at.isoformat() if kb.created_at else None,
        "updated_at": kb.updated_at.isoformat() if kb.updated_at else None,
    }
