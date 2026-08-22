# 深度审查总报告 — aiplatform（RAG 知识库问答平台）

> 审查团队：高见远（架构）· 寇豆码（代码质量）· 严过关（测试质量，主理人代位）｜汇编：齐活林（主理人）
> 日期：2026-07-29｜范围：全栈深度审查，**安全维度按需求排除**
> 分报告：[architecture-review.md](./architecture-review.md)｜[code-quality-review.md](./code-quality-review.md)｜[test-quality-review.md](./test-quality-review.md)

## 一、综合结论

**综合评分：7.5 / 10**（架构 7.0｜代码质量 7.0｜测试体系 8.5）

这是**显著高于一般秋招项目水准**的代码库：分层骨架成立、EventBus 解耦、Provider 降级闭环、幂等乐观锁、真可观测性、1574+692 个真实测试、8 个 CI workflow。作为面试展示项目，底子非常硬。

核心短板高度集中在两个问题域：

1. **SSE 聊天链路是全项目最大的"问题盆地"**——三个维度的最重要发现都指向它
2. **评估链路双份实现已发生行为漂移**——架构错位 + 代码重复互相印证

外加一个秋招场景下的现实风险：**仓库卫生**（40+ 调试残留文件、23GB 运行产物），打包提交前必须处理。

## 二、交叉印证发现（多维度指向同一问题域 = 最高优先级）

### 问题域 A：SSE 聊天链路（chat.py 及其周边）

| 来源 | 发现 | 级别 |
|------|------|------|
| 架构 P0-1 | SSE 编排管线 869 行全写在 API 路由层，`chat_service` 被架空（仅剩 CRUD） | 架构缺陷 |
| 代码 P0-1 | 后端发 `restart` 事件，前端白名单不含它 → **fallback 时聊天文本拼接错乱（真 Bug）** | 功能 Bug |
| 架构 P0-3 | `chat.py` 反向 `from app.main import _active_sse_requests` → api↔main 循环依赖 | 架构缺陷 |
| 代码 P1-3 | `finally` 中 `yield [DONE]` → 客户端断连时 RuntimeError 刷屏 | 错误处理 |
| 架构 P1-1 | feedback 5 个端点寄生在 chat.py（L755-868） | 职责混乱 |
| 测试 P2-8 | store/chat.ts 流式逻辑测试密度偏薄 | 测试盲区 |

**一次重构可解决大半**：抽 `services/chat_pipeline.py` 承载编排 + 拆 `api/v1/feedback.py` + 建 `core/sse_registry.py` + 前端补 restart 处理 + [DONE] 挪出 finally。

### 问题域 B：评估链路（evaluation 双实现）

| 来源 | 发现 | 级别 |
|------|------|------|
| 架构 P0-2 | `core/evaluation.py` 错位于 core 层，造成 core↔services 双向依赖 | 架构缺陷 |
| 代码 P1-6 | 数据集生成**双份实现**：task 走硬编码 OllamaProvider/temp=0.7，service 走 ModelFactory/temp=0.3，`_generate_ground_truth` 逐字重复 | 行为漂移 |

**修法**：core/evaluation.py 迁 services/，公共 `generate_dataset()` 单一实现，Celery 任务调用它。

### 问题域 C：仓库卫生（三维度 + 主理人侦察四方印证）

- 根目录：11 个 `step*.js` CDP 调试脚本、9 个日志/报告文件、`qdrant.exe` 二进制
- `backend/`：`_debug_chunker.py`、15+ 个 `.log`、`coverage.xml`、`pytest-results.xml`
- `deploy/`：20+ 个未追踪调试残留（cdp_test.mjs、截图目录、test_admin.json）
- 工作目录运行产物 **23GB+**（storage/ 20GB、qdrant_storage/ 2.4GB、qdrant_data/ 737MB）——秋招打包/克隆前必须清理
- 存在未提交修改：`chunker.py` + `test_chunker.py`（M 状态）

## 三、其余关键发现速览

**P0 级 Bug（除问题域 A/B 外）**
- 代码 P0-2：`save_upload_file` 在 async 链路中同步读写文件（storage.py:97-111），上传期间事件循环全局阻塞 → 包 `asyncio.to_thread`

**值得知道的 P1（按主题归并）**
- BM25：增删文档全量重建 + 分词执行两遍（bm25.py:132-150）；Redis 连接重置不关闭泄漏（:111-117）
- `retriever.add_chunks` 静默截断：vectors 不足时 chunk 丢失无告警（retriever.py:412）→ `zip(strict=True)`
- 检索延迟指标失真：vector/bm25 两路计时的都是 gather 总时长（retriever.py:137-146）
- loguru 误用 `%s` 占位符，异常信息丢失（chat_service.py:110，全仓建议 grep 同类）
- Celery"每任务新建 event loop + 重置单例连接"反模式（document_task.py:214-223 等 4 处）
- 测试：`reruns=2` 掩盖 flaky 无追踪；ruff check 有 skip fallback；main.py 被 omit 出覆盖率
- 文档漂移：ADR-003/004/005 与实现不符；覆盖率口径三处不一致（70%/80%/82%）

## 四、统一行动清单（按投入产出比排序）

| # | 行动 | 解决 | 预估改动 |
|---|------|------|---------|
| 1 | 前端补 `restart` SSE 事件处理（api/chat.ts 白名单 + store 清空 accContent） | 代码 P0-1 | <20 行 |
| 2 | `save_upload_file` 包 `asyncio.to_thread` | 代码 P0-2 | <5 行 |
| 3 | **仓库大扫除**：删 step*.js/日志/调试残留，qdrant.exe 移出仓库，gitignore 补 storage/qdrant_*/snapshots，打包前清 23GB 产物 | 问题域 C | 半天 |
| 4 | 抽 `services/chat_pipeline.py` + 拆 `api/v1/feedback.py` + 建 `core/sse_registry.py` + [DONE] 挪出 finally | 问题域 A（4 项） | 1-2 天 |
| 5 | 评估链路去重：core/evaluation.py 迁 services/ + 单一 generate_dataset（温度/provider 对齐） | 问题域 B | 半天 |
| 6 | BM25 分词去重（_build 复用 tokenized）+ retriever `zip(strict=True)` | 代码 P1-4/8 | <30 行 |
| 7 | loguru `%s` 全仓排查修正 + 检索分阶段计时修正 | 代码 P1-9/10 | <20 行 |
| 8 | 修订 ADR-003/004/005（或补 ADR-011 记录漂移）+ 统一覆盖率口径 | 文档一致性 | 2 小时 |
| 9 | 测试加固：flaky 重跑追踪、ruff fallback 删除、main.py 移出 omit | 测试 P1 | 半天 |
| 10 | import-linter 固化 api→services→db 契约 + 清理无必要延迟 import | 架构防腐 | 半天 |

## 五、秋招面试叙事建议

审查确认的**可讲亮点**（经得起追问）：
1. SSE 并发配额 Lua 原子计数 + 间隙兜底（连接泄漏考点的完整答案）
2. 幂等设计贯穿任务层（乐观锁抢占消 TOCTOU、唯一约束+重试转更新）
3. 全链路降级矩阵（Redis/LLM/Reranker/BM25 各有 fallback）
4. conftest.py 防污染体系（autouse 重置、stub 污染修复留痕）——测试工程意识的直接证据
5. EventBus 解耦服务循环依赖（有注释自证动因）
6. 配置中心化重构痕迹（config.py "Task XX" 注释）+ 10 篇 ADR——工程演进的叙事素材

**面试前务必先修**：#1-#3（行动清单），否则演示中 LLM 降级时会当众表演"文本错乱"，打包时 23GB 产物会当众尴尬。
