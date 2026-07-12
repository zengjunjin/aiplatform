import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from app.db.knowledge_base import KnowledgeBase
from app.db.document import Document
from app.db.document_chunk import DocumentChunk
from app.db.chat_session import ChatSession
from app.db.user import User
from app.core.exceptions import NotFoundError, ForbiddenError, ConflictError
from app.schemas.kb import KBCreate, KBUpdate


async def create_kb(req: KBCreate, user_id: int, db: AsyncSession) -> KnowledgeBase:
    existing = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.owner_id == user_id,
            KnowledgeBase.name == req.name
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError("同名知识库已存在")

    kb = KnowledgeBase(name=req.name, description=req.description, owner_id=user_id)
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


async def list_kbs(user_id: int, db: AsyncSession, page: int = 1, page_size: int = 20):
    from sqlalchemy import or_, cast
    from sqlalchemy.dialects.postgresql import JSONB

    filter_value = json.dumps([{"user_id": user_id}])
    collab_filter = cast(KnowledgeBase.collaborators, JSONB).op('@>')(cast(filter_value, JSONB))

    count_query = select(func.count()).select_from(KnowledgeBase).where(
        or_(KnowledgeBase.owner_id == user_id, collab_filter)
    )
    total = await db.scalar(count_query)

    data_query = select(KnowledgeBase).where(
        or_(KnowledgeBase.owner_id == user_id, collab_filter)
    ).order_by(KnowledgeBase.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(data_query)
    kbs = result.scalars().all()
    return kbs, total or 0


async def get_kb(kb_id: int, user_id: int, db: AsyncSession) -> KnowledgeBase:
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("Knowledge base not found")
    if kb.owner_id != user_id:
        # Check collaborators
        collaborators = kb.collaborators or []
        found = any(c.get("user_id") == user_id for c in collaborators)
        if not found:
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
    1-4. DB operations first (within a single transaction):
        Delete chat sessions, document chunks, documents, knowledge base
    5-7. External resources cleanup (best-effort, after DB is safe):
        Delete Qdrant collection, BM25 index, file storage directory
    """
    import logging
    logger = logging.getLogger(__name__)

    kb = await get_kb(kb_id, user_id, db)

    # 1-4. DB operations first — 先保证数据一致性
    await db.execute(
        delete(ChatSession).where(ChatSession.kb_id == kb_id)
    )
    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.kb_id == kb_id)
    )
    await db.execute(
        delete(Document).where(Document.kb_id == kb_id)
    )
    await db.delete(kb)
    await db.commit()

    # 5-7. External resources cleanup — best-effort (DB 已提交, 失败不影响一致性)
    # 5. Delete Qdrant collection (sync 方法, 用 to_thread 避免阻塞事件循环)
    try:
        import asyncio
        from app.rag.retriever import retriever
        await asyncio.to_thread(retriever.delete_collection, kb_id)
    except Exception as e:
        logger.warning("Qdrant collection delete failed: %s", e)

    # 6. Delete BM25 index from Redis
    try:
        from app.rag.bm25 import bm25_store
        await bm25_store.delete(kb_id)
    except Exception as e:
        logger.warning("BM25 index delete failed: %s", e)

    # 7. Delete file storage directory
    try:
        from app.utils.storage import delete_kb_dir
        delete_kb_dir(kb_id)
    except Exception as e:
        logger.warning("Storage dir delete failed: %s", e)


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


async def add_collaborator(kb_id: int, user_id: int, target_user_id: int, permission: str, db: AsyncSession) -> dict:
    """Add a collaborator to a knowledge base. Only owner can add collaborators."""
    kb = await get_kb(kb_id, user_id, db)
    if kb.owner_id != user_id:
        raise ForbiddenError("Only the owner can manage collaborators")

    # Verify target user exists
    result = await db.execute(select(User).where(User.id == target_user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise NotFoundError("User not found")
    if target_user_id == user_id:
        raise ForbiddenError("Cannot add yourself as collaborator")

    collaborators = list(kb.collaborators or [])
    # Remove existing entry for this user if any
    collaborators = [c for c in collaborators if c.get("user_id") != target_user_id]
    collaborators.append({"user_id": target_user_id, "permission": permission})
    kb.collaborators = collaborators
    await db.commit()
    await db.refresh(kb)
    return {"user_id": target_user_id, "username": target_user.username, "permission": permission}


async def remove_collaborator(kb_id: int, user_id: int, target_user_id: int, db: AsyncSession):
    """Remove a collaborator from a knowledge base."""
    kb = await get_kb(kb_id, user_id, db)
    if kb.owner_id != user_id:
        raise ForbiddenError("Only the owner can manage collaborators")

    collaborators = list(kb.collaborators or [])
    collaborators = [c for c in collaborators if c.get("user_id") != target_user_id]
    kb.collaborators = collaborators
    await db.commit()


async def get_collaborators(kb_id: int, user_id: int, db: AsyncSession) -> list[dict]:
    """Get list of collaborators for a knowledge base."""
    kb = await get_kb(kb_id, user_id, db)
    collaborators = list(kb.collaborators or [])
    # 批量查询所有协作者用户名（避免 N+1）
    uids = [c.get("user_id") for c in collaborators if c.get("user_id")]
    users_map: dict[int, User] = {}
    if uids:
        result = await db.execute(select(User).where(User.id.in_(uids)))
        users_map = {u.id: u for u in result.scalars().all()}
    enriched = []
    for c in collaborators:
        uid = c.get("user_id")
        if uid:
            u = users_map.get(uid)
            enriched.append({
                "user_id": uid,
                "username": u.username if u else f"User#{uid}",
                "permission": c.get("permission", "read"),
            })
    return enriched
