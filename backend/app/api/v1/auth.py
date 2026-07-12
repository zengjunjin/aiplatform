from fastapi import APIRouter, Depends, Request
from app.core.middleware import limiter
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.api.deps import get_current_user
from app.services import auth_service
from app.services.audit_service import log_audit
from app.schemas.auth import RegisterRequest, LoginRequest, RefreshRequest, ChangePasswordRequest, TokenResponse, UserResponse
from app.schemas.common import ok
from app.db.user import User
from app.core.errors import ErrorCode

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
@limiter.limit("5/minute")
async def register(request: Request, req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    user = await auth_service.register(req, db)
    await log_audit(db, action="user.register", user_id=user.id, request=request)
    return ok(data=UserResponse.model_validate(user).model_dump())


@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, req: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        tokens = await auth_service.login(req, db)
        await log_audit(db, action="user.login", user_id=tokens["user"]["id"], request=request)
        return ok(data=tokens)
    except Exception as e:
        from app.core.exceptions import AppException
        if isinstance(e, AppException):
            await log_audit(db, action="user.login", user_id=None, request=request,
                           details={"username": req.username}, result="fail")
        raise


@router.post("/refresh")
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    tokens = await auth_service.refresh_token(req.refresh_token, db)
    return ok(data=tokens)


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return ok(data=UserResponse.model_validate(user).model_dump())


@router.post("/logout")
async def logout(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.auth_service import add_to_blacklist
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        await add_to_blacklist(token, "access")
    try:
        body = await request.json()
        refresh_token = body.get("refresh_token")
        if refresh_token:
            await add_to_blacklist(refresh_token, "refresh")
    except Exception:
        pass
    await log_audit(db, action="user.logout", user_id=user.id, request=request)
    return ok(message="Logged out")


@router.put("/password")
async def change_password(
    req: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services import user_service
    await user_service.change_password(user.id, req.old_password, req.new_password, db)
    await log_audit(db, action="user.change_password", user_id=user.id, request=request)
    return ok(message="Password changed")