# Runbook: 检索流量归零

## 告警描述

**告警名称**：`ZeroRetrievalTraffic`
**告警规则**：`sum(rate(rag_retrievals_total[5m])) == 0`
**触发条件**：过去 30 分钟内 RAG 检索次数为 0
**严重级别**：critical
**影响范围**：
- 用户问答 / 检索功能不可用或无流量
- 可能是 backend 宕机、前端故障或 Nginx 路由错误
- 若为非工作时间，可能是正常无流量

**告警来源**：backend `/internal/metrics` 端点暴露的 `rag_retrievals_total` 指标

## 可能原因

1. **服务宕机**：backend 容器未运行或无响应
2. **前端故障**：用户无法发起检索请求
3. **流量丢失**：Nginx 路由配置错误，请求未到达 backend
4. **真正无流量**：非工作时间用户确实没有使用

## 排查步骤

### 1. 检查 backend 健康状态

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

如果 `/readyz` 返回 503，检查 DB/Redis/Qdrant 哪个依赖挂了。

### 2. 检查容器状态

```bash
docker ps | grep rag-platform
docker logs rag-platform-backend-1 --tail 100
```

### 3. 检查 Nginx 路由

```bash
curl -H "Host: your-domain.com" http://localhost:80/api/v1/system/models
```

### 4. 检查前端

访问前端页面，尝试发起一次检索，查看浏览器 Network 面板是否有请求。

### 5. 检查 Prometheus 抓取

```bash
curl -H "Authorization: Bearer $METRICS_TOKEN" http://localhost:8000/internal/metrics | grep rag_retrievals_total
```

如果指标存在但值为 0，说明确实无流量；如果指标不存在，说明 backend 未暴露指标或 Prometheus 未抓取。

## 应急处理

### 方案 A：重启 backend

```bash
docker compose restart backend
```

### 方案 B：修复依赖

如果 `/readyz` 显示 DB/Redis/Qdrant 不可用，对应重启依赖服务：

```bash
docker compose restart postgres redis qdrant
```

### 方案 C：确认非工作时间

如果是在非工作时间触发告警，且确认服务正常运行，可以调整告警规则的 `for` 持续时间，或在 Alertmanager 中配置静默规则。

## 恢复验证

1. **检索流量验证**：
   ```promql
   sum(rate(rag_retrievals_total[5m]))
   ```
   期望值：> 0（用户发起检索后流量恢复）

2. **健康端点验证**：
   ```bash
   curl -sf http://localhost:8000/readyz | jq .
   ```
   期望：所有依赖 healthy

3. **前端检索验证**：
   - 在前端页面发起一次问答检索
   - 监控 Grafana 检索面板确认 `rag_retrievals_total` 指标恢复增长

4. **Prometheus 抓取验证**：
   ```bash
   curl -H "Authorization: Bearer $METRICS_TOKEN" http://localhost:8000/internal/metrics | grep rag_retrievals_total
   ```
   期望：指标存在且随检索请求增长

## 预防措施

1. 配置 uptime 监控（外部 ping 检测）
2. 在非工作时间静默 `ZeroRetrievalTraffic` 告警
3. 定期检查 `/readyz` 端点

## 相关指标

- `rag_retrievals_total`：RAG 检索总次数（告警核心指标）
- `rag_http_requests_total`：HTTP 请求总数
- `rag_active_sessions`：活跃会话数
