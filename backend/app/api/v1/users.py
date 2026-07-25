from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_admin_user, get_current_user
from app.config import RATE_LIMIT_DEFAULT
from app.core.middleware import limiter
from app.database import get_db
from app.db.user import User
from app.schemas.common import ok, paginated_ok
from app.schemas.user import UpdateRoleRequest, UpdateStatusRequest, UserListResponse
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/search")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def search_users(
    request: Request,
    q: str = Query(..., min_length=1, max_length=100, description="用户名搜索关键词"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """搜索用户（按用户名），用于协作者添加等场景"""
    users = await user_service.search_users(db, q, limit)
    return ok(data=users)


@router.get("")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    users, total = await user_service.list_users(db, page, page_size)
    items = [UserListResponse.model_validate(u).model_dump() for u in users]
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.put("/{user_id}/role")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def update_role(
    user_id: int,
    req: UpdateRoleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    user = await user_service.update_role(user_id, req.role, db, admin.id)
    return ok(data=UserListResponse.model_validate(user).model_dump())


@router.put("/{user_id}/status")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def update_status(
    user_id: int,
    req: UpdateStatusRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    user = await user_service.update_status(user_id, req.is_active, db, admin.id)
    return ok(data=UserListResponse.model_validate(user).model_dump())
