from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from loguru import logger
import time
import uuid
import base64
import json
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.metrics import REQUEST_TOTAL, REQUEST_LATENCY, REQUEST_IN_PROGRESS


def _rate_limit_key(request: Request) -> str:
    """限流 key: 优先使用 JWT 中的 user_id, fallback 到 IP。

    对于登录用户使用 user_id 可避免共享 IP (如公司/校园网络) 的用户互相影响。
    JWT 解析不验证签名 (限流是辅助措施, 认证由 get_current_user 负责)。
    """
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        try:
            # JWT 格式: header.payload.signature, 只读 payload
            parts = token.split(".")
            if len(parts) >= 2:
                # base64url decode (补齐 padding)
                payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
                sub = payload.get("sub") or payload.get("user_id")
                if sub:
                    return f"user:{sub}"
        except Exception:
            pass  # 解析失败 fallback 到 IP
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    from app.core.errors import ErrorCode, get_error_message
    return JSONResponse(
        status_code=429,
        content={"code": ErrorCode.RATE_LIMITED, "message": get_error_message(ErrorCode.RATE_LIMITED), "data": None},
        headers={"Retry-After": "60"},
    )


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        client_ip = request.client.host if request.client else "unknown"
        
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"from {client_ip} - start"
        )
        
        response = await call_next(request)
        
        process_time = (time.time() - start_time) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
        
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"{response.status_code} - {process_time:.2f}ms"
        )
        
        return response


class PrometheusMiddleware(BaseHTTPMiddleware):
    EXCLUDE_PATHS = {"/metrics", "/health"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        if path in self.EXCLUDE_PATHS:
            return await call_next(request)

        REQUEST_IN_PROGRESS.inc()
        start_time = time.time()
        try:
            response = await call_next(request)
            status_code = str(response.status_code)
            REQUEST_TOTAL.labels(method=method, path=path, status_code=status_code).inc()
            latency = time.time() - start_time
            REQUEST_LATENCY.labels(method=method, path=path).observe(latency)
            return response
        finally:
            REQUEST_IN_PROGRESS.dec()
