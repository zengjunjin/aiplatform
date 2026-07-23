from typing import Any

from fastapi import Request
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.db.audit_log import AuditLog


async def log_audit(
    action: str,
    user_id: int | None = None,
    request: Request | None = None,
    details: dict[str, Any] | None = None,
    result: str = "success",
    db: AsyncSession | None = None,
):
    """记录审计日志。

    Task 34: 支持主事务一致性写入。
    - 传入 db 时：使用主 session 写审计（同事务），审计随主事务一起 commit/rollback，
      适用于需要强一致性的场景（如 delete_kb：DB 删除与审计同生共死）。
    - 不传 db 时：使用独立 session 写入（原行为），避免对主事务产生影响
      (提前 commit 会导致主事务中未提交的更改被意外持久化)。
    """
    ip = None
    ua = None
    if request:
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent")

    log = AuditLog(
        user_id=user_id,
        action=action,
        ip_address=ip,
        user_agent=ua,
        details=details,
        result=result,
    )
    try:
        if db is not None:
            # 主事务模式：仅 add，由调用方控制 commit/rollback
            db.add(log)
        else:
            # 独立 session 模式（原行为）：立即 commit 持久化
            async with async_session() as audit_db:
                audit_db.add(log)
                await audit_db.commit()
    except Exception as e:
        # 审计日志失败不应影响主业务流程
        logger.warning(f"Failed to write audit log: {e}")
