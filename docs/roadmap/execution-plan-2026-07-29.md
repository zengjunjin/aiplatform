# aiplatform 完善执行文档（Execution Plan）

> 版本：v1.0｜日期：2026-07-29｜编制：齐活林（主理人）
> 依据：`docs/review/` 三轮审查报告（architecture / code-quality / test-quality / containerization / runtime-audit）
> 使用方式：按"刀"顺序执行；每刀独立可验收，验收标准见配套《验收文档》（acceptance-criteria-2026-07-29.md）
> 执行环境基线：Windows 11 + Docker Desktop WSL2 + i7-13700H / 16GB / RTX 4060 8GB；后端测试使用 poetry 虚拟环境 `C:\Users\15116\AppData\Local\pypoetry\Cache\virtualenvs\rag-platform-backend-n1gY3d2C-py3.12\Scripts\python.exe`

---

## 总览

| 刀 | 主题 | 预估 | 前置依赖 | 风险 |
|---|------|------|---------|------|
| 一 | 修复验证与提交 | 0.5 天 | 无（立即开始） | 低 |
| 二 | chat.py 拆分 | 1.5 天 | 刀一完成 | 中（行为不变重构） |
| 三 | 评估链路去重 | 0.5 天 | 刀一完成（可与刀二并行） | 低 |
| 四 | 工程质量加固 | 0.5 天 | 刀二、三完成 | 低 |
| 五 | 秋招演示打磨 | 0.5 天 | 全部完成 | 低 |

---

# 刀一：修复验证与提交

## 1.1 目标

当前工作区有 8 个未提交的修复文件，**未经测试验证**。本刀目标：验证修复正确性 → 补充缺失测试 → 规范化提交。

涉及文件（git status 实测）：
```
M backend/app/api/v1/auth.py
M backend/app/api/v1/chat.py
M backend/app/rag/bm25.py
M backend/app/rag/retriever.py
M backend/app/services/chat_service.py
M backend/app/services/document_service.py
M backend/app/services/evaluation_service.py
M backend/app/tasks/evaluation_task.py
```

## 1.2 前置检查（10 分钟）

```bash
cd C:\Users\15116\Desktop\aiplatform
# 1. 确认改动清单与行数规模
git diff --stat
# 2. 逐文件审阅 diff，对照第一轮审查报告的修复建议，确认每处改动意图
git diff backend/app/api/v1/chat.py | head -100
# 对照检查点：
#   - chat.py: finally 中的 yield [DONE] 是否已移入正常结束分支（代码质量 P1-3）
#   - chat.py: 泛型 Exception 是否改专用异常（P2-11）
#   - chat_service.py:110: loguru %s 是否已改（P1-10）
#   - bm25.py: _build/_serialize_index 分词是否合并为一次（P1-4）
#   - bm25.py:111-117: Redis 连接重置前是否补 aclose（P1-5）
#   - retriever.py:412: zip 是否改 strict=True（P1-8）
#   - retriever.py:137-146: 分阶段计时是否挪进各自函数内部（P1-9）
#   - document_service.py:168: save_upload_file 是否包 to_thread（P0-2）
#   - evaluation_*.py: 双份实现是否已统一（P1-6）
```

**注意**：前端 `frontend/src/api/chat.ts` 与 `frontend/src/store/chat.ts` 的 restart 事件修复（代码质量 P0-1）**不在 git 修改列表中**——需向用户确认是已修未改、还是遗漏。若遗漏，按 1.3.4 补修。

## 1.3 详细步骤

### 1.3.1 后端定向测试（修复相关模块，约 15 分钟）

```bash
cd C:\Users\15116\Desktop\aiplatform\backend
# 使用 poetry 虚拟环境（系统 Python 3.13 无 pytest，勿用）
PY="C:\Users\15116\AppData\Local\pypoetry\Cache\virtualenvs\rag-platform-backend-n1gY3d2C-py3.12\Scripts\python.exe"

$PY -m pytest tests/test_chat_api.py tests/test_chat_service.py tests/test_chat_orchestrator.py tests/test_chat_cancel.py -q --no-header -p no:cacheprovider
$PY -m pytest tests/test_bm25.py tests/test_retriever.py tests/test_rrf.py -q --no-header -p no:cacheprovider
$PY -m pytest tests/test_evaluation_task.py tests/test_evaluation_service.py tests/test_evaluation_concurrency.py -q --no-header -p no:cacheprovider
$PY -m pytest tests/test_document_service.py tests/test_document_task.py tests/test_document_task_extend.py tests/test_documents_api.py -q --no-header -p no:cacheprovider
```

任一失败：先判定是修复引入的回归还是测试本身需随行为更新（参考 test-quality-review.md 的智能路由原则——源码 Bug 回给修复者，测试 Bug 改测试）。

### 1.3.2 前端定向测试

```bash
cd C:\Users\15116\Desktop\aiplatform\frontend
npx vitest run src/__tests__/store src/__tests__/api --reporter=dot
```

### 1.3.3 补充 restart 事件测试用例（QA 报告 P2-8 盲区）

在 `frontend/src/__tests__/api/chat.test.ts`（或对应文件）新增：

```ts
describe('SSE restart event', () => {
  it('should accept restart as a valid SSE event type', () => {
    // isSSEEvent 白名单必须包含 restart（backend chat.py 在 fallback 时发送）
    expect(isSSEEvent({ event: 'restart' })).toBe(true);
  });
});
```

在 `frontend/src/__tests__/store/chat.test.ts` 新增：

```ts
it('should clear accumulated content when restart event arrives', async () => {
  // 模拟 primary provider 已输出部分 token 后触发 fallback：
  // 事件序列 delta("abc") → restart → delta("xyz")
  // 最终消息内容必须为 "xyz"，不得为 "abcxyz"（修复前 Bug 表现）
});
```

### 1.3.4 （条件项）若前端 restart 修复遗漏

- `frontend/src/api/chat.ts:70`：`isSSEEvent` 白名单数组加入 `'restart'`
- `frontend/src/store/chat.ts` sendMessage 事件分发：新增 restart 分支，执行 `accContent = ''` 并更新对应消息内容后 return
- 改动量 < 20 行，勿顺手重构其他逻辑

### 1.3.5 全量回归（提交前最后一道闸）

```bash
cd C:\Users\15116\Desktop\aiplatform\backend
$PY -m pytest tests/ -m "not integration and not e2e and not real_rag" -n auto --cov=app --cov-report=term -q
# 基线：873 passed / 覆盖率 ≥ 82%（不得低于修复前基线）

cd ..\frontend
npx vitest run
# 基线：466+ passed（含新增 restart 用例）
npx eslint src/
npx tsc --noEmit
```

### 1.3.6 分组提交（Conventional Commits）

按 CONTRIBUTING.md 规范分 3-4 个提交，**禁止一个巨型 commit**：

```bash
# 提交 1：SSE 链路修复（对应 P0-1 / P1-3）
git add backend/app/api/v1/chat.py backend/app/services/chat_service.py frontend/src/api/chat.ts frontend/src/store/chat.ts frontend/src/__tests__/
git commit -m "fix(chat): handle SSE restart event on frontend and move [DONE] out of finally

- add 'restart' to SSE event whitelist (api/chat.ts) and clear accContent in store
- move [DONE] yield from finally block to normal completion path
- fix loguru %s placeholder in chat_service warning log
Refs: docs/review/code-quality-review.md P0-1, P1-3, P1-10"

# 提交 2：检索与上传修复（对应 P0-2 / P1-4 / P1-5 / P1-8 / P1-9）
git add backend/app/rag/bm25.py backend/app/rag/retriever.py backend/app/services/document_service.py
git commit -m "fix(rag): dedupe BM25 tokenization and harden retrieval pipeline

- reuse tokenized corpus between _build and _serialize_index
- close stale async redis connection before reset
- zip(strict=True) in add_chunks to fail loudly on vector/chunk mismatch
- move per-stage latency timing inside vector/bm25 search functions
- wrap save_upload_file in asyncio.to_thread to unblock event loop
Refs: docs/review/code-quality-review.md P0-2, P1-4, P1-5, P1-8, P1-9"

# 提交 3：评估链路统一（对应 P1-6，若已在本次修复内）
git add backend/app/services/evaluation_service.py backend/app/tasks/evaluation_task.py
git commit -m "refactor(evaluation): unify dataset generation via shared service implementation"
```

## 1.4 风险与回滚

| 风险 | 应对 |
|------|------|
| 定向测试失败且定位模糊 | `git stash` 单个文件对比验证，二分定位 |
| 全量回归覆盖率跌破 80% | 新代码必须补测试；不得为提高覆盖率调低 fail_under |
| 提交后发现遗漏 | 新提交修复，禁止 amend 已推送提交 |

---

# 刀二：chat.py 拆分（架构 P0-1 / P0-3 / P1-1 / P1-3 一次性解决）

## 2.1 目标结构

```
backend/app/
├── api/v1/
│   ├── chat.py              # ≤250 行：sessions CRUD 路由 + SSE 装配 + 鉴权/限流
│   └── feedback.py          # 新建，~150 行：5 个 feedback 端点（自 chat.py:734-868 迁入）
├── core/
│   └── sse_registry.py      # 新建，~40 行：活跃 SSE 任务注册表（替代 main._active_sse_requests）
├── services/
│   ├── chat_pipeline.py     # 新建，~500 行：RAG 编排管线（SSE 流式生成核心）
│   └── chat_service.py      # 保持 CRUD 职责不变
└── main.py                  # 删除 _active_sse_requests 定义，改从 sse_registry 导入
```

### chat_pipeline.py 类设计（骨架）

```python
# backend/app/services/chat_pipeline.py
"""聊天 RAG 编排管线：从 API 层剥离的 SSE 流式生成核心。

设计约束（来自架构评审 P0-1）：
- 不 import fastapi/starlette 的 Request/Response，保持框架无关、可窄单测
- 依赖全部通过构造函数注入，禁止函数级 import
- SSE 事件格式与前端协议（api/chat.ts isSSEEvent 白名单）保持字节级兼容
"""
from collections.abc import AsyncGenerator
from app.rag.retriever import HybridRetriever
from app.rag.reranker import Reranker
from app.core.model_router import ModelRouter

class ChatPipeline:
    def __init__(self, retriever: HybridRetriever, reranker: Reranker,
                 model_router: ModelRouter) -> None: ...

    async def run_stream(
        self, *, session_id: int, user_id: int, kb_id: int,
        question: str, model: str | None,
    ) -> AsyncGenerator[str, None]:
        """迁移自 chat.py:_run_sse_stream（L434-566）。

        职责链（保持现有顺序与语义）：
        存用户消息 → 历史加载 → 取消检查 → query rewrite → searching 事件
        → 混合检索（_retrieve_and_rerank 迁入为私有方法）
        → 摘要压缩 → Provider 选择 → _stream_llm_with_fallback（迁入）
        → 引用解析 → 占位回填 → done 事件
        取消/异常路径：cancelled/error 事件 + 配额清理（保持现有兜底逻辑）。
        """
```

### sse_registry.py（骨架）

```python
# backend/app/core/sse_registry.py
"""活跃 SSE 请求注册表：切断 api→main 反向循环依赖（架构评审 P0-3）。"""
import asyncio

_active_sse_requests: set[asyncio.Task] = set()

def register(task: asyncio.Task) -> None: ...
def discard(task: asyncio.Task) -> None: ...
def all() -> set[asyncio.Task]: ...  # 供 main.py 优雅关闭时取消
```

## 2.2 迁移步骤（5 步，每步独立提交、独立可验证）

**Step 1 — feedback 路由拆出（最小风险，先练手）**
1. 新建 `api/v1/feedback.py`，迁移 chat.py:734-868 的 5 个端点
2. 新建 `schemas/feedback.py` 的 `FeedbackDetailOut`（替代 get_low_rated_feedbacks 手工拼 dict，架构 P1-1）
3. 消除函数体内 `from app.services import feedback_service` × 5 的延迟 import，提到模块顶部
4. `api/v1/router.py` 注册新路由（路径前缀保持不变，**URL 一个字节不能变**）
5. chat.py 删除已迁移代码；`tests/test_chat_api.py` 中 feedback 相关用例迁移到 `tests/test_feedback_api.py`
6. 验证：`pytest tests/test_feedback_api.py tests/test_chat_api.py -q` 全绿

**Step 2 — 建 sse_registry.py**
1. 新建 core/sse_registry.py
2. main.py:35 的 `_active_sse_requests` 改为 `from app.core.sse_registry import all as get_active_sse`
3. chat.py:449 的 `from app.main import _active_sse_requests` 改为 `from app.core import sse_registry`
4. 验证：`pytest tests/test_chat_cancel.py -q`；grep 确认无 `from app.main import` 残留

**Step 3 — 抽 ChatPipeline（核心步骤）**
1. 新建 services/chat_pipeline.py，按 2.1 骨架迁移 `_run_sse_stream`、`_retrieve_and_rerank`、`_stream_llm_with_fallback`
2. primary/fallback 两个 token 循环合并为公共 `_stream_tokens()`（代码质量 P2-14）
3. chat.py 的 SSE 路由只保留：鉴权 → 参数校验 → 配额获取 → `StreamingResponse(pipeline.run_stream(...))` 装配
4. 内联 SQL 更新会话标题（chat.py:68-79）下沉到 chat_service
5. 验证：现有 `test_chat_api.py`、`test_chat_orchestrator.py`、`test_chat_cancel.py` **一个用例都不能改、必须全绿**（行为不变证明）

**Step 4 — 为 ChatPipeline 补窄单测**
1. 新建 `tests/test_chat_pipeline.py`：mock 注入的 retriever/reranker/model_router，验证编排顺序、事件序列、fallback 触发、取消路径
2. 目标覆盖率：chat_pipeline.py ≥ 80%

**Step 5 — 收尾清理**
1. chat.py 残留的无必要函数级 import 全部上提（架构 P1-3）
2. `get_session` 硬编码 page_size=100 改可配置（P2-13）
3. 泛型 Exception 改 `AllProvidersFailedError` 专用异常（P2-11）

## 2.3 风险点（重构红线）

| 红线 | 原因 |
|------|------|
| SSE 事件格式字节级不变 | 前端 isSSEEvent 白名单协议耦合；事件名/字段名一个都不能动 |
| 配额获取/释放时序不变 | Lua 原子计数 + `__aenter__` 间隙兜底是已验证的防泄漏闭环（代码亮点 #1），改动必须逐行对照 |
| 指标埋点一个不能丢 | TTFT、tokens/s、分阶段检索耗时——Grafana 面板依赖 |
| 限流装饰器保留在路由层 | slowapi limiter 依赖 Request 对象，不能随管线下沉 |
| 不引入新行为 | 本刀是 pure refactor；任何"顺手优化"另起提交 |

---

# 刀三：评估链路去重（架构 P0-2 + 代码 P1-6）

## 3.1 目标

消除 core↔services 双向依赖 + 双份实现漂移（temperature 0.3 vs 0.7、Ollama 硬编码 vs ModelFactory）。

## 3.2 步骤

1. **迁移**：`backend/app/core/evaluation.py`（414 行 RAGAS 引擎）→ `backend/app/services/evaluation_engine.py`，同步更新全部 import 引用（grep `core.evaluation` / `core\.evaluation` 全仓扫）
2. **下沉**：`get_rag_answer`（现 evaluation_service.py 顶部）→ `backend/app/rag/answer.py`（rag 层可被 services 依赖，方向合规）
3. **去重**：
   - 删除 `tasks/evaluation_task.py:248-271` 的 `_gen`/`_gen_with_sem`、`:283-303` 的 `_generate_ground_truth`
   - evaluation_task 改为调用 `services/evaluation_service.generate_dataset()`（公共实现）
   - provider 实例通过参数注入（task 传入 ModelFactory 创建的实例），禁止 task 内 `OllamaLLMProvider()` 硬编码
4. **对齐**：问题生成温度统一为 0.3（以 service 实现为准；如需区分场景，做成显式参数而非两处魔数）
5. **验证**：
   - `pytest tests/test_evaluation_task.py tests/test_evaluation_service.py tests/test_evaluation_concurrency.py tests/test_evaluation_api.py -q` 全绿
   - grep 验证无双向依赖：`grep -rn "from app.services" backend/app/core/ && echo FAIL`

## 3.3 风险

- RAGAS 评估对温度敏感：温度统一为 0.3 后，历史评估 run 的指标与新 run 不完全可比——在 CHANGELOG 注明
- `evaluation_task.py` 的 asyncio.to_thread 跨线程 Session（P2-22）顺手改为每步自建 session（小改动，纳入本刀）

---

# 刀四：工程质量加固

## 4.1 单一镜像双 command（容器层，30 分钟）

```yaml
# deploy/docker-compose.yml — celery_worker 服务修改
celery_worker:
  image: rag-platform-backend:latest   # 替代原 build: 块（整段删除）
  command: celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2 -Q queue_parsing,queue_evaluation,queue_default
  # ...其余 env/depends_on/volumes/healthcheck 不变
```

验证：`docker compose up -d celery_worker` 后 healthy；`docker compose build` 只构建一次 backend 镜像，两服务共用。

## 4.2 pytorch-cpu source（构建优化，1 小时）

1. `backend/pyproject.toml` 增加：

```toml
[[tool.poetry.source]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
priority = "explicit"
```

2. 显式声明 torch（在 `[tool.poetry.dependencies]`）：`torch = { version = "2.12.1+cpu", source = "pytorch-cpu" }`
3. 宿主机执行 `poetry lock --no-update` 重新生成 lock（用 poetry 虚拟环境或容器内 poetry，保持版本一致）
4. **删除** backend/Dockerfile:35-42 的 uninstall/重装块
5. 全量无缓存构建验证：`docker compose build --no-cache backend`，构建日志中**不得出现任何 nvidia-\* 包下载**
6. 容器内验证 reranker 可用：`docker exec rag-platform-backend-1 python -c "import torch; print(torch.__version__, torch.cuda.is_available())"` 期望 `2.12.1+cpu False`
7. 跑 reranker 相关测试：`pytest tests/test_reranker.py tests/test_reranker_fallback.py -q`

## 4.3 文档一致性修订（2 小时）

| 项 | 动作 |
|----|------|
| ADR-003 | 更新 rag/ 实际规模（500→1747 行）与 langchain wrapper 引入说明（RAGAS 专用） |
| ADR-004 | 补充前端实际用 fetch+ReadableStream 的原因（Authorization header 需求），非 EventSource |
| ADR-005 | 更新 BM25 实现（rank_bm25+jieba+Redis）与 alpha 加权融合的引入 |
| 覆盖率口径 | CONTRIBUTING.md "≥70%" 改为与 pyproject.toml 一致的 80%；README 82.08% 更新为实测值，或改为引用 pyproject 为唯一事实源 |
| README 架构图 | "Nginx + TLS + CSP" 改为 "Nginx 反向代理 + 安全响应头（CSP）"；或按 containerization-review P2-2 删除 HSTS 头 |
| nginx-exporter/node-exporter | README 可观测性章节注明 Docker Desktop WSL2 下监控对象为 VM（dashboard 标题建议改 "Docker VM (WSL2)"） |

## 4.4 CI/分层加固（1 小时）

1. `.github/workflows/backend-ci.yml:75-79`：删除 ruff check 的 skip fallback
2. 引入 import-linter（`backend/pyproject.toml` dev 依赖）：

```ini
# backend/pyproject.toml
[tool.importlinter]
root_package = "app"

[[tool.importlinter.contracts]]
name = "分层契约：api → services → db，core 不依赖 services"
type = "layers"
layers = ["app.api", "app.services", "app.db"]
containers = ["app"]

[[tool.importlinter.contracts]]
name = "core 禁止反向依赖 services"
type = "forbidden"
source_modules = ["app.core"]
forbidden_modules = ["app.services", "app.api"]
```

3. CI 增加一步：`poetry run lint-imports`
4. 验证：刀二、三完成后契约应直接通过；若不通过说明有残留反向依赖

## 4.5 测试体系加固（1 小时）

1. **flaky 追踪**：CI 单元测试步骤后增加 junitxml 重跑解析（pytest-rerunfailures 在 xml 中输出 `<rerun>` 标记），输出"靠重跑通过"清单为 warning annotation
2. `backend/pyproject.toml` coverage omit 移除 `app/main.py`（在刀二 main.py 瘦身之后执行）
3. `tests/test_auth_full_flow.py` 移到 `backend/scripts/`，conftest.py:38 的 collect_ignore 相应删除

---

# 刀五：秋招演示打磨

## 5.1 RAGAS 效果评估（2 小时）

```bash
# 前置：全栈运行 + 一个内容充实的知识库（建议上传 3-5 篇有问答价值的文档）
# 1. 通过 API 创建评估数据集（或使用现有种子数据集）
curl -X POST http://localhost:8000/api/v1/evaluation/datasets -H "Authorization: Bearer $TOKEN" -F file=@docs/review/../qa_seed_dataset.json
# 2. 发起评估 run
curl -X POST http://localhost:8000/api/v1/evaluation/runs -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"dataset_id": <id>, "kb_id": <kb_id>}'
# 3. 轮询结果
curl http://localhost:8000/api/v1/evaluation/runs/<run_id> -H "Authorization: Bearer $TOKEN"
```

- 报告解读：faithfulness / answer_relevancy / context_precision / context_recall 四项主指标
- 将结果（含数据集规模、模型版本、日期）写入 README"效果评估"小节与 docs/benchmark_report.md

## 5.2 面试问答预案（1 小时）

落盘 `docs/interview-prep.md`，内容大纲：
1. **六大可讲亮点**（三轮审查确认，每条含"是什么/为什么这么做/踩过的坑/代码位置"）：SSE 配额 Lua 闭环、幂等乐观锁矩阵、全链路降级、EventBus 解耦、conftest 防污染体系、配置中心化演进
2. **已知妥协点标准答案**：双 nginx（分层职责说辞）、bind mount（开发/交付形态区分说辞）、node-exporter VM 语义、HSTS/TLS 口径
3. **演示流程脚本**：启动预热（up -d + 模型已常驻显存）→ 建 KB → 传文档 → 问答（展示引用）→ Grafana 面板 → Jaeger trace → Flower 任务 → 评估报告
4. **兜底预案**：`docker save` 镜像 tarball 位置、常见问题快查（端口冲突改 .env、模型未拉取跑 make init-models）

## 5.3 最终交付检查

- `git log --oneline` 提交历史干净、Conventional 规范
- README 数字（测试数/覆盖率/效果指标）全部可复现
- `docs/review/` 五份报告 + runbook 作为工程证据链保留

---

## 附录：环境命令速查

| 用途 | 命令 |
|------|------|
| 后端测试 | `C:\Users\15116\AppData\Local\pypoetry\Cache\virtualenvs\rag-platform-backend-n1gY3d2C-py3.12\Scripts\python.exe -m pytest tests/ -q` |
| 前端测试 | `cd frontend && npx vitest run` |
| 全栈启停 | `cd deploy && docker compose up -d / down`（或根目录 `make up`） |
| 查看日志 | `docker compose -f deploy/docker-compose.yml logs -f backend celery_worker` |
| 构建镜像 | `docker compose -f deploy/docker-compose.yml build` |
| 数据库迁移 | `docker compose -f deploy/docker-compose.yml exec backend alembic upgrade head` |
