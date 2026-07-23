# Runbook: CPU 使用率过高

## 告警描述

**告警名称**：`HighCpuUsage`
**告警规则**：`100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80`
**触发条件**：节点 CPU 使用率 5 分钟平均超过 80%
**严重级别**：warning
**影响范围**：
- API 响应变慢、Tauri 客户端 SSE 流式对话卡顿
- 文档解析 / 评估任务积压（Celery worker 队列堆积）
- Ollama 模型推理延迟上升，对话首 token 延迟增加

**告警来源**：node_exporter 采集的 `node_cpu_seconds_total` 指标
**潜在根因**：
- Celery worker 并发过高
- Ollama 并发推理请求过多
- BM25 索引重建或大文档批量解析
- 某容器出现死循环或异常重试

## 排查步骤

### 1. 确认节点整体 CPU
```bash
top -bn1 | head -20
# 或
uptime  # 查看 1/5/15 分钟负载
```

### 2. 定位高 CPU 容器
```bash
docker stats --no-stream
```
- 关注 `CPU %` 列，重点排查 backend、celery_worker、ollama、postgres、qdrant

### 3. 检查 Celery worker 状态
```bash
# 查看活动任务数
docker exec rag-platform-celery_worker-1 celery -A app.tasks.celery_app inspect active
# 查看队列长度
docker exec rag-platform-redis-1 redis-cli -n 1 LLEN queue_parsing
docker exec rag-platform-redis-1 redis-cli -n 1 LLEN queue_evaluation
docker exec rag-platform-redis-1 redis-cli -n 1 LLEN queue_default
```
- 当前并发为 `--concurrency=2`，确认是否任务堆积触发满载

### 4. 检查 Ollama 推理负载
```bash
# 查看当前运行的模型与请求
curl -s http://localhost:11434/api/ps | jq .
# 查看模型加载情况
curl -s http://localhost:11434/api/tags | jq '.models[].name'
```
- 注意 `OLLAMA_KEEP_ALIVE=24h` 配置，模型常驻内存会持续占用 CPU / GPU

### 5. 检查 backend 进程
```bash
docker exec rag-platform-backend-1 ps aux --sort=-%cpu | head -20
```
- 定位具体进程（uvicorn worker、Python 推理、reranker 调用）

### 6. 查看 Jaeger trace 排查慢调用
- Jaeger UI（http://localhost:16686）查看 backend service 中耗时 > 5s 的 span
- 重点关注 Qdrant 检索、Ollama 推理、PostgreSQL 慢查询

## 应急处理

### 1. 降低 Celery 并发
```bash
# 编辑 docker-compose.yml，将 celery_worker command 改为 --concurrency=1
docker compose up -d --no-deps celery_worker
```

### 2. 限制 Ollama 并发请求
- 在 backend `.env` 中设置 `OLLAMA_MAX_CONCURRENCY=1` 并重启 backend
- 或临时暂停评估 / 文档解析任务队列：
  ```bash
  docker exec rag-platform-celery_worker-1 celery -A app.tasks.celery_app control shutdown
  ```

### 3. 暂停大任务
- 暂停批量评估任务、BM25 索引重建任务（通过后台管理界面或 API）

### 4. 扩容节点
- 横向扩容：增加 celery_worker 实例 `docker compose up -d --scale celery_worker=2`
- 纵向扩容：升级宿主机 CPU / 增加节点

### 5. 重启高 CPU 容器
```bash
docker compose restart ollama  # 释放卡死的推理进程
```

## 恢复验证

1. **CPU 使用率验证**：
   ```promql
   100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
   ```
   期望值：< 80%，持续 10 分钟以上

2. **Grafana 面板验证**：
   - "RAG Platform Overview" → CPU 面板回归正常
   - API p95 延迟恢复到 baseline

3. **Celery 队列验证**：
   ```bash
   docker exec rag-platform-redis-1 redis-cli -n 1 LLEN queue_default
   ```
   期望：队列长度不再持续增长

4. **Ollama 推理验证**：
   ```bash
   time curl -s http://localhost:11434/api/generate -d '{"model":"qwen2.5","prompt":"hi","stream":false}'
   ```
   期望：首 token 延迟恢复到 baseline

## 预防措施

1. **容器资源限制**：所有服务在 docker-compose.yml 中设置 `mem_limit` 和 `cpus`（当前已配置）
2. **Celery 并发上限**：根据 CPU 核数设置 `--concurrency`，避免抢占
3. **Ollama 并发控制**：backend 通过信号量限制 Ollama 并发调用数
4. **任务限流**：批量评估 / 解析任务接入令牌桶限流
5. **CPU 预留**：宿主机保留 20% CPU 余量，避免满载
6. **自动扩容**：接入 HPA（如使用 K8s）或基于队列长度的自动扩容脚本
