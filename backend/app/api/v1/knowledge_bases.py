from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import RATE_LIMIT_DEFAULT
from app.core.cache import cache_delete_pattern, cache_get, cache_set
from app.core.middleware import limiter
from app.database import get_db
from app.db.user import User
from app.schemas.common import APIResponse, PaginatedResponse, ok, paginated_ok
from app.schemas.kb import CollaboratorAdd, CollaboratorOut, KBCreate, KBOut, KBUpdate
from app.services import kb_service

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.post("", response_model=APIResponse[KBOut])
@limiter.limit(RATE_LIMIT_DEFAULT)
async def create_kb(
    req: KBCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建知识库。

    需要认证用户。owner 自动设为当前用户。限流 60 次/分钟。
    返回创建的知识库对象。
    """
    kb = await kb_service.create_kb(req, user.id, db)
    # Phase 5 / H49: 业务指标 - KB 创建计数
    from app.core.metrics import KB_CREATED_TOTAL

    KB_CREATED_TOTAL.labels(user_role=user.role).inc()
    # 缓存失效：清除该用户的 KB 列表缓存
    await cache_delete_pattern(f"kb:list:{user.id}:*")
    return ok(data=KBOut.model_validate(kb).model_dump())


@router.get("", response_model=PaginatedResponse[KBOut])
@limiter.limit(RATE_LIMIT_DEFAULT)
async def list_kbs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """分页查询当前用户可访问的知识库列表。

    需要认证。限流 60 次/分钟。支持 page/page_size 分页参数。
    返回分页格式的知识库列表。使用 Redis 缓存，TTL 5 分钟。
    """
    # 尝试命中缓存
    cache_key = f"kb:list:{user.id}:{page}:{page_size}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return paginated_ok(
            items=cached["items"], total=cached["total"], page=page, page_size=page_size
        )

    kbs, total = await kb_service.list_kbs(user.id, db, page, page_size)
    items = [KBOut.model_validate(kb).model_dump() for kb in kbs]
    # 写入缓存
    await cache_set(cache_key, {"items": items, "total": total})
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.get("/{kb_id}", response_model=APIResponse[KBOut])
@limiter.limit(RATE_LIMIT_DEFAULT)
async def get_kb(
    kb_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取指定知识库详情。

    需要认证且用户须对该知识库有访问权限（owner 或协作者）。限流 60 次/分钟。
    返回知识库对象。
    """
    kb = await kb_service.get_kb(kb_id, user.id, db)
    return ok(data=KBOut.model_validate(kb).model_dump())


@router.put("/{kb_id}", response_model=APIResponse[KBOut])
@limiter.limit(RATE_LIMIT_DEFAULT)
async def update_kb(
    kb_id: int,
    req: KBUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新知识库信息。

    需要认证且用户须为 owner（或具备写权限）。限流 60 次/分钟。
    返回更新后的知识库对象。
    """
    kb = await kb_service.update_kb(kb_id, req, user.id, db)
    # 缓存失效
    await cache_delete_pattern(f"kb:list:{user.id}:*")
    return ok(data=KBOut.model_validate(kb).model_dump())


@router.delete("/{kb_id}", response_model=APIResponse)
@limiter.limit(RATE_LIMIT_DEFAULT)
async def delete_kb(
    kb_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除知识库。

    需要认证且用户须为 owner。限流 60 次/分钟。会级联清理相关数据。
    返回空数据。
    """
    # 删除前查询协作者列表，用于删除后清理缓存
    # get_collaborators 需要 owner 或协作者权限，owner 调用即可
    collaborators = await kb_service.get_collaborators(kb_id, user.id, db)
    collaborator_ids = [c["user_id"] for c in collaborators if c.get("user_id")]

    await kb_service.delete_kb(kb_id, user.id, db)
    # 缓存失效：清理 owner + 所有协作者的 KB 列表缓存
    await cache_delete_pattern(f"kb:list:{user.id}:*")
    for cid in collaborator_ids:
        await cache_delete_pattern(f"kb:list:{cid}:*")
    return ok(message="Deleted")


# --- Collaboration endpoints ---


@router.post("/{kb_id}/collaborators", response_model=APIResponse[CollaboratorOut])
@limiter.limit(RATE_LIMIT_DEFAULT)
async def add_collaborator(
    kb_id: int,
    req: CollaboratorAdd,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """添加协作者。

    需要认证且当前用户须为该知识库 owner。限流 60 次/分钟。
    返回新增协作者信息。
    """
    data = await kb_service.add_collaborator(kb_id, user.id, req.user_id, req.permission, db)
    return ok(data=data)


@router.delete("/{kb_id}/collaborators/{user_id}", response_model=APIResponse)
@limiter.limit(RATE_LIMIT_DEFAULT)
async def remove_collaborator(
    kb_id: int,
    user_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """移除协作者。

    需要认证且当前用户须为该知识库 owner。限流 60 次/分钟。
    返回空数据。
    """
    await kb_service.remove_collaborator(kb_id, user.id, user_id, db)
    return ok(message="Removed")


@router.get("/{kb_id}/collaborators", response_model=APIResponse[list[CollaboratorOut]])
@limiter.limit(RATE_LIMIT_DEFAULT)
async def get_collaborators(
    kb_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查询知识库协作者列表。

    需要认证且用户须对该知识库有访问权限。限流 60 次/分钟。
    返回协作者列表（含权限信息）。
    """
    data = await kb_service.get_collaborators(kb_id, user.id, db)
    return ok(data=data)
