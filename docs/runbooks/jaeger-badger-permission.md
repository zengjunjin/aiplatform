# Runbook: Jaeger 崩溃循环（badger 卷权限）

## 故障描述

**现象**：`rag-platform-jaeger-1` 状态为 `Restarting (1)`，Jaeger UI（16686）不可访问；backend/celery 日志每 ~5 秒出现 `Exception while exporting Span batch ... Failed to resolve 'jaeger'` 长 traceback（OTel 导出失败的级联噪音）。

**根因**：jaegertracing/all-in-one 镜像以 **UID 10001** 非 root 运行，而 named volume `rag-platform_jaeger_badger_data` 首次创建时属 root，Badger 无法创建数据目录：

```
Failed to init storage factory: mkdir /badger/key: permission denied
```

**触发场景**：`docker compose down -v` 或删除 volume 后重新 `up`（fresh volume 必现）。

## 应急处理（一次性命令）

```bash
# 将 badger 数据卷属主修正为 jaeger 进程用户（UID 10001）
docker run --rm -v rag-platform_jaeger_badger_data:/badger alpine chown -R 10001:10001 /badger

# 重启 jaeger
cd deploy && docker compose restart jaeger
```

## 恢复验证

```bash
docker ps --filter "name=jaeger" --format "{{.Status}}"   # 期望：Up ... (healthy)
curl -s -o /dev/null -w "%{http_code}" http://localhost:16686/   # 期望：200
# backend OTel 级联错误应停止：
docker logs rag-platform-backend-1 --since 1m 2>&1 | grep -c "Exception while exporting Span"   # 期望：0
```

## 预防措施

- **不要**对 jaeger 使用 `docker compose down -v`（会删 volume 导致权限问题复发），除非接受再跑一次上面的 chown。
- 长期根治方案（二选一，暂未实施）：
  1. compose 中为 jaeger 增加 `user: "10001"` 并用初始化容器预创建 `/badger/key` `/badger/data` 目录；
  2. 改用 tmpfs/内存存储（`SPAN_STORAGE_TYPE` 去掉 badger 环境变量即回退内存模式，trace 重启即失）。
- 同类风险排查：任何「非 root 镜像 + named volume」组合都可能有此问题（本栈中 loki/grafana/prometheus 的 volume 由官方镜像的 entrypoint 自行处理权限，无需干预）。
