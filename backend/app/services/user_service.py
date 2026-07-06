from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.user import User
from app.core.security import hash_password, verify_password
from app.core.exceptions import NotFoundError, AppException
from app.core.errors import ErrorCode


async def list_users(db: AsyncSession, page: int = 1, page_size: int = 20):
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
    return user


async def change_password(user_id: int, old_pwd: str, new_pwd: str, db: AsyncSession):
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