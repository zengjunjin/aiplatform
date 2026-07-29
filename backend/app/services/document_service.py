import asyncio
import os
import uuid
from datetime import UTC, datetime

from fastapi import UploadFile
from loguru import logger
from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import ErrorCode
from app.core.events import EventBus
from app.core.exceptions import AppException, ConflictError, NotFoundError, ValidationError
from app.db.document import STATUS_PROGRESS, Document
from app.db.document_chunk import DocumentChunk
from app.db.user import User
from app.schemas.document import DocumentProgress, DocumentUpdate
from app.services import kb_service
from app.services.audit_service import log_audit
from app.utils.storage import ALLOWED_EXT, delete_file, get_kb_dir, save_upload_file


async def _on_kb_deleted(payload: dict) -> None:
    """订阅 KB_DELETED 事件，清理 KB 相关的外部资源。

    由 kb_service.delete_kb 在 DB 事务提交后通过 EventBus 发布。
    外部资源清理是 best-effort，失败不影响 DB 一致性。
    通过事件总线解耦，避免 kb_service ↔ document_service 循环依赖。
    """
    kb_id = payload.get("kb_id")
    if kb_id is None:
        return

    # 1. Delete Qdrant collection (sync 方法, 用 to_thread 避免阻塞事件循环)
    try:
        import asyncio

        from app.rag.retriever import retriever

        await asyncio.to_thread(retriever.delete_collection, kb_id)
    except Exception as e:
        logger.warning(f"Qdrant collection delete failed: {e}")

    # 2. Delete BM25 index from Redis
    try:
        from app.rag.bm25 import bm25_store

        await bm25_store.delete(kb_id)
    except Exception as e:
        logger.warning(f"BM25 index delete failed: {e}")

    # 3. Delete file storage directory
    try:
        from app.utils.storage import delete_kb_dir

        delete_kb_dir(kb_id)
    except Exception as e:
        logger.warning(f"Storage dir delete failed: {e}")


# Task 60: 事件订阅注册从模块加载时移到 lifespan 启动阶段，避免 import 副作用
def register_event_handlers() -> None:
    """注册 KB_DELETED 事件订阅者（同步注册，无需 await）。

    应在应用 lifespan 启动阶段调用（EventBus.init() 之后），
    避免在模块 import 时产生副作用。
    """
    EventBus.subscribe_sync(EventBus.KB_DELETED, _on_kb_deleted)


async def create_document_record(
    kb_id: int,
    user_id: int,
    filename: str,
    file_path: str,
    file_type: str,
    file_size: int,
    db: AsyncSession,
) -> Document:
    """创建文档记录（轻量级辅助函数，仅写 DB 不处理文件/hash/ Celery 派发）。

    保留作为低层 API 供测试或简单场景使用。完整上传流程请用 upload_document。
    """
    doc = Document(
        kb_id=kb_id,
        uploader_id=user_id,
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


async def _validate_upload(file: UploadFile, kb_id: int, user: User, db: AsyncSession) -> str:
    """验证上传：KB 写权限、文档数量限制、文件名安全化、扩展名校验。返回安全文件名。"""
    # 1. KB 权限校验（需要 write 权限）
    await kb_service.get_kb_for_write(kb_id, user.id, db)

    # 2. 文档数量限制检查
    count_result = await db.execute(select(func.count()).where(Document.kb_id == kb_id))
    doc_count = count_result.scalar_one()
    if doc_count >= settings.MAX_DOCUMENTS_PER_KB:
        raise AppException(
            code=ErrorCode.DOC_LIMIT_EXCEEDED,
            message=f"每个知识库最大 {settings.MAX_DOCUMENTS_PER_KB} 个文档",
            status_code=400,
        )

    # 3. 文件名安全化（防止路径穿越 + 长度限制）
    safe_filename = os.path.basename(file.filename or "")
    if not safe_filename or ".." in safe_filename or "/" in safe_filename or "\\" in safe_filename:
        raise ValidationError("Invalid filename")
    if len(safe_filename) > 255:
        raise ValidationError("Filename too long (max 255 characters)")

    # 4. 扩展名校验
    ext = os.path.splitext(safe_filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise AppException(
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            message=f"不支持的文件格式: {ext}",
            status_code=400,
        )

    return safe_filename


async def _create_doc_record(
    kb_id: int, user_id: int, safe_filename: str, db: AsyncSession
) -> Document:
    """创建文档记录（临时 hash 避免 UniqueConstraint 冲突）。"""
    ext = os.path.splitext(safe_filename)[1].lower()
    doc = Document(
        kb_id=kb_id,
        uploader_id=user_id,
        filename=safe_filename,
        file_path="",
        file_type=ext.lstrip("."),
        file_size=0,
        # 使用临时唯一值避免并发上传时 file_hash="" 冲突 (UniqueConstraint: kb_id+file_hash)
        file_hash=f"pending-{uuid.uuid4().hex}",
        status="pending",
    )
    db.add(doc)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppException(
            code=ErrorCode.INTERNAL_ERROR,
            message="创建文档记录失败,请重试",
            status_code=500,
        ) from None
    await db.refresh(doc)
    return doc


async def _save_file_and_verify_hash(
    file: UploadFile, kb_id: int, doc: Document, user: User, db: AsyncSession
) -> None:
    """保存文件 + 重复 hash 检查 + 更新 doc 元数据。"""
    try:
        file_path, file_type, file_size, file_hash = await asyncio.to_thread(
            save_upload_file, file, kb_id, doc.id
        )

        existing = await db.execute(
            select(Document).where(
                Document.kb_id == kb_id,
                Document.file_hash == file_hash,
                Document.id != doc.id,
            )
        )
        if existing.scalar_one_or_none():
            delete_file(file_path)
            await db.delete(doc)
            await db.commit()
            raise ConflictError(message="该文件已在此知识库中存在")

        doc.file_path = file_path
        doc.file_type = file_type
        doc.file_size = file_size
        doc.file_hash = file_hash
        try:
            await db.commit()
        except IntegrityError:
            # 并发竞争: 另一个请求已插入相同 (kb_id, file_hash)
            await db.rollback()
            delete_file(file_path)
            await db.delete(doc)
            await db.commit()
            raise ConflictError(message="该文件已在此知识库中存在") from None

        logger.info(
            f"Document uploaded: id={doc.id} kb={kb_id} user={user.id} "
            f"name={doc.filename} size={file_size}"
        )

    except ValueError as e:
        await db.rollback()
        await db.delete(doc)
        await db.commit()
        msg = str(e)
        if "too large" in msg.lower() or "max" in msg.lower():
            raise AppException(
                code=ErrorCode.FILE_TOO_LARGE,
                message=f"文件大小超过限制（最大 {settings.MAX_FILE_SIZE_MB}MB）",
                status_code=400,
            ) from e
        if "Unsupported" in msg or "magic" in msg.lower():
            raise AppException(
                code=ErrorCode.UNSUPPORTED_FILE_TYPE,
                message=msg,
                status_code=400,
            ) from e
        raise ValidationError(msg) from e
    except AppException:
        raise
    except Exception as e:
        await db.rollback()
        await db.delete(doc)
        await db.commit()
        logger.error(f"Upload failed: {e}")
        raise AppException(
            code=ErrorCode.INTERNAL_ERROR,
            message="文件上传失败",
            status_code=500,
        ) from e


def _dispatch_parse_task(doc: Document) -> object:
    """派发 Celery 解析任务。"""
    from app.tasks.document_task import parse_document_task

    return parse_document_task.delay(doc.id)


async def upload_document(
    file: UploadFile,
    kb_id: int,
    user: User,
    db: AsyncSession,
) -> tuple[Document, object]:
    """完整文档上传流程：数量检查/文件名安全化/扩展名校验/hash 临时值/事务/Celery 派发。

    封装原 documents.upload_document 路由的业务逻辑。API 层仅做参数绑定。

    Returns:
        (doc, task) 元组，task 为 Celery AsyncResult。
    """
    safe_filename = await _validate_upload(file, kb_id, user, db)
    doc = await _create_doc_record(kb_id, user.id, safe_filename, db)
    await _save_file_and_verify_hash(file, kb_id, doc, user, db)
    try:
        task = _dispatch_parse_task(doc)
    except Exception:
        # Celery 派发失败：将 doc 标记为 failed 并提交，避免孤儿 pending 记录。
        # 标记失败的提交若自身出错则回滚，但始终重新抛出原始异常以保持异常流程不变
        # （API 层仍返回 500）。
        logger.exception(f"Celery parse task dispatch failed for doc_id={doc.id}")
        doc.status = "failed"
        try:
            await db.commit()
        except Exception as ce:
            logger.debug(f"Failed to commit doc status=failed after dispatch failure: {ce}")
            await db.rollback()
        raise
    # 同步更新 KB doc_count (chunk_count 在文档解析完成后由解析任务更新)
    # 使用 SQLAlchemy 列表达式实现数据库层面原子更新, 避免并发竞争
    from app.db.knowledge_base import KnowledgeBase

    kb = await db.get(KnowledgeBase, kb_id)
    if kb:
        kb.doc_count = KnowledgeBase.doc_count + 1
        await db.commit()
    return doc, task


async def list_documents(
    user_id: int, db: AsyncSession, kb_id: int | None = None, page: int = 1, page_size: int = 20
) -> tuple[list[Document], int]:
    import json as _json

    from sqlalchemy import cast, or_
    from sqlalchemy.dialects.postgresql import JSONB

    from app.db.knowledge_base import KnowledgeBase

    # owner OR collaborator 可见性过滤（与 list_kbs 一致）
    collab_filter = cast(KnowledgeBase.collaborators, JSONB).op("@>")(
        cast(_json.dumps([{"user_id": user_id}]), JSONB)
    )
    base_filter = or_(
        KnowledgeBase.owner_id == user_id,
        collab_filter,
    )
    query = (
        select(Document)
        .join(KnowledgeBase, Document.kb_id == KnowledgeBase.id)
        .where(base_filter)
        .where(Document.deleted_at.is_(None))
    )
    # 独立构造 count_query：复用过滤条件但不带 ORDER BY/offset/limit，避免无意义子查询
    count_query = (
        select(func.count(Document.id))
        .join(KnowledgeBase, Document.kb_id == KnowledgeBase.id)
        .where(base_filter)
        .where(Document.deleted_at.is_(None))
    )
    if kb_id is not None:
        await kb_service.get_kb_for_read(kb_id, user_id, db)
        query = query.where(Document.kb_id == kb_id)
        count_query = count_query.where(Document.kb_id == kb_id)
    result = await db.execute(
        query.offset((page - 1) * page_size).limit(page_size).order_by(Document.created_at.desc())
    )
    total = await db.scalar(count_query)
    return result.scalars().all(), total or 0


async def get_document(doc_id: int, user_id: int, db: AsyncSession) -> Document:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.deleted_at.is_(None))
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("Document not found")
    await kb_service.get_kb_for_read(doc.kb_id, user_id, db)
    return doc


async def get_document_for_write(doc_id: int, user_id: int, db: AsyncSession) -> Document:
    """Load document and verify user has write permission on its KB.

    用于文档上传/删除/reparse 等写操作, 防止 read 权限协作者越权修改。
    """
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.deleted_at.is_(None))
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("Document not found")
    await kb_service.get_kb_for_write(doc.kb_id, user_id, db)
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


async def delete_document(doc_id: int, user_id: int, db: AsyncSession) -> None:
    """Delete document with full cascade cleanup.

    1. Delete Qdrant vectors for this document
    2. Update/remove from BM25 index
    3. Delete file from storage
    4. Delete document chunks from DB
    5. Delete document record
    """
    doc = await get_document_for_write(doc_id, user_id, db)

    # 1. Soft-delete document record first (DB transaction before external resources)
    #    如果 DB 操作失败, 外部资源不会被误删
    doc.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    doc.status = "deleted"

    # 2. Delete document chunks from DB
    await db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc.id))
    await db.commit()

    # 同步更新 KB doc_count / chunk_count
    # 使用 SQLAlchemy 列表达式实现数据库层面原子更新, 避免并发竞争
    from app.db.knowledge_base import KnowledgeBase

    kb = await db.get(KnowledgeBase, doc.kb_id)
    if kb:
        kb.doc_count = case((KnowledgeBase.doc_count > 1, KnowledgeBase.doc_count - 1), else_=0)
        kb.chunk_count = case(
            (
                KnowledgeBase.chunk_count > (doc.chunk_count or 0),
                KnowledgeBase.chunk_count - (doc.chunk_count or 0),
            ),
            else_=0,
        )
        await db.commit()

    # 审计日志（记录删除的文档信息）
    await log_audit(
        action="DOCUMENT_DELETE",
        user_id=user_id,
        details={
            "doc_id": doc_id,
            "filename": doc.filename,
            "kb_id": doc.kb_id,
        },
    )

    # 3. Delete Qdrant vectors (sync 方法, 用 to_thread 避免阻塞事件循环)
    #    外部资源删除失败不影响 DB 状态 (已 soft-delete, 可后续清理)
    try:
        import asyncio

        from app.rag.retriever import retriever

        await asyncio.to_thread(retriever.delete_by_doc_id, doc.kb_id, doc.id)
    except Exception as e:
        logger.warning(f"Qdrant doc delete failed: {e}")

    # 4. BM25: 删除该文档在 BM25 索引中的 chunks（增量更新）
    try:
        from app.rag.bm25 import bm25_store

        await bm25_store.remove_document(doc.kb_id, doc.id)
    except Exception as e:
        logger.warning(f"BM25 remove_document failed: {e}")

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
        logger.warning(f"File delete failed: {e}")


async def reparse_document(
    doc_id: int, user_id: int, db: AsyncSession, force: bool = False
) -> tuple[Document, object]:
    """原子地重解析文档，返回 (doc, task)。

    使用乐观锁防止并发重复触发。

    Args:
        force: True 时跳过 "正在处理中" 状态检查与乐观锁，强制重新解析。
    """
    doc = await get_document_for_write(doc_id, user_id, db)
    if not force and doc.status in ("parsing", "chunking", "embedding"):
        raise ConflictError(message="Document is already being processed")
    # 原子更新状态为 parsing, 防止并发重复触发
    from sqlalchemy import update as sa_update

    # 注意: 不使用 .returning() 子句。SQLAlchemy 2.0 中带 .returning() 的
    # UPDATE 返回 ChunkedIteratorResult（无 rowcount 属性）；不带 .returning()
    # 返回 CursorResult（有 rowcount 属性），可用于乐观锁影响行数判断。
    if force:
        # force=True: 跳过乐观锁，直接更新状态为 pending
        await db.execute(
            sa_update(Document)
            .where(Document.id == doc_id)
            .values(status="pending", error_message=None)
        )
    else:
        result = await db.execute(
            sa_update(Document)
            .where(Document.id == doc_id, Document.status == doc.status)
            .values(status="pending", error_message=None)
        )
        if result.rowcount == 0:
            raise ConflictError(message="Document status changed, please retry")
    # 同步更新内存对象, 保持与 DB 一致
    doc.status = "pending"
    doc.error_message = None
    await db.commit()
    from app.tasks.document_task import parse_document_task

    task = parse_document_task.delay(doc_id)
    await db.refresh(doc)
    # 重新解析会替换原有 chunks, 先从 KB chunk_count 中扣减旧值
    # 新 chunks 数量由解析任务完成后更新
    # 使用 SQLAlchemy 列表达式实现数据库层面原子更新, 避免并发竞争
    from app.db.knowledge_base import KnowledgeBase

    kb = await db.get(KnowledgeBase, doc.kb_id)
    if kb and doc.chunk_count:
        kb.chunk_count = case(
            (
                KnowledgeBase.chunk_count > (doc.chunk_count or 0),
                KnowledgeBase.chunk_count - (doc.chunk_count or 0),
            ),
            else_=0,
        )
        await db.commit()
    return doc, task


async def get_progress(doc_id: int, user_id: int, db: AsyncSession) -> dict:
    """获取文档处理进度（带 Redis 缓存）。

    业务流程：
    1. 优先从 Redis 缓存读取进度（命中则直接返回缓存数据，跳过 DB 查询）
    2. 缓存未命中则读取文档（复用 get_document，含 KB 读权限校验）
    3. 按 STATUS_PROGRESS 计算并返回 DocumentProgress

    缓存读取失败不影响主流程，降级为实时计算。
    """
    # Task 36: 缓存优先——先读 Redis，命中则直接返回，跳过 DB 查询
    try:
        from app.redis_client import get_redis

        redis = get_redis()
        if redis:
            cached = await redis.get(f"doc:progress:{doc_id}")
            if cached:
                import json

                return json.loads(cached)
    except Exception as e:
        logger.warning(f"Failed to read doc progress cache for doc={doc_id}: {e}", exc_info=True)

    doc = await get_document(doc_id, user_id, db)
    progress = STATUS_PROGRESS.get(doc.status, 0)
    return DocumentProgress(
        status=doc.status,
        progress=progress,
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
    ).model_dump()


async def preview_document(
    doc_id: int,
    user_id: int,
    db: AsyncSession,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """预览文档内容（分页按行）。

    业务流程：
    1. 读取文档（复用 get_document，含 KB 读权限校验）
    2. 获取 parser，不支持则抛 AppException(UNSUPPORTED_FILE_TYPE)
    3. 异步解析文件（asyncio.to_thread 避免阻塞事件循环）
    4. 按行分页计算并返回预览数据

    解析失败抛 AppException(DOC_PARSE_FAILED)。
    """
    doc = await get_document(doc_id, user_id, db)

    # Parse the file to get raw text
    from app.parsers import get_parser

    parser = get_parser(doc.file_path)
    if not parser:
        raise AppException(
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            message=f"不支持预览的文件格式: {doc.file_type}",
            status_code=400,
        )
    try:
        # parser.parse 是同步阻塞调用（读取文件 + 解析），用 asyncio.to_thread 避免阻塞事件循环
        import asyncio

        raw_text = await asyncio.to_thread(parser.parse, doc.file_path)
    except Exception as e:
        logger.error(f"Preview parse failed: doc={doc_id} {e}")
        raise AppException(
            code=ErrorCode.DOC_PARSE_FAILED,
            message="文档解析失败，无法预览",
            status_code=500,
        ) from e

    lines = raw_text.split("\n")
    total_lines = len(lines)
    total_pages = (total_lines + page_size - 1) // page_size if page_size > 0 else 1

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start = (page - 1) * page_size
    end = start + page_size
    page_lines = lines[start:end]

    return {
        "filename": doc.filename,
        "file_type": doc.file_type,
        "content": "\n".join(page_lines),
        "page": page,
        "page_size": page_size,
        "total_lines": total_lines,
        "total_pages": total_pages,
    }
