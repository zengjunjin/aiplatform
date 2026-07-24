import json

from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import EventBus
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.db.chat_session import ChatSession
from app.db.document import Document
from app.db.document_chunk import DocumentChunk
from app.db.knowledge_base import KnowledgeBase
from app.db.user import User
from app.redis_client import get_redis
from app.schemas.kb import KBCreate, KBUpdate
from app.services.audit_service import log_audit


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


async def list_kbs(user_id: int, db: AsyncSession, page: int = 1, page_size: int = 20) -> tuple[list[KnowledgeBase], int]:
    from sqlalchemy import text

    # 协作者过滤：collaborators JSONB 数组中包含 {"user_id": <user_id>} 的 KB
    # 诊断发现 SQLAlchemy ORM 形式（cast/literal + op('@>')）在 asyncpg 下参数绑定
    # 后 JSONB @> 比较不工作（SQL 不报错但条件不匹配，返回 0 行）。
    # 改用 text() where 子句 + bindparam 显式 cast，确保 @> 操作符正确执行，
    # 同时保留 ORM select 加载（避免手动构造对象丢失 instance state）。
    filter_value = json.dumps([{"user_id": user_id}])
    where_clause = text(
        "owner_id = :uid OR collaborators @> CAST(:filter AS JSONB)"
    )

    count_query = select(func.count(KnowledgeBase.id)).where(where_clause)
    total = await db.scalar(
        count_query, params={"uid": user_id, "filter": filter_value}
    )

    data_query = (
        select(KnowledgeBase)
        .where(where_clause)
        .order_by(KnowledgeBase.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(
        data_query, params={"uid": user_id, "filter": filter_value}
    )
    kbs = result.scalars().all()
    return kbs, total or 0


# 权限层级: read < write < admin
_PERMISSION_LEVELS = {"read": 1, "write": 2, "admin": 3}


def _has_permission(collab_perm: str, required: str) -> bool:
    """Return True if collaborator's permission satisfies required level."""
    return _PERMISSION_LEVELS.get(collab_perm, 0) >= _PERMISSION_LEVELS.get(required, 0)


async def _get_kb_with_perm(
    kb_id: int, user_id: int, db: AsyncSession, required: str
) -> KnowledgeBase:
    """Load KB and verify user has at least `required` permission.

    - owner: always allowed
    - collaborator: permission level must be >= required
      collaborators 项形如 {"user_id": int, "permission": "read"|"write"|"admin"}
    """
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("Knowledge base not found")
    if kb.owner_id == user_id:
        return kb
    for collab in kb.collaborators or []:
        if collab.get("user_id") == user_id:
            collab_perm = collab.get("permission", "read")
            if _has_permission(collab_perm, required):
                return kb
            raise ForbiddenError(
                f"Access denied: insufficient permission (requires {required})"
            )
    raise ForbiddenError("Access denied")


async def get_kb_for_read(kb_id: int, user_id: int, db: AsyncSession) -> KnowledgeBase:
    """Owner or any collaborator can read."""
    return await _get_kb_with_perm(kb_id, user_id, db, "read")


async def get_kb_for_write(kb_id: int, user_id: int, db: AsyncSession) -> KnowledgeBase:
    """Owner or write/admin collaborator can write."""
    return await _get_kb_with_perm(kb_id, user_id, db, "write")


async def get_kb_for_admin(kb_id: int, user_id: int, db: AsyncSession) -> KnowledgeBase:
    """Owner or admin collaborator can manage."""
    return await _get_kb_with_perm(kb_id, user_id, db, "admin")


async def get_kb(kb_id: int, user_id: int, db: AsyncSession) -> KnowledgeBase:
    """Backward-compatible alias for get_kb_for_read.

    保留旧调用方语义: owner 或任意协作者可读。
    新代码应直接调用 get_kb_for_read/write/admin 以显式表达所需权限级别。
    """
    return await get_kb_for_read(kb_id, user_id, db)


async def update_kb(kb_id: int, req: KBUpdate, user_id: int, db: AsyncSession) -> KnowledgeBase:
    kb = await get_kb_for_write(kb_id, user_id, db)
    if req.name is not None:
        kb.name = req.name
    if req.description is not None:
        kb.description = req.description
    await db.commit()
    await db.refresh(kb)
    await log_audit(
        action="KB_UPDATE",
        user_id=user_id,
        details={"kb_id": kb_id, "name": req.name, "description": req.description},
    )
    return kb


async def delete_kb(kb_id: int, user_id: int, db: AsyncSession) -> None:
    """Delete knowledge base with full cascade cleanup.

    仅 owner 可删除知识库 (spec: cdp-full-coverage-v2-2026-07-24 §admin 权限边界)。
    admin 协作者可管理协作者和内容，但不可删 KB 本身（删除是不可恢复的破坏性操作，
    保留给资源归属的最终责任人 owner）。此前实现调用 get_kb_for_admin 允许 admin
    协作者删除，违反 spec 设计，此处修正为 owner-only 校验。

    Order of operations:
    1. 统计待删除资源数量 (用于事件 payload 和审计日志)
    2-5. DB operations first (within a single transaction):
        Delete chat sessions, document chunks, documents, knowledge base
    6. 发布 KB_DELETED 事件，外部资源清理由 document_service 订阅者
       通过 EventBus 处理 (解耦 kb_service ↔ document_service 循环依赖)
    """
    # owner-only 校验：不使用 get_kb_for_admin（会允许 admin 协作者删除）
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("Knowledge base not found")
    if kb.owner_id != user_id:
        raise ForbiddenError("Only owner can delete the knowledge base")

    # 1. 统计待删除资源数量 (在删除前查询，提交后记录已不存在)
    doc_count = await db.scalar(
        select(func.count()).select_from(Document).where(Document.kb_id == kb_id)
    ) or 0
    chunk_count = await db.scalar(
        select(func.count()).select_from(DocumentChunk).where(DocumentChunk.kb_id == kb_id)
    ) or 0

    # 2-5. DB operations first — 先保证数据一致性
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

    # 6. 发布 KB_DELETED 事件，外部资源清理 (Qdrant collection / BM25 index /
    #    storage dir) 由 document_service 订阅者通过 EventBus 处理。
    #    通过事件总线解耦，避免 kb_service 直接依赖 document_service。
    try:
        await EventBus.publish(EventBus.KB_DELETED, {
            "kb_id": kb_id,
            "doc_count": doc_count,
            "chunk_count": chunk_count,
        })
    except Exception as e:
        # Task 30: EventBus.publish 失败时，将 kb_id 写入 Redis 补偿队列，
        # 由定时任务（kb cleanup worker）消费该队列重试外部资源清理
        # (Qdrant collection / BM25 index / storage dir)，避免资源泄漏。
        logger.warning(f"Failed to publish KB_DELETED event: {e}")
        try:
            redis = get_redis()
            if redis is not None:
                await redis.lpush("kb:cleanup:pending", str(kb_id))
        except Exception as redis_err:
            logger.error(
                f"Failed to enqueue kb_id={kb_id} to kb:cleanup:pending: {redis_err}"
            )

    # 7. 审计日志（记录删除的文档数、chunk 数）
    await log_audit(
        action="KB_DELETE",
        user_id=user_id,
        details={
            "kb_id": kb_id,
            "doc_count": doc_count,
            "chunk_count": chunk_count,
        },
    )


async def get_kb_stats(kb_id: int, user_id: int, db: AsyncSession) -> dict:
    """Get KB statistics: doc count, chunk count, total size (using SQL aggregation)."""
    kb = await get_kb_for_read(kb_id, user_id, db)

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
    """Add a collaborator to a knowledge base. Owner or admin collaborator can add."""
    kb = await get_kb_for_admin(kb_id, user_id, db)

    # Verify target user exists
    result = await db.execute(select(User).where(User.id == target_user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise NotFoundError("User not found")
    if target_user_id == user_id:
        raise ForbiddenError("Cannot add yourself as collaborator")
    if target_user_id == kb.owner_id:
        raise ForbiddenError("Cannot add owner as collaborator")

    collaborators = list(kb.collaborators or [])
    # Remove existing entry for this user if any
    collaborators = [c for c in collaborators if c.get("user_id") != target_user_id]
    collaborators.append({"user_id": target_user_id, "permission": permission})
    kb.collaborators = collaborators
    await db.commit()
    await db.refresh(kb)
    await log_audit(
        action="COLLABORATOR_ADD",
        user_id=user_id,
        details={
            "kb_id": kb_id,
            "target_user_id": target_user_id,
            "permission": permission,
        },
    )
    return {"user_id": target_user_id, "username": target_user.username, "permission": permission}


async def remove_collaborator(kb_id: int, user_id: int, target_user_id: int, db: AsyncSession):
    """Remove a collaborator from a knowledge base. Owner or admin collaborator can remove."""
    kb = await get_kb_for_admin(kb_id, user_id, db)

    collaborators = list(kb.collaborators or [])
    collaborators = [c for c in collaborators if c.get("user_id") != target_user_id]
    kb.collaborators = collaborators
    await db.commit()
    await log_audit(
        action="kb.collaborator.remove",
        user_id=user_id,
        details={
            "kb_id": kb_id,
            "target_user_id": target_user_id,
        },
    )


async def get_collaborators(kb_id: int, user_id: int, db: AsyncSession) -> list[dict]:
    """Get list of collaborators for a knowledge base."""
    kb = await get_kb_for_read(kb_id, user_id, db)
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
