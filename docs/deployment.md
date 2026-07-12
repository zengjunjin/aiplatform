# RAG 知识库平台 — 部署文档

> 版本：v0.2.0
> 更新日期：2026-07-11

---

## 目录

1. [Docker Compose 部署](#1-docker-compose-部署)
2. [裸机部署](#2-裸机部署)
3. [环境变量完整说明](#3-环境变量完整说明)
4. [常见问题排查](#4-常见问题排查)

---

## 1. Docker Compose 部署

### 1.1 前置要求

- Docker 24.x+
- Docker Compose v2.24.x+
- 至少 8GB 可用内存（含 Ollama 模型）
- 至少 20GB 可用磁盘空间

### 1.2 快速启动

```bash
# 1. 克隆项目
git clone <repository-url> rag-platform
cd rag-platform

# 2. 配置环境变量
cp deploy/.env.example deploy/.env
# 编辑 deploy/.env，修改必要配置（尤其是 JWT_SECRET）

# 3. 启动所有服务
docker compose -f deploy/docker-compose.yml up -d

# 4. 查看服务状态
docker compose -f deploy/docker-compose.yml ps

# 5. 查看日志
docker compose -f deploy/docker-compose.yml logs -f backend
```

### 1.3 服务架构

```
                    ┌─────────────────┐
                    │  Nginx (:80)    │
                    │  反向代理        │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
       ┌──────▼──────┐ ┌───▼────┐  ┌──────▼──────┐
       │  Frontend   │ │Backend │  │   /docs     │
       │  (React     │ │(:8000) │  │   /redoc    │
       │   SPA)      │ │        │  │   /health   │
       └─────────────┘ └───┬────┘  └─────────────┘
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
  ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
  │ PostgreSQL  │   │   Redis     │   │   Qdrant    │
  │   (:5432)   │   │  (:6379)    │   │  (:6333)    │
  └─────────────┘   └──────┬──────┘   └─────────────┘
                           │
                    ┌──────▼──────┐
                    │   Celery    │
                    │   Worker    │
                    └─────────────┘
```

### 1.4 服务说明

| 服务 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| nginx | nginx:alpine | 80 | 反向代理，统一入口 |
| frontend | 自定义构建 | 80 (内部) | React SPA 静态文件 |
| backend | 自定义构建 | 8000 (内部) | FastAPI 后端 |
| celery_worker | 自定义构建 | — | 异步文档解析 |
| postgres | postgres:16-alpine | 5432 | 关系型数据库 |
| redis | redis:7-alpine | 6379 | 缓存与消息队列 |
| qdrant | qdrant/qdrant:v1.10.1 | 6333, 6334 | 向量数据库 |
| ollama | ollama/ollama:latest | 11434 | 本地 LLM 推理 |

### 1.5 首次启动后操作

```bash
# 1. 拉取 Ollama 模型（需要一些时间）
docker exec -it deploy-ollama-1 ollama pull qwen2.5:7b
docker exec -it deploy-ollama-1 ollama pull nomic-embed-text

# 2. 数据库迁移已自动执行（backend 启动命令包含 alembic upgrade head）

# 3. 创建管理员账号
docker exec -it deploy-backend-1 python init_db.py
```

### 1.6 停止与清理

```bash
# 停止所有服务
docker compose -f deploy/docker-compose.yml down

# 停止并删除数据卷（慎用！）
docker compose -f deploy/docker-compose.yml down -v
```

---

## 2. 裸机部署

### 2.1 前置要求

- Ubuntu 22.04+ / Debian 12+ / CentOS Stream 9+
- Python 3.12+
- Node.js 20+
- PostgreSQL 15+
- Redis 7+
- Qdrant 1.10+
- Ollama（可选，用于本地 LLM 推理）

### 2.2 安装依赖

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev \
  postgresql postgresql-contrib redis-server \
  build-essential libpq-dev curl

# 安装 Poetry
curl -sSL https://install.python-poetry.org | python3 -

# 安装 Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

### 2.3 配置 PostgreSQL

```bash
sudo -u postgres psql <<EOF
CREATE USER rag WITH PASSWORD 'rag_password';
CREATE DATABASE rag_platform OWNER rag;
GRANT ALL PRIVILEGES ON DATABASE rag_platform TO rag;
\c rag_platform
GRANT ALL ON SCHEMA public TO rag;
EOF
```

### 2.4 配置 Redis

```bash
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

### 2.5 安装 Qdrant

```bash
# 方式一：Docker
docker run -d --name qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v qdrant_data:/qdrant/storage \
  qdrant/qdrant:v1.10.1

# 方式二：二进制安装
wget https://github.com/qdrant/qdrant/releases/download/v1.10.1/qdrant-x86_64-unknown-linux-gnu.tar.gz
tar -xzf qdrant-x86_64-unknown-linux-gnu.tar.gz
./qdrant
```

### 2.6 部署后端

```bash
cd backend

# 安装 Python 依赖
poetry install --no-dev

# 配置环境变量
cp .env.example .env
# 编辑 .env，修改数据库连接、JWT_SECRET 等

# 运行数据库迁移
poetry run alembic upgrade head

# 初始化管理员账号
poetry run python init_db.py

# 启动后端（生产环境使用 Gunicorn + Uvicorn）
poetry run gunicorn app.main:app \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  -b 0.0.0.0:8000 \
  --access-logfile - \
  --error-logfile -

# 启动 Celery Worker（另一个终端）
poetry run celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2
```

### 2.7 部署前端

```bash
cd frontend

# 安装依赖
npm install

# 构建生产版本
npm run build

# 使用 Nginx 托管静态文件
sudo cp -r dist/* /var/www/html/

# 配置 Nginx（参考 deploy/nginx.conf）
sudo cp deploy/nginx.conf /etc/nginx/sites-available/rag-platform
sudo ln -s /etc/nginx/sites-available/rag-platform /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 2.8 配置 Systemd 服务

创建 `/etc/systemd/system/rag-backend.service`：

```ini
[Unit]
Description=RAG Platform Backend
After=network.target postgresql.service redis-server.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/rag-platform/backend
ExecStart=/opt/rag-platform/backend/.venv/bin/gunicorn app.main:app \
  -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
Restart=always
RestartSec=5
EnvironmentFile=/opt/rag-platform/backend/.env

[Install]
WantedBy=multi-user.target
```

创建 `/etc/systemd/system/rag-celery.service`：

```ini
[Unit]
Description=RAG Platform Celery Worker
After=network.target redis-server.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/rag-platform/backend
ExecStart=/opt/rag-platform/backend/.venv/bin/celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2
Restart=always
RestartSec=5
EnvironmentFile=/opt/rag-platform/backend/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable rag-backend rag-celery
sudo systemctl start rag-backend rag-celery
```

---

## 3. 环境变量完整说明

### 3.1 应用配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_NAME` | `RAG Platform` | 应用名称 |
| `DEBUG` | `false` | 调试模式（开启后显示 /docs 和 /redoc） |

### 3.2 数据库配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `POSTGRES_HOST` | `localhost` | PostgreSQL 主机地址 |
| `POSTGRES_PORT` | `5432` | PostgreSQL 端口 |
| `POSTGRES_USER` | `rag` | 数据库用户名 |
| `POSTGRES_PASSWORD` | `rag_dev_pwd` | 数据库密码 |
| `POSTGRES_DB` | `rag_platform` | 数据库名称 |
| `DB_POOL_SIZE` | `20` | 连接池大小 |
| `DB_MAX_OVERFLOW` | `30` | 连接池最大溢出 |
| `DB_POOL_RECYCLE` | `3600` | 连接回收时间（秒） |
| `DB_POOL_PRE_PING` | `true` | 连接前检查可用性 |

### 3.3 Redis 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REDIS_HOST` | `localhost` | Redis 主机地址 |
| `REDIS_PORT` | `6379` | Redis 端口 |
| `REDIS_DB` | `0` | Redis 数据库编号 |

### 3.4 Qdrant 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `QDRANT_HOST` | `localhost` | Qdrant 主机地址 |
| `QDRANT_PORT` | `6333` | Qdrant HTTP 端口 |
| `QDRANT_GRPC_PORT` | `6334` | Qdrant gRPC 端口 |

### 3.5 JWT 安全配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `JWT_SECRET` | `change-me-in-production` | **生产环境必须修改！** JWT 签名密钥 |
| `JWT_ALGORITHM` | `HS256` | JWT 签名算法 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access Token 有效期（分钟） |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh Token 有效期（天） |

### 3.6 LLM 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama 服务地址 |
| `LLM_PROVIDER` | `ollama` | 默认 LLM Provider |
| `LLM_MODEL` | `qwen2.5:7b` | 默认 LLM 模型 |
| `LLM_PROVIDERS` | JSON 数组 | 多 Provider 配置（详见下方） |
| `LLM_ROUTING_STRATEGY` | `round_robin` | 路由策略 |
| `LLM_FALLBACK_ENABLED` | `true` | 是否启用 Fallback |
| `LLM_HEALTH_CHECK_INTERVAL` | `30` | 健康检查间隔（秒） |

### 3.7 Embedding 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EMBEDDING_PROVIDER` | `ollama` | Embedding Provider |
| `EMBEDDING_MODEL` | `bge-m3` | Embedding 模型名称 |
| `EMBEDDING_DIM` | `1024` | 向量维度 |

### 3.8 Reranker 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RERANKER_MODEL` | `BAAI/bge-reranker-base` | Reranker 模型名称 |

### 3.9 文档处理配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CHUNK_SIZE` | `512` | 分块大小（字符数） |
| `CHUNK_OVERLAP` | `50` | 分块重叠大小 |
| `MAX_FILE_SIZE_MB` | `20` | 最大文件上传大小（MB） |
| `MAX_DOCUMENTS_PER_KB` | `100` | 每个知识库最大文档数 |

### 3.10 CORS 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:1420,tauri://localhost` | 允许的跨域来源（逗号分隔） |

### 3.11 Celery 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Celery Broker 地址 |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | Celery Result Backend |

### 3.12 日志配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LOG_LEVEL` | `info` | 日志级别 (debug/info/warning/error/critical) |

### 3.13 LLM_PROVIDERS JSON 格式

```json
[
  {
    "name": "ollama",
    "type": "ollama",
    "api_base": "http://localhost:11434/v1",
    "model": "qwen2.5:7b",
    "priority": 99,
    "max_retries": 1,
    "timeout": 300,
    "fallback_to": null,
    "is_free": true
  },
  {
    "name": "openai",
    "type": "openai_compatible",
    "api_base": "https://api.openai.com/v1",
    "api_key": "sk-xxxxxxxxxxxxxxxxxxxx",
    "model": "gpt-4o",
    "priority": 50,
    "max_retries": 3,
    "timeout": 120,
    "fallback_to": "ollama",
    "is_free": false
  }
]
```

字段说明：
- `name`：Provider 唯一标识
- `type`：`ollama` 或 `openai_compatible`
- `api_base`：API 基础 URL
- `api_key`：API 密钥（仅 `openai_compatible` 类型）
- `model`：模型名称
- `priority`：优先级（数字越大越优先）
- `max_retries`：最大重试次数
- `timeout`：请求超时（秒）
- `fallback_to`：Fallback 目标 Provider 名称
- `is_free`：是否免费（用于成本统计）

---

## 4. 常见问题排查

### 4.1 数据库连接失败

**症状**：`could not connect to server: Connection refused`

**排查**：
```bash
# 检查 PostgreSQL 是否运行
sudo systemctl status postgresql
docker ps | grep postgres

# 检查连接
psql -h localhost -U rag -d rag_platform -c "SELECT 1"
```

**解决**：确保 PostgreSQL 正在运行，且 `.env` 中的连接信息正确。

### 4.2 Redis 连接失败

**症状**：`Error connecting to Redis`

**排查**：
```bash
redis-cli ping  # 应返回 PONG
```

**解决**：确保 Redis 正在运行，Docker 环境注意 `REDIS_HOST=redis`。

### 4.3 Qdrant 连接失败

**症状**：`ConnectionRefusedError` 或 Qdrant 相关错误

**排查**：
```bash
curl http://localhost:6333/collections
```

**解决**：确保 Qdrant 服务正在运行，Docker 环境注意 `QDRANT_HOST=qdrant`。

### 4.4 Ollama 模型未加载

**症状**：`model 'qwen2.5:7b' not found`

**排查**：
```bash
curl http://localhost:11434/api/tags
```

**解决**：
```bash
# Docker 环境
docker exec -it deploy-ollama-1 ollama pull qwen2.5:7b
docker exec -it deploy-ollama-1 ollama pull nomic-embed-text

# 裸机环境
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

### 4.5 数据库迁移失败

**症状**：`alembic upgrade head` 报错

**解决**：
```bash
# 查看当前迁移版本
alembic current

# 查看迁移历史
alembic history

# 手动执行迁移
alembic upgrade head

# 如果需要重置（开发环境）
alembic downgrade base
alembic upgrade head
```

### 4.6 文件上传失败

**症状**：上传文件返回 400 或 413 错误

**排查**：
- 检查文件大小是否超过 `MAX_FILE_SIZE_MB`（默认 20MB）
- 检查文件格式是否在允许列表中（.pdf, .docx, .md, .txt）
- 检查 Nginx `client_max_body_size` 配置（默认 50M）

**解决**：
```bash
# 修改 .env
MAX_FILE_SIZE_MB=50

# 修改 Nginx 配置
# deploy/nginx.conf: client_max_body_size 100M;
```

### 4.7 SSE 流式中断

**症状**：SSE 连接在 Nginx 后断开

**解决**：确保 Nginx 配置包含以下设置：
```nginx
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 300s;
proxy_set_header Connection '';
proxy_http_version 1.1;
```

### 4.8 内存不足

**症状**：OOM Killer 杀死进程，或服务响应极慢

**解决**：
- 减少 Gunicorn Worker 数量（`-w 2`）
- 使用云端 API 替代本地 Ollama
- 增加服务器内存或 Swap
- 限制 Celery Worker 并发数（`--concurrency=1`）

### 4.9 Token 验证失败

**症状**：401 错误，`Token has expired` 或 `Invalid token`

**排查**：
- `access_token` 有效期 60 分钟（默认），过期后用 `refresh_token` 刷新
- 检查系统时间是否正确
- 登出后 Token 会加入黑名单，需重新登录

### 4.10 端口冲突

**症状**：`port is already allocated`

**解决**：
```bash
# 查看占用端口的进程
sudo lsof -i :8000
sudo lsof -i :80

# 修改端口（在 .env 或 docker-compose.yml 中）
```