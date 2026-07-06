from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from loguru import logger
from app.config import settings
from app.redis_client import init_redis, get_redis
import asyncio
from app.tasks.metrics_collector import metrics_collector_loop
from app.core.exceptions import (
    AppException,
    app_exception_handler,
    generic_exception_handler,
    validation_exception_handler,
)
from app.core.middleware import limiter, rate_limit_exceeded_handler, RequestLogMiddleware, PrometheusMiddleware
from slowapi.errors import RateLimitExceeded
from app.api.v1.router import api_router
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME}...")
    init_redis()
    logger.info("Redis initialized")

    metrics_task = asyncio.create_task(metrics_collector_loop(60))
    logger.info("Metrics collector started")

    try:
        yield
    finally:
        metrics_task.cancel()
        try:
            await metrics_task
        except asyncio.CancelledError:
            pass
        # Close Redis connection gracefully
        redis = get_redis()
        if redis:
            await redis.aclose()
        logger.info("Shutting down...")


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(RequestLogMiddleware)
app.add_middleware(PrometheusMiddleware)
# CORS: 当 origins 为 * 时禁止 credentials (浏览器规范)
cors_origins = settings.cors_origin_list
allow_creds = cors_origins != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_creds,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

app.include_router(api_router)


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health():
    return {"code": 0, "message": "ok", "data": {"status": "healthy"}}


@app.get("/")
async def root():
    return {"code": 0, "message": "ok", "data": {"app": settings.APP_NAME, "version": "0.1.0"}}