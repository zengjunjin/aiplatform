# 面试问答预案

> 本文档为秋招演示准备，涵盖六大可讲亮点、已知妥协点标准答案、演示流程脚本、兜底预案。

---

## 一、六大可讲亮点

### 1. SSE 配额 Lua 闭环
- **是什么**：用 Redis Lua 脚本（INCR+EXPIRE 原子操作）实现每用户 SSE 并发连接数限制，超限返回 429。
- **为什么这么做**：SSE 是长连接，无限制创建会耗尽 worker；用 Lua 保证 INCR+TTL 的原子性，避免竞态。
- **踩过的坑**：DECR 时需 cleanup 已过期 key（否则计数泄漏）；测试时 Redis 不可用要降级放行。
- **代码位置**：`app/core/redis_scripts.py`（_INCR_EXPIRE_LUA / _DECR_CLEANUP_LUA）、`app/services/chat_pipeline.py`（_sse_counter）

### 2. 幂等乐观锁矩阵
- **是什么**：文档解析任务用 `status = 'parsing'` WHERE 条件做乐观锁，防止 Celery 任务重复执行。
- **为什么这么做**：Celery at-least-once 语义下，网络抖动会导致同一任务被多次投递；乐观锁比悲观锁性能好，不需额外锁表。
- **踩过的坑**：需覆盖 pending→parsing→parsed/failed 全状态机，漏掉任意路径都会导致文档卡死。
- **代码位置**：`app/tasks/document_task.py`（parse_document）、`app/services/document_service.py`

### 3. 全链路降级
- **是什么**：Redis 挂→BM25 内存 LRU 兜底；Qdrant 挂→BM25 only；Reranker 挂→score 阈值过滤；LLM 主 provider 挂→fallback provider 自动切换 + restart 事件通知前端清空残留。
- **为什么这么做**：单点故障不应导致整个问答不可用；每层降级都通过 SSE warn 事件告知用户。
- **踩过的坑**：fallback 时前端需清空已渲染的 partial answer（restart 事件），否则用户看到拼接混乱。
- **代码位置**：`app/services/chat_pipeline.py`（_stream_llm_with_fallback、_retrieve_and_rerank）、`app/rag/bm25.py`

### 4. EventBus 解耦
- **是什么**：文档解析完成后通过 EventBus 发布事件，知识库索引、统计、通知等模块订阅处理，不直接调用。
- **为什么这么做**：消除模块间硬编码依赖，新增订阅者不需修改发布方；符合开闭原则。
- **踩过的坑**：事件处理器需异步且不阻塞发布方；失败重试需幂等。
- **代码位置**：`app/core/event_bus.py`

### 5. conftest 防污染体系
- **是什么**：conftest.py 在模块级 mock langchain_community 的 vertexai 依赖（避免 import 时初始化 GCP 客户端），条件注入 pytest-rerunfailures（未安装时不报错）。
- **为什么这么做**：CI 环境无 GCP 凭证，import 阶段就失败；条件注入避免 dev 依赖缺失时 pytest 报未知参数。
- **踩过的坑**：mock 必须在 conftest 顶部、任何 test 模块 import 之前执行；用 sys.modules 注入。
- **代码位置**：`backend/tests/conftest.py`

### 6. 配置中心化演进
- **是什么**：所有魔法数字（历史长度、分页大小、并发限制、TTL）统一收归 settings（Pydantic BaseSettings），从 .env 注入。
- **为什么这么做**：消除散落在路由参数、服务层、task 中的硬编码；环境差异通过 .env 管理而非改代码。
- **踩过的坑**：BM25 测试曾因 settings 默认值在 pytest fixture 修改后未恢复而 flaky；改用 monkeypatch 确保隔离。
- **代码位置**：`app/config.py`

---

## 二、已知妥协点标准答案

### Q: 为什么有两层 nginx（容器内 + 宿主机）？
A: 容器内 nginx 做 frontend 静态资源 + backend API 反向代理（docker-compose 内网）；宿主机 nginx（可选）做 TLS 终结 + 外网入口。开发环境只起容器内 nginx 即可，生产部署时加宿主机 nginx 或 Caddy 做 TLS。这是分层职责，不是冗余。

### Q: 为什么用 bind mount 而不是 volume？
A: 开发环境用 bind mount 挂载源码，改代码 `docker compose restart` 即生效，无需重建镜像。生产环境改为 COPY 进镜像或使用 named volume。这是开发/交付形态的区别，Dockerfile 本身不依赖 bind mount。

### Q: node-exporter 在 Docker Desktop (WSL2) 下监控的是什么？
A: 监控的是 Docker Desktop VM（WSL2 轻量级 VM），不是宿主机 Windows。Grafana dashboard 标题已注明 "Docker VM (WSL2)"，面试时主动说明这一点体现对容器运行时的理解。

### Q: HSTS/TLS 口径？
A: 容器内 nginx 不做 TLS（内网通信无需），TLS 由宿主机 nginx/Caddy 或云 LB 终结。安全响应头（CSP、X-Frame-Options 等）在容器内 nginx 配置。HSTS 仅在 HTTPS 入口启用，避免 HTTP 开发环境出问题。

---

## 三、演示流程脚本

1. **预热**（面试前 10 分钟）
   - `cd deploy && docker compose up -d`
   - 确认模型已常驻显存：`docker exec ollama ollama ps`
   - 若未拉取：`docker exec ollama ollama pull qwen2.5:7b`

2. **建知识库**
   - 打开前端 → 登录 → 新建知识库"面试演示"
   - 上传 3 篇文档（建议：RAG 综述、项目 README、技术博客）

3. **问答演示**
   - 提问"什么是 RAG？"→ 展示流式回答 + 引用来源
   - 提问复杂问题 → 展示 reranker 重排序效果

4. **可观测性**
   - Grafana → RAG Platform Overview dashboard（QPS / 延迟 / token/s）
   - Jaeger → 查看一次问答的完整 trace（检索 → rerank → LLM 生成）
   - Flower → 查看 Celery 任务队列

5. **评估报告**
   - 展示 RAGAS 四项指标（faithfulness / answer_relevancy / context_precision / context_recall）
   - 说明指标含义和当前水平

---

## 四、兜底预案

- **镜像 tarball**：`docker save rag-platform-backend:latest | gzip > deploy/images/backend.tar.gz`
- **端口冲突**：修改 `.env` 中 `BACKEND_PORT` / `FRONTEND_PORT` 等
- **模型未拉取**：`docker exec ollama ollama pull qwen2.5:7b`
- **Ollama 超时**：检查 `OLLAMA_HOST` 是否用服务名 `http://ollama:11434`（不是 localhost）
- **数据库迁移失败**：`docker compose exec backend alembic downgrade -1` 回滚
- **Redis 连接泄漏**：`docker compose restart redis` + 检查 SSE 并发计数器 DECR 逻辑
