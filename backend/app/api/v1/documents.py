import os
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, Form, Request
from app.core.middleware import limiter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.api.deps import get_current_user
from app.services import document_service, kb_service
from app.schemas.document import DocumentOut, DocumentProgress
from app.schemas.common import ok, paginated_ok
from app.core.exceptions import AppException, ValidationError, ConflictError
from app.core.errors import ErrorCode
from app.config import settings
from app.db.user import User
from app.db.document import Document
from app.utils.storage import save_upload_file, ALLOWED_EXT, delete_file
from loguru import logger

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload")
@limiter.limit("10/hour")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    kb_id: int = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    kb = await kb_service.get_kb(kb_id, user.id, db)

    # Check document count limit
    count_result = await db.execute(
        select(func.count()).where(Document.kb_id == kb_id)
    )
    doc_count = count_result.scalar_one()
    if doc_count >= settings.MAX_DOCUMENTS_PER_KB:
        raise AppException(
            code=ErrorCode.DOC_LIMIT_EXCEEDED,
            message=f"每个知识库最多 {settings.MAX_DOCUMENTS_PER_KB} 个文档",
            status_code=400,
        )

    safe_filename = os.path.basename(file.filename or "")
    if not safe_filename or ".." in safe_filename or "/" in safe_filename or "\\" in safe_filename:
        raise ValidationError("Invalid filename")

    ext = os.path.splitext(safe_filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise AppException(
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            message=f"不支持的文件格式: {ext}",
            status_code=400,
        )

    doc = Document(
        kb_id=kb_id,
        uploader_id=user.id,
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
        )
    await db.refresh(doc)

    try:
        file_path, file_type, file_size, file_hash = save_upload_file(file, kb_id, doc.id)

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
            # 并发竞态: 另一个请求已插入相同 (kb_id, file_hash)
            await db.rollback()
            delete_file(file_path)
            # 清理当前文档记录
            await db.delete(doc)
            await db.commit()
            raise ConflictError(message="该文件已在此知识库中存在")

        logger.info(f"Document uploaded: id={doc.id} kb={kb_id} user={user.id} name={safe_filename} size={file_size}")

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
            )
        if "Unsupported" in msg or "magic" in msg.lower():
            raise AppException(
                code=ErrorCode.UNSUPPORTED_FILE_TYPE,
                message=msg,
                status_code=400,
            )
        raise ValidationError(msg)
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
        )

    from app.tasks.document_task import parse_document_task
    task = parse_document_task.delay(doc.id)

    return ok(data={
        "document_id": doc.id,
        "status": "pending",
        "task_id": task.id,
    })


@router.get("")
async def list_documents(
    kb_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    docs, total = await document_service.list_documents(user.id, db, kb_id, page, page_size)
    items = [DocumentOut.model_validate(d).model_dump() for d in docs]
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.get("/{doc_id}")
async def get_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_service.get_document(doc_id, user.id, db)
    return ok(data=DocumentOut.model_validate(doc).model_dump())


@router.get("/{doc_id}/progress")
async def get_progress(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_service.get_document(doc_id, user.id, db)
    try:
        from app.redis_client import get_redis
        redis = get_redis()
        if redis:
            cached = await redis.get(f"doc:progress:{doc_id}")
            if cached:
                import json
                data = json.loads(cached)
                return ok(data=data)
    except Exception:
        pass
    status_map = {
        "pending": 0,
        "parsing": 10,
        "chunking": 30,
        "embedding": 60,
        "done": 100,
        "failed": 100,
    }
    progress = status_map.get(doc.status, 0)
    return ok(data=DocumentProgress(
        status=doc.status,
        progress=progress,
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
    ).model_dump())


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Check if document is currently being processed
    doc = await document_service.get_document(doc_id, user.id, db)
    if doc.status in ("parsing", "chunking", "embedding"):
        raise ConflictError(message="文档正在处理中，无法删除，请稍候")
    await document_service.delete_document(doc_id, user.id, db)
    logger.info(f"Document deleted: id={doc_id} user={user.id}")
    return ok(message="Deleted")


@router.post("/{doc_id}/reparse")
async def reparse_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_service.get_document(doc_id, user.id, db)
    if doc.status in ("parsing", "chunking", "embedding"):
        raise ConflictError(message="文档正在处理中，请稍候")
    doc.status = "parsing"
    doc.error_message = None
    await db.commit()
    from app.tasks.document_task import parse_document_task
    task = parse_document_task.delay(doc.id)
    logger.info(f"Document reparse: id={doc_id} user={user.id}")
    return ok(data={"document_id": doc.id, "task_id": task.id})


@router.get("/{doc_id}/preview")
async def preview_document(
    doc_id: int,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Preview document content with pagination (lines)."""
    doc = await document_service.get_document(doc_id, user.id, db)

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
        raw_text = parser.parse(doc.file_path)
    except Exception as e:
        logger.error(f"Preview parse failed: doc={doc_id} {e}")
        raise AppException(
            code=ErrorCode.DOC_PARSE_FAILED,
            message="文档解析失败，无法预览",
            status_code=500,
        )

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

    return ok(data={
        "filename": doc.filename,
        "file_type": doc.file_type,
        "content": "\n".join(page_lines),
        "page": page,
        "page_size": page_size,
        "total_lines": total_lines,
        "total_pages": total_pages,
    })
