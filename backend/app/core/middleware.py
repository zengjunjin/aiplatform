import contextvars
import logging
import re
import sys
import time
import uuid
from typing import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from loguru import logger
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.core.metrics import REQUEST_IN_PROGRESS, REQUEST_LATENCY, REQUEST_TOTAL


# ---------- stdlib logging → loguru 转发（Task 2.1）----------
# InterceptHandler 将所有 stdlib logging 调用转发到 loguru，确保 LOG_JSON=true 时
# 仍使用 stdlib logging 的第三方库（如 celery、sqlalchemy、uvicorn.access）的日志
# 也被统一结构化输出。
class InterceptHandler(logging.Handler):
    """将 stdlib logging 记录转发到 loguru。

    按标准 logging level 映射到 loguru level，保留 message/format/args，
    并把原始 logger name 作为 loguru 的 extra[name]。
    """

    def emit(self, record: logging.LogRecord) -> None:
        # 获取对应的 loguru level
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 找到真正发出日志的调用栈深度（跳过 logging 内部帧）
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _configure_stdlib_logging() -> None:
    """配置 stdlib logging 使用 InterceptHandler 转发到 loguru。

    覆盖 root logger 与常见第三方库 logger（uvicorn/celery/sqlalchemy）。
    """
    intercept = InterceptHandler()
    # root logger
    logging.basicConfig(handlers=[intercept], level=0, force=True)
    # 常见第三方库 logger 显式设置 level，避免被默认 WARNING 过滤
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "celery", "sqlalchemy"):
        target_logger = logging.getLogger(name)
        target_logger.handlers = [intercept]
        target_logger.propagate = False
        target_logger.setLevel(0)


_configure_stdlib_logging()


# ---------- request_id contextvar（Task 46）----------
# 用于 loguru patcher 把 request_id 注入到所有日志 record 的 extra 字段。
# contextvars 在 async 上下文中自动隔离，避免并发请求互相覆盖。
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


# ---------- loguru 配置（Task 46 + Task 4 + Task 5）----------
# patcher：
#   1. 注入 request_id（来自 contextvar，async 隔离）
#   2. 注入 trace_id / span_id（来自 OpenTelemetry 当前 span，Task 4）
# 这样 LOG_JSON=true 时 JSON sink 输出会包含 request_id/trace_id/span_id 字段，
# 使日志可在 Loki 中通过 trace_id 关联到 Jaeger trace。
def _log_patcher(record: dict) -> None:
    """注入 request_id / trace_id / span_id 到 loguru record 的 extra 字段。"""
    record["extra"]["request_id"] = request_id_var.get()
    # Task 4: 从 OTel 当前 span 获取 trace_id / span_id
    # 无活跃 span 时（如非请求上下文或 OTel 未启用）注入空字符串占位
    trace_id = ""
    span_id = ""
    try:
        from opentelemetry.trace import INVALID_SPAN, get_current_span

        span = get_current_span()
        if span is not None and span is not INVALID_SPAN:
            ctx = span.get_span_context()
            if ctx is not None and ctx.is_valid:
                trace_id = f"{ctx.trace_id:032x}"
                span_id = f"{ctx.span_id:016x}"
    except Exception:
        # opentelemetry 未安装或运行时异常时不影响日志输出
        pass
    record["extra"]["trace_id"] = trace_id
    record["extra"]["span_id"] = span_id


logger.configure(patcher=_log_patcher)


# Task 5: 日志脱敏过滤
# 匹配 password / token / api_key / secret 字段及其值，替换为 ***REDACTED***
_SENSITIVE_PATTERNS = re.compile(
    r'(password|token|api_key|secret)["\']?\s*[:=]\s*["\']?([^\s"\']+)',
    re.I,
)


def _redact_filter(record: dict) -> bool:
    """对 loguru record 的 message 做脱敏处理。

    匹配 password|token|api_key|secret 字段的值替换为 ***REDACTED***，
    其他字段保持不变。返回 True 表示日志继续输出。
    """
    if record.get("message"):
        record["message"] = _SENSITIVE_PATTERNS.sub(
            r'\1=***REDACTED***', record["message"]
        )
    return True


# LOG_JSON=true 时启用 JSON sink：输出包含 timestamp/level/request_id/trace_id/
# span_id/message/module/function/line 等字段的 JSON 行，便于 ELK/Loki 等日志采集系统解析。
# 同时应用脱敏 filter（Task 5）。
if settings.LOG_JSON:
    logger.add(sys.stdout, serialize=True, filter=_redact_filter)


def _rate_limit_key(request: Request) -> str:
    """限流 key: 优先使用 JWT 中的 user_id, fallback 到 IP。

    对于登录用户使用 user_id 可避免共享 IP (如公司/校园网络) 的用户互相影响。
    验证 JWT 签名防止伪造 sub 字段绕过限流。
    """
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        try:
            from app.core.security import decode_token
            payload = decode_token(token)
            if payload:
                sub = payload.get("sub") or payload.get("user_id")
                if sub:
                    return f"user:{sub}"
        except Exception:
            pass  # 验证失败 fallback 到 IP
    return get_remote_address(request)


# RATE_LIMIT_ENABLED 开关：测试环境可设 false 全局禁用限流。
# slowapi 0.1.9+ 的 Limiter 支持 enabled 参数，为 False 时所有 @limiter.limit
# 装饰器变为 no-op，不执行限流计数和 429 响应。
limiter = Limiter(
    key_func=_rate_limit_key,
    enabled=settings.RATE_LIMIT_ENABLED,
)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    from app.core.errors import ErrorCode, get_error_message
    return JSONResponse(
        status_code=429,
        content={"code": ErrorCode.RATE_LIMITED, "message": get_error_message(ErrorCode.RATE_LIMITED), "data": None},
        headers={"Retry-After": "60"},
    )


class RequestLogMiddleware:
    """纯 ASGI 中间件: 记录请求日志并添加 X-Request-ID / X-Process-Time header。

    使用纯 ASGI 实现（而非 BaseHTTPMiddleware）以避免 call_next 通过
    anyio.create_task_group() 创建后台任务导致的跨事件循环问题：
    后台任务可能运行在与 Redis/DB 连接不同的事件循环上，引发
    "got Future attached to a different loop" 错误。
    """

    def __init__(self, app: Callable[..., Awaitable[None]]):
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        client = scope.get("client")
        client_ip = client[0] if client else "unknown"

        method = scope["method"]
        path = scope["path"]

        # Task 46: 把 request_id 写入 contextvar，使 loguru patcher 能注入到
        # 本次请求范围内所有日志 record 的 extra 字段。
        # 使用 set/reset token 模式确保 async 上下文隔离，避免并发请求互相污染。
        token = request_id_var.set(request_id)
        status_code: int | None = None
        try:
            logger.info(
                f"[{request_id}] {method} {path} from {client_ip} - start"
            )

            async def send_wrapper(message: dict) -> None:
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = message["status"]
                    process_time = (time.time() - start_time) * 1000
                    headers = list(message.get("headers", []))
                    headers.append((b"x-request-id", request_id.encode()))
                    headers.append((b"x-process-time", f"{process_time:.2f}ms".encode()))
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, send_wrapper)

            process_time = (time.time() - start_time) * 1000
            logger.info(
                f"[{request_id}] {method} {path} {status_code} - {process_time:.2f}ms"
            )
        finally:
            request_id_var.reset(token)


class PrometheusMiddleware:
    """纯 ASGI 中间件: 记录 Prometheus 指标 (REQUEST_TOTAL / REQUEST_LATENCY / REQUEST_IN_PROGRESS)。

    使用纯 ASGI 实现（而非 BaseHTTPMiddleware）以避免跨事件循环问题。
    """

    EXCLUDE_PATHS = {"/metrics", "/health", "/healthz", "/readyz", "/internal/metrics"}

    def __init__(self, app: Callable[..., Awaitable[None]]):
        self.app = app

    @staticmethod
    def _get_path_template(scope: dict) -> str:
        """获取路由模板路径, 避免 /api/v1/users/123 等路径参数导致指标基数爆炸。

        优先使用 FastAPI 路由的 path 模板; 取不到时回退到原始路径。
        """
        route = scope.get("route")
        if route is not None:
            path = getattr(route, "path", None)
            if isinstance(path, str):
                return path
        return scope["path"]

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]

        if path in self.EXCLUDE_PATHS:
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        # 使用路由模板路径, 避免路径参数导致 Prometheus 指标基数爆炸
        metric_path = self._get_path_template(scope)

        REQUEST_IN_PROGRESS.inc()
        start_time = time.time()
        status_code: str | None = None
        try:
            async def send_wrapper(message: dict) -> None:
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = str(message["status"])
                await send(message)

            await self.app(scope, receive, send_wrapper)

            if status_code is not None:
                REQUEST_TOTAL.labels(
                    method=method, path=metric_path, status_code=status_code
                ).inc()
                latency = time.time() - start_time
                REQUEST_LATENCY.labels(method=method, path=metric_path).observe(latency)
        finally:
            REQUEST_IN_PROGRESS.dec()
