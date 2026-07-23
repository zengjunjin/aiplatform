# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-07-22

> PR: [platform-optimization-pass-2026-07 (#7)](https://github.com/zengjunjin/aiplatform/pull/7)

### Added
- **Dashboard 平台概览页**：KPI 焦点区（今日问答数 + 健康徽章）+ 4 小图（文档解析趋势/评估指标趋势/反馈正负比环形/模型健康）
- **SystemPage 系统健康可视化**：postgres/redis/ollama/qdrant/celery 状态卡片网格 + ollama 模型列表 + qdrant collections 数量 + celery workers
- **/healthz + /readyz 端点分离**：liveness 仅进程存活；readiness 探测 DB/Redis/Qdrant
- **/internal/metrics 端点**：Bearer token 鉴权，供 Prometheus 抓取（区别于 `/metrics` 的 admin 鉴权）
- **结构化日志 + request_id 注入**：`logger.configure(patcher=...)` 通过 `contextvars` 把 `request_id` 注入所有 loguru record；`LOG_JSON=true` 时启用 JSON sink
- **OpenTelemetry 分布式追踪**：自动埋点 FastAPI/SQLAlchemy/Celery/httpx，通过 `OTEL_EXPORTER_OTLP_ENDPOINT` 控制启用，导出到 Jaeger
- **Tauri updater 插件**：`tauri-plugin-updater` + `bundle.windows.certificateThumbprint` + `publish.publicKey`
- **Dockerfile 多阶段构建 + 非 root 用户**：builder（含 build-essential/poetry）+ runtime（python:3.12-slim + appuser），镜像 ≤ 400MB
- **docker-compose 资源限制 + healthcheck**：backend/celery_worker/frontend/nginx/ollama 全部带 healthcheck；ollama 限制 4G/2cpus
- **CI service containers**：backend-ci 增加 postgres/redis/qdrant services + unit vs integration 矩阵分离
- **SAST 安全扫描门禁**：CodeQL + Bandit + Trivy + pip-audit/cargo audit/npm audit（critical 级别 fail）
- **Dependabot 自动化**：pip/npm/cargo/docker 四个 ecosystem，weekly schedule
- **CONTRIBUTING.md + LICENSE(MIT) + docs/adr/008-secret-management.md**
- **README mermaid 架构图 + Quickstart + Contributing 段落**
- 新增 `test_18_dashboard_e2e.py` 与 `test_19_system_e2e.py` E2E 测试覆盖新页面
- 新增 `test_evaluation_api.py`/`test_chat_orchestrator.py`/`test_document_service.py`/`test_health_endpoints.py`/`test_event_bus.py`/`test_evaluation_concurrency.py` 单元测试
- 新增 `SystemPage.test.tsx`/`DashboardPage.test.tsx`/`ErrorBoundary.test.tsx`/`MessageBubble.test.tsx` 前端测试

### Changed
- **拆分 chat.py event_stream 巨型函数**：抽出 `_save_user_msg`/`_retrieve_and_rerank`/`_stream_llm_with_fallback`/`_save_assistant_msg`/`_send_sse`/`_send_sse_error`，主函数仅做流程编排（≤ 50 行）
- **document_service.upload_document 业务下沉**：路由层仅做参数绑定，service 封装 KB 权限/数量/文件名/扩展名/hash/事务/Celery 派发
- **evaluation.run_evaluation 并发化**：`asyncio.gather` + `Semaphore(8)` 并发；单题失败隔离；DB 写入串行
- **chat_service Redis pipeline 合并**：`lpush`+`expire`+`ltrim` 合并为 1 次 RTT
- **notification_manager broadcast 并行**：`asyncio.gather(*, return_exceptions=True)`；`_connections` 用 `asyncio.Lock` 保护
- **BM25 async 路径改用 asyncio.Lock**：sync 路径保留 threading.Lock 给 Celery
- **retriever._chunks_cache singleflight 模式**：per-kb_id asyncio.Lock
- **EventBus.close() 不再清空 _subscribers**：仅关闭 Redis 连接，支持 Celery 重启后订阅恢复
- **CachedEmbeddingProvider 移除 None 过滤**：`any(r is None)` 时直接 raise ValueError
- **audit_service.log_audit 移除 db 参数**（未使用）
- **魔法数字迁到 config**：`SSE_MAX_CONCURRENT`/`SSE_COUNT_TTL`/`CANCEL_CHECK_INTERVAL`/`LOG_JSON`/`METRICS_TOKEN`
- **DocumentsPage 修复假分页**：服务端 `kbFilter` + `page` + `pageSize` state
- **MessageBubble feedback 缓存**：`feedbackByMessageId` state + `getFeedback(messageId)` action
- **EvaluationPage 趋势图优化**：X 轴 `created_at` 格式化、RAGAS 0.7 阈值 markLine、>20 点启用 dataZoom、delta vs prev run、单题 mini-bar、箱线图、Skeleton loading、running 状态 30s 自动刷新
- **FeedbackPage 类型分布图表化**：横向条形图 + 堆叠柱状图 + 7/30/90 天正反馈率折线图 + 热力图日历
- **文档解析阶段化进度**：横向 Stepper（pending→parsing→chunking→embedding→done）
- **Token 消耗展示**：MessageBubble token chip + 响应时长 chip；ChatPage 累计 token / 成本徽章
- **颜色 token 化**：ChatPage/MessageBubble 硬编码颜色替换为 `var(--accent-primary-light)` / `var(--accent-info-bg)` 等 design token
- **路由级 ErrorBoundary**：每个 `<Route element>` 内部包 `<ErrorBoundary>`；全局错误 toasts
- **注册表单密码强度可视化**：5 段 strength bar + 实时匹配校验 + `validateFirst` + `hasFeedback`
- **大文件拆分**：KnowledgeBaseDetailPage/Layout/MessageBubble/ChatPage 拆出 10 个独立组件
- **utils/format.ts i18n 迁移**：`getStatusText` 返回 i18n key；所有调用方改为 `t(getStatusText(status))`
- **api/documents.ts upload 改用 axios**：`client.post` + `onUploadProgress`
- **DocumentsPage 聚合统计**：状态环形图 + 类型横向条形图 + 总大小 Statistic + 失败文档置顶红色徽章
- **KnowledgeBasesPage 顶部聚合统计**：4 个 Statistic 卡 + 近 7 天 sparkline

### Fixed
- 修复 `evaluation.py:34` `get_kb_for_read(db, kb_id, admin.id)` 参数顺序错误（应为 `get_kb_for_read(kb_id, admin.id, db)`）
- 修复 `reranker_provider.py:81` fallback 返回 `tuple[int, float]` 类型（idx 与 score 不再相等）
- 修复 `DocumentsPage` 假分页（`page_size: 200` 全量拉取 + `Promise.all`）
- 修复通知未读数永远等于总数（基于 `readAt` 时间戳过滤）
- 修复 `ChatPage` 会话列表 a11y（`<div onClick>` 改为可键盘 Tab 聚焦 + Enter/Space 触发）
- 修复 `documents.py:277` `parser.parse` 同步阻塞（改用 `await asyncio.to_thread`）
- 修复 `system.py:63` `retriever.qdrant.get_collections` 同步阻塞
- 修复 `evaluation_task.py:173` `_generate_question_sync` 不再使用 `requests.post`，复用 ModelRegistry LLM Provider 异步调用

### Security
- **JWT 引入 iss="rag-platform" + aud="rag-client" 校验**（**BREAKING**：所有旧 token 失效，需重新登录）
- **WebSocket Origin 校验**：`WEBSOCKET_ALLOWED_ORIGINS` 白名单，禁止则返回 4003
- **SSE 并发限流**：max 3 per user via Redis counter；超出返回 429
- **WebSocket 连接限制**：max 5 per user（4004）、10 messages/minute（4005）、30s ping/pong timeout（4006）
- **JWT_SECRET + POSTGRES_PASSWORD 弱值黑名单**：`model_post_init` 强制校验，非 DEBUG 模式 raise
- **/metrics admin 鉴权 + /internal/metrics Bearer token 鉴权**
- **Tauri additionalBrowserArgs 移除 `--remote-debugging-port=9222`**（RCE 风险）
- **CSP 增强**：`connect-src` 显式允许 http://localhost:8000 / ws://localhost:8000 / tauri.localhost
- **MarkdownRenderer urlTransform 白名单**：block `javascript:` / `data:` / `vbscript:`

### Documentation
- 新增 `docs/adr/007-observability-stack.md`（OTel + Jaeger 选型）
- 新增 `docs/adr/008-secret-management.md`（密钥管理决策）
- 新增 `docs/adr/009-tauri-updater.md`（Tauri updater 选型）
- 新增 `CONTRIBUTING.md`（commit 规范 / PR 流程 / coverage 门槛）
- 新增 `LICENSE`（MIT）
- 更新 `README.md` 增加 mermaid 架构图 + Quickstart + Contributing 段落

### BREAKING CHANGES
1. **JWT iss/aud 校验**：所有阶段二之前签发的 token 失效，需重新登录。`JWT_ISSUER=rag-platform` / `JWT_AUDIENCE=rag-client` 必须在 `.env` 中配置。
2. **`/health` 拆分为 `/healthz` + `/readyz`**：`deploy/nginx.conf` 与 `deploy/docker-compose.yml` healthcheck 改用 `/readyz`。
3. **`audit_service.log_audit` 移除 `db` 参数**：所有调用点需更新。
4. **`get_kb_for_read` 参数顺序**：`(kb_id, user_id, db)`（不是 `(db, kb_id, user_id)`）。

## [0.2.0] - 2026-07-11

### Added
- RAGAS 评估体系，支持自动化 RAG 质量评估（忠实度、相关性、上下文精度、上下文召回）
- 多模型支持：通过 ModelFactory 支持 OpenAI 兼容 API 与 Ollama，可热切换
- 反馈闭环：用户对回答的满意度反馈（点赞/点踩），自动记录用于后续优化
- 性能基准测试（Locust），覆盖 RAG 检索、生成、并发等关键路径
- 深色模式（Dark Mode），支持系统主题跟随与手动切换
- 国际化（i18n），支持中英文语言切换
- PWA 支持，可安装为桌面应用并支持离线缓存
- WebSocket 通知系统，实时推送文档处理状态、系统消息
- 事件驱动架构：核心流程解耦为事件-监听器模式
- API 版本化（v1），为未来 API 演进预留空间
- 数据库连接池可配置（pool_size、max_overflow、pool_timeout）
- 代码质量优化：ESLint、Prettier、pre-commit hooks 统一代码风格

### Changed
- 优化 RAG 检索精度，引入缓存层减少重复 embedding 计算
- 改进前端 UI/UX，提升交互体验
- 重构部分后端代码，消除技术债务

## [0.1.0] - 2026-07-04

### Added
- 核心 RAG 问答功能：混合检索（BM25 + 向量）+ RRF 融合 + Rerank 重排序
- 用户认证与权限管理：JWT 认证（access + refresh token）、RBAC 角色控制
- 文档上传与解析：支持 PDF、DOCX、Markdown、TXT 多格式
- Tauri 桌面端打包：Windows 平台原生桌面应用
- 知识库管理：创建、删除、文档列表
- 流式对话：SSE 流式响应，支持引用来源标注
- 异步文档处理：Celery 异步文档解析与向量入库
- 数据库迁移：Alembic 版本化 schema 管理
- API 限流保护：防止滥用
- Token 黑名单机制：支持主动登出

[Unreleased]: https://github.com/zengjunjin/aiplatform/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/zengjunjin/aiplatform/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/zengjunjin/aiplatform/releases/tag/v0.1.0