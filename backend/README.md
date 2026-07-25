# RAG 知识库平台后端

RAG 知识库平台的后端服务，提供知识库管理、文档解析、向量检索、对话问答、评估反馈等完整能力。

## 技术栈

- **Web 框架**：FastAPI 0.115 + Uvicorn
- **ORM / 数据库**：SQLAlchemy 2.0 + Alembic + PostgreSQL（asyncpg）
- **任务队列**：Celery 5.4（Broker/Backend：Redis）
- **向量数据库**：Qdrant
- **缓存 / 限流**：Redis 5 + slowapi
- **认证**：JWT（PyJWT + passlib/bcrypt）
- **RAG**：sentence-transformers + rank-bm25 + jieba
- **文档解析**：pdfplumber / python-docx / markdown
- **可观测性**：loguru + prometheus-client + OpenTelemetry（OTLP 导出至 Jaeger）
- **测试**：pytest + pytest-asyncio + pytest-cov + pytest-xdist

## 快速开始

### 前置依赖

- Python 3.12+
- [Poetry](https://python-poetry.org/)
- PostgreSQL、Redis、Qdrant（可参考根目录 `deploy/` 中的 docker-compose 启动）

### 安装与运行

```bash
# 1. 创建虚拟环境并安装依赖
poetry env use python3.12
poetry install

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填写 POSTGRES_PASSWORD、JWT_SECRET 等必填项

# 3. 进入虚拟环境
poetry shell

# 4. 执行数据库迁移
alembic upgrade head

# 5. 启动服务（默认监听 8000）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

启动后访问：

- API 文档：`http://localhost:8000/docs`（需 `ENABLE_DOCS=true`）
- 健康检查：`http://localhost:8000/healthz`、`/readyz`
- Prometheus 指标：`/metrics`（需配置 `METRICS_TOKEN`）

## 项目结构

```
backend/
├── app/
│   ├── api/                # HTTP 路由层
│   │   ├── deps.py         # 公共依赖（鉴权、DB 会话等）
│   │   └── v1/             # v1 版本路由（auth/users/kb/documents/chat/system/evaluation/ws）
│   │       └── router.py   # 路由聚合
│   ├── services/           # 业务服务层（auth/chat/document/kb/evaluation/feedback/audit/user）
│   ├── core/               # 横切关注点（middleware/security/exceptions/health/metrics/cache/events）
│   ├── db/                 # SQLAlchemy ORM 模型（user/kb/document/chat_session/evaluation 等）
│   ├── models/             # LLM / Embedding / Reranker 提供商抽象与实现
│   ├── rag/                # RAG 核心组件（retriever/bm25/reranker/context_manager/prompt_builder）
│   ├── parsers/            # 文档解析与分块（pdf/docx/markdown/text）
│   ├── tasks/              # Celery 异步任务（document/evaluation/feedback/metrics_collector）
│   ├── schemas/            # Pydantic 请求/响应模型
│   ├── utils/              # 通用工具（storage/token_counter）
│   ├── config.py           # 配置加载（pydantic-settings）
│   ├── database.py         # 数据库引擎与会话
│   ├── redis_client.py     # Redis 客户端
│   └── main.py             # 应用入口、生命周期、中间件、路由挂载
├── tests/                  # 测试代码
├── alembic/                # 数据库迁移脚本
├── pyproject.toml          # Poetry 依赖与工具配置
└── .env.example            # 环境变量模板
```

## 测试

```bash
# 运行全部测试
poetry run pytest

# 多进程加速
poetry run pytest -n auto

# 仅运行集成测试 / E2E / RAG 真实链路测试
poetry run pytest -m integration
poetry run pytest -m e2e
poetry run pytest -m real_rag

# 生成覆盖率报告（配置见 pyproject.toml [tool.coverage]）
poetry run pytest --cov=app --cov-report=term-missing
```

测试标记说明（定义于 `pyproject.toml`）：

- `integration`：依赖真实服务（PG/Redis/Qdrant）的集成测试
- `real_rag`：基于真实 Ollama + Qdrant 的 RAG 链路测试
- `e2e`：端到端用户旅程测试
- `slow`：耗时较长的测试

## 配置说明

所有配置通过环境变量注入，模板见 `.env.example`，主要分组：

- **应用**：`APP_NAME` / `DEBUG` / `ENABLE_DOCS` / `LOG_LEVEL` / `LOG_JSON`
- **数据库**：`POSTGRES_*` / `DB_POOL_*`
- **Redis / Qdrant**：`REDIS_*` / `QDRANT_*`
- **安全**：`JWT_*` / `PASSWORD_*` / `INITIAL_ADMIN_PASSWORD`
- **LLM / Embedding / Reranker**：`LLM_*` / `EMBEDDING_*` / `RERANKER_MODEL`
- **检索与分块**：`CHUNK_*` / `RETRIEVAL_*` / `BM25_*` / `RRF_K`
- **CORS / WebSocket / SSE**：`CORS_ORIGINS` / `WEBSOCKET_*` / `SSE_*`
- **Celery**：`CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND`
- **可观测性**：`OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_SERVICE_NAME` / `METRICS_TOKEN`

请参考 `.env.example` 中的注释逐项配置。

## 部署

部署相关说明请参考：

- 根目录 `README.md`：整体部署架构与一键启动方式
- `deploy/` 目录：docker-compose、环境编排、初始化脚本等

## 代码规范

- 格式与 Lint：`ruff check .` / `ruff format .`（配置见 `pyproject.toml [tool.ruff]`）
- 类型检查：`mypy app`（宽松策略，专注真实缺陷，详见 `pyproject.toml [tool.mypy]`）
