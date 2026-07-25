import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, Request
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_admin_user, get_current_user
from app.core.health_checks import check_db, check_redis
from app.core.middleware import limiter
from app.database import get_db
from app.db.user import User
from app.schemas.common import ok

router = APIRouter(prefix="/system", tags=["system"])


async def _probe(name: str, check: Callable[[], Awaitable[dict]]) -> dict:
    """执行单个组件健康检查，返回状态 dict。失败时返回 {name: "down"}。

    统一处理 try/except + 日志记录，消除 system_status 中的重复结构。
    """
    try:
        return await check()
    except Exception as e:
        logger.warning(f"{name} health check failed: {e}", exc_info=True)
        return {name: "down"}


@router.get("/status")
@limiter.limit("60/minute")
async def system_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Check system component health status (admin only)"""
    from app.config import settings

    async def _check_pg():
        ok, _ = await check_db(db_session=db)
        return {"postgresql": "up" if ok else "down"}

    async def _check_redis():
        ok, msg = await check_redis()
        if ok:
            return {"redis": "up"}
        if msg == "error: not initialized":
            return {"redis": "down (not initialized)"}
        return {"redis": "down"}

    async def _check_ollama():
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.OLLAMA_HOST}/api/tags")
            if r.status_code == 200:
                data = r.json()
                models = [m.get("name") for m in data.get("models", [])]
                return {"ollama": "up", "ollama_models": models}
            return {"ollama": f"down: HTTP {r.status_code}"}

    async def _check_qdrant():
        # Task 14.2: qdrant.get_collections() 是同步阻塞 HTTP 调用，用 asyncio.to_thread 避免阻塞事件循环
        from app.rag.retriever import retriever

        collections = await asyncio.to_thread(retriever.qdrant.get_collections)
        return {"qdrant": "up", "qdrant_collections": len(collections.collections)}

    async def _check_celery():
        from app.tasks.celery_app import celery_app

        stats = await asyncio.to_thread(lambda: celery_app.control.inspect(timeout=2).stats())
        if stats:
            return {"celery": "up", "celery_workers": list(stats.keys())}
        return {"celery": "no_active_workers"}

    probes: list[tuple[str, Callable[[], Awaitable[dict]]]] = [
        ("postgresql", _check_pg),
        ("redis", _check_redis),
        ("ollama", _check_ollama),
        ("qdrant", _check_qdrant),
        ("celery", _check_celery),
    ]

    status: dict = {}
    for name, check in probes:
        status.update(await _probe(name, check))

    return ok(data=status)


@router.get("/models")
@limiter.limit("60/minute")
async def list_models(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """获取所有可用模型列表（需认证）"""
    from app.models.factory import ModelRegistry

    providers = ModelRegistry.list_all()
    models = []
    for name in providers:
        provider = ModelRegistry.get(name)
        models.append(
            {
                "name": provider.provider_name,
                "display_name": f"{provider.model_name} ({'本地' if provider.provider_name.startswith('ollama') else '云端'})",
                "source": "local" if provider.provider_name.startswith("ollama") else "cloud",
                "status": "healthy" if provider.is_healthy else "unhealthy",
            }
        )
    return ok(data={"models": models, "default_model": "ollama"})
