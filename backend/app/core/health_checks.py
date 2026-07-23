"""共享的健康检查逻辑。

抽取自 ``app/main.py`` 的 ``/readyz`` 端点与 ``app/api/v1/system.py`` 的
``/system/status`` 端点中重复的 DB / Redis / Qdrant 探测逻辑。

约定：每个探测函数返回 ``(ok, message)`` 元组——``ok=True`` 表示组件就绪，
``message`` 在成功时为 ``"ok"``，失败时为 ``"error: <详情>"``，供调用方直接填入
``checks`` 详情或自行格式化为 up/down 状态。

注意：``/system/status`` 的 Qdrant 探测使用 ``retriever.qdrant.get_collections()``
并返回集合数量，属于不同业务语义，不在此处统一，仍保留在 ``system.py`` 中。
"""

import asyncio

import httpx
from sqlalchemy import text

from app.config import settings
from app.database import async_session


async def check_db(db_session=None) -> tuple[bool, str]:
    """检查 PostgreSQL 连接 (SELECT 1)。

    - ``db_session`` 为 ``None`` 时（``/readyz`` 场景）：内部新建独立 session 并施加
      2s 超时，与原 ``main._check_db`` 行为一致。
    - 传入 session 时（``/system/status`` 场景）：复用该 session，不施加额外超时，
      与原 ``system._check_pg`` 行为一致。
    """
    try:
        if db_session is not None:
            await db_session.execute(text("SELECT 1"))
        else:
            async with async_session() as session:
                await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2)
        return True, "ok"
    except Exception as e:
        return False, f"error: {e}"


async def check_redis() -> tuple[bool, str]:
    """检查 Redis 连接 (PING)。

    本函数不施加超时——``/readyz`` 调用方（``main._check_redis``）通过
    ``asyncio.wait_for`` 在外层施加 2s 超时；``/system/status`` 调用方不施加超时，
    以保持两端的原始超时配置不变。

    ``get_redis`` 采用局部导入，以保证测试可通过 ``patch("app.redis_client.get_redis")``
    进行替换。
    """
    from app.redis_client import get_redis

    try:
        redis = get_redis()
        if not redis:
            return False, "error: not initialized"
        await redis.ping()
        return True, "ok"
    except Exception as e:
        return False, f"error: {e}"


async def check_qdrant() -> tuple[bool, str]:
    """检查 Qdrant 连接 (GET /healthz，2s 超时)。

    与原 ``main._check_qdrant`` 行为一致，供 ``/readyz`` 使用。
    """
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            url = f"http://{settings.QDRANT_HOST}:{settings.QDRANT_PORT}/healthz"
            resp = await client.get(url)
            resp.raise_for_status()
        return True, "ok"
    except Exception as e:
        return False, f"error: {e}"


async def check_all() -> dict:
    """检查所有组件 (DB/Redis/Qdrant)，返回结构化结果。

    返回::

        {
            "db": {"ok": bool, "message": str},
            "redis": {"ok": bool, "message": str},
            "qdrant": {"ok": bool, "message": str},
        }

    供需要一次性获取全部探测结果的调用方使用；各端点可按自身响应格式从此结构中
    提取 ``message`` 或 ``ok`` 进行格式化。
    """
    db_ok, db_msg = await check_db()
    redis_ok, redis_msg = await check_redis()
    qdrant_ok, qdrant_msg = await check_qdrant()
    return {
        "db": {"ok": db_ok, "message": db_msg},
        "redis": {"ok": redis_ok, "message": redis_msg},
        "qdrant": {"ok": qdrant_ok, "message": qdrant_msg},
    }
