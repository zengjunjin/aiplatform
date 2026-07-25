# DbPoolExhaustion Runbook

## 告警含义

数据库连接池使用率超过 80%（`rag_db_pool_in_use / rag_db_pool_size > 0.8`），持续 10 分钟。

## 严重性

critical

## 可能原因

1. **慢查询积压**：某些 SQL 查询执行时间过长，占用连接未释放
2. **连接泄漏**：代码中未正确关闭数据库会话（`Session` 未 `close()`）
3. **并发激增**：QPS 突增导致连接池耗尽
4. **死锁**：多个事务互相等待，连接被锁住

## 排查步骤

### 1. 查看当前连接池状态

```bash
curl -H "Authorization: Bearer $METRICS_TOKEN" http://localhost:8000/internal/metrics | grep rag_db_pool
```

或访问 Grafana dashboard 的 "DB 连接池使用率" 面板。

### 2. 查看当前活跃查询

```sql
SELECT pid, state, query, query_start, NOW() - query_start AS duration
FROM pg_stat_activity
WHERE state != 'idle'
ORDER BY duration DESC;
```

### 3. 检查慢查询日志

```bash
docker logs rag-platform-backend --tail 1000 | grep "slow query"
```

### 4. 检查 Celery 任务

```bash
docker logs rag-platform-celery-worker --tail 500
```

Celery 任务中的文档解析可能产生大量 DB 操作。

## 处置方案

### 方案 A：终止慢查询

```sql
SELECT pg_terminate_backend(<pid>);
```

### 方案 B：临时调大连接池

修改 `DB_POOL_SIZE` 环境变量（需重启 backend）：

```bash
# docker-compose.yml
backend:
  environment:
    - DB_POOL_SIZE=30  # 默认 20
```

### 方案 C：定位连接泄漏

检查代码中是否有未 `close()` 的 `Session`，特别是：

- `app/api/v1/*.py` 中的 `get_db()` 依赖
- `app/tasks/*.py` 中的 Celery 任务
- `app/rag/*.py` 中的检索逻辑

## 预防措施

1. 启用慢查询监控（`SLOW_QUERY_THRESHOLD=1.0` 秒）
2. CI 中加入 SQL 查询性能测试
3. 定期审查 `Session` 使用，确保 `try/finally` 或 `contextmanager` 正确关闭

## 相关指标

- `rag_db_pool_size`：连接池大小
- `rag_db_pool_in_use`：使用中连接数
- `rag_db_pool_idle`：空闲连接数
- `rag_http_requests_total{status=~"5.."}`：5xx 错误率（连接池耗尽会触发 500）
