# 测试与工程化审查报告 — aiplatform（RAG 知识库问答平台）

> 审查人：严过关（Yan）· QA 工程师（本次由主理人代位执行，因 QA 子代理类型在运行环境不可用且平台限流）
> 审查方式：抽查后端 6 个测试文件精读 + 前端 2 个测试文件精读 + 全量统计 grep + CI workflow 逐行审读 + **实际运行测试验证**。安全项按要求忽略。

## 总体评价

测试体系是这个项目最硬的实力之一：**1574 个后端测试函数 + 692 个前端测试用例**，断言精确到公式级（RRF 分数验证到 `pytest.approx(1/61)`），conftest.py 有一套自觉的防污染体系（autouse 重置限流计数器与单例、修复记录进注释），CI 真跑覆盖率门槛且单元/集成分批。未发现走过场式测试与覆盖率造假。主要扣分项：`reruns=2` 自动重跑可能掩盖 flaky 测试、lint 关卡存在可绕过的 fallback、覆盖率 omit 了最需要关注的 main.py。**测试体系评分：8.5/10**。

## 可运行性验证结果（实测）

| 命令 | 结果 |
|------|------|
| 后端 `pytest tests/test_bm25.py tests/test_reference_parser.py tests/test_chunker.py`（poetry 环境 Python 3.12） | ✅ **57 passed in 1.08s** |
| 前端 `npx vitest run src/hooks/useApiToast.test.ts` | ✅ **12 passed in 4.24s**（vitest 4.1.9） |

环境备注：系统 Python 3.13 无 pytest；项目 poetry 虚拟环境（`rag-platform-backend-n1gY3d2C-py3.12`）可用。前端 vitest 对不存在的文件路径静默忽略（传了 2 个文件只跑 1 个，无报错），CI 全量跑无此问题。

## 问题清单

### P1 — 明显质量问题（4 条）

**1. `reruns=2` 自动重跑掩盖 flaky 测试，且无追踪机制**
- 位置：`backend/tests/conftest.py:58-66`（pytest_configure 条件注入 `reruns=2, reruns_delay=3`）
- 问题：任何 flaky 测试失败后会自动重跑至多 2 次，最终报告只显示 passed。README 宣称的 "873 passed / 0 failed" 可能包含靠重跑通过的测试，但没有任何机制识别"哪些测试是靠重跑才过的"。flaky 测试是测试体系最大的隐性债务。
- 建议：CI 增加重跑统计（pytest-rerunfailures 输出解析或 junitxml 中 `<rerun>` 标记提取），将"重跑后通过"的测试列入 flaky 清单逐步修复；至少在接受报告中披露重跑次数。

**2. Ruff lint 关卡存在静默绕过 fallback**
- 位置：`.github/workflows/backend-ci.yml:75-79`（`if poetry run ruff --version 2>/dev/null; then ... else echo "Ruff not configured, skipping lint check"`）
- 问题：ruff 未安装时 lint 步骤跳过而非失败；而同文件 82 行的 `ruff format --check` 无 fallback 必跑——两个 lint 关卡行为不一致。
- 建议：删除 fallback（ruff 本就在 dev 依赖中），或改为显式失败。

**3. 覆盖率 omit `app/main.py`（453 行组合根）**
- 位置：`backend/pyproject.toml` `[tool.coverage.run] omit = ["app/main.py", "*/__init__.py"]`
- 问题：main.py 恰是架构评审指出的"组合根过载"文件（6 个端点 + lifespan），最需要测试雷达覆盖，却被排除出统计，fail_under=80 的分母因此缩小约 2.5%。属于轻微注水，且与架构改进方向相悖。
- 建议：main.py 拆分（端点迁 api 层）后移出 omit；拆分前可先移出 omit 让真实覆盖率可见。

**4. 文档与实际覆盖率门槛三处不一致**
- 位置：`CONTRIBUTING.md`（"后端 ≥ 70%"）vs `backend/pyproject.toml`（`fail_under = 80`，注释称实测 83%）vs `README.md`（"后端总覆盖率 82.08%"、前端 466 passed vs 实测 692 个 it/test 用例）
- 问题：数字各自滞后于演进，秋招面试中被追问"到底哪个准"会失分。
- 建议：以 pyproject.toml 为唯一事实源，README/CONTRIBUTING 引用而非复制数字，或在 CI 中自动生成徽章。

### P2 — 改进建议（4 条）

5. `backend/tests/test_auth_full_flow.py` 是独立脚本（模块顶层 requests + sys.exit），靠 `conftest.py:38 collect_ignore` 排除收集——应移至 `scripts/` 目录而非混在测试目录。
6. `tests/e2e/test_11~14_cdp_*.py`（CDP 浏览器测试）与单测同处 tests/ 树，依赖外部浏览器环境；CI 用 `-m "not e2e"` 隔离，但本地直接 `pytest tests/` 全量跑时依赖 e2e/conftest.py 的环境守卫，建议给 CDP 测试加显式 marker + 环境检测 skip。
7. CI 单元测试批次 `-m "not integration and not e2e and not real_rag"`（backend-ci.yml:240）与集成批次 `-m "integration"`（:423）之外，`real_rag`/`e2e`/`slow` marker 的测试在常规 CI 中无批次覆盖（仅 full-ci 全量），建议 README 说明各 marker 的执行入口。
8. 前端 `src/store/` 的测试集中在 `__tests__/store/`（仅 2 个文件），而 store/chat.ts（497 行，核心流式逻辑）的测试密度与后端相比较薄，建议补强流式节流与 restart 事件（见代码质量报告 P0-1）的用例。

## 测试体系亮点（秋招视角）

1. **断言精确到公式级**：`test_retriever.py` 验证 RRF 分数 `pytest.approx(1/61, rel=1e-6)`、自定义 k=100 → 1/101、双路叠加分数；`test_bm25.py` 验证分数降序、top_k 边界（0/超限）、CJK/混合分词——是真算法测试，不是冒烟。
2. **conftest.py 防污染体系（336 行）**：autouse fixture 每个测试重置 slowapi 限流计数器与 ModelFactory 单例缓存；`pytest_configure` 预导入 retriever 防止他文件的 sys.modules stub 污染（v0.4.0 修复，注释留痕）；全局 mock 掉 sentence_transformers 避免 CI 触发 1.1GB HuggingFace 下载；pyarrow/ragas 兼容性 patch 集中管理。
3. **factory fixture 消重**：`make_user`/`make_db`/`make_auth_db` 替代各文件内联 `_make_*`，`mock_sse_common` 抽取 12+ 处重复 patch——测试代码本身也讲 DRY。
4. **服务层分支清单式 docstring**：`test_document_service.py` 文件头列出 20+ 覆盖分支（权限/超限/路径穿越/hash 冲突/IntegrityError 二次提交/清理分支），可对照源码核验。
5. **CI 工程化完整**：Poetry/pip 双层缓存、concurrency 取消冗余运行、postgres/redis 服务容器带健康检查、单元/集成分批（`-n auto` 并行、集成批 `--dist=loadscope`）、失败时从 junitxml 自动提取失败测试名、SBOM 生成 + GPL/AGPL license 白名单（真失败）、覆盖率门槛真执行（`--cov=app` + `fail_under=80`）。
6. **e2e 真实全链路**：`test_03_kb_e2e.py` 真实 HTTP 请求、断言带失败上下文消息（`f"Create KB failed: {r.text}"`）、每个用例自清理；e2e 编号自增约定（test_01~14）写入 CONTRIBUTING。
7. **前端 hook 测试有深度**：`useApiToast.test.ts` 用 `vi.hoisted` 保证 mock 引用稳定（避免 useCallback 依赖无限重建），docstring 声明分支覆盖目标（成功/失败/||回退/axios 400-500/网络/超时）。
8. **pytest-timeout=60 全局防挂死** + markers 分层（integration/real_rag/e2e/slow）声明式管理。

## TOP 5 优先改进项

1. **建立 flaky 追踪**：解析 junitxml 重跑标记，CI 输出"靠重跑通过"的测试清单（对应 P1-1）——保护 "873 passed" 这块招牌的含金量。
2. **删除 ruff check 的 skip fallback**（backend-ci.yml:75-79），两个 lint 关卡行为对齐（P1-2）。
3. **main.py 拆分后移出 coverage omit**（与架构评审 P1-2 联动），让覆盖率统计无盲区（P1-3）。
4. **统一三处覆盖率/测试数口径**（CONTRIBUTING/README/pyproject），以 pyproject 为唯一事实源（P1-4）。
5. **补强 store/chat.ts 流式逻辑测试**：restart 事件处理（待前端修复后）、100ms/16token 节流、HMR dispose（P2-8，与代码质量报告 P0-1 联动）。
