# ADR-006: 明确 WebSocket 与 SSE 的职责边界

## 状态

已采纳

## 日期

2026-07-20

## 上下文

项目中同时存在两种实时通信机制，且各有实现入口：

- **WebSocket**：通过 `api/v1/ws.py` 暴露 WS 端点，由 `core/notification_manager.py` 维护连接池与消息分发，承担双向实时通信能力
- **SSE（Server-Sent Events）**：通过 `api/v1/chat.py` 的 `send_message` 端点以 `StreamingResponse` 形式输出 LLM token 流，承担单向流式生成能力

ADR-004 已经确立了"流式生成用 SSE"的选型，但随着系统演进，WebSocket 端点也接入了部分通知推送能力（文档处理状态更新、系统通知、协作提醒），导致开发者在新接入实时通信场景时容易混淆二者职责，可能出现：
- 误用 WebSocket 推送 LLM token 流（与 ADR-004 决策冲突）
- 误用 SSE 实现需要客户端→服务端反向通信的场景
- 同一类业务同时建立 WS 与 SSE 两路连接，造成资源浪费

需要一份 ADR 显式划清二者职责边界，作为新功能接入时的选型依据。

## 决策

明确 **WebSocket 与 SSE 职责不重叠**，按数据流向与交互模式划分：

### WebSocket 职责：实时通知推送（双向实时通信）

由 `api/v1/ws.py` + `core/notification_manager.py` 承担，适用于：
- **文档处理状态更新**：异步文档解析、向量化、索引构建等长任务的进度与完成通知
- **系统通知**：系统级告警、维护公告、配额预警等推送
- **协作提醒**：多用户协作场景下的知识库变更、评论 @ 提醒、权限调整通知

特征：
- 需要服务端主动推送、客户端可随时回传消息（如 ACK、心跳、订阅/取消订阅）
- 通知事件离散、不可预知触发时机
- 单连接复用多类通知，由 `notification_manager` 统一管理订阅与分发

### SSE 职责：聊天流式输出（单向流式生成）

由 `api/v1/chat.py` 的 `send_message` 端点承担，适用于：
- **LLM token 逐字生成**：RAG 问答中 LLM 推理输出的 token 流式返回
- **检索-生成过程事件**：与本次请求强相关的阶段性事件（如检索完成、引用片段就绪）

特征：
- 数据流向严格单向（服务端 → 客户端）
- 与一次 HTTP 请求强绑定，请求开始即流开始，流结束即连接关闭
- 与 ADR-004 决策保持一致

## 后果

### 正面影响

- 职责清晰：开发者可按"单向流式输出 → SSE，双向实时通信 → WebSocket"快速决策，避免选型摇摆
- 与 ADR-004 形成互补：ADR-004 解决"流式生成为何选 SSE"，本 ADR 解决"何时不该用 SSE"
- 运维成本降低：两类连接的故障域、限流策略、监控指标可分别治理
- 资源利用率提升：避免同一业务重复建立两路实时连接

### 负面影响

- 部分场景下客户端需同时持有 WS（通知）与 SSE（聊天）两类连接，连接管理复杂度略增
- WS 通知与 SSE 流的生命周期不同（WS 长连接 vs SSE 请求级），前端需分别处理重连与清理逻辑
- 跨端点共享上下文（如当前会话 ID）需通过业务层传递，不能依赖传输层关联

## 选型决策树

开发者接入新实时通信场景时按以下顺序判断：

1. 数据是否为 **LLM 生成 token 流**？→ 是：使用 SSE（`chat.py` 模式）
2. 数据流向是否为 **严格单向** 且与一次请求强绑定？→ 是：使用 SSE
3. 是否需要 **服务端主动推送** 且客户端需要回传（ACK/订阅/心跳）？→ 是：使用 WebSocket（`ws.py` + `notification_manager`）
4. 是否为 **离散通知事件**（任务进度、系统通知、协作提醒）？→ 是：使用 WebSocket

## 参考

- [ADR-004: 选择 SSE 而非 WebSocket 做流式生成](./ADR-004-sse-over-websocket-for-streaming.md) — 确立 SSE 作为流式生成协议的选型依据
- 实现入口：
  - WebSocket：`backend/app/api/v1/ws.py`、`backend/app/core/notification_manager.py`
  - SSE：`backend/app/api/v1/chat.py` 的 `send_message` 端点
