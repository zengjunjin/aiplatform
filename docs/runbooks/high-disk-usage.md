# Runbook: 磁盘使用率过高

## 告警描述

**告警名称**：`HighDiskUsage`
**告警规则**：`(1 - (node_filesystem_avail_bytes / node_filesystem_size_bytes)) * 100 > 85`
**触发条件**：磁盘使用率超过 85%
**严重级别**：warning
**影响范围**：
- PostgreSQL 无法写入 WAL，事务失败
- Redis 持久化（RDB / AOF）失败，可能丢数据
- Qdrant 向量写入失败，文档解析任务报错
- 文档上传失败，用户上传的 PDF / DOCX 无法落盘
- Prometheus TSDB 写入失败，监控数据丢失
- 日志写入失败，影响排查

**告警来源**：node_exporter 采集的 `node_filesystem_*` 指标
**潜在根因**：
- 用户上传文档累积（`/app/storage` 目录）
- Qdrant 向量数据增长（`qdrant_data` volume）
- Prometheus TSDB 未配置 retention，历史指标堆积
- 日志文件未轮转
- E2E 测试报告累积（`tests/e2e/reports`）
- Docker 镜像 / 容器 / 卷垃圾堆积

## 排查步骤

### 1. 确认磁盘整体使用
```bash
df -h
# 关注挂载点（根分区 / 和 docker volume 所在分区）
```

### 2. 检查 Docker 磁盘占用
```bash
docker system df
# 详细查看
docker system df -v
```
- 关注 Images、Containers、Volumes、Build cache 各项大小

### 3. 检查 Qdrant 向量存储
```bash
docker exec rag-platform-qdrant-1 du -sh /qdrant/storage
# 查看各 collection 大小
curl -s http://localhost:6333/collections | jq '.result.collections[]'
```

### 4. 检查上传文档目录
```bash
du -sh c:/Users/15116/Desktop/aiplatform/release/RAG知识库平台/backend/storage
# 或容器内
docker exec rag-platform-backend-1 du -sh /app/storage
# 按子目录排查
docker exec rag-platform-backend-1 du -sh /app/storage/* | sort -h
```

### 5. 检查 Prometheus TSDB
```bash
docker exec rag-platform-prometheus-1 du -sh /prometheus
# 查看当前 retention 配置
docker exec rag-platform-prometheus-1 cat /etc/prometheus/prometheus.yml | grep -A2 retention
```

### 6. 检查日志占用
```bash
# Docker 日志
docker inspect --format='{{.LogPath}}' rag-platform-backend-1 | xargs du -sh
# 宿主机日志
du -sh /var/log/* 2>/dev/null | sort -h | tail -20
```

### 7. 检查 E2E 测试报告
```bash
du -sh c:/Users/15116/Desktop/aiplatform/release/RAG知识库平台/backend/tests/e2e/reports/* 2>/dev/null
```

## 应急处理

### 1. 清理 Docker 垃圾
```bash
# 清理停止的容器、悬空镜像、无用网络
docker system prune -f
# 进一步清理未使用的镜像（谨慎，会删除当前未运行服务的镜像）
docker image prune -a -f
# 清理 build cache
docker builder prune -f
# 清理未使用的 volume（谨慎，会删除未挂载的数据卷）
docker volume prune -f
```

### 2. 清理旧日志
```bash
# 截断容器日志
docker inspect --format='{{.LogPath}}' rag-platform-backend-1 | xargs truncate -s 0
# 或配置日志轮转后重启
```

### 3. 清理 E2E 测试报告
```bash
rm -rf c:/Users/15116/Desktop/aiplatform/release/RAG知识库平台/backend/tests/e2e/reports/*.html
rm -rf c:/Users/15116/Desktop/aiplatform/release/RAG知识库平台/backend/tests/e2e/reports/*.json
```

### 4. 清理已删除文档的物理文件
- 通过 API 软删除的文档需定期物理清理：
  ```bash
  # 查询 deleted_at 不为空超过 30 天的文档
  docker exec rag-platform-postgres-1 psql -U rag -d rag_platform -c \
    "SELECT count(*) FROM documents WHERE deleted_at < now() - interval '30 days';"
  ```
- 配合脚本物理删除 storage 目录中对应文件

### 5. 压缩 Prometheus TSDB
- 临时调小 retention 并重启：
  ```bash
  # 编辑 prometheus.yml 或启动参数加 --storage.tsdb.retention.time=7d
  docker compose restart prometheus
  ```

### 6. 扩容磁盘
- 宿主机扩容磁盘（云盘扩容 + 文件系统 resize）
- 或迁移大目录到独立磁盘（如 Qdrant storage 迁移到独立卷）

## 恢复验证

1. **磁盘使用率验证**：
   ```promql
   (1 - (node_filesystem_avail_bytes / node_filesystem_size_bytes)) * 100
   ```
   期望值：< 85%，持续 10 分钟以上

2. **df 验证**：
   ```bash
   df -h
   ```
   期望：可用空间充足（> 15%）

3. **服务写入验证**：
   ```bash
   # 上传一个测试文档
   curl -X POST http://localhost:8000/api/v1/documents/upload -F "file=@test.txt"
   # 验证 Qdrant 写入
   curl -s http://localhost:6333/collections | jq .
   ```
   期望：写入成功，无磁盘错误

4. **Prometheus 写入验证**：
   ```bash
   curl -sf http://localhost:9090/-/healthy && echo "prometheus healthy"
   ```
   期望：返回 healthy

## 预防措施

1. **日志轮转**：在 docker-compose.yml 中为所有服务配置日志驱动轮转：
   ```yaml
   logging:
     driver: json-file
     options:
       max-size: "50m"
       max-file: "5"
   ```
2. **定时清理策略**：通过 cron 定期执行 `docker system prune -f` 和 E2E 报告清理
3. **Prometheus retention**：启动参数 `--storage.tsdb.retention.time=15d`、`--storage.tsdb.retention.size=10GB`
4. **文档生命周期管理**：软删除文档 30 天后自动物理清理（Celery 定时任务）
5. **Qdrant 容量监控**：在 70% 时设置 warning 告警，提前规划扩容
6. **磁盘容量规划**：根据知识库 / 文档增长率预留 30% 余量，季度评估
