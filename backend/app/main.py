import asyncio
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from loguru import logger
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi.errors import RateLimitExceeded

from app.api.deps import get_admin_user
from app.api.v1.router import api_router
from app.config import settings
from app.db.user import User
from app.core.exceptions import (
    AppException,
    app_exception_handler,
    generic_exception_handler,
    validation_exception_handler,
)
from app.core.middleware import (
    PrometheusMiddleware,
    RequestLogMiddleware,
    limiter,
    rate_limit_exceeded_handler,
)
from app.redis_client import get_redis, init_redis
from app.tasks.metrics_collector import metrics_collector_loop


# Task 32: 跟踪进行中的 SSE 请求，用于优雅关闭时等待其完成。
# 在 chat._run_sse_stream 中将当前 asyncio.Task 加入此集合，finally 中移除。
_active_sse_requests: set[asyncio.Task] = set()


def _setup_opentelemetry() -> None:
    """初始化 OpenTelemetry 追踪（导出到 OTLP/Jaeger）。

    通过环境变量 ``OTEL_EXPORTER_OTLP_ENDPOINT`` 控制启用：
    - 未配置时直接跳过，不影响应用启动；
    - 配置后会对 SQLAlchemy / Celery / httpx 进行自动埋点，
      FastAPI 仪器化由 lifespan 在 app 创建后调用 ``FastAPIInstrumentor.instrument_app``。

    Service name 默认 ``rag-platform-backend``，可通过 ``OTEL_SERVICE_NAME`` 覆盖。
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set, OpenTelemetry disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        service_name = os.getenv("OTEL_SERVICE_NAME", "rag-platform-backend")
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # SQLAlchemy / httpx / Celery 全局仪器化（FastAPI 在 lifespan 中单独 instrument_app）
        # 注意：项目使用 async engine（create_async_engine），SQLAlchemyInstrumentor
        # 默认全局仪器化即可覆盖；显式传 sync_engine 在纯异步项目里容易触发 ImportError。
        SQLAlchemyInstrumentor().instrument(enable_commenter=True, commenter_options={})
        HTTPXClientInstrumentor().instrument()
        CeleryInstrumentor().instrument()
        logger.info(f"OpenTelemetry initialized, exporting to {endpoint}/v1/traces")
    except Exception as exc:  # pragma: no cover - OTel 初始化失败不应阻断启动
        logger.warning(f"OpenTelemetry initialization failed: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME}...")
    init_redis()
    logger.info("Redis initialized")

    # Task 10: 从 DB 加载 prompt 模板到内存缓存（失败时 fallback 到默认值，不阻断启动）
    from app.rag.prompt_builder import load_prompt_templates
    await load_prompt_templates()
    logger.info("Prompt templates loaded")

    # Initialize EventBus
    from app.core.events import EventBus
    await EventBus.init()
    logger.info("EventBus initialized")

    # Task 60: 注册 document_service 的事件订阅（原在模块加载时注册，移到 lifespan 避免 import 副作用）
    from app.services.document_service import register_event_handlers
    register_event_handlers()
    logger.info("Document service event handlers registered")

    # Initialize model registry from config
    from app.models import init_model_registry
    init_model_registry()
    logger.info("Model registry initialized")

    # Start model health checker
    from app.core.model_health import get_health_checker
    health_checker = get_health_checker()
    await health_checker.start()
    logger.info("Model health checker started")

    metrics_task = asyncio.create_task(metrics_collector_loop(settings.METRICS_COLLECTOR_INTERVAL))
    logger.info("Metrics collector started")

    # OpenTelemetry 追踪初始化（仅当 OTEL_EXPORTER_OTLP_ENDPOINT 配置时启用）
    _setup_opentelemetry()
    # FastAPI 仪器化需在 app 创建后执行；lifespan 在 app 创建后才被调用，安全
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)
            logger.info("FastAPI OpenTelemetry instrumentation enabled")
        except Exception as exc:  # pragma: no cover
            logger.warning(f"FastAPI instrumentation failed: {exc}")

    try:
        yield
    finally:
        # Task 32: 优雅关闭 — 等待进行中的 SSE 请求完成（超时 30s 强制取消）
        if _active_sse_requests:
            logger.info(
                f"Graceful shutdown: waiting for {len(_active_sse_requests)} active SSE requests"
            )
            try:
                await asyncio.wait_for(
                    asyncio.gather(*_active_sse_requests, return_exceptions=True),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                still_active = len(_active_sse_requests)
                logger.warning(
                    f"Graceful shutdown: {still_active} SSE requests still active after 30s, force cancelling"
                )
                for task in list(_active_sse_requests):
                    task.cancel()
                await asyncio.gather(*_active_sse_requests, return_exceptions=True)
        metrics_task.cancel()
        try:
            await metrics_task
        except asyncio.CancelledError:
            pass
        # Stop health checker
        await health_checker.stop()
        # Close EventBus
        await EventBus.close()
        # Close all LLM/Embedding/Reranker provider httpx clients
        from app.models.factory import ModelFactory, ModelRegistry
        try:
            await ModelRegistry.close_all()
        except Exception as exc:
            logger.warning(f"Error closing ModelRegistry providers: {exc}")
        try:
            await ModelFactory.close_all()
        except Exception as exc:
            logger.warning(f"Error closing ModelFactory providers: {exc}")
        # Close Redis connection gracefully
        redis = get_redis()
        if redis:
            await redis.aclose()
        logger.info("Shutting down...")


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(RequestLogMiddleware)
app.add_middleware(PrometheusMiddleware)
# CORS: 当 origins 包含 * 时禁止 credentials (浏览器规范)
cors_origins = settings.cors_origin_list
if "*" in cors_origins:
    # 通配符 origin 与 credentials=true 互斥（CORS 规范），
    # 即使配置中显式开启了 credentials 也要强制关闭，避免浏览器拒绝请求或泄漏 cookie。
    allow_creds = False
    logger.warning(
        "CORS origins contains wildcard '*'; force-disabling allow_credentials "
        "per browser CORS spec (cookies/Authorization won't be sent cross-site)."
    )
else:
    allow_creds = True
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_creds,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

app.include_router(api_router)


@app.get("/metrics")
async def metrics(admin: User = Depends(get_admin_user)):
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/internal/metrics")
async def internal_metrics(
    authorization: str | None = Header(None, alias="Authorization"),
):
    """Prometheus 抓取端点，使用 METRICS_TOKEN Bearer 鉴权。

    与 `/metrics`（admin 浏览器查看）分离，避免 Prometheus scraper 持有 admin JWT。
    未配置 METRICS_TOKEN 时返回 503，明确表示该端点未启用。
    """
    if not settings.METRICS_TOKEN:
        raise HTTPException(status_code=503, detail="METRICS_TOKEN not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token")
    token = authorization.removeprefix("Bearer ")
    if not secrets.compare_digest(token, settings.METRICS_TOKEN or ""):
        raise HTTPException(status_code=401, detail="Invalid token")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health():
    return {"code": 0, "message": "ok", "data": {"status": "healthy"}}


# ---------- 健康探测辅助函数（Task 45）----------
# 每个探测有独立超时（2s），避免单一依赖故障阻塞 /readyz 响应
# 返回 (ok, message)：ok=True 表示就绪，message 用于 checks 详情


async def _check_db() -> tuple[bool, str]:
    """Probe DB with SELECT 1（2s 超时，委托 app.core.health_checks）。"""
    return await health_checks.check_db()


async def _check_redis() -> tuple[bool, str]:
    """Probe Redis with PING（2s 超时，委托 app.core.health_checks）。"""
    try:
        return await asyncio.wait_for(health_checks.check_redis(), timeout=2)
    except asyncio.TimeoutError as e:
        return False, f"error: {e}"


async def _check_qdrant() -> tuple[bool, str]:
    """Probe Qdrant with GET /healthz（2s 超时，委托 app.core.health_checks）。"""
    return await health_checks.check_qdrant()


@app.get("/healthz")
async def healthz():
    """Liveness probe：仅进程存活。

    不探测外部依赖，只要进程能响应即返回 200。
    用于 Kubernetes/Docker 判断是否需要重启容器。
    """
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    """Readiness probe：探测 DB/Redis/Qdrant 是否就绪。

    全部就绪返回 200 + ``{"status": "ready", "checks": {...}}``，
    任一失败返回 503 + ``{"status": "not_ready", "checks": {...}}``。
    用于 Kubernetes/Docker 判断是否可以将流量路由到本实例。
    """
    db_ok, db_msg = await _check_db()
    redis_ok, redis_msg = await _check_redis()
    qdrant_ok, qdrant_msg = await _check_qdrant()

    checks = {
        "db": db_msg,
        "redis": redis_msg,
        "qdrant": qdrant_msg,
    }
    all_ready = db_ok and redis_ok and qdrant_ok

    if all_ready:
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "checks": checks},
        )
    return JSONResponse(
        status_code=503,
        content={"status": "not_ready", "checks": checks},
    )


@app.get("/")
async def root():
    return {"code": 0, "message": "ok", "data": {"app": settings.APP_NAME, "version": "0.1.0"}}
