from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.errors import ErrorCode, get_error_message


class AppException(Exception):
    def __init__(self, code: int, message: str | None = None, status_code: int = 400):
        self.code = code
        self.message = message or get_error_message(code)
        self.status_code = status_code


class NotFoundError(AppException):
    def __init__(self, message: str | None = None):
        super().__init__(
            code=ErrorCode.RESOURCE_NOT_FOUND,
            message=message or get_error_message(ErrorCode.RESOURCE_NOT_FOUND),
            status_code=404,
        )


class AuthError(AppException):
    def __init__(self, message: str | None = None, code: int = ErrorCode.AUTH_FAILED):
        super().__init__(
            code=code,
            message=message or get_error_message(code),
            status_code=401,
        )


class ForbiddenError(AppException):
    def __init__(self, message: str | None = None):
        super().__init__(
            code=ErrorCode.PERMISSION_DENIED,
            message=message or get_error_message(ErrorCode.PERMISSION_DENIED),
            status_code=403,
        )


class ConflictError(AppException):
    def __init__(self, code: int = 30001, message: str | None = None):
        super().__init__(
            code=code,
            message=message or get_error_message(code),
            status_code=409,
        )


class RateLimitError(AppException):
    def __init__(self, message: str | None = None):
        super().__init__(
            code=ErrorCode.RATE_LIMITED,
            message=message or get_error_message(ErrorCode.RATE_LIMITED),
            status_code=429,
        )


class ValidationError(AppException):
    def __init__(self, message: str | None = None):
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=message or get_error_message(ErrorCode.VALIDATION_ERROR),
            status_code=400,
        )


class AllProvidersFailedError(AppException):
    """主 provider 失败 + 所有 fallback provider 均失败时抛出（Blade 2 Step 5 专用异常，
    替代原通用 Exception("All LLM providers failed after fallback attempts")），
    便于上游按类型精确处理 / 埋点监控 / 写专用单测。"""

    def __init__(
        self,
        message: str | None = None,
        primary: str | None = None,
        fallbacks_tried: int = 0,
    ):
        detail_parts = []
        if primary:
            detail_parts.append(f"primary={primary}")
        detail_parts.append(f"fallbacks_tried={fallbacks_tried}")
        msg = message or (
            f"All LLM providers failed after fallback attempts ({', '.join(detail_parts)})"
        )
        super().__init__(
            code=ErrorCode.INTERNAL_ERROR,
            message=msg,
            status_code=502,
        )
        self.primary = primary
        self.fallbacks_tried = fallbacks_tried


async def app_exception_handler(request: Request, exc: AppException):
    logger.warning(
        f"AppException: {exc.code} - {exc.message} - {request.method} {request.url.path}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = ".".join(str(loc) for loc in err.get("loc", []))
        msg = err.get("msg", "")
        errors.append(f"{loc}: {msg}")
    message = "; ".join(errors) if errors else get_error_message(ErrorCode.VALIDATION_ERROR)
    logger.warning(f"ValidationError: {message} - {request.method} {request.url.path}")
    return JSONResponse(
        status_code=400,
        content={"code": ErrorCode.VALIDATION_ERROR, "message": message, "data": None},
    )


async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {request.method} {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={
            "code": ErrorCode.INTERNAL_ERROR,
            "message": get_error_message(ErrorCode.INTERNAL_ERROR),
            "data": None,
        },
    )
