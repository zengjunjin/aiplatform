from fastapi import APIRouter, Depends, Request
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.middleware import limiter
from app.database import get_db
from app.db.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    UserResponse,
)
from app.schemas.common import ok
from app.services import auth_service
from app.services.audit_service import log_audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
@limiter.limit("5/minute")
async def register(request: Request, req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    user = await auth_service.register(req, db)
    await log_audit(action="user.register", user_id=user.id, request=request)
    return ok(data=UserResponse.model_validate(user).model_dump())


@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, req: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        tokens = await auth_service.login(req, db)
        await log_audit(action="user.login", user_id=tokens["user"]["id"], request=request)
        return ok(data=tokens)
    except Exception as e:
        from app.core.exceptions import AppException

        if isinstance(e, AppException):
            await log_audit(
                action="user.login",
                user_id=None,
                request=request,
                details={"username": req.username},
                result="fail",
            )
        else:
            # Task 32: 非 AppException（内部异常）也记录审计，便于排查 5xx 类故障
            logger.exception("login internal error for username=%s", req.username)
            await log_audit(
                action="user.login",
                user_id=None,
                request=request,
                details={"username": req.username},
                result="fail_internal",
            )
        raise


@router.post("/refresh")
@limiter.limit("10/minute")
async def refresh(request: Request, req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    tokens = await auth_service.refresh_token(req.refresh_token, db)
    return ok(data=tokens)


@router.get("/me")
@limiter.limit("60/minute")
async def me(request: Request, user: User = Depends(get_current_user)):
    return ok(data=UserResponse.model_validate(user).model_dump())


@router.post("/logout")
@limiter.limit("60/minute")
async def logout(
    request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    from app.services.auth_service import add_to_blacklist

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        await add_to_blacklist(token, "access")
    try:
        body = await request.json()
        # 显式类型校验：客户端可能发送 JSON 数组/字符串/数字等非对象类型，
        # 此时 body 不是 dict，直接跳过 refresh_token 处理（不抛异常，保持 200 响应）。
        if not isinstance(body, dict):
            logger.warning(
                f"Logout body is not a JSON object, skip refresh_token blacklist: type={type(body).__name__}"
            )
        else:
            refresh_token = body.get("refresh_token")
            if refresh_token:
                await add_to_blacklist(refresh_token, "refresh")
    except Exception as e:
        logger.warning(f"Failed to parse refresh_token from logout body: {e}", exc_info=True)
    await log_audit(action="user.logout", user_id=user.id, request=request)
    return ok(message="Logged out")


@router.put("/password")
@limiter.limit("10/minute")
async def change_password(
    req: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services import user_service

    await user_service.change_password(user.id, req.old_password, req.new_password, db)
    await log_audit(action="user.change_password", user_id=user.id, request=request)
    return ok(message="Password changed")
