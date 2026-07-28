import asyncio
import re
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import ErrorCode
from app.core.exceptions import AuthError, ConflictError, ValidationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.user import User
from app.schemas.auth import LoginRequest, RegisterRequest

# 内存降级黑名单（Redis 不可用时使用）
# 注意：这是 best-effort 降级，不保证跨进程一致。
# 内存黑名单仅在当前进程有效，进程重启后失效；多进程/多实例部署下其他进程无法感知。
# 仅用于 Redis 不可用时避免 fail-open，不应作为常规黑名单存储。
_memory_blacklist: dict[str, float] = {}  # key="{token_type}:{token}" -> exp timestamp
_memory_blacklist_max = (
    settings.TOKEN_BLACKLIST_MAX
)  # 上限防止无限增长（可通过 TOKEN_BLACKLIST_MAX 环境变量配置）
# P0-D1: 保护 _memory_blacklist 的并发访问，避免 Redis 降级路径下
# "dictionary changed size during iteration" 导致全站认证失败
_memory_blacklist_lock = asyncio.Lock()


def validate_password_strength(password: str) -> None:
    from app.config import settings

    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise ValidationError(f"密码至少 {settings.PASSWORD_MIN_LENGTH} 个字符")
    if settings.PASSWORD_REQUIRE_UPPER and not re.search(r"[A-Z]", password):
        raise ValidationError("密码需包含至少一个大写字母")
    if settings.PASSWORD_REQUIRE_LOWER and not re.search(r"[a-z]", password):
        raise ValidationError("密码需包含至少一个小写字母")
    if settings.PASSWORD_REQUIRE_DIGIT and not re.search(r"[0-9]", password):
        raise ValidationError("密码需包含至少一个数字")
    if settings.PASSWORD_REQUIRE_SPECIAL and not re.search(
        r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\/]', password
    ):
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
    except IntegrityError as e:
        await db.rollback()
        raise ConflictError("Username or email already exists") from e
    await db.refresh(user)
    return user


async def login(req: LoginRequest, db: AsyncSession) -> dict:
    from app.config import settings

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
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
        },
    }


async def refresh_token(refresh: str, db: AsyncSession) -> dict:
    from app.config import settings

    payload = decode_token(refresh)
    if not payload or payload.get("type") != "refresh":
        raise AuthError("Invalid refresh token")
    if await is_blacklisted(refresh, "refresh"):
        raise AuthError("Refresh token has been revoked")
    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError) as e:
        raise AuthError("Invalid refresh token: malformed subject") from e
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise AuthError("User not found or disabled")

    access = create_access_token(str(user.id), extra={"role": user.role, "username": user.username})
    new_refresh = create_refresh_token(str(user.id))
    await add_to_blacklist(refresh, "refresh")
    return {
        "access_token": access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
        },
    }


async def _memory_blacklist_add(token_type: str, token: str, exp: float) -> None:
    """将 token 加入内存黑名单。超限时丢弃最旧条目（插入顺序）。

    best-effort 降级：不保证跨进程一致，仅当前进程可见。
    使用 asyncio.Lock 保护并发访问，避免 "dictionary changed size during iteration"。
    """
    key = f"{token_type}:{token}"
    async with _memory_blacklist_lock:
        _memory_blacklist[key] = exp
        if len(_memory_blacklist) > _memory_blacklist_max:
            # dict 保持插入顺序（Python 3.7+），弹出最旧条目
            # 注意：dict.popitem() 不接受 last 参数（那是 OrderedDict 的接口）
            oldest_key = next(iter(_memory_blacklist))
            del _memory_blacklist[oldest_key]


async def _memory_blacklist_contains(token_type: str, token: str) -> bool:
    """检查 token 是否在内存黑名单中，顺带清理该条目的过期项。

    best-effort 降级：不保证跨进程一致，仅当前进程可见。
    使用 asyncio.Lock 保护并发访问。
    """
    key = f"{token_type}:{token}"
    async with _memory_blacklist_lock:
        exp = _memory_blacklist.get(key)
        if exp is None:
            return False
        now = datetime.now(UTC).timestamp()
        if exp <= now:
            # 已过期，清理并返回未命中
            _memory_blacklist.pop(key, None)
            return False
        return True


async def add_to_blacklist(token: str, token_type: str = "access") -> None:
    """Add token to Redis blacklist with TTL = remaining time.

    Redis 不可用时降级到进程内存黑名单（best-effort，不保证跨进程一致）。
    """
    from app.redis_client import get_redis

    payload = decode_token(token)
    if not payload:
        return
    exp = payload.get("exp")
    if not exp:
        return
    now = datetime.now(UTC).timestamp()
    ttl = int(exp - now)
    if ttl <= 0:
        return
    redis = get_redis()
    if redis:
        key = f"auth:blacklist:{token_type}:{token}"
        await redis.setex(key, ttl, "1")
    else:
        # Redis 不可用：降级到内存黑名单（best-effort，不保证跨进程一致）
        await _memory_blacklist_add(token_type, token, exp)


async def is_blacklisted(token: str, token_type: str = "access") -> bool:
    from app.redis_client import get_redis

    redis = get_redis()
    if redis:
        key = f"auth:blacklist:{token_type}:{token}"
        return await redis.exists(key) > 0
    # Redis 不可用：检查内存降级黑名单（best-effort，不保证跨进程一致）
    return await _memory_blacklist_contains(token_type, token)
