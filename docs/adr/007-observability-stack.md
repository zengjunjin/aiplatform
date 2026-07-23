# ADR-007: 可观测性技术栈（OpenTelemetry + Jaeger）

## 状态

已采纳

## 日期

2026-07-21

## 上下文

平台阶段五（P1 基础设施与可观测性）需要在已有的 Prometheus 指标 + loguru 结构化日志基础上补齐**分布式追踪**能力，以解决以下问题：

- **跨服务链路定位困难**：一次用户问答会顺序穿过 FastAPI 路由 → 检索（BM25 + Qdrant）→ Reranker → LLM Provider（含 fallback）→ DB 写入 → SSE 推送，任一环节慢都会拉高 P95，但当前仅有指标无法定位具体阶段。
- **Celery 异步任务黑盒**：文档解析、评估、反馈分析等任务在 worker 内部多步执行，失败时日志分散难以串联。
- **httpx 外部调用无追踪**：LLM Provider 通过 httpx 调用 Ollama / OpenAI 兼容接口，单次请求耗时与重试链路不可见。
- **未来需要接入更多客户端**（Tauri 桌面端、移动端），跨端追踪需要统一标准。

关键约束：

- 项目已用 Poetry + Python 3.12 + FastAPI + Celery + SQLAlchemy（async）+ httpx，新增组件必须兼容现有栈。
- 不能引入新的强外部依赖（如需独立部署 Jaeger/SkyWalking/Tempo 才能工作），但允许在 docker-compose 中新增可选服务。
- 不能阻断应用启动；追踪后端不可用时应用必须继续运行。
- 必须可配置启用/禁用，本地开发默认不启用，避免本地无 Jaeger 时启动报错。

## 决策

选择 **OpenTelemetry（OTLP/HTTP）+ Jaeger all-in-one** 作为分布式追踪方案。

### 1. 追踪协议与 SDK：OpenTelemetry

- 使用官方 `opentelemetry-api` / `opentelemetry-sdk` / `opentelemetry-exporter-otlp`，CNCF 标准，与厂商解耦。
- 自动埋点覆盖 4 个组件：
  - `opentelemetry-instrumentation-fastapi`：HTTP 入口 span
  - `opentelemetry-instrumentation-sqlalchemy`：DB 查询 span
  - `opentelemetry-instrumentation-celery`：异步任务 span（含 task enqueue / execute）
  - `opentelemetry-instrumentation-httpx`：外部 LLM Provider 调用 span
- 导出协议选择 **OTLP/HTTP**（`/v1/traces`），原因：
  - OTLP 是 OpenTelemetry 原生协议，未来切换后端无需改代码
  - HTTP 比 gRPC 在容器网络中更易调试（curl 可直接验证）
  - 与 Jaeger all-in-one 1.60+ 原生兼容（`COLLECTOR_OTLP_ENABLED=true`）

### 2. 追踪后端：Jaeger all-in-one

- 单容器部署（`jaegertracing/all-in-one:1.60`），同时提供 collector + query + UI，无需额外存储依赖。
- 端口规划：
  - `16686`：Jaeger UI（管理员浏览器访问）
  - `4317`：OTLP gRPC（保留给未来 gRPC exporter）
  - `4318`：OTLP HTTP（当前 backend/celery_worker 使用）
- 通过 `COLLECTOR_OTLP_ENABLED=true` 显式启用 OTLP 接收。
- 配置 healthcheck（`/` on 14269）以便 docker-compose 编排。

### 3. 启用控制：环境变量驱动

通过 `OTEL_EXPORTER_OTLP_ENDPOINT` 环境变量控制：

- **未设置**：`_setup_opentelemetry()` 直接 return，不进行任何仪器化，应用零开销启动。
- **已设置**（如 `http://jaeger:4318`）：初始化 TracerProvider + BatchSpanProcessor + 全局 instrumentor，并在 lifespan 中对 FastAPI app 执行 `FastAPIInstrumentor.instrument_app(app)`。

Service name 通过 `OTEL_SERVICE_NAME` 环境变量覆盖，默认 `rag-platform-backend`，便于区分 backend / celery_worker。

### 4. 故障隔离

- OTel 初始化代码全部包裹在 try/except 中，**任何失败仅 warning 日志，不阻断应用启动**。
- Jaeger 不可用时 `BatchSpanProcessor` 内部缓冲并最终丢弃 span，不影响请求路径。

## 后果

### 正面影响

- 一次用户问答可在 Jaeger UI 中看到完整链路：HTTP → DB 查询 → Qdrant 检索 → LLM 调用（含 fallback）→ SSE 推送，每个阶段耗时可见。
- Celery 任务从 enqueue 到 execute 全程追踪，失败任务可快速定位慢阶段。
- httpx 调用 Ollama/OpenAI 的重试链路可视化，fallback 触发条件可观测。
- OTLP 协议标准化，未来可平滑切换到 Tempo / Datadog / 阿云 ARMS 等后端，无需改业务代码。
- 与已有 Prometheus 指标 + loguru 日志形成 metrics / logs / traces 三位一体可观测性栈。

### 负面影响

- Jaeger all-in-one 单容器内存占用 ~300MB，生产高吞吐场景需替换为 Jaeger + Elasticsearch/ClickHouse 分布式部署。
- 自动埋点会对每个 HTTP 请求与 DB 查询生成 span，高 QPS 下 span 数量爆炸；需后续根据实际流量调整 `BatchSpanProcessor` 的 `max_queue_size` / `max_export_batch_size`。
- 当前未对 span 主动采样，全部上报；生产环境建议后续配置 `ParentBased(TraceIdRatioBased(0.1))` 采样器。
- OTel 依赖增加 backend 镜像体积约 30MB（opentelemetry-sdk + instrumentation 包）。

## 替代方案

| 方案 | 优点 | 缺点 | 为何未选择 |
|------|------|------|------------|
| SkyWalking Python agent | 自动埋点开箱即用，UI 信息密度高 | 厂商耦合（需部署 SkyWalking OAP + ES），Python agent 生态不如 OTel 成熟 | 厂商耦合，部署链路重 |
| Tempo + Grafana | 与已有 Grafana 生态融合，对象存储成本低 | 需额外部署 Tempo + Grafana，trace 检索能力弱于 Jaeger | 部署复杂度高于 Jaeger all-in-one |
| Datadog APM | 商业产品开箱即用，UI 极佳 | 商业付费，数据出公网，厂商锁定 | 不符合自部署与数据主权要求 |
| Pinpoint | 韩国开源，UI 美观 | Python 支持弱，社区维护不活跃 | Python 生态支持不足 |
| 自研 trace middleware | 完全可控 | 重复造轮子，无标准协议，未来扩展成本高 | 不符合 CNCF 标准化方向 |

## 参考

- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)
- [Jaeger all-in-one Docker image](https://www.jaegertracing.io/docs/1.60/getting-started/)
- 实现：
  - `backend/app/main.py` 的 `_setup_opentelemetry()` 与 `lifespan`
  - `deploy/docker-compose.yml` 的 `jaeger` 服务
  - `backend/pyproject.toml` 的 opentelemetry-* 依赖
