# RAG 平台 - 设计文档对齐补全实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 严格按照设计文档补全所有缺失功能，使项目与设计文档 100% 对齐

**Architecture:** 分 6 个 Phase 逐步实施，从高优先级的安全修复到低优先级的优化功能，每个 Phase 结束后进行验收

**Tech Stack:** FastAPI + SQLAlchemy + Redis + Chroma + Celery + pytest + Alembic + slowapi

---

## 文件结构总览

### 新建文件
- `backend/app/core/middleware.py` - 日志 + 限流中间件
- `backend/app/api/deps.py` - 已有，补充 Redis 黑名单检查
- `backend/alembic.ini` - Alembic 配置
- `backend/alembic/env.py` - Alembic 环境
- `backend/alembic/versions/001_init.py` - 初始迁移
- `backend/tests/__init__.py`
- `backend/tests/conftest.py` - 测试配置
- `backend/tests/test_security.py` - 安全模块测试
- `backend/tests/test_rrf.py` - RRF 算法测试
- `backend/tests/test_reference_parser.py` - 引用解析测试
- `backend/tests/test_chunker.py` - 分块测试
- `backend/tests/test_auth_api.py` - 认证 API 测试
- `deploy/docker-compose.yml` - Docker Compose
- `deploy/.env.example` - 环境变量示例
- `backend/README.md` - 启动说明

### 修改文件
- `backend/app/main.py` - 添加中间件、系统状态 API
- `backend/app/api/v1/router.py` - 添加系统状态路由
- `backend/app/api/v1/users.py` - 添加 admin 自我保护
- `backend/app/services/user_service.py` - 添加自我保护逻辑
- `backend/app/api/deps.py` - JWT 黑名单检查
- `backend/app/api/v1/auth.py` - 完善 logout
- `backend/app/services/auth_service.py` - 黑名单逻辑
- `backend/app/api/v1/documents.py` - reparse 防重复
- `backend/app/services/document_service.py` - 状态检查
- `backend/app/tasks/document_task.py` - 解析中状态标记
- `backend/phase4_test.py` - 更新测试
- `backend/phase8_test.py` - 更新测试

---

## Phase A: 安全修复 (高优先级)

### Task A1: Admin 自我保护

**Files:**
- Modify: `backend/app/services/user_service.py`
- Modify: `backend/app/api/v1/users.py`
- Test: `backend/tests/test_admin_protection.py`

- [ ] **Step 1: 在 user_service.py 添加自我保护逻辑**

在 `update_role` 和 `update_status` 函数开头添加检查：
```python
async def update_role(user_id: int, role: str, db: AsyncSession, admin_id: int) -> User:
    if user_id == admin_id:
        raise AppException(code=400, message="Admin cannot modify own role")
    # ... existing code
```

```python
async def update_status(user_id: int, is_active: bool, db: AsyncSession, admin_id: int) -> User:
    if user_id == admin_id:
        raise AppException(code=400, message="Admin cannot disable own account")
    # ... existing code
```

- [ ] **Step 2: 修改 users.py 路由传入 admin_id**

```python
@router.put("/{user_id}/role")
async def update_role(
    user_id: int,
    req: UpdateRoleRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    user = await user_service.update_role(user_id, req.role, db, admin.id)
    return ok(data=UserListResponse.model_validate(user).model_dump())
```

```python
@router.put("/{user_id}/status")
async def update_status(
    user_id: int,
    req: UpdateStatusRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    user = await user_service.update_status(user_id, req.is_active, db, admin.id)
    return ok(data=UserListResponse.model_validate(user).model_dump())
```

- [ ] **Step 3: 验证 - 尝试 admin 禁用自己应返回 400**
- [ ] **Step 4: 验证 - 尝试 admin 修改自己角色应返回 400**
- [ ] **Step 5: 验证 - admin 修改普通用户正常**

---

### Task A2: JWT 黑名单 (登出功能)

**Files:**
- Modify: `backend/app/api/deps.py`
- Modify: `backend/app/api/v1/auth.py`
- Modify: `backend/app/services/auth_service.py`

- [ ] **Step 1: 在 auth_service.py 添加黑名单函数**

```python
from app.redis_client import get_redis
from datetime import datetime, timezone

async def add_to_blacklist(token: str, token_type: str = "access"):
    """Add token to Redis blacklist with TTL = remaining time"""
    redis = get_redis()
    payload = decode_token(token)
    if not payload:
        return
    exp = payload.get("exp")
    if not exp:
        return
    now = datetime.now(timezone.utc).timestamp()
    ttl = int(exp - now)
    if ttl <= 0:
        return
    key = f"auth:blacklist:{token_type}:{token}"
    await redis.setex(key, ttl, "1")


async def is_blacklisted(token: str, token_type: str = "access") -> bool:
    redis = get_redis()
    key = f"auth:blacklist:{token_type}:{token}"
    return await redis.exists(key) > 0
```

- [ ] **Step 2: 修改 logout 接口**

```python
@router.post("/logout")
async def logout(user: User = Depends(get_current_user), request: Request = None):
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        from app.services.auth_service import add_to_blacklist
        await add_to_blacklist(token, "access")
    return ok(message="Logged out")
```

- [ ] **Step 3: 在 deps.py 的 get_current_user 中检查黑名单**

```python
async def get_current_user(...):
    # ... after decoding token
    from app.services.auth_service import is_blacklisted
    if await is_blacklisted(token, "access"):
        raise AuthError("Token has been revoked")
    # ... rest of the code
```

- [ ] **Step 4: 验证 - 登录后调用 logout，再用该 token 访问 /me 返回 401**

---

### Task A3: 限流中间件 (slowapi)

**Files:**
- Create: `backend/app/core/middleware.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/v1/auth.py`
- Modify: `backend/app/api/v1/chat.py`
- Modify: `backend/app/api/v1/documents.py`

- [ ] **Step 1: 创建 Limiter 实例**

在 `app/core/middleware.py` 中：
```python
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from app.redis_client import get_redis
from app.core.exceptions import AppException

limiter = Limiter(key_func=get_remote_address)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    from app.schemas.common import error
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=429,
        content=error(code=429, message="Rate limit exceeded"),
    )
```

- [ ] **Step 2: 在 main.py 注册 limiter**

```python
from app.core.middleware import limiter, rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
```

- [ ] **Step 3: 给登录接口加限流 (5次/分钟/IP)**

```python
from app.core.middleware import limiter
from fastapi import Request

@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, req: LoginRequest, db: AsyncSession = Depends(get_db)):
    tokens = await auth_service.login(req, db)
    return ok(data=tokens)
```

- [ ] **Step 4: 给注册接口加限流 (5次/分钟/IP)**

- [ ] **Step 5: 给文档上传加限流 (10次/小时/用户 - 用 user_id key)**

- [ ] **Step 6: 给聊天消息加限流 (20次/分钟/用户)**

- [ ] **Step 7: 验证 - 连续6次登录返回第6次429**

---

## Phase B: 系统功能补全

### Task B1: 系统状态 API

**Files:**
- Modify: `backend/app/api/v1/router.py`
- Create: `backend/app/api/v1/system.py`

- [ ] **Step 1: 创建 system.py 路由**

```python
from fastapi import APIRouter, Depends
from app.api.deps import get_admin_user
from app.db.user import User
from app.schemas.common import ok
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
async def system_status(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    status = {}
    
    # PostgreSQL check
    try:
        from sqlalchemy import text
        await db.execute(text("SELECT 1"))
        status["postgresql"] = "up"
    except Exception as e:
        status["postgresql"] = f"down: {str(e)}"
    
    # Redis check
    try:
        from app.redis_client import get_redis
        redis = get_redis()
        await redis.ping()
        status["redis"] = "up"
    except Exception as e:
        status["redis"] = f"down: {str(e)}"
    
    # Ollama check
    try:
        import httpx
        from app.config import settings
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.OLLAMA_HOST}/api/tags")
            if r.status_code == 200:
                status["ollama"] = "up"
            else:
                status["ollama"] = f"down: HTTP {r.status_code}"
    except Exception as e:
        status["ollama"] = f"down: {str(e)}"
    
    # Chroma check
    try:
        import chromadb
        from app.config import settings
        client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        client.heartbeat()
        status["chroma"] = "up"
    except Exception as e:
        status["chroma"] = f"down: {str(e)}"
    
    return ok(data=status)
```

- [ ] **Step 2: 在 router.py 中注册**

```python
from app.api.v1.system import router as system_router
api_router.include_router(system_router)
```

- [ ] **Step 3: 验证 - admin 访问 /api/v1/system/status 返回各组件状态**
- [ ] **Step 4: 验证 - 普通用户访问返回 403**

---

### Task B2: 请求日志中间件

**Files:**
- Modify: `backend/app/core/middleware.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: 添加日志中间件**

在 `middleware.py` 中添加：
```python
import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from loguru import logger


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"start"
        )
        
        response = await call_next(request)
        
        process_time = (time.time() - start_time) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
        
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"{response.status_code} {process_time:.2f}ms"
        )
        
        return response
```

- [ ] **Step 2: 在 main.py 注册中间件**

```python
from app.core.middleware import RequestLogMiddleware

app.add_middleware(RequestLogMiddleware)
```

- [ ] **Step 3: 验证 - 访问接口有 request_id 和耗时日志**

---

### Task B3: 文档重新解析防重复

**Files:**
- Modify: `backend/app/api/v1/documents.py`
- Modify: `backend/app/tasks/document_task.py`

- [ ] **Step 1: 在 reparse 接口检查状态**

```python
@router.post("/{doc_id}/reparse")
async def reparse_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_service.get_document(doc_id, user.id, db)
    if doc.status in ("parsing", "embedding", "chunking"):
        raise AppException(code=409, message="Document is already being parsed")
    doc.status = "parsing"
    doc.error_message = None
    await db.commit()
    from app.tasks.document_task import parse_document_task
    task = parse_document_task.delay(doc.id)
    return ok(data={"document_id": doc.id, "task_id": task.id})
```

- [ ] **Step 2: 验证 - 连续点击两次 reparse，第二次返回 409**

---

## Phase C: Alembic 数据库迁移

### Task C1: 初始化 Alembic

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/001_init_tables.py`

- [ ] **Step 1: 创建 alembic.ini**

```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+psycopg2://rag:rag_dev_pwd@localhost:5432/rag_platform

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic
```

- [ ] **Step 2: 创建 alembic/env.py**

```python
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db.base import Base
from app.config import settings

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url_sync)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: 创建初始迁移 001_init_tables.py**

手动编写所有 6 张表的创建语句（users, knowledge_bases, documents, document_chunks, chat_sessions, chat_messages）

- [ ] **Step 4: 运行 alembic upgrade head 验证能成功创建表**
- [ ] **Step 5: 运行 alembic downgrade base 验证可逆**
- [ ] **Step 6: 再 upgrade 回来恢复数据**

---

## Phase D: 单元测试

### Task D1: 测试基础设施

**Files:**
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: 创建 conftest.py 测试配置**

```python
import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.db.base import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
```

---

### Task D2: 核心模块单元测试

**Files:**
- Create: `backend/tests/test_security.py`
- Create: `backend/tests/test_rrf.py`
- Create: `backend/tests/test_reference_parser.py`
- Create: `backend/tests/test_chunker.py`

- [ ] **Step 1: 密码哈希测试 (test_security.py)**
  - 正常密码验证通过
  - 错误密码验证失败
  - 哈希值不包含明文

- [ ] **Step 2: JWT 测试 (test_security.py)**
  - 创建 token 能解码
  - 过期 token 解码失败
  - 篡改 token 解码失败

- [ ] **Step 3: RRF 融合测试 (test_rrf.py)**
  - 已知输入验证分数计算正确
  - 重叠项排前面
  - 空输入返回空

- [ ] **Step 4: 引用解析测试 (test_reference_parser.py)**
  - 正常引用 [1][2] 正确解析
  - 无引用返回空
  - 越界引用 [99] 被忽略
  - 重复引用去重

- [ ] **Step 5: 分块策略测试 (test_chunker.py)**
  - 正常长度文档分块数正确
  - 相邻 chunk 有重叠
  - 拼接后与原文相似度 ≥ 99%
  - 短文档不分块

- [ ] **Step 6: 运行 pytest --cov=app 查看覆盖率**
- [ ] **Step 7: 目标: rag/ ≥ 70%, parsers/ ≥ 70%, core/ ≥ 80%**

---

## Phase E: Docker Compose 部署 + README

### Task E1: Docker Compose

**Files:**
- Create: `deploy/docker-compose.yml`
- Create: `deploy/.env.example`
- Create: `backend/Dockerfile`

- [ ] **Step 1: 创建 docker-compose.yml**

包含服务: postgres:16, redis:7-alpine, backend, celery_worker
（Ollama 和 Chroma 用本地卷挂载方式）

- [ ] **Step 2: 创建 Dockerfile**
  - 基于 python:3.12-slim
  - 安装 poetry 和系统依赖
  - 拷贝代码安装依赖
  - 启动 uvicorn

- [ ] **Step 3: 创建 .env.example**

---

### Task E2: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: 编写完整启动步骤**
  - 环境要求
  - 快速启动 (Docker Compose)
  - 手动启动步骤
  - 默认账号
  - API 文档地址

---

## Phase F: Phase 8 可选优化

### Task F1: Embedding 缓存

**Files:**
- Modify: `backend/app/models/ollama_provider.py`

- [ ] **Step 1: 添加 Redis 缓存**
  - 用 SHA256(text) 作为 key
  - 缓存 7 天
  - 相同文本第二次 embed 从缓存读

---

### Task F2: BM25 增量更新

**Files:**
- Modify: `backend/app/rag/bm25.py`

- [ ] **Step 1: 添加增量 add_documents 方法**
- [ ] **Step 2: 添加删除文档方法**
- [ ] **Step 3: 修改 document_task 用增量而非全量重建**

---

### Task F3: 流式停止生成

**Files:**
- Modify: `backend/app/api/v1/chat.py`
- Modify: `backend/app/services/chat_service.py`

- [ ] **Step 1: 添加 cancel 标志到 Redis**
- [ ] **Step 2: 在生成循环中检查 cancel 标志**
- [ ] **Step 3: 添加取消生成 API 端点**

---

## 最终验收

- [ ] 重跑 phase4_test.py → 全部通过
- [ ] 重跑 phase5_test.py → 全部通过
- [ ] 重跑 phase6_test.py → 全部通过
- [ ] 重跑 phase7_test.py → 全部通过
- [ ] 重跑 phase8_test.py → 全部通过
- [ ] 运行 pytest --cov=app → 核心模块 ≥ 70%
- [ ] 访问 /api/v1/system/status → 正常
- [ ] admin 自我保护测试 → 通过
- [ ] 限流测试 → 通过
- [ ] JWT 黑名单测试 → 通过
