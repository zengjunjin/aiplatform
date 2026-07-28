# RAG 平台 P1 级问题审计报告

> 版本：v0.4.0
> 日期：2026-07-28
> 状态：待修复
> 审计范围：API 契约 + 后端资源 + 前端状态 + 配置规范
> P0 已修复：7/7 ✅

---

## 问题汇总（42 项）

| 模块 | 数量 | ID 范围 |
|------|------|---------|
| API 契约一致性 | 10 | P1-API-01 ~ P1-API-10 |
| 后端资源管理 | 10 | P1-BE-01 ~ P1-BE-10 |
| 前端状态管理 | 12 | P1-FE-01 ~ P1-FE-12 |
| 配置规范化 | 10 | P1-CFG-01 ~ P1-CFG-10 |

---

## 模块 1: API 契约一致性（10 项）

### P1-API-01: getMessages 返回类型与后端分页结构不匹配
- **前端**: frontend/src/api/chat.ts:55-60
- **后端**: backend/app/api/v1/chat.py:656-668
- **问题**: 前端声明返回 `Message[]`，后端返回分页对象 `{items, total, page, page_size, total_pages}`
- **修复**: 改为 `Promise<PaginatedResponse<Message>>`

### P1-API-02: triggerEvaluation 响应字段名 run_id vs id
- **前端**: frontend/src/api/evaluation.ts:31-36
- **后端**: backend/app/api/v1/evaluation.py:34-42
- **问题**: 后端返回 `run_id`，前端类型期望 `id`
- **修复**: 前端类型改用 `run_id`

### P1-API-03: SystemStatus 字段名 postgres vs postgresql
- **前端**: frontend/src/api/system.ts:3-10
- **后端**: backend/app/api/v1/system.py:41-91
- **问题**: 后端返回 `postgresql`，前端读 `postgres`；前端有幽灵 `status` 字段
- **修复**: 前端改为 `postgresql`，移除 `status`

### P1-API-04: ModelInfo 重复定义且缺少 source 字段
- **前端**: frontend/src/types/index.ts:163-167 + frontend/src/api/system.ts:12-17
- **后端**: backend/app/api/v1/system.py:108-115
- **问题**: 两个 ModelInfo 定义，types/index.ts 版本缺 source 字段
- **修复**: 删除 types/index.ts 中的定义，统一从 system.ts 导出

### P1-API-05: User 类型期望 created_at/updated_at 但后端不返回
- **前端**: frontend/src/types/index.ts:1-9
- **后端**: backend/app/schemas/auth.py:46-53
- **问题**: 前端必填，后端不返回
- **修复**: 改为可选 `created_at?: string`

### P1-API-06: Document 类型期望 file_path 但后端不返回
- **前端**: frontend/src/types/index.ts:34-48
- **后端**: backend/app/schemas/document.py:6-20
- **问题**: 前端必填 file_path，后端不返回（安全考虑）
- **修复**: 移除 file_path 字段

### P1-API-07: reparse 前端发送 force 参数但后端不接受
- **前端**: frontend/src/api/documents.ts:75-80
- **后端**: backend/app/api/v1/documents.py:102-113
- **问题**: FastAPI 静默忽略未声明查询参数
- **修复**: 后端添加 force 参数 或 前端移除

### P1-API-08: 用户列表 keyword 参数前端可传但后端不接受
- **前端**: frontend/src/api/users.ts:6-10
- **后端**: backend/app/api/v1/users.py:30-41
- **问题**: FastAPI 静默忽略 keyword
- **修复**: 后端添加搜索 或 前端移除 keyword

### P1-API-09: KnowledgeBase.description 类型 string vs str | None
- **前端**: frontend/src/types/index.ts:11-21
- **后端**: backend/app/schemas/kb.py:33-42
- **问题**: 后端可为 None，前端断言为 string
- **修复**: 前端改为 `string | null`

### P1-API-10: PaginatedResponse 缺少 total_pages 字段
- **前端**: frontend/src/types/index.ts:100-105
- **后端**: backend/app/schemas/common.py:14-19
- **问题**: 共享类型缺 total_pages，其他模块各自绕过
- **修复**: 添加 total_pages 字段

---

## 模块 2: 后端资源管理（10 项）

### P1-BE-01: warmup_llm 和 warmup_reranker 孤儿任务未跟踪
- **文件**: backend/app/main.py:172, 188
- **问题**: asyncio.create_task 未保存引用，shutdown 时未取消
- **修复**: 保存 task 引用，finally 块取消

### P1-BE-02: CachedEmbeddingProvider 缺少 reset_connection 方法 ⚠️ 高优先级
- **文件**: backend/app/models/cached_embedding.py
- **问题**: document_task.py:187 的 hasattr 检查始终 False，embedding 缓存在 Celery 中完全失效
- **修复**: 添加 reset_connection 方法

### P1-BE-03: CachedEmbeddingProvider 缺少 close 方法
- **文件**: backend/app/models/cached_embedding.py
- **问题**: Redis 连接泄漏
- **修复**: 覆盖 close 方法

### P1-BE-04: _warmup_llm 中 ModelRouter.release 在异常路径未调用
- **文件**: backend/app/main.py:155-170
- **问题**: least_busy 计数器永久 +1，路由策略失效
- **修复**: 使用 try/finally

### P1-BE-05: document_task.py 中 publish 事件的新事件循环未关闭
- **文件**: backend/app/tasks/document_task.py:327-360
- **问题**: 新创建的 loop 未关闭，内存泄漏
- **修复**: try/finally 确保 loop.close()

### P1-BE-06: HybridRetriever 的 QdrantClient 未关闭
- **文件**: backend/app/rag/retriever.py:73-79
- **问题**: HTTP 连接池泄漏
- **修复**: 添加 close 方法，main.py shutdown 调用

### P1-BE-07: BM25Store 的 Redis 连接未在 shutdown 时关闭
- **文件**: backend/app/rag/bm25.py
- **问题**: sync + async Redis 连接泄漏
- **修复**: 添加 close 方法

### P1-BE-08: EventBus._listen 中 handler 无超时保护 ⚠️ 高优先级
- **文件**: backend/app/core/events.py:103-107
- **问题**: 单个慢 handler 阻塞整个事件总线
- **修复**: asyncio.wait_for(handler(payload), timeout=30.0)

### P1-BE-09: Celery worker 中 EventBus 绑定到错误循环 ⚠️ 高优先级
- **文件**: backend/app/tasks/celery_app.py:87-96
- **问题**: listener task 绑定到 init loop，publish 在另一个 loop，事件订阅失效
- **修复**: 确保 EventBus 跨循环工作或用同步 Redis publish fallback

### P1-BE-10: document_task.py _update_progress 中 Redis 写入在 session close 之后
- **文件**: backend/app/tasks/document_task.py:43-76
- **问题**: DB 与 Redis 状态可能不一致
- **修复**: Redis 写入移到 try 块内

---

## 模块 3: 前端状态管理（12 项）

### P1-FE-01: chat store 字典无限增长（内存泄漏） ⚠️ 高优先级
- **文件**: frontend/src/store/chat.ts:53-55, 77-105, 146-177
- **问题**: messagesById/messageOrder/feedbackByMessageId 无限增长
- **修复**: LRU 策略限制字典大小（MAX_SESSIONS=20, MAX_FEEDBACK=200）

### P1-FE-02: logout 未清理 chat store（隐私泄漏） ⚠️ 高优先级
- **文件**: frontend/src/store/auth.ts:55-70
- **问题**: 上一个用户消息残留在内存中
- **修复**: logout 时调用 chat store 的 reset()

### P1-FE-03: auth store 持久化 user 对象导致 role 变化不感知
- **文件**: frontend/src/store/auth.ts:142-199
- **问题**: 后端修改用户角色后，客户端刷新仍用旧 role
- **修复**: onRehydrateStorage 中调用 fetchMe 更新 user

### P1-FE-04: Layout WS 通知高频同步 stringify + setItem
- **文件**: frontend/src/components/Layout.tsx:85-105
- **问题**: 每条 WS 消息同步执行 localStorage.setItem，阻塞主线程
- **修复**: debounce 批量持久化

### P1-FE-05: errorReporter 面包屑高频同步 stringify + setItem
- **文件**: frontend/src/utils/errorReporter.ts:42-66
- **问题**: 每个 API 请求触发同步 localStorage 操作
- **修复**: 内存缓冲 + 定时 flush

### P1-FE-06: DocumentUploadModal 上传无 AbortController
- **文件**: frontend/src/components/DocumentUploadModal.tsx:25-49
- **问题**: 关闭 Modal 后上传仍继续
- **修复**: 使用 AbortController，卸载时 abort

### P1-FE-07: streamChat 401 重试无 timeout 保护
- **文件**: frontend/src/api/chat.ts:91, 119-135
- **问题**: 第二次 fetch 无 timeout，可能无限阻塞
- **修复**: 401 重试时重新设置 timeout

### P1-FE-08: ChatPage 模型列表加载未使用 AbortController
- **文件**: frontend/src/pages/ChatPage.tsx:91-107
- **问题**: 卸载后请求仍发送
- **修复**: 使用 AbortController

### P1-FE-09: 多个 fetchXxx 未使用 AbortController（批量问题）
- **文件**: FeedbackStatsOverview, LowRatedTable, DocumentPreviewModal, UsersPage, MessageBubble
- **问题**: 快速切换时竞态 + 资源浪费
- **修复**: 统一添加 AbortController

### P1-FE-10: dev 模式 useChatStore.subscribe 未 unsubscribe
- **文件**: frontend/src/store/chat.ts:409-433
- **问题**: HMR 累积 subscribe 监听器
- **修复**: import.meta.hot.dispose 中 unsubscribe

### P1-FE-11: tauri/updater.ts setTimeout 未清理
- **文件**: frontend/src/tauri/updater.ts:49-68
- **问题**: 卸载后 timer 触发 onUpdate 回调
- **修复**: 保存 timer id，提供 cancelAutoCheck

### P1-FE-12: DashboardPage setTimeout 未在 cleanup 中清理
- **文件**: frontend/src/pages/DashboardPage.tsx:130-148
- **问题**: timer 未保存，cleanup 中未清理
- **修复**: 保存 timer id，cleanup 中 clearTimeout

---

## 模块 4: 配置规范化（10 项）

### P1-CFG-01: JWT_SECRET 黑名单与 .env.example 默认值不匹配
- **文件**: backend/app/config.py:305 vs backend/.env.example:42
- **问题**: .env.example 默认值不在黑名单中，用户复制后校验通过但密钥公开
- **修复**: 黑名单添加 .env.example 的默认值

### P1-CFG-02: LOG_LEVEL 配置定义但从未应用到 loguru
- **文件**: backend/app/config.py:194 + backend/app/core/middleware.py:130-131
- **问题**: loguru 默认 DEBUG，LOG_LEVEL 被忽略
- **修复**: logger.add() 传入 level=settings.LOG_LEVEL.upper()

### P1-CFG-03: LOG_JSON=true 导致双重日志输出
- **文件**: backend/app/core/middleware.py:130-131
- **问题**: 未调用 logger.remove()，stderr + stdout 双重输出
- **修复**: logger.add 前调用 logger.remove()

### P1-CFG-04: Redis 客户端无 socket 超时配置 ⚠️ 高优先级
- **文件**: backend/app/redis_client.py:10-14
- **问题**: Redis 慢响应时所有操作无限挂起，拖垮后端
- **修复**: 添加 socket_timeout=5, socket_connect_timeout=2

### P1-CFG-05: WebSocket nginx 代理超时 86400s 过长
- **文件**: deploy/nginx.conf:101-102
- **问题**: 24h 超时，空闲连接耗尽 nginx 连接池
- **修复**: 改为 3600s（1 小时）

### P1-CFG-06: docker-compose.prod.yml 必需变量未在 .env.example 定义
- **文件**: deploy/docker-compose.prod.yml:15,29,105
- **问题**: REDIS_PASSWORD/QDRANT_API_KEY 强制要求但未文档化
- **修复**: .env.example 添加这两个变量

### P1-CFG-07: Celery task_time_limit=300s 对评估任务过短
- **文件**: backend/app/tasks/celery_app.py:42-43
- **问题**: 评估 100 问题需要 1000s，5 分钟被强制终止
- **修复**: 评估任务单独设置 task_time_limit=1800

### P1-CFG-08: Jaeger all-in-one 内存存储重启丢失 trace
- **文件**: deploy/docker-compose.yml:318-334
- **问题**: 默认内存存储，重启丢失
- **修复**: 配置 Badger 持久化存储

### P1-CFG-09: docker-compose.yml 基础文件无日志轮转配置
- **文件**: deploy/docker-compose.yml
- **问题**: dev/test 环境容器日志无限增长
- **修复**: 添加 logging driver + max-size + max-file

### P1-CFG-10: Tauri additionalBrowserArgs 包含 --allow-running-insecure-content
- **文件**: frontend/src-tauri/tauri.conf.json:24
- **问题**: 允许 HTTPS 页面执行 HTTP 不安全内容
- **修复**: 移除 --allow-running-insecure-content，仅保留 --remote-debugging-port=9223

---

## 修复优先级排序

### 第一批（数据安全 + 关键功能）- 12 项
1. P1-BE-02: CachedEmbeddingProvider.reset_connection（embedding 缓存失效）
2. P1-BE-09: EventBus 跨循环绑定（事件订阅失效）
3. P1-BE-08: EventBus handler 无超时（事件总线阻塞）
4. P1-FE-02: logout 未清理 chat store（隐私泄漏）
5. P1-FE-01: chat store 字典无限增长（内存泄漏）
6. P1-FE-03: auth store 持久化 user 导致 role 不感知
7. P1-CFG-04: Redis 无 socket 超时（可用性）
8. P1-API-01: getMessages 返回类型不匹配
9. P1-API-02: triggerEvaluation 字段名不一致
10. P1-API-03: SystemStatus 字段名不一致
11. P1-API-07: reparse force 参数被丢弃
12. P1-API-08: 用户列表 keyword 参数被丢弃

### 第二批（资源管理 + 性能）- 15 项
13. P1-BE-01: warmup 孤儿任务
14. P1-BE-03: CachedEmbeddingProvider.close 缺失
15. P1-BE-04: warmup_llm release 异常路径
16. P1-BE-05: publish 事件 loop 未关闭
17. P1-BE-06: HybridRetriever QdrantClient 未关闭
18. P1-BE-07: BM25Store Redis 连接未关闭
19. P1-BE-10: _update_progress Redis 写入顺序
20. P1-FE-04: Layout WS 通知同步 I/O
21. P1-FE-05: errorReporter 面包屑同步 I/O
22. P1-FE-06: DocumentUploadModal 无 AbortController
23. P1-FE-07: streamChat 401 重试无 timeout
24. P1-FE-08: ChatPage 模型列表无 AbortController
25. P1-FE-09: 多个 fetchXxx 无 AbortController
26. P1-CFG-02: LOG_LEVEL 未应用
27. P1-CFG-03: LOG_JSON 双重日志

### 第三批（类型契约 + 配置规范）- 15 项
28. P1-API-04: ModelInfo 重复定义
29. P1-API-05: User 类型必填字段后端不返回
30. P1-API-06: Document 类型必填字段后端不返回
31. P1-API-09: KnowledgeBase.description 类型不一致
32. P1-API-10: PaginatedResponse 缺 total_pages
33. P1-CFG-01: JWT_SECRET 黑名单不匹配
34. P1-CFG-05: nginx WS 超时过长
35. P1-CFG-06: prod 必需变量未文档化
36. P1-CFG-07: Celery 评估任务超时过短
37. P1-CFG-08: Jaeger 内存存储
38. P1-CFG-09: 基础 compose 无日志轮转
39. P1-CFG-10: Tauri insecure-content
40. P1-FE-10: dev subscribe 未 unsubscribe
41. P1-FE-11: tauri updater setTimeout 未清理
42. P1-FE-12: DashboardPage setTimeout 未清理

---

## 验收标准

每个修复项必须满足：
- [ ] 代码修改完成
- [ ] 相关单元测试通过
- [ ] 无回归（现有测试不受影响）
- [ ] 代码已提交 git commit

---

## 备注

- Notion MCP 不可用，暂用本地文件跟踪
- Notion 恢复后同步到 https://app.notion.com/p/3ab0b8fcffe281ccb5a7c7e3684f82ca
- P0 已修复 7/7，已推送到 GitHub（commit 7311a21）
