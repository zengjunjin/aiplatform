from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.exceptions import ConflictError
from app.core.middleware import limiter
from app.database import get_db
from app.db.user import User
from app.schemas.common import ok, paginated_ok
from app.schemas.document import DocumentOut
from app.services import document_service

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
    """上传文档到知识库。业务逻辑下沉到 document_service.upload_document。"""
    doc, task = await document_service.upload_document(file, kb_id, user, db)
    logger.info(f"Document uploaded: id={doc.id} kb={kb_id} user={user.id} name={doc.filename}")
    return ok(data={
        "document_id": doc.id,
        "status": "pending",
        "task_id": task.id,
    })


@router.get("")
@limiter.limit("60/minute")
async def list_documents(
    request: Request,
    kb_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    docs, total = await document_service.list_documents(user.id, db, kb_id, page, page_size)
    items = [DocumentOut.model_validate(d).model_dump() for d in docs]
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.get("/{doc_id}")
@limiter.limit("60/minute")
async def get_document(
    doc_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_service.get_document(doc_id, user.id, db)
    return ok(data=DocumentOut.model_validate(doc).model_dump())


@router.get("/{doc_id}/progress")
@limiter.limit("60/minute")
async def get_progress(
    doc_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取文档处理进度。业务逻辑（Redis 缓存读写、进度计算）下沉到
    document_service.get_progress。本层仅做参数绑定与响应格式化。"""
    data = await document_service.get_progress(doc_id, user.id, db)
    return ok(data=data)


@router.delete("/{doc_id}")
@limiter.limit("60/minute")
async def delete_document(
    doc_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Check if document is currently being processed
    doc = await document_service.get_document_for_write(doc_id, user.id, db)
    if doc.status in ("parsing", "chunking", "embedding"):
        raise ConflictError(message="文档正在处理中，无法删除，请稍候")
    await document_service.delete_document(doc_id, user.id, db)
    logger.info(f"Document deleted: id={doc_id} user={user.id}")
    return ok(message="Deleted")


@router.post("/{doc_id}/reparse")
@limiter.limit("5/hour")
async def reparse_document(
    doc_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 使用 service 的原子锁, 防止并发重复触发
    doc, task = await document_service.reparse_document(doc_id, user.id, db)
    logger.info(f"Document reparse: id={doc_id} user={user.id}")
    return ok(data={"document_id": doc.id, "task_id": task.id})


@router.get("/{doc_id}/preview")
@limiter.limit("30/minute")
async def preview_document(
    doc_id: int,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Preview document content with pagination (lines).

    业务逻辑（文件解析、分页计算、错误处理）下沉到
    document_service.preview_document。本层仅做参数绑定与响应格式化。
    """
    data = await document_service.preview_document(doc_id, user.id, db, page, page_size)
    return ok(data=data)
