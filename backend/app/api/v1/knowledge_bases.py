from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.api.deps import get_current_user
from app.services import kb_service
from app.schemas.kb import KBCreate, KBUpdate, KBOut
from app.schemas.common import ok, paginated_ok
from app.db.user import User

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.post("")
async def create_kb(
    req: KBCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    kb = await kb_service.create_kb(req, user.id, db)
    return ok(data=KBOut.model_validate(kb).model_dump())


@router.get("")
async def list_kbs(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    kbs, total = await kb_service.list_kbs(user.id, db, page, page_size)
    items = [KBOut.model_validate(kb).model_dump() for kb in kbs]
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.get("/{kb_id}")
async def get_kb(
    kb_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    kb = await kb_service.get_kb(kb_id, user.id, db)
    return ok(data=KBOut.model_validate(kb).model_dump())


@router.put("/{kb_id}")
async def update_kb(
    kb_id: int,
    req: KBUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    kb = await kb_service.update_kb(kb_id, req, user.id, db)
    return ok(data=KBOut.model_validate(kb).model_dump())


@router.delete("/{kb_id}")
async def delete_kb(
    kb_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await kb_service.delete_kb(kb_id, user.id, db)
    return ok(message="Deleted")