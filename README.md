# RAG 知识库问答平台

[![Backend CI](https://github.com/your-username/your-repo/actions/workflows/backend-ci.yml/badge.svg)](https://github.com/your-username/your-repo/actions/workflows/backend-ci.yml)
[![Frontend CI](https://github.com/your-username/your-repo/actions/workflows/frontend-ci.yml/badge.svg)](https://github.com/your-username/your-repo/actions/workflows/frontend-ci.yml)
[![Full CI & Release](https://github.com/your-username/your-repo/actions/workflows/full-ci.yml/badge.svg)](https://github.com/your-username/your-repo/actions/workflows/full-ci.yml)

基于 FastAPI + Qdrant + Ollama 的企业级 RAG (Retrieval-Augmented Generation) 知识库问答系统。

## 功能特性

- **混合检索**: BM25 关键词检索 + 向量相似度检索 + RRF 融合
- **Rerank 重排序**: 基于交叉编码器的结果重排序
- **流式对话**: SSE 流式响应，支持引用来源标注
- **多格式支持**: PDF、DOCX、Markdown、TXT 文档解析
- **RBAC 权限**: 管理员/用户角色权限控制
- **JWT 认证**: Token 黑名单 + 刷新令牌机制
- **限流保护**: API 速率限制，防止滥用
- **异步处理**: Celery 异步文档解析和向量入库
- **数据库迁移**: Alembic 版本化数据库 schema 管理

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | FastAPI (Python 3.12) |
| 数据库 | PostgreSQL + SQLAlchemy 2.0 |
| 缓存/队列 | Redis + Celery |
| 向量库 | Qdrant |
| LLM | Ollama (兼容 OpenAI API) |
| ORM/迁移 | SQLAlchemy + Alembic |
| 认证 | JWT (access + refresh) |

## 快速开始

### 便捷命令 (Makefile)

项目在 `deploy/` 目录提供了 Makefile，简化常用操作：

```bash
make up        # 启动所有服务 (docker-compose up -d)
make down      # 停止所有服务
make logs      # 查看后端和 worker 日志 (实时跟踪)
make migrate   # 执行数据库迁移 (alembic upgrade head)
make restart   # 重启后端和 worker
make init-models  # 拉取 Ollama 模型 (qwen2.5:7b 等)
make test      # 运行后端单元测试
make clean     # 清理所有容器和数据卷
```

> 提示: Makefile 会自动 `cd deploy && docker-compose ...`，无需手动切换目录。

### 方式一: Docker Compose (推荐)

```bash
# 克隆项目后进入目录
cd aiplatform

# 启动所有服务
docker-compose up -d

# 初始化数据库
docker-compose exec backend alembic upgrade head

# 创建管理员账号
docker-compose exec backend python -c "
import asyncio
from app.db.database import async_session
from app.services.user_service import create_user
async def main():
    async with async_session() as db:
        await create_user(db, 'admin', 'admin123', 'admin@example.com', role='admin')
        print('Admin created')
asyncio.run(main())
"
```

访问: http://localhost:8000

### 方式二: 本地开发

#### 前置依赖

- Python 3.12+
- PostgreSQL 14+
- Redis 7+
- Qdrant (可选，使用持久化模式)
- Ollama (运行 LLM)

#### 安装步骤

```bash
cd backend

# 安装依赖
pip install poetry
poetry install

# 配置环境变量
cp ../.env.example .env
# 编辑 .env 填入你的配置

# 数据库迁移
poetry run alembic upgrade head

# 创建管理员
poetry run python -c "
import asyncio
from app.db.database import async_session
from app.services.user_service import create_user
async def main():
    async with async_session() as db:
        await create_user(db, 'admin', 'admin123', 'admin@example.com', role='admin')
asyncio.run(main())
"

# 启动后端
poetry run uvicorn app.main:app --reload

# 启动 Celery worker (另开终端)
poetry run celery -A app.core.celery_app worker --loglevel=info

# 启动前端 (另开终端)
cd ../frontend
npm install
npm run tauri:dev   # 桌面应用 (Tauri)
# 或
npm run dev         # 仅 Web 模式
```

## API 文档

启动后访问:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 主要 API

### 认证
- `POST /api/v1/auth/register` - 用户注册
- `POST /api/v1/auth/login` - 用户登录
- `POST /api/v1/auth/logout` - 用户登出
- `POST /api/v1/auth/refresh` - 刷新 Token

### 知识库
- `GET /api/v1/knowledge-bases` - 知识库列表
- `POST /api/v1/knowledge-bases` - 创建知识库
- `DELETE /api/v1/knowledge-bases/{id}` - 删除知识库

### 文档
- `POST /api/v1/knowledge-bases/{kb_id}/documents/upload` - 上传文档
- `GET /api/v1/knowledge-bases/{kb_id}/documents` - 文档列表
- `DELETE /api/v1/documents/{doc_id}` - 删除文档
- `POST /api/v1/documents/{doc_id}/reparse` - 重新解析

### 对话
- `GET /api/v1/chat/sessions` - 会话列表
- `POST /api/v1/chat/sessions` - 创建会话
- `POST /api/v1/chat/send` - 发送消息（流式 SSE）

### 系统
- `GET /health` - 健康检查
- `GET /api/v1/system/status` - 系统状态（需管理员）

## 项目结构

```
aiplatform/
├── backend/
│   ├── app/
│   │   ├── api/              # API 路由
│   │   │   ├── deps.py
│   │   │   └── v1/
│   │   │       ├── auth.py
│   │   │       ├── chat.py
│   │   │       ├── documents.py
│   │   │       ├── knowledge_bases.py
│   │   │       ├── router.py
│   │   │       ├── system.py
│   │   │       └── users.py
│   │   ├── core/             # 核心模块
│   │   │   ├── exceptions.py
│   │   │   ├── generation_manager.py
│   │   │   ├── middleware.py
│   │   │   └── security.py
│   │   ├── db/               # 数据库模型
│   │   │   ├── base.py
│   │   │   ├── chat_message.py
│   │   │   ├── chat_session.py
│   │   │   ├── document.py
│   │   │   ├── document_chunk.py
│   │   │   ├── knowledge_base.py
│   │   │   └── user.py
│   │   ├── models/           # 模型工厂 / Provider
│   │   │   ├── base.py
│   │   │   ├── factory.py
│   │   │   ├── cached_embedding.py
│   │   │   ├── ollama_provider.py
│   │   │   └── reranker_provider.py
│   │   ├── parsers/          # 文档解析
│   │   │   ├── base.py
│   │   │   ├── pdf_parser.py
│   │   │   ├── docx_parser.py
│   │   │   ├── markdown_parser.py
│   │   │   ├── text_parser.py
│   │   │   └── chunker.py
│   │   ├── rag/              # RAG 核心
│   │   │   ├── retriever.py
│   │   │   ├── bm25.py
│   │   │   ├── reranker.py
│   │   │   ├── prompt_builder.py
│   │   │   ├── reference_parser.py
│   │   │   └── context_manager.py
│   │   ├── schemas/          # Pydantic 请求/响应模型
│   │   │   ├── auth.py
│   │   │   ├── chat.py
│   │   │   ├── document.py
│   │   │   ├── kb.py
│   │   │   └── user.py
│   │   ├── services/         # 业务服务
│   │   │   ├── auth_service.py
│   │   │   ├── chat_service.py
│   │   │   ├── user_service.py
│   │   │   ├── kb_service.py
│   │   │   └── document_service.py
│   │   ├── tasks/            # 异步任务 (Celery)
│   │   │   ├── celery_app.py
│   │   │   └── document_task.py
│   │   ├── utils/            # 工具
│   │   │   ├── storage.py
│   │   │   └── token_counter.py
│   │   ├── config.py         # 配置
│   │   ├── database.py       # 数据库连接
│   │   ├── redis_client.py   # Redis 客户端
│   │   └── main.py           # 应用入口
│   ├── alembic/              # 数据库迁移
│   ├── tests/                # 单元测试
│   ├── storage/              # 上传文件存储
│   └── pyproject.toml
├── frontend/                 # 前端 (React + Tauri)
│   ├── src/
│   │   ├── api/
│   │   ├── store/
│   │   ├── pages/
│   │   └── components/
│   ├── src-tauri/            # Tauri 桌面应用
│   └── package.json
├── deploy/                   # 部署配置
│   ├── Makefile
│   ├── docker-compose.yml
│   └── nginx.conf
├── docker-compose.yml
└── .env.example
```

## 单元测试

```bash
cd backend
poetry run pytest tests/ -v --cov=app
```

核心模块覆盖率:
- `app.core.security`: 100%
- `app.rag.prompt_builder`: 100%
- `app.rag.reference_parser`: 100%
- `app.parsers.base`: 100%
- `app.rag.bm25`: 86%
- `app.parsers.chunker`: 85%

## 配置说明

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接串 | - |
| `REDIS_URL` | Redis 连接串 | - |
| `QDRANT_HOST` / `QDRANT_PORT` | Qdrant 地址 | localhost:6333 |
| `JWT_SECRET` | JWT 签名密钥 | - |
| `OLLAMA_BASE_URL` | Ollama API 地址 | http://localhost:11434 |
| `LLM_MODEL` | LLM 模型名 | qwen2.5:7b |
| `EMBEDDING_MODEL` | Embedding 模型 | nomic-embed-text |
| `CHUNK_SIZE` | 文本分块大小 | 512 |
| `TOP_K` | 检索返回数量 | 10 |

## 安全说明

- 生产环境必须修改 `JWT_SECRET`
- 默认管理员账号请及时修改密码
- 所有 API 均经过认证授权校验
- JWT Token 支持黑名单机制
- API 限流防止暴力攻击

## 架构决策记录 (ADR)

本项目的重要架构决策以 ADR（Architecture Decision Record）形式记录在 `docs/adr/` 目录中：

| ADR | 标题 | 决策 |
|-----|------|------|
| [ADR-001](docs/adr/ADR-001-fastapi-over-django-flask.md) | 为何选择 FastAPI 而非 Django/Flask | FastAPI：异步支持、高性能、自动文档生成 |
| [ADR-002](docs/adr/ADR-002-qdrant-over-milvus-weaviate-pinecone.md) | 为何选择 Qdrant 而非 Milvus/Weaviate/Pinecone | Qdrant：轻量、Rust 实现、本地部署友好 |
| [ADR-003](docs/adr/ADR-003-diy-rag-over-langchain-llamaindex.md) | 为何自建 RAG 管线而非使用 LangChain/LlamaIndex | 自建：避免框架锁定、深入理解原理 |
| [ADR-004](docs/adr/ADR-004-sse-over-websocket-for-streaming.md) | 为何选择 SSE 而非 WebSocket 做流式生成 | SSE：单向数据流、HTTP 兼容、实现简单 |
| [ADR-005](docs/adr/ADR-005-hybrid-retrieval-over-pure-vector.md) | 为何选择混合检索而非纯向量检索 | BM25 + 向量 + RRF：关键词与语义互补 |

新增 ADR 请使用 [TEMPLATE.md](docs/adr/TEMPLATE.md) 模板。

## License

MIT
