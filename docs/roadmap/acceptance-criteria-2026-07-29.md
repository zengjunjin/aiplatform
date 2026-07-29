# aiplatform 完善验收文档（Acceptance Criteria）

> 版本：v1.0｜日期：2026-07-29｜编制：齐活林（主理人）
> 配套：《执行文档》（execution-plan-2026-07-29.md）
> 使用方式：每刀执行完毕后，由**非执行者**（交叉验收）按本文档逐项验收；每项记录实测证据（命令输出/截图/链接），不得凭印象打勾。
> 验收总原则：**全部测试绿是前提，行为不变是底线，指标不劣化是红线。**

---

## 验收总闸（每刀必过，任何一刀不过则该刀不通过）

| 编号 | 验收项 | 验证方法 | 通过标准 |
|------|--------|---------|---------|
| G-1 | 后端测试全绿 | `backend/` 下 `pytest tests/ -m "not integration and not e2e and not real_rag" -n auto -q` | 0 failed；passed 数 ≥ 873 基线 |
| G-2 | 后端覆盖率不降级 | 同上命令带 `--cov=app --cov-report=term` | 总覆盖率 ≥ 82%（刀四后期望 ≥80% 为 fail_under 硬门槛） |
| G-3 | 前端测试全绿 | `frontend/` 下 `npx vitest run` | 0 failed |
| G-4 | 前端静态检查 | `npx eslint src/ && npx tsc --noEmit` | 0 error |
| G-5 | 全栈运行时健康 | `docker ps` + `curl -s http://localhost:8000/readyz` | 19 容器 Up（应 healthy 的全部 healthy）；readyz 返回 `{"status":"ready",...}` |

---

## 刀一验收：修复验证与提交

| 编号 | 验收项 | 验证方法 | 通过标准 | 验收记录 |
|------|--------|---------|---------|---------|
| 1-1 | 8 个修改文件均有测试覆盖验证 | 执行文档 1.3.1 四组定向测试命令 | 四组全部 passed，输出附后 | ☐ |
| 1-2 | SSE restart 事件前端处理生效 | 代码审查：`grep -n "restart" frontend/src/api/chat.ts frontend/src/store/chat.ts` | isSSEEvent 白名单含 restart；store 有清空 accContent 的分支 | ☐ |
| 1-3 | restart 新增测试用例存在且通过 | `npx vitest run -t "restart"` | ≥2 个相关用例通过（白名单 + 内容清空） | ☐ |
| 1-4 | [DONE] 不再从 finally 发出 | `grep -n -A5 "finally" backend/app/api/v1/chat.py` | finally 块内无 yield；正常结束分支有 yield [DONE] | ☐ |
| 1-5 | loguru %s 已修正 | `grep -rn "%s" backend/app/services/chat_service.py` | 0 命中 | ☐ |
| 1-6 | BM25 单次分词 | 读 bm25.py `rebuild`：_build 返回 tokenized 并被序列化复用 | 同一语料不再两次调用 _tokenize | ☐ |
| 1-7 | retriever 静默截断修复 | `grep -n "strict=True" backend/app/rag/retriever.py` | add_chunks 处命中 | ☐ |
| 1-8 | 上传 to_thread | `grep -n "to_thread" backend/app/services/document_service.py` | 上传路径命中 | ☐ |
| 1-9 | 评估双实现合并 | `grep -c "_generate_ground_truth" backend/app/tasks/evaluation_task.py backend/app/services/evaluation_service.py` | task 文件 0 处定义（仅调用）；温度/provider 一致 | ☐ |
| 1-10 | 提交规范 | `git log --oneline -5` | 2-4 个 Conventional Commits；无 amend/巨型提交；工作区 `git status` 干净 | ☐ |

**刀一手工 E2E 验证（必做）**：

| 编号 | 场景 | 操作 | 通过标准 | 验收记录 |
|------|------|------|---------|---------|
| 1-E1 | LLM fallback 文本正确 | 临时将 primary provider 指向无效地址，发起问答 | 前端显示内容无重复拼接（restart 后只显示 fallback 输出） | ☐ |
| 1-E2 | 上传不阻塞 | 上传 ~50MB PDF 的同时另开标签发起问答 | 问答 SSE 流正常开始，无等待感 | ☐ |
| 1-E3 | 断连无刷屏 | 问答中途关闭页面，`docker logs backend --since 1m` | 无 `async generator ignored GeneratorExit` RuntimeError | ☐ |

---

## 刀二验收：chat.py 拆分

| 编号 | 验收项 | 验证方法 | 通过标准 | 验收记录 |
|------|--------|---------|---------|---------|
| 2-1 | chat.py 瘦身达标 | `wc -l backend/app/api/v1/chat.py` | ≤ 250 行 | ☐ |
| 2-2 | 新文件就位 | `ls backend/app/services/chat_pipeline.py backend/app/api/v1/feedback.py backend/app/core/sse_registry.py` | 三文件存在 | ☐ |
| 2-3 | 循环依赖消除 | `grep -rn "from app.main import" backend/app/api/ backend/app/services/` | 0 命中 | ☐ |
| 2-4 | pipeline 框架无关 | `grep -n "fastapi\|starlette" backend/app/services/chat_pipeline.py` | 0 命中（Request/Response 不得入 service 层） | ☐ |
| 2-5 | 函数级延迟 import 清理 | `grep -n "^\s\+from app\.\|^\s\+import app\." backend/app/api/v1/chat.py` | ≤ 2 处（仅保留确有循环理由的） | ☐ |
| 2-6 | **行为不变证明**（本刀红线） | `pytest tests/test_chat_api.py tests/test_chat_orchestrator.py tests/test_chat_cancel.py tests/test_feedback_service.py -q` | 全部通过；且与重构前相比**用例零修改**（git diff tests/ 这些文件无改动） | ☐ |
| 2-7 | 新增 pipeline 窄单测 | `pytest tests/test_chat_pipeline.py --cov=app.services.chat_pipeline --cov-report=term -q` | 通过且该文件覆盖率 ≥ 80% | ☐ |
| 2-8 | feedback URL 不变 | `docker compose exec backend python -c "from app.main import app; print([r.path for r in app.routes if 'feedback' in r.path])"` | 与重构前路由清单逐一相同 | ☐ |
| 2-9 | main.py 同步瘦身 | `wc -l backend/app/main.py`；`grep -c "add_api_route\|@app.get\|@app.post" backend/app/main.py` | ≤ 380 行；端点定义减少（_active_sse_requests 已迁出） | ☐ |

**刀二手工 E2E 验证（必做）**：

| 编号 | 场景 | 操作 | 通过标准 | 验收记录 |
|------|------|------|---------|---------|
| 2-E1 | 完整问答流 | 前端发起带 KB 的问答 | SSE 事件序列完整：searching → delta×N → done；引用标注正常显示 | ☐ |
| 2-E2 | 取消生成 | 生成中点停止 | 流立即中断，后端日志出现 cancelled，配额释放（Redis 计数器回落，`docker exec rag-platform-redis-1 redis-cli keys "*sse*"`） | ☐ |
| 2-E3 | 反馈闭环 | 对回答点踩 → 管理端查看低分反馈列表 | 数据正常返回且走 schema 序列化（响应结构与 FeedbackDetailOut 一致） | ☐ |
| 2-E4 | 性能不劣化 | 连续 3 次问答，对比 Grafana TTFT / tokens-per-sec 面板 | TTFT 波动在重构前基线 ±15% 以内 | ☐ |

---

## 刀三验收：评估链路去重

| 编号 | 验收项 | 验证方法 | 通过标准 | 验收记录 |
|------|--------|---------|---------|---------|
| 3-1 | core/evaluation.py 已迁出 | `ls backend/app/core/evaluation.py 2>&1`；`ls backend/app/services/evaluation_engine.py` | 前者不存在；后者存在 | ☐ |
| 3-2 | 双向依赖消除 | `grep -rn "from app.services\|import app.services" backend/app/core/` | 0 命中（core 不依赖 services） | ☐ |
| 3-3 | get_rag_answer 下沉 | `grep -rn "def get_rag_answer" backend/app/` | 仅在 rag/answer.py 一处定义 | ☐ |
| 3-4 | 重复实现删除 | `grep -c "_gen_with_sem\|_generate_ground_truth" backend/app/tasks/evaluation_task.py` | 0 处定义 | ☐ |
| 3-5 | provider 硬编码消除 | `grep -n "OllamaLLMProvider()" backend/app/tasks/evaluation_task.py` | 0 命中 | ☐ |
| 3-6 | 温度一致 | 对比 task 与 service 中问题生成的 temperature | 均为 0.3（或同一显式参数） | ☐ |
| 3-7 | 评估测试全绿 | `pytest tests/test_evaluation_task.py tests/test_evaluation_service.py tests/test_evaluation_concurrency.py tests/test_evaluation_api.py -q` | 全部通过 | ☐ |
| 3-8 | CHANGELOG 注明温度对齐 | `grep -n -i "temperature\|评估" CHANGELOG.md | head -3` | 有记录 | ☐ |

**刀三手工验证**：

| 编号 | 场景 | 操作 | 通过标准 | 验收记录 |
|------|------|------|---------|---------|
| 3-E1 | 数据集生成端到端 | 对测试 KB 发起数据集生成（API 或 Flower 触发） | Celery 任务成功完成；生成条目非空且 ground_truth 字段完整 | ☐ |

---

## 刀四验收：工程质量加固

| 编号 | 验收项 | 验证方法 | 通过标准 | 验收记录 |
|------|--------|---------|---------|---------|
| 4-1 | 单一镜像双 command | `grep -n "image: rag-platform-backend" deploy/docker-compose.yml`；`grep -c "build:" deploy/docker-compose.yml` | celery_worker 用 image；build 块仅剩 backend 与 webhook 两处 | ☐ |
| 4-2 | 镜像共用生效 | `docker images \| grep rag-platform` | backend 与 celery_worker 同 SIZE（同一镜像 ID） | ☐ |
| 4-3 | torch CPU 化 | `docker exec rag-platform-backend-1 python -c "import torch;print(torch.__version__, torch.cuda.is_available())"` | 输出 `2.12.1+cpu False` | ☐ |
| 4-4 | 无 CUDA 残留 | `docker run --rm --entrypoint sh rag-platform-backend:latest -c "ls /app/.venv/lib/python3.12/site-packages \| grep -i nvidia \| wc -l"` | 0 | ☐ |
| 4-5 | 全量构建无 CUDA 下载 | `docker compose build --no-cache backend 2>&1 \| grep -ci "nvidia"` | 0（构建日志无 nvidia 包） | ☐ |
| 4-6 | reranker 功能正常 | `pytest tests/test_reranker.py tests/test_reranker_fallback.py -q` + 手工问答观察检索结果排序 | 测试通过；问答引用排序合理 | ☐ |
| 4-7 | ADR 修订完成 | 逐条读 docs/adr/003、004、005 | 描述与当前代码一致（rag 行数、fetch 流式、rank_bm25+alpha 融合） | ☐ |
| 4-8 | 覆盖率口径统一 | `grep -n "70\|80" CONTRIBUTING.md backend/pyproject.toml README.md \| grep -i "cov\|覆盖"` | 三处一致（80%） | ☐ |
| 4-9 | ruff fallback 删除 | `grep -n -A3 "Ruff not configured" .github/workflows/backend-ci.yml` | 0 命中 | ☐ |
| 4-10 | import-linter 契约通过 | `cd backend && poetry run lint-imports` | 2 个契约全部 KEPT | ☐ |
| 4-11 | main.py 移出 omit | `grep -n "omit" backend/pyproject.toml` | omit 中无 app/main.py；`pytest --cov` 后 fail_under=80 仍通过 | ☐ |
| 4-12 | test_auth_full_flow.py 已迁移 | `ls backend/scripts/test_auth_full_flow.py`；`grep -n "collect_ignore" backend/tests/conftest.py` | 文件在 scripts/；collect_ignore 已清理 | ☐ |
| 4-13 | flaky 追踪上线 | 查看最近一次 CI 运行日志 | 含"靠重跑通过"统计输出（或为 0 的明确说明） | ☐ |

---

## 刀五验收：秋招演示打磨

| 编号 | 验收项 | 验证方法 | 通过标准 | 验收记录 |
|------|--------|---------|---------|---------|
| 5-1 | RAGAS 评估完成 | `curl http://localhost:8000/api/v1/evaluation/runs/<id>` | status=completed；四项主指标有值 | ☐ |
| 5-2 | 效果数据入文档 | README / docs/benchmark_report.md | 含数据集规模、模型版本、日期、四项指标；数字与 run 结果一致 | ☐ |
| 5-3 | 面试问答预案 | `ls docs/interview-prep.md` | 覆盖：6 亮点（含代码位置）、全部已知妥协点口径、演示流程脚本、兜底预案 | ☐ |
| 5-4 | 演示彩排 | 按预案脚本完整走一遍（建 KB→上传→问答→监控→评估） | 全程无报错、无卡顿；每步有预期画面 | ☐ |
| 5-5 | 离线兜底 | `ls` 镜像 tarball 存放位置 | rag-platform 镜像 tarball 存在且 ≤7 天新鲜度 | ☐ |
| 5-6 | 提交历史整洁 | `git log --oneline -15` | 全部 Conventional 规范；无 WIP/fixup 提交 | ☐ |

---

## 最终签署

| 角色 | 结论 | 签名 | 日期 |
|------|------|------|------|
| 执行者自验 | ☐ 通过 / ☐ 不通过（附原因） | | |
| 交叉验收 | ☐ 通过 / ☐ 不通过（附原因） | | |

**未通过处理**：任一验收项不过 → 回到执行文档对应刀的步骤修复后重验；总闸（G-1~G-5）任何一项不过 → 当刀全部验收项视为不通过。
