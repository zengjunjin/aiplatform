import json

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import AuthError, ForbiddenError
from app.core.security import decode_token
from app.database import get_db
from app.db.user import User
from app.redis_client import get_redis

security = HTTPBearer(auto_error=False)

# ---------- 用户信息缓存 ----------
# 缓存用户基本信息以减少 get_current_user 的 DB 查询；
# TTL 较短（默认 60s，可通过 USER_CACHE_TTL 环境变量配置），在角色/状态/密码变更时主动失效。
USER_CACHE_TTL = settings.USER_CACHE_TTL


def _user_cache_key(user_id: int) -> str:
    return f"user:{user_id}"


def _serialize_user(user: User) -> dict:
    """将 User ORM 对象序列化为可缓存 dict。

    故意排除 password_hash 等敏感字段；仅保留鉴权链路所需字段。
    """
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
    }


def _deserialize_user(data: dict) -> User:
    """从缓存 dict 构造 User 实例（不绑定到任何 session）。"""
    return User(
        id=data["id"],
        username=data["username"],
        email=data["email"],
        role=data["role"],
        is_active=data["is_active"],
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise AuthError("Missing authentication token")

    token = credentials.credentials
    payload = decode_token(token)
    if not payload:
        raise AuthError("Invalid or expired token")

    if payload.get("type") != "access":
        raise AuthError("Invalid token type")

    try:
        user_id = int(payload.get("sub", 0))
    except (TypeError, ValueError):
        raise AuthError("Invalid token subject") from None
    if user_id <= 0:
        raise AuthError("Invalid token subject")

    # Check blacklist
    redis = get_redis()
    if redis:
        blacklisted = await redis.get(f"auth:blacklist:access:{token}")
        if blacklisted:
            raise AuthError("Token has been revoked")
    else:
        # Redis 不可用：降级到内存黑名单检查（best-effort，不保证跨进程一致）
        from app.services.auth_service import is_blacklisted

        if await is_blacklisted(token, "access"):
            raise AuthError("Token has been revoked")

    # 优先查 Redis 用户缓存（命中则跳过 DB 查询）
    if redis:
        try:
            cached = await redis.get(_user_cache_key(user_id))
            if cached:
                try:
                    return _deserialize_user(json.loads(cached))
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    logger.warning(f"User cache corrupted for {_user_cache_key(user_id)}: {e}")
        except Exception as e:
            logger.warning(f"Redis cache read failed for {_user_cache_key(user_id)}: {e}")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise AuthError("User not found")
    if not user.is_active:
        raise AuthError("User is disabled")

    # 仅缓存活跃用户，避免禁用用户被短期复用
    if redis:
        try:
            await redis.setex(
                _user_cache_key(user_id),
                USER_CACHE_TTL,
                json.dumps(_serialize_user(user), default=str),
            )
        except Exception as e:
            logger.warning(f"Redis cache write failed for {_user_cache_key(user_id)}: {e}")

    return user


async def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise ForbiddenError("Admin access required")
    return user
