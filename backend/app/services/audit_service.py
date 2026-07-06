from typing import Any
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.audit_log import AuditLog
from app.database import async_session
from loguru import logger


async def log_audit(
    db: AsyncSession,
    action: str,
    user_id: int | None = None,
    request: Request | None = None,
    details: dict[str, Any] | None = None,
    result: str = "success",
):
    """记录审计日志。

    使用独立 db 会话写入, 避免对主事务产生影响 (提前 commit 会导致主事务中未提交的更改被意外持久化)。
    db 参数保留用于向后兼容, 但不再直接使用。
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
        async with async_session() as audit_db:
            audit_db.add(log)
            await audit_db.commit()
    except Exception as e:
        # 审计日志失败不应影响主业务流程
        logger.warning(f"Failed to write audit log: {e}")
