# RAG 知识库平台 — 部署文档（v0.2.0）

> 版本：v0.2.0
> 更新日期：2026-07-28
> 适用范围：Docker Compose 一体化部署 + Tauri 桌面客户端构建
> 历史版本：v0.2.0 (2026-07-11) 内容已合并到本文件

---

## 目录

1. [系统要求](#1-系统要求)
2. [快速启动](#2-快速启动)
3. [服务清单（19 个服务）](#3-服务清单19-个服务)
4. [配置说明](#4-配置说明)
5. [健康检查](#5-健康检查)
6. [监控访问](#6-监控访问)
7. [常见问题排查](#7-常见问题排查)
8. [备份与恢复](#8-备份与恢复)
9. [Tauri 桌面客户端构建](#9-tauri-桌面客户端构建)

---

## 1. 系统要求

### 1.1 操作系统

- **Linux**：Ubuntu 22.04+ / Debian 12+ / CentOS Stream 9+（生产推荐）
- **Windows**：Windows 11 + WSL2 + Docker Desktop（开发/验收环境）
- **macOS**：Docker Desktop for Mac（开发环境）

### 1.2 软件依赖

| 组件 | 最低版本 | 备注 |
|------|----------|------|
| Docker Engine | 24.x | 推荐 24.0.7+ |
| Docker Compose | v2.24.x | 使用 `docker compose`（v2 内置子命令） |
| Git | 2.40+ | 拉取代码 / Tauri 更新流程 |
| Rust toolchain | 1.78+ | **仅 Tauri 客户端构建需要**（参见 §9） |
| Node.js | 20.x | **仅 Tauri 客户端构建需要** |

### 1.3 硬件要求

| 维度 | 最低 | 推荐 | 说明 |
|------|------|------|------|
| CPU | 4 核 | 8 核 | Ollama LLM 推理需要 2 核专享 |
| 内存 | 8 GB | 16 GB | Ollama 4GB + Backend 2GB + Celery 2GB + 其他服务 4GB |
| 磁盘 | 20 GB | 50 GB | Docker 镜像 ~6GB + Ollama 模型 ~6GB + 数据卷 ~5GB + 日志 |
| GPU | 无 | NVIDIA GPU（可选） | 无 GPU 时使用 qwen2.5:1.5b CPU 模型，有 GPU 时可升级至 qwen2.5:7b |

### 1.4 端口规划

默认端口（均可通过 `.env` 调整）：

| 端口 | 服务 | 用途 |
|------|------|------|
| 80 | nginx | HTTP 入口（Web UI + API 反代） |
| 8000 | backend | FastAPI 直连（调试用） |
| 5432 | postgres | PostgreSQL |
| 6379 | redis | Redis |
| 6333/6334 | qdrant | Qdrant HTTP / gRPC |
| 11434 | ollama | Ollama API |
| 9090 | prometheus | Prometheus UI |
| 9093 | alertmanager | Alertmanager UI |
| 3000 | grafana | Grafana UI |
| 16686 | jaeger | Jaeger UI |
| 3100 | loki | Loki HTTP |
| 5555 | flower | Flower Celery 监控 |
| 9100 | node-exporter | 主机指标 |
| 9113 | nginx-exporter | nginx 指标 |
| 9121 | redis-exporter | Redis 指标 |
| 5001 | webhook-receiver | 告警 webhook |

---

## 2. 快速启动

### 2.1 一键启动流程

```bash
# 1. 克隆项目
git clone <repository-url> aiplatform
cd aiplatform

# 2. 配置环境变量（必填项：POSTGRES_PASSWORD / JWT_SECRET / GRAFANA_ADMIN_PASSWORD）
cp deploy/.env.example deploy/.env
# 编辑 deploy/.env：
#   POSTGRES_PASSWORD=<强随机密码>
#   JWT_SECRET=<强随机密码>
#   GRAFANA_ADMIN_PASSWORD=<强随机密码>
#   OLLAMA_CHAT_MODEL=qwen2.5:1.5b   # CPU 环境推荐
#   LLM_PROVIDERS_JSON=<见 §4.4>

# 3. 启动所有服务（19 个容器）
docker compose -f deploy/docker-compose.yml up -d

# 4. 查看服务状态（等待所有 healthcheck 通过，约 60-90 秒）
docker compose -f deploy/docker-compose.yml ps

# 5. 拉取 Ollama 模型（首次启动需要）
docker exec -it aiplatform-ollama-1 ollama pull qwen2.5:1.5b   # LLM 对话模型（CPU 优化）
docker exec -it aiplatform-ollama-1 ollama pull bge-m3          # Embedding 模型
# 可选：reranker 模型
docker exec -it aiplatform-ollama-1 ollama pull bge-reranker-base

# 6. 初始化管理员账号（首次启动）
docker exec -it aiplatform-backend-1 python init_db.py
```

### 2.2 验证启动成功

```bash
# 检查所有服务健康状态
docker compose -f deploy/docker-compose.yml ps

# 期望输出：所有服务 Up，至少 11 个为 healthy 状态

# 验证 API 网关
curl http://localhost/healthz    # 期望：{"status":"ok"}
curl http://localhost/readyz     # 期望：{"status":"ready","db":"ok","redis":"ok","qdrant":"ok"}

# 验证 Web UI
# 浏览器访问 http://localhost/  → 应显示登录页
```

### 2.3 停止与清理

```bash
# 停止所有服务（保留数据卷）
docker compose -f deploy/docker-compose.yml down

# 停止并删除数据卷（⚠️ 谨慎！会丢失所有数据）
docker compose -f deploy/docker-compose.yml down -v

# 仅重启某个服务
docker compose -f deploy/docker-compose.yml restart backend
```

---

## 3. 服务清单（19 个服务）

`deploy/docker-compose.yml` 共定义 19 个服务，分属 5 个层级：

### 3.1 数据层（4 个）

| # | 服务名 | 镜像 | 端口 | 资源限制 | 健康检查 | 用途 |
|---|--------|------|------|----------|----------|------|
| 1 | `postgres` | postgres:16-alpine | 5432 | 1GB / 2 CPU | `pg_isready` | 关系型数据库（用户/KB/文档/会话） |
| 2 | `redis` | redis:7-alpine | 6379 | 512MB / 1 CPU | `redis-cli ping` | 缓存 + Celery 队列 + 限流 |
| 3 | `qdrant` | qdrant/qdrant:v1.18.3 | 6333, 6334 | 1GB / 1 CPU | TCP 端口探测 | 向量数据库 |
| 4 | `ollama` | ollama/ollama:0.3.14 | 11434 | 4GB / 2 CPU | TCP 端口探测 | 本地 LLM + Embedding + Reranker |

### 3.2 应用层（4 个）

| # | 服务名 | 镜像 | 端口 | 资源限制 | 健康检查 | 用途 |
|---|--------|------|------|----------|----------|------|
| 5 | `backend` | 自构建（FastAPI） | 8000 | 2GB / 2 CPU | `/readyz` | API 后端 + Alembic 自动迁移 |
| 6 | `celery_worker` | 自构建（FastAPI） | — | 2GB / 2 CPU | `celery inspect ping` | 异步任务（文档解析 / 评估） |
| 7 | `frontend` | 自构建（Nginx） | 80（内部） | 256MB / 1 CPU | `wget /` | React SPA 静态资源 |
| 8 | `nginx` | nginx:alpine | 80, 8080 | 128MB / 1 CPU | `nginx -t` | 反向代理 + TLS + CSP + stub_status |

### 3.3 可观测性层（8 个）

| # | 服务名 | 镜像 | 端口 | 资源限制 | 用途 |
|---|--------|------|------|----------|------|
| 9 | `prometheus` | prom/prometheus:latest | 9090 | 256MB / 0.5 CPU | 指标抓取与存储 |
| 10 | `grafana` | grafana/grafana:latest | 3000 | 256MB / 0.5 CPU | 仪表板 UI（预置 2 个 dashboard） |
| 11 | `jaeger` | jaegertracing/all-in-one:1.60 | 16686, 4317, 4318 | 256MB / 1 CPU | 分布式追踪（OTLP 接收） |
| 12 | `loki` | grafana/loki:2.9.0 | 3100 | 512MB / 0.5 CPU | 日志聚合后端 |
| 13 | `promtail` | grafana/promtail:2.9.0 | — | 256MB / 0.25 CPU | 容器日志采集 → Loki |
| 14 | `alertmanager` | prom/alertmanager:v0.27.0 | 9093 | 256MB / 0.5 CPU | 告警路由 |
| 15 | `alertmanager-webhook-receiver` | 自构建（Python） | 5001 | 128MB / 0.25 CPU | 告警 webhook 接收 + 落盘 |
| 16 | `flower` | mher/flower:2.0 | 5555 | 256MB / 0.5 CPU | Celery 任务监控 UI |

### 3.4 Exporter 层（3 个）

| # | 服务名 | 镜像 | 端口 | 资源限制 | 用途 |
|---|--------|------|------|----------|------|
| 17 | `redis-exporter` | oliver006/redis_exporter:v1.59.0 | 9121 | 128MB / 0.25 CPU | Redis 指标 |
| 18 | `node-exporter` | prom/node-exporter:v1.8.2 | 9100 | 128MB / 0.25 CPU | 主机指标（CPU/内存/磁盘） |
| 19 | `nginx-exporter` | nginx/nginx-prometheus-exporter:1.1.0 | 9113 | 64MB / 0.25 CPU | nginx stub_status 指标 |

> **说明**：旧版 ACCEPTANCE_REPORT 提及"20 个服务"，实际 docker-compose.yml 定义 19 个服务（早期版本曾包含一个辅助容器，已合并）。

---

## 4. 配置说明

### 4.1 配置文件位置

| 文件 | 用途 |
|------|------|
| `deploy/.env` | 环境变量主配置（**必填项必须设置**） |
| `deploy/.env.example` | 配置模板 |
| `deploy/docker-compose.yml` | 服务编排 |
| `deploy/nginx.conf` | Nginx 反向代理 + CSP |
| `deploy/prometheus.yml` | Prometheus 抓取配置 |
| `deploy/prometheus/alerts.yml` | 告警规则（11 条） |
| `deploy/alertmanager.yml` | 告警路由 |
| `deploy/promtail.yml` | 日志采集配置 |
| `deploy/grafana/provisioning/` | Grafana 数据源 + dashboard 自动加载 |

### 4.2 必填环境变量

以下变量必须在 `deploy/.env` 中显式设置（不设置则容器启动失败）：

```env
# 数据库密码（强随机，建议 32+ 字符）
POSTGRES_PASSWORD=<strong-random-password>

# JWT 签名密钥（强随机，建议 64+ 字符）
JWT_SECRET=<strong-random-secret>

# Grafana 管理员密码
GRAFANA_ADMIN_PASSWORD=<strong-random-password>
```

### 4.3 关键业务配置

```env
# LLM 模型（CPU 环境使用 qwen2.5:1.5b，GPU 环境可升级 qwen2.5:7b）
OLLAMA_CHAT_MODEL=qwen2.5:1.5b
OLLAMA_EMBEDDING_MODEL=bge-m3

# CORS 允许来源
CORS_ORIGINS=http://localhost:5173,http://localhost:1420,tauri://localhost

# 日志 JSON 化（生产环境强烈建议 true，启用 _redact_filter 脱敏）
LOG_JSON=true

# OpenTelemetry（已通过 docker-compose env 覆盖，无需在 .env 设置）
# OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318
```

### 4.4 LLM_PROVIDERS_JSON 配置

支持多 Provider + Fallback（详见 `docs/deployment.md` §3.15）：

```json
[
  {
    "name": "ollama",
    "type": "ollama",
    "api_base": "http://ollama:11434/v1",
    "model": "qwen2.5:1.5b",
    "priority": 99,
    "max_retries": 1,
    "timeout": 300,
    "is_free": true
  }
]
```

### 4.5 资源限制总览

`deploy/docker-compose.yml` 已为所有服务设置 `mem_limit` 和 `cpus`，合计：

| 维度 | 总分配 | 推荐宿主机配置 |
|------|--------|----------------|
| 内存 | ~13.3 GB | ≥ 16 GB |
| CPU | ~12.75 核 | ≥ 8 核（部分服务不会同时满载） |

---

## 5. 健康检查

### 5.1 应用层健康端点

| 端点 | 用途 | 期望响应 |
|------|------|----------|
| `GET /healthz` | Liveness（进程存活） | `{"status":"ok"}` |
| `GET /readyz` | Readiness（依赖就绪） | `{"status":"ready","db":"ok","redis":"ok","qdrant":"ok"}` |
| `GET /docs` | Swagger UI（DEBUG=true 时） | HTML |
| `GET /redoc` | ReDoc（DEBUG=true 时） | HTML |
| `GET /internal/metrics` | Prometheus 指标（Bearer 鉴权） | Prometheus exposition format |

### 5.2 数据层健康检查

```bash
# PostgreSQL
docker exec -it aiplatform-postgres-1 pg_isready -U rag -d rag_platform

# Redis
docker exec -it aiplatform-redis-1 redis-cli ping    # 期望 PONG

# Qdrant
curl http://localhost:6333/healthz                     # 期望健康状态

# Ollama
curl http://localhost:11434/api/tags                   # 期望返回已加载模型列表
```

### 5.3 Docker Compose healthcheck

所有支持健康检查的服务已配置 healthcheck，可通过以下命令查看：

```bash
docker compose -f deploy/docker-compose.yml ps --format "table {{.Name}}\t{{.Status}}"
```

期望结果：19 个服务全部 `Up`，其中至少 11 个为 `Up (healthy)`。

---

## 6. 监控访问

### 6.1 监控端点入口

| 服务 | URL | 默认账号 | 用途 |
|------|-----|----------|------|
| Grafana | http://localhost:3000 | admin / `${GRAFANA_ADMIN_PASSWORD}` | 仪表板 UI（预置 RAG 平台总览 + Celery 任务详情） |
| Prometheus | http://localhost:9090 | 无 | 指标查询 + Alert 状态 |
| Alertmanager | http://localhost:9093 | 无 | 告警路由 + 静默 |
| Jaeger UI | http://localhost:16686 | 无 | 分布式追踪查询 |
| Flower | http://localhost:5555 | 无 | Celery 任务监控 |
| Loki | http://localhost:3100 | 无（通过 Grafana 查询） | 日志聚合查询 |

### 6.2 预置 Grafana Dashboard

`deploy/grafana/dashboards/`：

- `rag-platform-overview.json` — RAG 平台总览（14 个面板）
- `celery-tasks.json` — Celery 任务详情

### 6.3 Prometheus 抓取目标

`deploy/prometheus.yml` 配置的 6 个 scrape target：

| Job Name | Target | 状态 |
|----------|--------|------|
| rag-platform-backend | http://backend:8000/internal/metrics | ✅ up |
| qdrant | http://qdrant:6333/metrics | ✅ up |
| redis-exporter | http://redis-exporter:9121/metrics | ✅ up |
| node-exporter | http://node-exporter:9100/metrics | ✅ up |
| flower | http://flower:5555/metrics | ✅ up |
| nginx-exporter | http://nginx-exporter:9113/metrics | ✅ up |

### 6.4 告警规则

`deploy/prometheus/alerts.yml` 共 11 条规则：

- **critical-alerts（4 条）**：HighErrorRate / HighMemoryUsage / DbPoolExhaustion / ZeroRetrievalTraffic
- **warning-alerts（2 条）**：HighCpuUsage / HighDiskUsage
- **phase5-business-alerts（5 条）**：KBCreateAnomaly / DocParseHighFailureRate / ChatResponseSlowP95 / RedisMemoryHigh / LLMInferenceTimeoutP99

---

## 7. 常见问题排查

### 7.1 服务启动失败

**症状**：`docker compose up -d` 后某些服务立即退出

**排查步骤**：
```bash
# 查看退出服务的日志
docker compose -f deploy/docker-compose.yml logs <service-name>

# 检查 .env 必填项是否设置
grep -E "POSTGRES_PASSWORD|JWT_SECRET|GRAFANA_ADMIN_PASSWORD" deploy/.env
```

**常见原因**：
- `POSTGRES_PASSWORD must be set in .env` → 未设置必填环境变量
- `port is already allocated` → 端口被宿主机其他进程占用

### 7.2 Ollama 模型未加载

**症状**：聊天请求返回 `model 'qwen2.5:1.5b' not found`

**解决**：
```bash
# 拉取模型
docker exec -it aiplatform-ollama-1 ollama pull qwen2.5:1.5b
docker exec -it aiplatform-ollama-1 ollama pull bge-m3

# 验证模型列表
curl http://localhost:11434/api/tags
```

### 7.3 LLM 推理超时

**症状**：聊天响应时间 > 30 秒，RAGAS 评估超时

**排查**：
```bash
# 检查 CPU 使用率
docker stats aiplatform-ollama-1

# 检查是否使用 GPU
docker exec -it aiplatform-ollama-1 ollama ps
```

**解决方案**：
- CPU 环境：确认使用 `qwen2.5:1.5b`（小模型）
- GPU 环境：可升级至 `qwen2.5:7b`，并配置 Docker GPU runtime

### 7.4 数据库连接失败

**症状**：`could not connect to server: Connection refused`

**排查**：
```bash
# 检查 postgres 容器状态
docker compose -f deploy/docker-compose.yml ps postgres

# 测试连接
docker exec -it aiplatform-postgres-1 psql -U rag -d rag_platform -c "SELECT 1"
```

### 7.5 Redis 连接失败

**症状**：`Error connecting to Redis`

**排查**：
```bash
docker exec -it aiplatform-redis-1 redis-cli ping    # 应返回 PONG
```

### 7.6 SSE 流式中断

**症状**：SSE 连接在 Nginx 后断开

**解决**：确认 `deploy/nginx.conf` 包含以下配置：
```nginx
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 300s;
proxy_set_header Connection '';
proxy_http_version 1.1;
```

### 7.7 内存不足（OOM）

**症状**：OOM Killer 杀死进程，或服务响应极慢

**解决方案**：
- 减少后端 Gunicorn Worker 数量（默认 uvicorn 单进程）
- 限制 Celery 并发：`--concurrency=1`
- 升级 Ollama 模型至云端 API（OpenAI 兼容）
- 增加宿主机内存或 Swap

### 7.8 磁盘空间不足

**症状**：`no space left on device`

**排查与清理**：
```bash
# 查看 Docker 磁盘使用
docker system df -v

# 清理未使用的镜像、卷、构建缓存
docker image prune -a --filter "until=24h" --force
docker volume prune --force
docker builder prune --force
```

详细清理流程参见 §8.5 磁盘维护。

---

## 8. 备份与恢复

### 8.1 备份策略

| 数据类型 | 备份方式 | 频率 | 保留 |
|----------|----------|------|------|
| PostgreSQL | `pg_dump -F c`（custom 格式） | 每日 02:00 | 7/30/365 天分级 |
| Qdrant | tar 打包 volume | 每日 02:00 | 7 天 |
| Redis | AOF（可选） | 实时 | — |
| Ollama 模型 | docker volume | 一次性 | 永久 |

### 8.2 PostgreSQL 自动备份

平台内置脚本 `deploy/scripts/backup_db.sh`：

```bash
# 直接运行（需 export POSTGRES_* 环境变量）
./deploy/scripts/backup_db.sh

# 试运行
./deploy/scripts/backup_db.sh --dry-run

# 通过 Makefile
make backup
make backup ARGS=--dry-run
```

**备份类型与保留**：

| 类型 | 触发 | 保留 | 文件名示例 |
|------|------|------|------------|
| daily | 每日 | 7 天 | `backup_daily_rag_platform_20260728_020000.dump` |
| weekly | 每周日 | 30 天 | `backup_weekly_rag_platform_20260727_020000.dump` |
| monthly | 每月 1 号 | 365 天 | `backup_monthly_rag_platform_20260801_020000.dump` |

### 8.3 定时备份（crontab）

```bash
# 添加到 crontab -e
0 2 * * * cd /opt/aiplatform && set -a && . ./deploy/.env && set +a && ./deploy/scripts/backup_db.sh >> /var/log/rag-backup.log 2>&1
```

### 8.4 恢复流程

```bash
# 恢复 PostgreSQL
pg_restore -h localhost -U rag -d rag_platform -c backups/backup_daily_rag_platform_20260728_020000.dump

# 恢复 Qdrant
docker run --rm -v qdrant_data:/data -v $(pwd):/backup alpine sh -c "cd /data && tar xzf /backup/qdrant_20260728.tar.gz"
```

### 8.5 磁盘维护

定期执行（建议每周一次）：

```bash
# 1. 查看 Docker 磁盘使用
docker system df -v

# 2. 清理未使用的镜像（保留 24 小时内的）
docker image prune -a --filter "until=24h" --force

# 3. 清理未使用的卷（⚠️ 确认无重要数据）
docker volume prune --force

# 4. 清理构建缓存
docker builder prune --force

# 5. 清理 Python 缓存（项目目录）
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -name "*.pyc" -delete

# 6. 清理超大日志文件（> 10MB）
find . -name "*.log" -size +10M -delete
```

### 8.6 RPO/RTO 目标

| 指标 | 目标 | 说明 |
|------|------|------|
| RPO（恢复点目标） | 24h | 依赖每日 `pg_dump` 备份 |
| RTO（恢复时间目标） | 4h | 从故障到服务恢复 |

### 8.7 全栈恢复顺序

灾难恢复时按以下顺序启动：

1. `postgres` — 数据库基座
2. `redis` — 缓存与队列
3. `qdrant` — 向量数据库
4. `ollama` — LLM 推理（可选，可降级到云端 API）
5. `backend` — API 后端
6. `celery_worker` — 异步任务
7. `frontend` — 前端静态资源
8. `nginx` — 反向代理（最后启动对外暴露）
9. 可观测性栈（prometheus / grafana / jaeger / loki 等）

```bash
# 按依赖顺序启动
docker compose -f deploy/docker-compose.yml up -d postgres redis qdrant ollama
docker compose -f deploy/docker-compose.yml up -d backend celery_worker
docker compose -f deploy/docker-compose.yml up -d frontend nginx
docker compose -f deploy/docker-compose.yml up -d prometheus grafana jaeger loki promtail alertmanager flower
```

---

## 9. Tauri 桌面客户端构建

### 9.1 前置要求

| 工具 | 版本 | 用途 |
|------|------|------|
| Rust toolchain | 1.78+（stable） | 编译 Rust 后端 |
| Node.js | 20.x + npm | 构建前端资源 |
| Windows SDK | 10.0+ | Windows 打包（NSIS） |
| WebView2 Runtime | 最新版 | Windows 运行时依赖 |

### 9.2 构建步骤

```bash
# 1. 进入 Tauri 项目目录
cd frontend

# 2. 安装前端依赖
npm install

# 3. 检查 Tauri CLI
npx tauri --version    # 期望 2.x

# 4. 开发模式（热重载）
npm run tauri dev

# 5. 生产构建（生成 NSIS 安装包）
npm run tauri build
```

### 9.3 构建产物

构建成功后产物位于 `frontend/src-tauri/target/release/bundle/nsis/`：

- `RAG 知识库平台_0.2.0_x64-setup.exe` — NSIS 安装包
- `RAG 知识库平台_0.2.0_x64_en-US.msi` — MSI 安装包（如启用）

### 9.4 关键配置文件

| 文件 | 用途 |
|------|------|
| `frontend/src-tauri/tauri.conf.json` | Tauri 主配置（窗口/CDP/CSP/Bundle/Updater） |
| `frontend/src-tauri/Cargo.toml` | Rust 依赖 |
| `frontend/src-tauri/src/main.rs` | Rust 业务逻辑（窗口/托盘/深链/快捷键/更新） |
| `frontend/src-tauri/icons/` | 应用图标 |
| `frontend/src/utils/tauri.ts` | 前端 Tauri API 封装 |

### 9.5 Tauri 业务能力

v0.2.0 实现的 Tauri 业务逻辑（详见 `docs/TAURI_ARCHITECTURE.md`）：

| 模块 | 文件 | 功能 |
|------|------|------|
| 窗口管理 | `main.rs` `window module` | 单实例锁、最小化到托盘、窗口状态持久化 |
| 系统托盘 | `main.rs` `tray module` | 托盘菜单（显示/退出）、托盘图标双击显示 |
| 深度链接 | `main.rs` `deep_link module` | `rag-platform://` 协议注册与解析 |
| 全局快捷键 | `main.rs` `shortcut module` | `Ctrl+Shift+R` 显示窗口 |
| 自动更新 | `main.rs` `updater module` | 启动时检查 GitHub Releases `latest.json` |

### 9.6 CDP 调试

Tauri 配置已启用 CDP（Chrome DevTools Protocol）：

```json
// tauri.conf.json
{
  "app": {
    "windows": [{
      "additionalBrowserArgs": ["--remote-debugging-port=9223"]
    }]
  }
}
```

调试方法：
```bash
# 1. 启动 Tauri 应用
npm run tauri dev

# 2. 在浏览器中访问 CDP 端点
curl http://localhost:9223/json    # 期望返回 WebView2 调试信息

# 3. 在 Chrome 中打开
# 访问 chrome://inspect → 配置 localhost:9223 → 调试 WebView2
```

### 9.7 自动更新配置

`tauri.conf.json` 中的 updater 配置：

```json
{
  "plugins": {
    "updater": {
      "active": true,
      "endpoints": [
        "https://github.com/<org>/<repo>/releases/latest/download/latest.json"
      ],
      "pubkey": "<base64-encoded-public-key>"
    }
  },
  "bundle": {
    "windows": {
      "certificateThumbprint": "<optional-code-signing-cert>"
    }
  }
}
```

发布流程：
1. 在 GitHub Releases 上传 `*-setup.exe` 和 `latest.json`
2. 应用启动时自动检查更新并提示用户

### 9.8 跨平台构建说明

当前 v0.2.0 仅在 Windows 上验证通过。跨平台构建需要：

- **macOS**：在 macOS 主机上 `npm run tauri build`，产物为 `.dmg` / `.app`
- **Linux**：在 Linux 主机上 `npm run tauri build`，产物为 `.deb` / `.AppImage`
- 推荐：使用 GitHub Actions matrix 构建多平台产物

---

## 附录：相关文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 开发文档 | `docs/development.md` | 本地开发环境搭建 |
| API 指南 | `docs/api_guide.md` | API 使用说明 |
| 用户手册 | `docs/USER_MANUAL.md` | 终端用户使用手册 |
| Tauri 架构 | `docs/TAURI_ARCHITECTURE.md` | Tauri 业务逻辑架构设计 |
| CHANGELOG | `CHANGELOG.md` | 版本变更记录 |
| Release Notes | `docs/RELEASE_NOTES_v0.2.0.md` | v0.2.0 发布说明 |
| Phase 4 报告 | `docs/PHASE4_REPORT_2026-07-27.md` | 性能与安全加固 |
| Phase 5 报告 | `docs/PHASE5_REPORT_2026-07-27.md` | 可观测性深化 |

---

**文档版本**：v0.2.0
**最后更新**：2026-07-28
**维护者**：RAG 平台团队
