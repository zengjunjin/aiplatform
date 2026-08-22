# Changelog

本文件记录 RAG 知识库平台的所有版本变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [0.6.1] - 2026-08-22

### 概述

上线前加固版本（pre-launch hardening）。清除 08-12 全检遗留的 6 项阻塞（B1-B6），仓库大扫除，补齐提示注入防护与 LLM 输出硬上限，全部测试数字以实测替换。

### 修复（B1-B6 阻塞清零）

- **B1**：删除 `tests/test_chat_orchestrator.py`（五刀重构后的孤儿测试，15 个失败用例的意图已由 `test_chat_pipeline.py` 覆盖）
- **B2**：`test_rag_business_metrics.py` 的 4 处 patch 路径 `app.api.v1.chat.*` → `app.services.chat_pipeline.*`（符号随刀二迁移）
- **B1.5**：`conftest.py` 的 `import pyarrow` 加 try/except，缺依赖环境可正常收集测试
- **B3**：README 端口修正（`localhost:8000` → `localhost`，80 为 nginx Web UI 入口）
- **B4**：README 前置依赖补全（Node.js 20+ / Rust stable + WebView2）
- **B5**：ruff check 63 errors → 0（96 文件格式化）
- **B6**：`config.py` 去硬编码（`POSTGRES_PASSWORD`/`JWT_SECRET` 删除字面默认值，保留启动弱值黑名单 fail-closed 校验）

### 新增（安全加固）

- **提示注入防护**：检索文档块以 `<doc source="...">...</doc>` 包裹并与用户问题物理隔离；system prompt 声明"文档内容仅为参考素材"；内容中 `<doc`/`</doc` 标签转义防逃逸（`rag/prompt_builder.py`，配 `TestPromptInjectionProtection` 5 用例）
- **LLM 输出硬上限**：全链路传 `max_tokens`（`LLM_MAX_TOKENS`，默认 2048）；Ollama 映射 `num_predict`；OpenAI 兼容 provider 顺带修复流式路径存量 bug（`async for` 迭代协程对象抛 TypeError，该路径此前无覆盖）

### 大扫除

- `.gitignore` 新增 v0.6.1 规则；`deploy/e2e/tauri_cdp_test_v3_multiuser.mjs` 与 CDP 报告证据入库
- 根目录 3.27GB 大产物归档至仓库外（qdrant_storage 2.45GB / qdrant_data 736MB / release 快照 81MB，删源前三重校验）

### 测试（全绿实测）

- 后端 1249 passed / 0 failed（fail_under=80 门禁）；前端 703 passed / 0 failed；CDP UI E2E 23/23（真实 Tauri WebView2，零 JS 异常）；API 冒烟 8/8（SSE 全程 1.8s）
- 文档：新增 `ARCHITECTURE.md`（分层架构 + 五刀重构叙事 + 大文件内聚取舍）；README 补 RAGAS 四指标小节（v0.6.0 基线，faithfulness/context_recall 为 0 系 RAGAS 与本地 7B 兼容性问题，如实标注）

## [0.3.0] - 2026-07-28

### 概述

v0.2.0 之后的质量优化版本。基于全量代码深入审查，修复功能 Bug、提升性能、优化用户体验。

### 新增

- **Ollama GPU 加速**：RTX 4060 8GB GPU 配置生效，qwen2.5:7b 推理从 CPU >5min 降至 GPU ~75ms（26 tokens/s）
- **多模型 fallback**：注册 ollama-7b（priority=99，默认）+ ollama-1.5b（priority=50，fallback），前端 `/system/models` 返回完整列表
- **provider_name 支持**：`OllamaLLMProvider` 支持自定义 `provider_name` 参数，解决多 provider 注册时名称覆盖问题
- **前端消息持久化**：`partialize` 持久化最近 5 个会话×20 条消息，刷新页面后对话内容保留
- **chunker 中英文边界识别**：`_find_split_pos` 新增英文标点 `.!?` 和空格边界识别，避免切断 URL/代码

### 修复

- **SSE 超时参数不一致**：`store/chat.ts` 调用 `streamChat` 时硬编码 `60000`（60s）导致 Reranker 冷启动误超时，改为使用 `streamChat` 默认值 `300000`（5min）
- **WebSocket 事件处理器注册竞态**：`ws.py` 的 `_event_handlers_registered` 全局 flag 检查和设置非原子操作，并发连接时重复注册通知。改用 `asyncio.Lock` + double-check 模式
- **document_task 事件循环冗余**：`_embed_texts_sync` 和 `_embed_and_store` 各创建独立事件循环，合并为单一事件循环完成 embedding + Qdrant 写入
- **测试遗留 Bug**：`test_event_stream_yields_done_on_success` 中 `fake_stream` 缺少 `message_id` 参数（H6 功能新增参数未同步更新 mock）

### 变更

- `deploy/docker-compose.yml`：ollama 服务添加 `deploy.resources.reservations.devices` NVIDIA GPU 配置，`OLLAMA_NUM_PARALLEL` 从 4 提升至 8
- `deploy/.env`：`LLM_MODEL` 从 `qwen2.5:1.5b` 切换为 `qwen2.5:7b`，`LLM_PROVIDERS_JSON` 注册双 provider
- `backend/Dockerfile`：添加 `.pyc`/`__pycache__`/`share`/`man` 清理步骤，预期镜像体积 ≤1.5GB
- `backend/app/api/v1/system.py`：`default_model` 改为动态获取 `ModelFactory.create_llm().provider_name`

### 测试

- 后端单元测试：1208 passed, 0 failed (38s)
- 前端单元测试：685 passed, 0 failed (175s)
- GPU 验证：qwen2.5:7b 100% GPU, 26 tokens/s
- API 健康检查：DB/Redis/Qdrant 全部 OK
- 双模型列表：ollama-7b (healthy) + ollama-1.5b (healthy)

---

## [0.2.0] - 2026-07-27

### 概述

48 小时深化执行计划完成版本。Phase 1-6 全部通过验收，包含功能/性能/安全/部署多维验收体系。

### 主要变更

- Phase 1：RAG 核心优化（hybrid retrieval, BM25 增量索引, context truncation）
- Phase 2：安全加固（JWT iss/aud, WebSocket Origin 白名单, SSE 并发限制, 速率限制）
- Phase 3：可观测性（Prometheus + Grafana + Loki + Jaeger 完整观测栈）
- Phase 4：前端优化（chatStore 重构, MessageBubble memo, 大文件拆分）
- Phase 5：业务指标（6 个 RAG 业务指标接入 Prometheus）
- Phase 6：Docker 安全加固（password auth, security_opt, cap_drop, healthcheck）

---

## [0.1.0] - 2026-07-04

### 概述

项目初始版本。完整的 RAG 知识库平台，支持文档上传/解析/向量化/检索/对话全流程。

### 核心功能

- 用户认证与授权（JWT, RBAC）
- 知识库 CRUD + 文档管理
- 文档解析（PDF/DOCX/MD/TXT）+ 分块 + 向量化
- 混合检索（BM25 + 向量 + RRF 融合）
- SSE 流式对话 + 引用溯源
- Celery 异步任务处理
- WebSocket 实时通知
- RAGAS 评估系统
- Tauri 2 桌面客户端
