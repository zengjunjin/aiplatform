from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_db
from app.api.deps import get_admin_user
from app.db.user import User
from app.schemas.common import ok

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
async def system_status(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Check system component health status (admin only)"""
    status = {}

    # PostgreSQL
    try:
        await db.execute(text("SELECT 1"))
        status["postgresql"] = "up"
    except Exception:
        status["postgresql"] = "down"

    # Redis
    try:
        from app.redis_client import get_redis
        redis = get_redis()
        if redis is None:
            status["redis"] = "down (not initialized)"
        else:
            await redis.ping()
            status["redis"] = "up"
    except Exception:
        status["redis"] = "down"

    # Ollama
    try:
        import httpx
        from app.config import settings
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.OLLAMA_HOST}/api/tags")
            if r.status_code == 200:
                data = r.json()
                models = [m.get("name") for m in data.get("models", [])]
                status["ollama"] = "up"
                status["ollama_models"] = models
            else:
                status["ollama"] = f"down: HTTP {r.status_code}"
    except Exception:
        status["ollama"] = f"down"

    # Qdrant
    try:
        from app.rag.retriever import retriever
        collections = retriever.qdrant.get_collections()
        status["qdrant"] = "up"
        status["qdrant_collections"] = len(collections.collections)
    except Exception:
        status["qdrant"] = f"down"

    # Celery (best effort, check broker)
    try:
        from app.tasks.celery_app import celery_app
        insp = celery_app.control.inspect(timeout=2)
        stats = insp.stats()
        if stats:
            status["celery"] = "up"
            status["celery_workers"] = list(stats.keys())
        else:
            status["celery"] = "no_active_workers"
    except Exception:
        status["celery"] = f"down"

    return ok(data=status)


@router.get("/models")
async def list_models():
    """获取所有可用模型列表"""
    from app.models.factory import ModelRegistry

    providers = ModelRegistry.list_all()
    models = []
    for name in providers:
        provider = ModelRegistry.get(name)
        models.append({
            "name": provider.provider_name,
            "display_name": f"{provider.model_name} ({'本地' if provider.provider_name.startswith('ollama') else '云端'})",
            "source": "local" if provider.provider_name.startswith("ollama") else "cloud",
            "status": "healthy" if provider.is_healthy else "unhealthy",
        })
    return ok(data={"models": models, "default_model": "ollama"})
