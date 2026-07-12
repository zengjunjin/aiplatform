from fastapi import Depends, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.core.security import decode_token
from app.core.exceptions import AuthError, ForbiddenError, NotFoundError
from app.db.user import User
from app.redis_client import get_redis
import uuid

security = HTTPBearer(auto_error=False)


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
        raise AuthError("Invalid token subject")
    if user_id <= 0:
        raise AuthError("Invalid token subject")

    # Check blacklist
    redis = get_redis()
    if redis:
        blacklisted = await redis.get(f"auth:blacklist:access:{token}")
        if blacklisted:
            raise AuthError("Token has been revoked")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise AuthError("User not found")
    if not user.is_active:
        raise AuthError("User is disabled")

    return user


async def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise ForbiddenError("Admin access required")
    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not credentials:
        return None
    try:
        return await get_current_user(credentials, db)
    except AuthError:
        return None


async def check_kb_permission(
    kb_id: int,
    permission: str = "read",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if user has access to a knowledge base.
    
    - owner: full access
    - collaborator: checked against collaborators JSON field
    """
    from app.db.knowledge_base import KnowledgeBase

    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("Knowledge base not found")

    # Owner has full access
    if kb.owner_id == user.id:
        return kb

    # Check collaborators
    collaborators = kb.collaborators or []
    for collab in collaborators:
        if collab.get("user_id") == user.id:
            collab_perm = collab.get("permission", "read")
            if permission == "read":
                return kb
            if permission == "write" and collab_perm in ("write", "admin"):
                return kb
            if permission == "admin" and collab_perm == "admin":
                return kb
            raise ForbiddenError("Access denied: insufficient permission")

    raise ForbiddenError("Access denied")