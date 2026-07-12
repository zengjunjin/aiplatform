import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from app.db.user import User
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.core.exceptions import AuthError, ConflictError, ValidationError
from app.core.errors import ErrorCode
from app.schemas.auth import RegisterRequest, LoginRequest


def validate_password_strength(password: str) -> None:
    from app.config import settings

    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise ValidationError(f"密码至少 {settings.PASSWORD_MIN_LENGTH} 个字符")
    if settings.PASSWORD_REQUIRE_UPPER and not re.search(r'[A-Z]', password):
        raise ValidationError("密码需包含至少一个大写字母")
    if settings.PASSWORD_REQUIRE_LOWER and not re.search(r'[a-z]', password):
        raise ValidationError("密码需包含至少一个小写字母")
    if settings.PASSWORD_REQUIRE_DIGIT and not re.search(r'[0-9]', password):
        raise ValidationError("密码需包含至少一个数字")
    if settings.PASSWORD_REQUIRE_SPECIAL and not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\/]', password):
        raise ValidationError("密码需包含至少一个特殊字符")


async def register(req: RegisterRequest, db: AsyncSession) -> User:
    existing = await db.execute(
        select(User).where(or_(User.username == req.username, User.email == req.email))
    )
    if existing.scalar_one_or_none():
        raise ConflictError("Username or email already exists")

    validate_password_strength(req.password)

    user = User(
        username=req.username,
        email=req.email,
        password_hash=hash_password(req.password),
        role="user",
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("Username or email already exists")
    await db.refresh(user)
    return user


async def login(req: LoginRequest, db: AsyncSession) -> dict:
    result = await db.execute(
        select(User).where(or_(User.username == req.username, User.email == req.username))
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise AuthError("用户名或密码错误", code=ErrorCode.INVALID_CREDENTIALS)
    if not user.is_active:
        raise AuthError("账户已被禁用")

    access = create_access_token(str(user.id), extra={"role": user.role, "username": user.username})
    refresh = create_refresh_token(str(user.id))
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": 30 * 60,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
        },
    }


async def refresh_token(refresh: str, db: AsyncSession) -> dict:
    payload = decode_token(refresh)
    if not payload or payload.get("type") != "refresh":
        raise AuthError("Invalid refresh token")
    if await is_blacklisted(refresh, "refresh"):
        raise AuthError("Refresh token has been revoked")
    user_id = int(payload.get("sub", 0))
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise AuthError("User not found or disabled")

    access = create_access_token(str(user.id), extra={"role": user.role, "username": user.username})
    new_refresh = create_refresh_token(str(user.id))
    return {
        "access_token": access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "expires_in": 30 * 60,
    }

async def add_to_blacklist(token: str, token_type: str = "access"):
    """Add token to Redis blacklist with TTL = remaining time"""
    from app.redis_client import get_redis
    redis = get_redis()
    if not redis:
        return
    payload = decode_token(token)
    if not payload:
        return
    exp = payload.get("exp")
    if not exp:
        return
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).timestamp()
    ttl = int(exp - now)
    if ttl <= 0:
        return
    key = f"auth:blacklist:{token_type}:{token}"
    await redis.setex(key, ttl, "1")


async def is_blacklisted(token: str, token_type: str = "access") -> bool:
    from app.redis_client import get_redis
    redis = get_redis()
    if not redis:
        return False
    key = f"auth:blacklist:{token_type}:{token}"
    return await redis.exists(key) > 0
