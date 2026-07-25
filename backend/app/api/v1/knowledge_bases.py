from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.middleware import limiter
from app.database import get_db
from app.db.user import User
from app.schemas.common import ok, paginated_ok
from app.schemas.kb import CollaboratorAdd, KBCreate, KBOut, KBUpdate
from app.services import kb_service

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.post("")
@limiter.limit("60/minute")
async def create_kb(
    req: KBCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    kb = await kb_service.create_kb(req, user.id, db)
    return ok(data=KBOut.model_validate(kb).model_dump())


@router.get("")
@limiter.limit("60/minute")
async def list_kbs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    kbs, total = await kb_service.list_kbs(user.id, db, page, page_size)
    items = [KBOut.model_validate(kb).model_dump() for kb in kbs]
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.get("/{kb_id}")
@limiter.limit("60/minute")
async def get_kb(
    kb_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    kb = await kb_service.get_kb(kb_id, user.id, db)
    return ok(data=KBOut.model_validate(kb).model_dump())


@router.put("/{kb_id}")
@limiter.limit("60/minute")
async def update_kb(
    kb_id: int,
    req: KBUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    kb = await kb_service.update_kb(kb_id, req, user.id, db)
    return ok(data=KBOut.model_validate(kb).model_dump())


@router.delete("/{kb_id}")
@limiter.limit("60/minute")
async def delete_kb(
    kb_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await kb_service.delete_kb(kb_id, user.id, db)
    return ok(message="Deleted")


# --- Collaboration endpoints ---


@router.post("/{kb_id}/collaborators")
@limiter.limit("60/minute")
async def add_collaborator(
    kb_id: int,
    req: CollaboratorAdd,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await kb_service.add_collaborator(kb_id, user.id, req.user_id, req.permission, db)
    return ok(data=data)


@router.delete("/{kb_id}/collaborators/{user_id}")
@limiter.limit("60/minute")
async def remove_collaborator(
    kb_id: int,
    user_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await kb_service.remove_collaborator(kb_id, user.id, user_id, db)
    return ok(message="Removed")


@router.get("/{kb_id}/collaborators")
@limiter.limit("60/minute")
async def get_collaborators(
    kb_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await kb_service.get_collaborators(kb_id, user.id, db)
    return ok(data=data)
