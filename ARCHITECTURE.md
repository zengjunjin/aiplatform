# 架构设计文档（ARCHITECTURE.md）

> 面向读者：希望快速理解本项目设计决策的工程师 / 面试官。
> 所有结论均附代码位置证据，行数为 2026-08-22 实测。

## 1. 分层架构

```
┌─────────────────────────────────────────────────────┐
│  api/v1/（路由装配层，只做鉴权/参数校验/限流/SSE 装配）      │
│    chat.py 191 行 · knowledge_bases.py · documents.py │
│    feedback.py · users.py · system.py                │
├─────────────────────────────────────────────────────┤
│  services/（业务编排层）                                │
│    chat_pipeline.py 548 行 —— SSE 全流编排核心          │
│    chat_service / kb_service / document_service      │
│    evaluation_service / feedback_service / auth_*    │
├─────────────────────────────────────────────────────┤
│  rag/（领域算法层）+ models/（LLM 工厂）+ core/（横切）    │
│    retriever.py 613 · bm25.py · reranker.py          │
│    prompt_builder.py · context_manager.py            │
│    models/factory.py（Provider 注册表）                │
│    core/events.py（EventBus）· model_router.py       │
├─────────────────────────────────────────────────────┤
│  db/（SQLAlchemy 模型）· tasks/（Celery 异步任务）       │
└─────────────────────────────────────────────────────┘
```

**依赖方向铁律**（刀二重构后以 grep 验证归零）：
`api → services → rag/models/core → db`，任何层不得反向 import 上层，
`services/` 不得出现 `fastapi.Request/Response`（框架无关，可单测可复用）。

## 2. 五刀重构：chat.py 869 → 191 行的取舍

2026-07-29 架构评审（`docs/review/architecture-review.md`）认定
`api/v1/chat.py` 869 行为全项目最大文件：路由装配、SSE 编排、指标埋点、
消息落库、LLM fallback 混在一层，循环依赖（chat.py import main.py）。

**五刀执行计划**（`docs/roadmap/execution-plan-2026-07-29.md`，逐刀验收于
`docs/roadmap/acceptance-criteria-2026-07-29.md`）：

| 刀 | 内容 | 关键产出 |
|----|------|---------|
| 刀一 | 修复验证与提交 | SSE restart / BM25 重复分词 / retriever 静默截断等 8 项修复 |
| 刀二 | chat.py 拆分 | `services/chat_pipeline.py`（编排）+ `api/v1/feedback.py`（反馈路由独立）+ `core/sse_registry.py`（连接登记），chat.py 降至 191 行 |
| 刀三 | 评估链路去重 | `rag/answer.py` 下沉回答生成（原 evaluation_service 与 chat 双实现）；`models/factory.py` 供 Celery task 独立 LLM 实例 |
| 刀四 | 工程质量加固 | 覆盖率 fail_under=80、Ruff 全量、CI 门禁 |
| 刀五 | 秋招演示打磨 | CDP UI 测试、可观测性面板 |

**为什么值得拆（而不是"多写几个函数"）**：

1. **可单测**：chat_pipeline 不依赖 FastAPI Request，测试直接 mock DB/LLM 即可
   （`tests/test_chat_pipeline.py` 16 用例，该文件覆盖率 ≥80%）。
2. **可复用**：评估链路（刀三）直接复用 `rag/answer.py`，消除双实现漂移风险。
3. **可观测**：TTFT / tokens-per-sec / RAG_E2E_LATENCY 埋点集中收口在管线内
   （`chat_pipeline.py` import 的 `core/metrics.py`），路由层零侵入。
4. **行为不变的证明方式**：重构前后测试用例零修改（验收项 2-6），
   全量 1249 passed 保持绿。

## 3. 三个横切机制的架构位置

### 3.1 EventBus 解耦（`core/events.py`）

文档解析完成后需要通知"会话缓存失效、ES 可选同步、统计更新"等多个下游。
直接调用会让 document_task 依赖所有下游 → 用 Redis Pub/Sub 的事件总线解耦：
publisher 只管 `EventBus.publish("doc.parsed", ...)`，subscriber 自行订阅。
Celery worker 进程级初始化复用同一事件循环（`tasks/document_task.py` L332 注释）。

### 3.2 Provider 降级矩阵（`core/model_router.py` + `models/factory.py`）

`LLM_PROVIDERS` 配置声明多个 provider（本地 Ollama 多模型 / 可扩展云端），
`ModelFactory` 启动时注册，`model_router` 按健康度选主。问答链路中
`chat_pipeline._stream_llm_with_fallback`（L242-358）实现**流式中途降级**：
主 provider 首包失败 → 已生成内容清空（SSE `restart` 事件通知前端）→
切 fallback 续流；全部失败才抛 `AllProvidersFailedError`（`core/exceptions.py` L71）。

### 3.3 幂等乐观锁（`services/document_service.py` L463-478）

重复触发解析是真实事故源（用户连点 / MQ 重投）。重新解析走
`UPDATE ... SET status='pending' WHERE status != 'pending'` 乐观锁语义，
影响行数 rowcount=0 即并发已占用，直接返回；`force=True` 显式跳过锁用于运维强制重跑。
同模式用于 kb 删除与评估任务的幂等保护。

## 4. 大文件为什么保留内聚（而不是继续拆）

| 文件 | 行数 | 内聚理由 |
|------|------|---------|
| `rag/retriever.py` | 613 | 混合检索三件套（BM25 + 向量 + RRF 融合）共享同一份分词缓存与 Qdrant 连接，拆开会造成跨文件传参爆炸；对外接口只有一个 `HybridRetriever` |
| `services/document_service.py` | 603 | 上传→落盘→建任务→乐观锁重解析是单一事务边界，拆开事务语义就碎了 |
| `services/chat_pipeline.py` | 548 | SSE 全流编排（保存→检索→构建→fallback→回填）必须线性可读，这是面试讲解的主叙事文件，拆散反而失去"一条线读完整个 RAG 链路"的价值 |

取舍标准：**拆分解决的是依赖方向与可测性，不是行数审美**。
刀二之后 api 层再无超 300 行文件；services/rag 层的大文件均有明确事务/算法内聚边界。

## 5. 测试与可观测性如何挂在架构上

- 单测：`backend/tests/` 与源码同构（1249 passed），`fail_under=80` 是 CI 硬门禁。
- UI E2E：CDP 协议直连 Tauri WebView2（`deploy/tauri_cdp_test_v4_ui_coverage.mjs`，
  23 场景全绿），不依赖 Playwright 类浏览器自动化。
- 指标：Prometheus 抓 `/internal/metrics`；trace 走 OTel → Jaeger；
  业务指标（TTFT、检索延迟、tokens/s）在管线内埋点，见 §2 第 3 条。
