# Runbook: 内存使用率过高

## 告警描述

**告警名称**：`HighMemoryUsage`
**告警规则**：`(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 90`
**触发条件**：节点内存使用率超过 90%
**严重级别**：critical
**影响范围**：
- OOM Killer 可能杀掉 PostgreSQL、Redis、Qdrant 进程，导致服务中断
- backend / celery_worker 因内存不足无法分配对象，触发异常
- Ollama 模型加载失败，对话 / 检索不可用

**告警来源**：node_exporter 采集的 `node_memory_*` 指标

## 可能原因

1. **Redis 缓存未设置 maxmemory**：缓存无限增长，最终吃满内存
2. **PostgreSQL `shared_buffers` 设置过大**：占用过多内存
3. **BM25 倒排索引常驻内存**：索引占用过高
4. **Ollama 模型常驻**：`OLLAMA_KEEP_ALIVE=24h` 导致多个模型累积占用
5. **容器内存泄漏**：backend / celery_worker 进程内存持续增长不释放

## 排查步骤

### 1. 确认节点内存
```bash
free -h
# 关注 available 列
```

### 2. 定位高内存容器
```bash
docker stats --no-stream
```
- 关注 `MEM USAGE / LIMIT` 列和 `MEM %` 列
- 当前限制：postgres 1g、redis 512m、qdrant 1g、ollama 4g、backend 2g、celery 2g

### 3. 检查 PostgreSQL 内存
```bash
docker exec rag-platform-postgres-1 psql -U rag -d rag_platform -c "SHOW shared_buffers; SHOW effective_cache_size; SHOW work_mem;"
# 查看连接数与缓存命中
docker exec rag-platform-postgres-1 psql -U rag -d rag_platform -c "SELECT count(*) FROM pg_stat_activity;"
```

### 4. 检查 Redis 内存
```bash
docker exec rag-platform-redis-1 redis-cli INFO memory | grep -E "used_memory_human|used_memory_peak_human|maxmemory_human"
# 检查是否配置了 maxmemory policy
docker exec rag-platform-redis-1 redis-cli CONFIG GET maxmemory
docker exec rag-platform-redis-1 redis-cli CONFIG GET maxmemory-policy
```
- 若 `maxmemory=0` 表示未限制，存在风险

### 5. 检查 BM25 索引内存占用
```bash
docker exec rag-platform-backend-1 python -c "import psutil; print(psutil.Process().memory_info().rss / 1024 / 1024, 'MB')"
# 查看 BM25 索引大小（按知识库粒度）
docker exec rag-platform-redis-1 redis-cli -n 0 DBSIZE
```

### 6. 检查 Ollama 模型常驻
```bash
curl -s http://localhost:11434/api/ps | jq '.models[] | {name, size_vram, size}'
```
- `OLLAMA_KEEP_ALIVE=24h` 会导致多个模型常驻，累积占用内存

### 7. 检查 OOM 历史
```bash
dmesg | grep -i "killed process" | tail -20
```

## 应急处理

### 1. 清理 Redis 缓存（非持久化数据）
```bash
# 仅清理缓存 key，保留会话 / 任务数据
docker exec rag-platform-redis-1 redis-cli --scan --pattern "cache:*" | xargs -n 100 docker exec -i rag-platform-redis-1 redis-cli DEL
# 紧急情况清空缓存 DB（确认无关键数据后）
docker exec rag-platform-redis-1 redis-cli -n 0 FLUSHDB
```

### 2. 卸载 Ollama 不常用模型
```bash
curl -X DELETE http://localhost:11434/api/unload -d '{"model":"<unused_model>"}'
# 或临时调小 keep_alive
curl http://localhost:11434/api/generate -d '{"model":"qwen2.5","keep_alive":0}'
```

### 3. 重启内存泄漏容器
```bash
docker compose restart backend celery_worker
```

### 4. 扩容内存
- 升级宿主机内存
- 或增加节点并迁移部分服务（如独立 Qdrant / Ollama 节点）

### 5. 紧急降低 PostgreSQL shared_buffers
- 编辑 `.env` 或 docker-compose.yml，调小 `shared_buffers`
- 重启 PostgreSQL：`docker compose restart postgres`

## 恢复验证

1. **内存使用率验证**：
   ```promql
   (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
   ```
   期望值：< 90%，持续 10 分钟以上

2. **容器内存验证**：
   ```bash
   docker stats --no-stream
   ```
   期望：所有容器 `MEM %` < 80%

3. **服务健康验证**：
   ```bash
   curl -sf http://localhost:8000/readyz | jq .
   ```
   期望：所有依赖 healthy

4. **OOM 验证**：
   ```bash
   dmesg | grep -i "killed process" | tail -5
   ```
   期望：恢复后无新增 OOM 记录

## 预防措施

1. **Redis maxmemory policy**：在 redis 启动配置中设置 `maxmemory 512mb` 和 `maxmemory-policy allkeys-lru`
2. **PostgreSQL shared_buffers**：按宿主机内存的 25% 设置，避免过大
3. **BM25 索引分片**：大知识库拆分索引，限制单进程内存占用
4. **Ollama 模型管理**：调小 `OLLAMA_KEEP_ALIVE`（如 30m），按需加载
5. **内存监控告警**：在 80% 时设置 warning 告警，提前干预
6. **容器内存泄漏检测**：定期对比容器 RSS 趋势，发现泄漏及时重启

## 相关指标

- `node_memory_MemAvailable_bytes` / `node_memory_MemTotal_bytes`：节点可用 / 总内存（告警核心指标）
- `rag_db_pool_in_use` / `rag_db_pool_size`：DB 连接池使用率
- `rag_http_requests_total{status=~"5.."}`：5xx 错误率（OOM 会触发 5xx）
