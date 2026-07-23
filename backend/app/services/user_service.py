from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundError
from app.core.security import hash_password, verify_password
from app.db.user import User
from app.redis_client import get_redis


async def _invalidate_user_cache(user_id: int) -> None:
    """删除用户信息缓存；失败仅记录日志，不影响主流程。

    与 deps.get_current_user 中的缓存 key 保持一致：user:{user_id}。
    """
    redis = get_redis()
    if not redis:
        return
    try:
        await redis.delete(f"user:{user_id}")
    except Exception as e:
        logger.warning(f"Failed to invalidate user cache for user:{user_id}: {e}")


async def list_users(db: AsyncSession, page: int = 1, page_size: int = 20) -> tuple[list[User], int]:
    count_result = await db.execute(select(func.count()).select_from(User))
    total = count_result.scalar_one()

    result = await db.execute(
        select(User).offset((page - 1) * page_size).limit(page_size).order_by(User.id.asc())
    )
    items = result.scalars().all()
    return items, total


async def update_role(user_id: int, role: str, db: AsyncSession, admin_id: int) -> User:
    if user_id == admin_id:
        raise AppException(code=400, message="Admin cannot modify own role to prevent lockout")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    user.role = role
    await db.commit()
    await db.refresh(user)
    await _invalidate_user_cache(user_id)
    return user


async def update_status(user_id: int, is_active: bool, db: AsyncSession, admin_id: int) -> User:
    if user_id == admin_id:
        raise AppException(code=400, message="Admin cannot disable own account to prevent lockout")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    user.is_active = is_active
    await db.commit()
    await db.refresh(user)
    await _invalidate_user_cache(user_id)
    return user


def _escape_like(query: str) -> str:
    """转义 SQL LIKE 通配符 % 和 _，以及转义字符本身 \\。

    防止用户输入的 % / _ 被当作通配符，避免信息泄露
    （例如搜索 "%" 不应返回所有用户）。
    """
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_users(db: AsyncSession, query: str, limit: int = 10) -> list[dict]:
    """搜索用户（按用户名），用于协作者添加等场景。

    对用户输入中的 LIKE 通配符（% 和 _）及反斜杠进行转义，
    并通过 escape='\\\\' 告知 SQL 引擎转义字符，避免通配符注入。
    """
    escaped = _escape_like(query)
    pattern = f"%{escaped}%"
    result = await db.execute(
        select(User.id, User.username)
        .where(User.username.ilike(pattern, escape="\\"))
        .limit(limit)
    )
    rows = result.all()
    return [{"id": row[0], "username": row[1]} for row in rows]


async def change_password(user_id: int, old_pwd: str, new_pwd: str, db: AsyncSession) -> None:
    from app.services.auth_service import validate_password_strength
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    if not verify_password(old_pwd, user.password_hash):
        from app.core.exceptions import AppException
        raise AppException(code=400, message="Old password is incorrect")
    validate_password_strength(new_pwd)
    user.password_hash = hash_password(new_pwd)
    await db.commit()
    await _invalidate_user_cache(user_id)
