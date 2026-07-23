# Runbook: API 5xx 高错误率处理流程

## 告警描述

**告警名称**：`HighErrorRate`
**告警规则**：`rate(rag_http_requests_total{status=~"5.."}[5m]) > 0.1`
**触发条件**：后端 API 5xx 错误率在 5 分钟窗口内每秒超过 0.1 次（约每分钟 6 次）
**严重级别**：critical
**影响范围**：
- 用户无法正常使用 RAG 平台核心功能（登录、知识库管理、文档上传、对话）
- 前端 Tauri 客户端收到 5xx 错误，可能导致功能不可用
- 涉及服务：backend（FastAPI，端口 8000）、nginx、celery_worker

**告警来源**：Prometheus 抓取 backend `/metrics` 端点的 `rag_http_requests_total` 指标
**通知渠道**：AlertManager → 配置的接收器（邮件 / IM webhook）

## 排查步骤

### 1. 确认告警有效性
- 登录 Grafana（默认 http://localhost:3000），查看 "RAG Platform Overview" dashboard
- 在 Prometheus（http://localhost:9090）执行查询确认当前 5xx 速率：
  ```promql
  rate(rag_http_requests_total{status=~"5.."}[5m])
  ```

### 2. 检查 backend 健康端点
```bash
curl -s http://localhost:8000/readyz | jq .
curl -s http://localhost:8000/livez | jq .
```
- 关注各依赖（postgres、redis、qdrant、ollama）状态是否为 healthy

### 3. 查看 backend 日志
```bash
docker logs --tail 200 rag-platform-backend-1
# 过滤 ERROR 级别（LOG_JSON=true 时为结构化日志）
docker logs rag-platform-backend-1 2>&1 | grep -E '"level":"ERROR"'
```
- 重点查看异常堆栈、数据库连接错误、依赖服务超时

### 4. 检查依赖服务连接
- **PostgreSQL**：`docker exec rag-platform-postgres-1 pg_isready -U rag`
- **Redis**：`docker exec rag-platform-redis-1 redis-cli ping`
- **Qdrant**：`curl -s http://localhost:6333/collections | jq '.collections | length'`
- **Ollama**：`curl -s http://localhost:11434/api/tags | jq '.models | length'`

### 5. 查看 Jaeger 链路追踪
- 打开 Jaeger UI（http://localhost:16686）
- Service 选择 `rag-platform-backend`
- 筛选 `error=true` 的 trace
- 定位耗时异常或错误 span（DB 查询、Qdrant 检索、Ollama 推理）

### 6. 检查最近部署变更
```bash
git log --oneline -10
docker images | grep rag-platform
```
- 确认是否最近有镜像更新或配置变更

## 应急处理

### 1. 重启 backend 服务（首选快速恢复）
```bash
docker compose restart backend
# 等待健康检查通过
docker compose ps backend
```

### 2. 重启 celery_worker（如错误来自异步任务）
```bash
docker compose restart celery_worker
```

### 3. 回滚最近部署
```bash
# 查看最近镜像
docker images rag-platform-backend --format "{{.ID}} {{.CreatedAt}} {{.Tag}}"
# 回滚到上一个稳定镜像（替换 <IMAGE_ID>）
docker compose up -d --no-deps backend --no-build
```

### 4. 扩容 backend 实例（如为负载过高导致）
```bash
docker compose up -d --scale backend=2
# 注意：扩容前需确认 nginx upstream 配置支持多实例
```

### 5. 临时降级非核心功能
- 在 `.env` 中临时关闭评估任务队列、关闭文档自动解析

## 恢复验证

1. **5xx 错误率验证**：
   ```promql
   rate(rag_http_requests_total{status=~"5.."}[5m])
   ```
   期望值：`0`（持续 10 分钟以上）

2. **健康端点验证**：
   ```bash
   curl -sf http://localhost:8000/readyz && echo "healthy"
   ```
   期望返回：`{"status":"healthy"}` 且所有依赖 status 为 healthy

3. **业务功能验证**：
   - 登录、创建知识库、上传文档、发起对话各执行一次
   - 监控 Grafana 5xx 面板保持为 0

4. **关闭告警**：AlertManager 自动 resolved，确认通知群收到 resolved 通知

## 预防措施

1. **CI 测试覆盖率门槛**：backend 测试覆盖率 >= 70%（CI 中通过 `pytest --cov` 强制检查）
2. **部署前 smoke test**：每次部署后自动执行 `tests/e2e/test_01_auth_e2e.py` 等核心 E2E 用例
3. **金丝雀发布**：新版本先部署到 10% 流量，观察 5xx 指标后再全量
4. **依赖熔断**：backend 配置 Qdrant / Ollama 调用超时与熔断，避免级联失败
5. **告警前置**：4xx 异常增长（> 1/s）也接入告警，提前发现潜在问题
6. **定期混沌演练**：每月模拟 PostgreSQL / Redis 故障，验证降级路径
