# 贡献指南

感谢你对 RAG 知识库问答平台的关注！本文档说明如何向本项目提交贡献。

## 仓库与协作流程

1. Fork 仓库 [zengjunjin/aiplatform](https://github.com/zengjunjin/aiplatform)
2. 在 fork 中创建特性分支：`git checkout -b feat/your-feature`
3. 完成开发并自测（后端 `pytest --cov`、前端 `npm run build && npx vitest run`）
4. 提交（参见下方 [Commit 规范](#commit-规范)）
5. 推送分支并创建 Pull Request 到 `main` 分支
6. CI 全绿后等待 reviewer 评审

## Commit 规范

采用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/)：

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type

| type       | 说明                                                        |
|------------|-------------------------------------------------------------|
| `feat`     | 新功能                                                       |
| `fix`      | bug 修复                                                    |
| `refactor` | 重构（不改变外部行为）                                       |
| `perf`     | 性能优化                                                    |
| `docs`     | 文档变更                                                    |
| `test`     | 新增/修改测试                                               |
| `chore`    | 构建/工具/依赖等杂项                                         |
| `ci`       | CI 配置变更                                                 |
| `revert`   | 回滚之前的 commit                                           |

### Scope（可选）

后端：`api`/`rag`/`services`/`tasks`/`core`/`db`/`schemas`/`models`/`parsers`/`config`
前端：`pages`/`components`/`store`/`api`/`i18n`/`styles`/`utils`
基础设施：`deploy`/`docker`/`tauri`/`github`

### 示例

```
feat(rag): add BM25 async lock to prevent concurrent index rebuild

- Replace threading.Lock with asyncio.Lock in async paths
- Preserve threading.Lock for Celery sync API
- Add tests/test_bm25.py::test_async_lock_singleflight
```

```
fix(api): correct get_kb_for_read parameter order in evaluation.py

BREAKING CHANGE: evaluation.py:34 now uses get_kb_for_read(kb_id, user_id, db)
```

## Pull Request 流程

1. **标题**：与 commit 规范一致，例如 `feat(rag): add BM25 async lock`
2. **描述**：
   - 关联 issue（如 `Closes #123`）
   - 改动摘要（What & Why）
   - 测试方式（如何验证）
   - Breaking Changes（如有）
3. **检查清单**：
   - [ ] 后端测试通过：`cd backend && poetry run pytest -m "not integration and not e2e and not real_rag" --cov`
   - [ ] 前端构建无错：`cd frontend && npm run build`
   - [ ] 前端测试通过：`cd frontend && npx vitest run`
   - [ ] 新增代码有对应测试
   - [ ] 不提交 `.env` / 密钥 / `storage/` / `__pycache__/`
4. **Review**：至少 1 名 reviewer 批准后合并（squash merge 优先）

## Coverage 门槛

| 模块   | 项                                | 阈值 |
|--------|-----------------------------------|------|
| 后端   | `pyproject.toml` `fail_under`     | 70%  |
| 前端   | `vitest.config.ts` lines/statements/functions | 70%  |
| 前端   | `vitest.config.ts` branches       | 60%  |

CI 中 `backend-ci.yml` 与 `frontend-ci.yml` 会自动检查覆盖率，未达标 PR 会被标红。

## 测试约定

- **后端单元测试**：`backend/tests/test_*.py`，不依赖外部服务（用 `pytest-asyncio` + `httpx.AsyncClient`）
- **集成测试**：`backend/tests/integration/`，需要真实 PostgreSQL/Redis/Qdrant
- **E2E 测试**：`backend/tests/e2e/`，需要完整后端 + 可选 Tauri CDP
- **前端测试**：`frontend/src/__tests__/*.test.tsx`，使用 Vitest + Testing Library + jsdom

### 标记策略

- `@pytest.mark.integration`：需要真实服务
- `@pytest.mark.real_rag`：需要真实 Ollama + Qdrant
- `@pytest.mark.e2e`：端到端测试
- `@pytest.mark.slow`：耗时较长的测试

CI 默认只跑单元测试（`-m "not integration and not e2e and not real_rag"`）。

## 代码风格

### 后端

- Python 3.12+，使用 type hints
- `ruff check` + `ruff format` 格式化
- 行宽 100 字符
- Pydantic v2 输入 schema 必须使用 `model_config = ConfigDict(extra='forbid')`

### 前端

- TypeScript strict mode（`tsconfig.json` 启用 `noUnusedLocals`/`noUnusedParameters`/`noImplicitReturns`）
- React 18 + 函数组件 + Hooks
- Ant Design 5 + lucide-react 图标
- `catch` 块使用 `catch (e: unknown)` + `getErrorMessage(e)` helper
- 表格 columns 用 `useMemo`，避免每次 render 重建

## 安全约束

- 永远不要在代码或日志中硬编码密钥（`JWT_SECRET`/`POSTGRES_PASSWORD`/`METRICS_TOKEN` 等）
- 永远不要提交 `.env` 文件（`.gitignore` 已排除）
- JWT Token 不要持久化在前端 `localStorage`（仅 `refreshToken`）
- 前端 MarkdownRenderer 必须使用 `urlTransform` 白名单（block `javascript:`/`data:`/`vbscript:`）
- 用户输入必须经过 Pydantic schema 校验（`extra='forbid'`）

## 项目记忆

本项目使用 `c:\Users\15116\.trae-cn\memory\projects\-c-Users-15116-Desktop-aiplatform\project_memory.md` 记录 Hard Constraints 与 Lessons Learned。重要约束（如 API 签名、已删除的死代码、并发模型）必须在 `project_memory.md` 中记录，避免后续 PR 误改。
