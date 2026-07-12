import logging
from datetime import datetime, timezone
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
    from sqlalchemy import or_, cast
    from sqlalchemy.dialects.postgresql import JSONB
    import json as _json

    # owner OR collaborator 可见性过滤（与 list_kbs 一致）
    collab_filter = cast(KnowledgeBase.collaborators, JSONB).op('@>')(
        cast(_json.dumps([{"user_id": user_id}]), JSONB)
    )
    base_filter = or_(
        KnowledgeBase.owner_id == user_id,
        collab_filter,
    )
    query = select(Document).join(KnowledgeBase, Document.kb_id == KnowledgeBase.id).where(base_filter).where(Document.deleted_at.is_(None))
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
    result = await db.execute(select(Document).where(Document.id == doc_id, Document.deleted_at.is_(None)))
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

    # 1. Soft-delete document record first (DB transaction before external resources)
    #    如果 DB 操作失败, 外部资源不会被误删
    doc.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    doc.status = "deleted"

    # 2. Delete document chunks from DB
    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.doc_id == doc.id)
    )
    await db.commit()

    # 3. Delete Qdrant vectors (sync 方法, 用 to_thread 避免阻塞事件循环)
    #    外部资源删除失败不影响 DB 状态 (已 soft-delete, 可后续清理)
    try:
        import asyncio
        from app.rag.retriever import retriever
        await asyncio.to_thread(retriever.delete_by_doc_id, doc.kb_id, doc.id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Qdrant doc delete failed: %s", e)

    # 4. BM25: 删除该文档在 BM25 索引中的 chunks（增量更新）
    try:
        from app.rag.bm25 import bm25_store
        await bm25_store.remove_document(doc.kb_id, doc.id)
    except Exception as e:
        logger.warning("BM25 remove_document failed: %s", e)

    # 5. Delete file from storage (精确匹配 "{doc.id}_" 前缀)
    try:
        kb_dir = get_kb_dir(doc.kb_id)
        prefix = f"{doc.id}_"
        for f in kb_dir.iterdir():
            if f.name.startswith(prefix):
                # 防御性校验: 确认下划线前是 doc.id 而非数字前缀 (如 "1" 匹配 "10")
                name_doc_id = f.name.split("_", 1)[0]
                if name_doc_id == str(doc.id):
                    delete_file(str(f))
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("File delete failed: %s", e)


async def reparse_document(doc_id: int, user_id: int, db: AsyncSession) -> Document:
    doc = await get_document(doc_id, user_id, db)
    if doc.status in ("parsing", "chunking", "embedding"):
        from app.core.exceptions import ConflictError
        raise ConflictError(message="Document is already being processed")
    # 原子更新状态为 parsing, 防止并发重复触发
    from sqlalchemy import update as sa_update
    from app.db.document import Document as DocModel
    result = await db.execute(
        sa_update(DocModel)
        .where(DocModel.id == doc_id, DocModel.status == doc.status)
        .values(status="pending", error_message=None)
        .returning(DocModel.id)
    )
    if result.rowcount == 0:
        from app.core.exceptions import ConflictError
        raise ConflictError(message="Document status changed, please retry")
    # 同步更新内存对象, 保持与 DB 一致
    doc.status = "pending"
    doc.error_message = None
    await db.commit()
    from app.tasks.document_task import parse_document_task
    parse_document_task.delay(doc_id)
    await db.refresh(doc)
    return doc
