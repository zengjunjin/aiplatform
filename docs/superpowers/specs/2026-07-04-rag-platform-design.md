# RAG 知识库平台设计文档 v2.0

> 版本：v2.0
> 更新日期：2026-07-05
> 状态：已确认

---

## 1. 项目概述

### 1.1 项目目标

构建一个企业级 RAG（检索增强生成）知识库平台，支持文档上传、自动解析向量化、智能问答、会话管理等功能。提供 Web 端和桌面端（Tauri）两种交付形态。

### 1.2 核心功能

- 用户系统：注册/登录/权限管理/修改密码
- 知识库管理：创建/编辑/删除知识库
- 文档管理：PDF/DOCX/MD/TXT 上传、解析、向量化、重解析
- RAG 引擎：混合检索（BM25+向量+RRF融合）+ Rerank 重排 + LLM 生成
- 对话系统：多轮对话、SSE 流式输出、引用溯源、会话管理
- 管理后台：用户管理、系统监控
- 桌面端：Tauri 打包，Sidecar 模式内嵌后端

---

## 2. 技术架构

### 2.1 技术栈

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| 前端 | React 18 + TypeScript + Vite + Ant Design 5 + Zustand | SPA 单页应用 |
| 后端 | Python 3.11 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 | RESTful API |
| 数据库 | PostgreSQL 15+ | 关系型数据存储 |
| 向量库 | Qdrant（本地持久化模式） | 向量存储与检索 |
| 缓存 | Redis 7+ | 限流、会话缓存、Embedding 缓存 |
| 任务队列 | Celery + Redis | 文档异步解析/向量化 |
| LLM | OpenAI 兼容 API（通义千问 / GPT 等） | 对话生成 |
| Embedding | 阿里云 multimodal-embedding-v1 / OpenAI text-embedding-3-small | 文本向量化 |
| Rerank | bge-reranker-base / Cohere Rerank | 检索结果重排序 |
| 桌面端 | Tauri 2 + Rust | 桌面端打包 |
| 桌面端后端 | PyInstaller 打包 Python 后端为 Sidecar exe | 内嵌后端服务 |

### 2.2 架构图

```
┌─────────────────────────────────────────────────┐
│                    客户端层                       │
│  ┌──────────┐    ┌──────────────────────────┐   │
│  │  Web 端  │    │   桌面端 (Tauri + Rust)  │   │
│  │ (React)  │    │  ┌────────────────────┐  │   │
│  └────┬─────┘    │  │ 前端 (React SPA)    │  │   │
│       │          │  └─────────┬──────────┘  │   │
│       │          │            │ Sidecar     │   │
│       │          │  ┌─────────▼──────────┐  │   │
│       │          │  │ 后端 (Python exe)   │  │   │
│       │          │  └────────────────────┘  │   │
│       │          └──────────────────────────┘   │
└───────┼─────────────────────────────────────────┘
        │ HTTP / WebSocket (SSE)
        ▼
┌─────────────────────────────────────────────────┐
│                    后端层                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ 认证授权 │  │ 知识库   │  │   文档管理   │  │
│  │  (JWT)   │  │ 管理     │  │  (异步解析)  │  │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘  │
│       │             │                │          │
│  ┌────▼─────────────▼────────────────▼───────┐  │
│  │              RAG 引擎层                     │  │
│  │  ┌────────┐  ┌────────┐  ┌────────────┐   │  │
│  │  │ 检索器 │  │ 重排序 │  │ LLM 生成器 │   │  │
│  │  │(混合)  │  │        │  │ (流式SSE)  │   │  │
│  │  └────────┘  └────────┘  └────────────┘   │  │
│  └────────────────────┬───────────────────────┘  │
│                       │                          │
└───────────────────────┼──────────────────────────┘
                        │
         ┌──────────────┼──────────────┐
         ▼              ▼              ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐
    │PostgreSQL│  │ Qdrant  │   │  Redis  │
    │ (关系型) │  │ (向量)  │   │ (缓存)  │
    └─────────┘   └─────────┘   └─────────┘
```

---

## 3. 数据模型

### 3.1 数据库表设计

#### users 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| id | Integer | 用户ID | PK, AUTO_INCREMENT |
| username | String(50) | 用户名 | UNIQUE, NOT NULL |
| email | String(255) | 邮箱 | UNIQUE, NOT NULL |
| password_hash | String(255) | 密码哈希 | NOT NULL |
| role | String(20) | 角色 | DEFAULT 'user', CHECK IN ('user', 'admin') |
| is_active | Boolean | 是否启用 | DEFAULT true |
| created_at | DateTime | 创建时间 | DEFAULT now() |
| updated_at | DateTime | 更新时间 | DEFAULT now() |

#### knowledge_bases 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| id | Integer | 知识库ID | PK, AUTO_INCREMENT |
| name | String(100) | 知识库名称 | NOT NULL |
| description | Text | 描述 | NULL |
| user_id | Integer | 创建用户ID | FK -> users.id, NOT NULL |
| doc_count | Integer | 文档数量 | DEFAULT 0 |
| chunk_count | Integer | 分块数量 | DEFAULT 0 |
| is_public | Boolean | 是否公开 | DEFAULT false |
| created_at | DateTime | 创建时间 | DEFAULT now() |
| updated_at | DateTime | 更新时间 | DEFAULT now() |

#### documents 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| id | Integer | 文档ID | PK, AUTO_INCREMENT |
| kb_id | Integer | 知识库ID | FK -> knowledge_bases.id, NOT NULL |
| filename | String(255) | 文件名 | NOT NULL |
| file_type | String(10) | 文件类型 | NOT NULL (pdf/docx/md/txt) |
| file_size | Integer | 文件大小(字节) | NOT NULL |
| file_path | String(500) | 存储路径 | NOT NULL |
| status | String(20) | 状态 | DEFAULT 'pending' |
| chunk_count | Integer | 分块数 | DEFAULT 0 |
| error_message | Text | 错误信息 | NULL |
| created_by | Integer | 上传用户ID | FK -> users.id, NOT NULL |
| created_at | DateTime | 创建时间 | DEFAULT now() |
| updated_at | DateTime | 更新时间 | DEFAULT now() |

状态枚举：`pending` → `parsing` → `chunking` → `embedding` → `done` / `failed`

#### chunks 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| id | Integer | 分块ID | PK, AUTO_INCREMENT |
| doc_id | Integer | 文档ID | FK -> documents.id, NOT NULL |
| kb_id | Integer | 知识库ID | FK -> knowledge_bases.id, NOT NULL |
| chunk_index | Integer | 分块序号 | NOT NULL |
| content | Text | 分块内容 | NOT NULL |
| char_length | Integer | 字符数 | NOT NULL |
| token_estimate | Integer | 预估token数 | NULL |
| vector_id | String(100) | Qdrant中的向量ID | UNIQUE, NOT NULL |
| created_at | DateTime | 创建时间 | DEFAULT now() |

#### chat_sessions 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| id | Integer | 会话ID | PK, AUTO_INCREMENT |
| user_id | Integer | 用户ID | FK -> users.id, NOT NULL |
| kb_id | Integer | 关联知识库ID | FK -> knowledge_bases.id, NULL |
| title | String(200) | 会话标题 | NOT NULL |
| message_count | Integer | 消息数 | DEFAULT 0 |
| created_at | DateTime | 创建时间 | DEFAULT now() |
| updated_at | DateTime | 更新时间 | DEFAULT now() |

#### chat_messages 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| id | Integer | 消息ID | PK, AUTO_INCREMENT |
| session_id | Integer | 会话ID | FK -> chat_sessions.id, NOT NULL |
| role | String(20) | 角色 | NOT NULL (user/assistant/system) |
| content | Text | 消息内容 | NOT NULL |
| references | JSON | 引用来源 | NULL |
| token_input | Integer | 输入token数 | NULL |
| token_output | Integer | 输出token数 | NULL |
| latency_ms | Integer | 耗时(毫秒) | NULL |
| created_at | DateTime | 创建时间 | DEFAULT now() |

#### cached_embeddings 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| id | Integer | ID | PK, AUTO_INCREMENT |
| text_hash | String(64) | 文本哈希(SHA256) | UNIQUE, NOT NULL |
| embedding | JSON | 向量数据 | NOT NULL |
| model | String(100) | Embedding 模型 | NOT NULL |
| created_at | DateTime | 创建时间 | DEFAULT now() |

#### audit_logs 表

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| id | Integer | ID | PK, AUTO_INCREMENT |
| user_id | Integer | 用户ID | FK -> users.id, NULL |
| action | String(50) | 操作类型 | NOT NULL |
| ip_address | String(45) | IP地址 | NULL |
| user_agent | String(500) | UA | NULL |
| details | JSON | 详情 | NULL |
| result | String(10) | 结果 | NOT NULL (success/fail) |
| created_at | DateTime | 创建时间 | DEFAULT now() |

### 3.2 Qdrant 向量库设计

每个知识库对应一个 collection，命名规则：`kb_{kb_id}_v1`

**向量维度**：1536（text-embedding-3-small）或 1024（multimodal-embedding-v1）

**Payload 结构**：
```json
{
  "chunk_id": 123,
  "doc_id": 45,
  "kb_id": 3,
  "chunk_index": 5,
  "char_length": 512,
  "created_at": "2024-01-01T00:00:00Z"
}
```

---

## 4. API 设计

### 4.1 统一响应格式

**成功响应**：
```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
}
```

**错误响应**：
```json
{
  "code": 10001,
  "message": "用户名或密码错误",
  "data": null
}
```

**分页响应**：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [...],
    "total": 100,
    "page": 1,
    "page_size": 20,
    "total_pages": 5
  }
}
```

### 4.2 错误码表

| 码段 | 类别 | 错误码 | 说明 |
|------|------|--------|------|
| 0 | 成功 | 0 | 成功 |
| 10000-19999 | 认证授权 | 10001 | 认证失败 |
| | | 10002 | Token 已过期 |
| | | 10003 | 权限不足 |
| | | 10004 | 用户名或密码错误 |
| | | 10005 | Token 刷新失败 |
| 20000-29999 | 参数校验 | 20001 | 参数错误 |
| | | 20002 | 资源不存在 |
| | | 20003 | 请求方法不支持 |
| | | 20004 | 内容过大 |
| 30000-39999 | 业务逻辑 | 30001 | 知识库名称已存在 |
| | | 30002 | 文档解析失败 |
| | | 30003 | 不支持的文件格式 |
| | | 30004 | 文件大小超限 |
| | | 30005 | 知识库数量超出限制 |
| | | 30006 | 文档数量超出限制 |
| | | 30007 | 旧密码错误 |
| 40000-49999 | 限流配额 | 40001 | 请求过于频繁 |
| | | 40002 | 存储空间不足 |
| 50000-59999 | 系统错误 | 50001 | 服务器内部错误 |
| | | 50002 | 第三方服务不可用 |
| | | 50003 | 数据库连接失败 |

### 4.3 分页规范

所有列表类接口统一使用以下查询参数：

| 参数 | 类型 | 默认值 | 范围 | 说明 |
|------|------|--------|------|------|
| page | Integer | 1 | >=1 | 页码 |
| page_size | Integer | 20 | 1-100 | 每页数量 |
| keyword | String | "" | - | 搜索关键词（可选） |
| sort_by | String | "created_at" | - | 排序字段（可选） |
| sort_order | String | "desc" | asc/desc | 排序方向（可选） |

### 4.4 认证 API

#### POST /api/v1/auth/register
注册新用户

请求体：
```json
{
  "username": "string (3-50)",
  "email": "string (email格式)",
  "password": "string (6-128)"
}
```

#### POST /api/v1/auth/login
登录

请求体：
```json
{
  "username": "string",
  "password": "string"
}
```

响应：
```json
{
  "access_token": "string",
  "refresh_token": "string",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": 1,
    "username": "string",
    "email": "string",
    "role": "user",
    "created_at": "datetime"
  }
}
```

#### POST /api/v1/auth/refresh
刷新 token

请求体：
```json
{ "refresh_token": "string" }
```

#### GET /api/v1/auth/me
获取当前用户信息

#### POST /api/v1/auth/logout
登出

#### PUT /api/v1/auth/password
修改密码

请求体：
```json
{
  "old_password": "string",
  "new_password": "string (6-128)"
}
```

### 4.5 知识库 API

#### GET /api/v1/knowledge-bases
获取知识库列表（分页）

查询参数：`page`, `page_size`, `keyword`

#### POST /api/v1/knowledge-bases
创建知识库

请求体：
```json
{
  "name": "string (1-100)",
  "description": "string (可选, 最大500)"
}
```

#### GET /api/v1/knowledge-bases/{id}
获取知识库详情

#### PUT /api/v1/knowledge-bases/{id}
更新知识库

请求体：
```json
{
  "name": "string (可选)",
  "description": "string (可选)"
}
```

#### DELETE /api/v1/knowledge-bases/{id}
删除知识库（同时删除向量库和文档）

### 4.6 文档 API

#### GET /api/v1/knowledge-bases/{kb_id}/documents
获取文档列表（分页）

查询参数：`page`, `page_size`, `keyword`, `status`

#### POST /api/v1/knowledge-bases/{kb_id}/documents/upload
上传文档（multipart/form-data）

表单字段：`file` (二进制)

限制：
- 单文件最大 50MB
- 支持格式：.pdf, .docx, .md, .markdown, .txt
- 单用户并发上传上限：3

#### GET /api/v1/documents/{id}
获取文档详情

#### DELETE /api/v1/documents/{id}
删除文档（同时删除分块和向量）

#### POST /api/v1/documents/{id}/reparse
重新解析文档

#### GET /api/v1/documents/{id}/progress
获取解析进度

响应：
```json
{
  "status": "parsing | chunking | embedding | done | failed",
  "progress": 0-100,
  "error_message": "string (失败时)"
}
```

### 4.7 对话 API

#### GET /api/v1/chat/sessions
获取会话列表（分页）

查询参数：`page`, `page_size`, `keyword`

#### POST /api/v1/chat/sessions
创建会话

请求体：
```json
{
  "kb_id": "integer (可选，不传则不绑定知识库)",
  "title": "string (可选，默认'新对话')"
}
```

#### GET /api/v1/chat/sessions/{id}
获取会话详情

#### PUT /api/v1/chat/sessions/{id}
更新会话（重命名）

请求体：
```json
{ "title": "string" }
```

#### DELETE /api/v1/chat/sessions/{id}
删除会话

#### GET /api/v1/chat/sessions/{id}/messages
获取消息列表（分页）

查询参数：`page`, `page_size`

#### POST /api/v1/chat/stream
流式聊天（SSE）

请求体：
```json
{
  "session_id": "integer (可选，不传则创建新会话)",
  "kb_id": "integer (可选，未绑定知识库时必传)",
  "content": "string (用户问题)",
  "stream": true
}
```

SSE 事件流：
```
event: searching
data: { "event": "searching", "query": "用户问题" }

event: delta
data: { "event": "delta", "content": "部分回答内容" }

event: done
data: {
  "event": "done",
  "message_id": 123,
  "references": [
    {
      "doc_id": 1,
      "doc_name": "文档名.pdf",
      "chunk_index": 3,
      "score": 0.92,
      "snippet": "引用片段..."
    }
  ]
}

event: error
data: { "event": "error", "message": "错误信息" }
```

### 4.8 系统 API

#### GET /api/v1/system/health
系统健康检查

响应：
```json
{
  "status": "ok",
  "version": "1.0.0",
  "services": {
    "postgres": "up",
    "redis": "up",
    "qdrant": "up",
    "qdrant_collections": 5
  }
}
```

#### GET /api/v1/system/stats
系统统计（仅管理员）

### 4.9 管理员 API

#### GET /api/v1/admin/users
用户列表（分页，仅管理员）

#### PUT /api/v1/admin/users/{id}
更新用户（角色/状态，仅管理员）

#### DELETE /api/v1/admin/users/{id}
删除用户（仅管理员）

---

## 5. RAG 引擎设计

### 5.1 文档处理管线

```
上传文档 → 格式检测 → 文本提取 → 文本清洗 → 分块 → 向量化 → 存入 Qdrant
```

#### 文本提取
- PDF：PyMuPDF (fitz)
- DOCX：python-docx
- Markdown / TXT：直接读取

#### 分块策略
- 方法：递归字符分块
- 块大小：512 字符（可配置）
- 重叠：50 字符（可配置）
- 按语义边界优先（段落、句子）

#### 向量化
- Embedding 模型：multimodal-embedding-v1（1024维）或 text-embedding-3-small（1536维）
- 批量大小：32
- 缓存：SHA256 哈希文本，命中缓存直接返回

### 5.2 混合检索策略

三层检索 + RRF 融合 + Rerank 重排：

```
用户问题
   │
   ├─→ BM25 检索 (top-50) ──┐
   │                         │
   ├─→ 向量检索 (top-50) ────┤→ RRF 融合 → top-20 → Rerank → top-5 → LLM
   │                         │
   └─→ (可选) 关键词召回 ────┘
```

#### BM25 检索
- 基于 chunks 表 content 字段
- PostgreSQL 全文检索 + BM25 相似度
- 中文分词：jieba

#### 向量检索
- Qdrant 余弦相似度搜索
- top-K：50

#### RRF 融合
Reciprocal Rank Fusion 算法：
```
score(doc) = Σ 1 / (k + rank_i)
k = 60
```

#### Rerank 重排序
- 模型：bge-reranker-base
- 输入：query + 每个 chunk 内容
- 输出：相关性分数
- 返回 top-5 给 LLM

### 5.3 Prompt 设计

**系统提示词**：
```
你是一个专业的知识助手。请基于以下参考资料回答用户的问题。

参考资料：
{context}

要求：
1. 只基于参考资料回答，不要编造信息
2. 如果参考资料中没有答案，请明确说明"根据现有资料无法回答"
3. 回答要准确、简洁、有条理
4. 关键信息可以用 Markdown 格式标注
```

上下文组装：按相关度从高到低排列，最多 5 个片段，总 token 不超过 3000。

### 5.4 引用溯源
- 每个回答片段标注来源文档和位置
- 前端点击引用可跳转到对应文档
- 引用格式：`[文档名.pdf #3]`

---

## 6. 安全设计

### 6.1 认证与授权
- JWT Token 认证（access_token 1小时，refresh_token 7天）
- 密码哈希：bcrypt（cost=12）
- RBAC 角色权限控制（user / admin）
- 资源级权限校验（只能操作自己的知识库和文档）

### 6.2 接口限流
基于 Redis 滑动窗口限流：

| 接口 | 粒度 | 阈值 |
|------|------|------|
| 登录/注册 | IP | 10次/分钟 |
| 聊天接口 | 用户 | 60次/分钟 |
| 文档上传 | 用户 | 20次/小时 |
| 全局 API | 用户 | 1000次/分钟 |

返回 429 状态码 + `Retry-After` 响应头。

### 6.3 输入校验
- 所有输入参数 Pydantic 校验
- 文件名白名单校验，禁止路径遍历
- 文件内容 MIME type + 扩展名双重校验
- SQL 注入防护：全部使用 ORM 参数化查询

### 6.4 XSS 防护
- 后端输出不自动转义（API 返回 JSON）
- 前端 Markdown 渲染使用白名单 sanitize
- 禁止 script、iframe、style 等危险标签
- 链接自动加 `rel="noopener noreferrer"`

### 6.5 文件上传安全
- 文件名随机化（UUID + 原始扩展名）
- 存储路径按用户/知识库分层隔离
- 静态文件服务设 `Content-Disposition: attachment`
- 禁止执行权限

### 6.6 审计日志
记录以下操作：
- 登录/登出/修改密码
- 知识库创建/删除
- 文档上传/删除
- 用户管理操作（管理员）

记录字段：用户ID、IP、UA、操作类型、详情、结果、时间。

---

## 7. 缓存策略

### 7.1 缓存层级

| 层级 | 存储 | 用途 |
|------|------|------|
| L1 | Redis | 热点数据缓存、限流、会话 |
| L2 | 数据库 | 持久化数据 |
| L3 | Qdrant | 向量数据 |

### 7.2 缓存设计

| 缓存内容 | Key 格式 | TTL | 失效时机 |
|----------|---------|-----|----------|
| 用户信息 | `user:{id}` | 1小时 | 修改用户信息/密码时删除 |
| 知识库详情 | `kb:{id}` | 30分钟 | 更新/删除知识库时删除 |
| 文档列表 | `kb:{id}:docs:{page}:{size}:{keyword}` | 10分钟 | 上传/删除/重解析文档时删除 |
| Embedding 缓存 | `embed:{model}:{sha256(text)}` | 永久 | - |
| 会话上下文 | `session:{id}:context` | 24小时 | 新消息时更新 |
| 限流计数 | `rate:{ip|user}:{action}:{window}` | 窗口时长 | 自动过期 |

---

## 8. 前端设计

### 8.1 技术栈
- React 18 + TypeScript
- Vite 5 构建工具
- Ant Design 5 UI 组件库
- Zustand 状态管理
- React Router v6 路由
- axios HTTP 客户端
- react-markdown + rehype-sanitize Markdown 渲染

### 8.2 页面结构

```
/ (重定向到 /chat)
├─ /login          登录页
├─ /register       注册页
├─ /chat           聊天页（主页面）
│   └─ /chat/:sessionId
├─ /knowledge-bases     知识库列表
│   └─ /knowledge-bases/:kbId  知识库详情
├─ /users          用户管理（仅管理员）
└─ *               404 页
```

### 8.3 核心页面功能

#### 聊天页
- 左侧：会话列表（新建、搜索、重命名、删除）
- 中间：对话区域（流式消息、引用展示、Markdown 渲染）
- 右侧：知识库选择器
- 底部：输入框（支持多行、回车发送、Shift+回车换行）

#### 知识库列表页
- 知识库卡片网格展示
- 创建知识库弹窗
- 删除确认
- 点击进入详情

#### 知识库详情页
- 文档列表表格（文件名、类型、大小、状态、操作）
- 上传文档（拖拽 + 点击）
- 重新解析 / 删除文档
- 进度条展示解析状态

#### 用户管理页（管理员）
- 用户列表表格
- 启用/禁用用户
- 修改用户角色

### 8.4 状态管理
使用 Zustand 分模块：
- `authStore`：认证状态、用户信息
- `kbStore`：知识库列表、文档列表
- `chatStore`：会话列表、消息、流式状态

---

## 9. 桌面端设计（Tauri）

### 9.1 总体架构
- **Sidecar 模式**：Python 后端打包为独立 exe，Tauri 启动时拉起子进程
- 前端复用 Web 版 React SPA
- 前后端通过 HTTP 通信（localhost 随机端口）
- 数据存储在程序安装目录下

### 9.2 技术架构

```
┌─────────────────────────────────────┐
│       Tauri 主进程 (Rust)           │
│  ┌───────────────────────────────┐  │
│  │  WebView (React SPA)          │  │
│  └───────────────┬───────────────┘  │
│                  │ HTTP             │
│  ┌───────────────▼───────────────┐  │
│  │  Sidecar: 后端.exe (Python)   │  │
│  │  - FastAPI                    │  │
│  │  - SQLite (替代PostgreSQL)    │  │
│  │  - Qdrant (本地模式)          │  │
│  │  - 嵌入式 Redis(可选)         │  │
│  └───────────────────────────────┘  │
└─────────────────────────────────────┘
```

### 9.3 后端打包
- PyInstaller 打包为单文件 exe
- 静态链接 Python 解释器
- 包含所有依赖（FastAPI、SQLAlchemy、Qdrant-client 等）
- 数据库：桌面端用 SQLite 替代 PostgreSQL（零配置）

### 9.4 进程管理
- Tauri 启动时：分配随机端口 → 启动后端 sidecar → 等待就绪 → 加载前端
- Tauri 关闭时：发送关闭信号 → 等待后端优雅退出 → 强制终止超时
- 进程健康检查：定期心跳检测，异常自动重启

### 9.5 窗口与系统托盘
- 主窗口：可调整大小，最小宽度 800x600
- 系统托盘图标：
  - 左键点击：显示/隐藏窗口
  - 右键菜单：打开主窗口 / 开机自启 / 退出
- 关闭按钮：最小化到托盘（可配置）
- 开机自启：通过注册表/启动项实现

### 9.6 数据存储
- 安装目录：`C:\Program Files\RAG知识库平台\`
- 数据目录：`%APPDATA%\RAG知识库平台\`（用户数据）
  - `data/` - SQLite 数据库文件
  - `qdrant/` - Qdrant 向量数据
  - `uploads/` - 上传的文档文件
  - `logs/` - 日志文件

---

## 10. 部署方案

### 10.1 Web 端部署
- 后端：Gunicorn + Uvicorn Worker，Nginx 反向代理
- 前端：静态文件 Nginx 托管
- 数据库：PostgreSQL + Qdrant + Redis 独立部署
- 任务队列：Celery Worker 单独进程
- 操作系统：Linux (Ubuntu 22.04+)

### 10.2 桌面端部署
- 打包格式：
  - Windows：.msi 安装包 + .exe 便携版
  - macOS：.dmg
  - Linux：.AppImage / .deb
- 自动更新：Tauri Updater + GitHub Releases
- 安装路径：
  - Windows：`C:\Program Files\`
  - macOS：`/Applications/`

---

## 11. 日志与监控

### 11.1 日志规范
- 格式：JSON 结构化日志
- 级别：DEBUG / INFO / WARNING / ERROR / CRITICAL
- 字段：timestamp, level, module, user_id, ip, request_id, message, duration_ms

### 11.2 关键指标
- 请求量 / 错误率 / 响应时间（P50, P95, P99）
- 向量检索耗时 / 召回率
- LLM 调用耗时 / Token 用量
- 任务队列长度 / 成功率
- 在线用户数

---

## 12. 性能指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| API 响应时间 | < 200ms | 普通接口 P95 |
| 文档解析 | < 30s | 10MB PDF |
| 检索耗时 | < 500ms | 混合检索 + Rerank |
| 首字延迟 | < 2s | LLM 流式首字 |
| 并发用户 | 100+ | 同时在线 |
| RAG 准确率 | ≥ 80% | 测试集评测 |
| 召回率 | ≥ 85% | Recall@5 |

---
## 13. 架构演进

### 13.1 版本演进路线

| 版本 | 日期 | 里程碑 | 核心变化 |
|------|------|--------|----------|
| v0.1.0 | 2026-07-04 | MVP 发布 | 核心 RAG 问答、用户系统、文档管理、Tauri 桌面端 |
| v0.2.0 | 2026-07-11 | 质量与体验提升 | 多模型支持、RAGAS 评估、反馈闭环、国际化、PWA、性能基准 |

### 13.2 v0.1.0 → v0.2.0 关键变化

#### 架构层面

```
v0.1.0                                   v0.2.0
┌──────────────┐                    ┌──────────────────────┐
│  Ollama 单模型 │  ────────▶        │  ModelRegistry 多模型  │
│  (硬编码)     │                    │  ollama / openai /   │
│              │                    │  compatible API      │
└──────────────┘                    └──────────────────────┘

┌──────────────┐                    ┌──────────────────────┐
│  无评测体系   │  ────────▶        │  RAGAS 四维评测        │
│              │                    │  Faithfulness        │
│              │                    │  Answer Relevancy    │
│              │                    │  Context Precision   │
│              │                    │  Context Recall      │
└──────────────┘                    └──────────────────────┘

┌──────────────┐                    ┌──────────────────────┐
│  无反馈机制   │  ────────▶        │  反馈闭环              │
│              │                    │  点赞/点踩 → 统计     │
│              │                    │  → 分析 → 优化        │
└──────────────┘                    └──────────────────────┘
```

#### 新增模块

| 模块 | 路径 | 功能 |
|------|------|------|
| ModelRegistry | `app/models/factory.py` | 统一管理多个 LLM Provider，支持热切换 |
| ModelRouter | `app/core/model_router.py` | 智能路由：健康检查 + 路由策略 + Fallback |
| ModelHealth | `app/core/model_health.py` | 定期心跳检测所有 Provider |
| OpenAI Provider | `app/models/openai_compatible_provider.py` | 对接任意 OpenAI 兼容 API |
| Evaluation | `app/core/evaluation.py` | RAGAS 评估引擎 |
| Feedback | `app/services/feedback_service.py` | 用户反馈收集与分析 |
| Prometheus | `app/core/metrics.py` | 指标采集与暴露 |
| Audit Log | `app/services/audit_service.py` | 操作审计日志 |
| Cache | `app/core/cache.py` | 多层缓存（Redis + 数据库级） |
| i18n | `frontend/src/i18n/` | 中英文国际化 |
| PWA | `frontend/public/manifest.json` | Service Worker + 离线支持 |

#### 数据库 Schema 变更

v0.2.0 新增以下表：
- `evaluation_runs`：评估运行记录
- `evaluation_results`：逐题评估结果
- `message_feedback`：消息反馈（点赞/点踩）
- `audit_logs`：操作审计日志
- `cached_embeddings`：Embedding 缓存

v0.2.0 新增字段：
- `chat_sessions.kb_id`：会话绑定知识库
- `chat_messages.references`：引用来源（JSON）
- `chat_messages.token_input / token_output / latency_ms`：性能指标

#### API 变更

| 变更类型 | 端点 | 说明 |
|----------|------|------|
| 新增 | `POST /api/v1/evaluation/runs` | 触发评估 |
| 新增 | `GET /api/v1/evaluation/runs` | 评估运行列表 |
| 新增 | `POST /api/v1/chat/messages/{id}/feedback` | 提交反馈 |
| 新增 | `GET /api/v1/chat/feedback/stats` | 反馈统计 |
| 新增 | `POST /api/v1/chat/sessions/{id}/cancel` | 取消生成 |
| 新增 | `GET /api/v1/system/models` | 可用模型列表 |
| 新增 | `GET /api/v2/version` | v2 API 版本信息 |
| 增强 | `POST /api/v1/chat/stream` | 支持 model 参数、取消、Fallback |

### 13.3 多模型架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        ModelRegistry                            │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    Provider Pool                          │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │  │
│  │  │ Ollama   │  │ OpenAI   │  │ 通义千问  │  │ DeepSeek │ │  │
│  │  │ qwen2.5  │  │ GPT-4o   │  │ qwen-max │  │ v3       │ │  │
│  │  │ (本地)   │  │ (云端)   │  │ (云端)   │  │ (云端)   │ │  │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘ │  │
│  │       │             │             │             │        │  │
│  │       └─────────────┼─────────────┼─────────────┘        │  │
│  │                     │             │                       │  │
│  │              ┌──────▼──────┐ ┌───▼──────────┐            │  │
│  │              │ Health Check│ │ Health Check  │            │  │
│  │              │ (is_healthy)│ │ (is_healthy)  │            │  │
│  │              └──────┬──────┘ └───┬──────────┘            │  │
│  └─────────────────────┼───────────┼────────────────────────┘  │
│                        │           │                           │
│                 ┌──────▼───────────▼──────┐                    │
│                 │      ModelRouter         │                    │
│                 │  - Round Robin 路由      │                    │
│                 │  - 健康检查过滤          │                    │
│                 │  - Fallback 自动切换     │                    │
│                 │  - 用户指定模型优先      │                    │
│                 └──────────┬──────────────┘                    │
│                            │                                    │
│                     ┌──────▼──────┐                            │
│                     │  LLM 调用   │                            │
│                     │  (SSE 流式) │                            │
│                     └─────────────┘                            │
└─────────────────────────────────────────────────────────────────┘

Embedding 层 (同样支持多 Provider):
┌──────────────────────────────────────────────┐
│           ModelFactory.create_embedding()     │
│  ┌────────────────┐  ┌────────────────────┐  │
│  │ Ollama nomic   │  │ OpenAI text-embed  │  │
│  │ embed-text     │  │ -3-small (1536d)   │  │
│  │ (768d)         │  │                    │  │
│  └───────┬────────┘  └─────────┬──────────┘  │
│          │                     │              │
│          └──────────┬──────────┘              │
│                     │                         │
│          ┌──────────▼──────────┐              │
│          │ CachedEmbedding     │              │
│          │ (SHA256 哈希缓存)   │              │
│          └─────────────────────┘              │
└──────────────────────────────────────────────┘
```

### 13.4 数据流图

#### 文档处理数据流

```
用户上传文档
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│  API Layer (FastAPI)                                         │
│  POST /api/v1/documents/upload                               │
│  - 文件校验（大小、类型、MIME）                               │
│  - 保存到本地存储（UUID 重命名）                              │
│  - 创建 Document 记录（status: pending）                     │
│  - 提交 Celery 异步任务                                      │
└──────────────────────────┬───────────────────────────────────┘
                           │ Celery Task
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  Celery Worker: parse_document_task                          │
│                                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐ │
│  │ 格式检测  │──▶│ 文本提取  │──▶│ 文本清洗  │──▶│   分块   │ │
│  │ (MIME)   │   │          │   │          │   │ 512+50  │ │
│  └──────────┘   └──────────┘   └──────────┘   └─────┬────┘ │
│                                                      │      │
│  ┌───────────────────────────────────────────────────▼────┐ │
│  │                    向量化 (Embedding)                   │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  for each chunk:                                  │  │ │
│  │  │    1. SHA256(text) → 查缓存                       │  │ │
│  │  │    2. 命中 → 直接用缓存                            │  │ │
│  │  │    3. 未命中 → 调用 Embedding API → 写入缓存       │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  └────────────────────────┬───────────────────────────────┘ │
│                           │                                  │
│  ┌────────────────────────▼───────────────────────────────┐ │
│  │  批量写入 Qdrant                                       │ │
│  │  - collection: kb_{kb_id}_v1                          │ │
│  │  - vectors: embedding                                  │ │
│  │  - payload: {chunk_id, doc_id, kb_id, ...}            │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  更新 Document.status = "done"                               │
│  更新 KB.chunk_count / doc_count                             │
│  清除相关 Redis 缓存                                         │
└──────────────────────────────────────────────────────────────┘
```

#### 问答数据流

```
用户提问
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│  POST /api/v1/chat/sessions/{id}/messages (SSE 流式)             │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ 1. 保存用户消息 (user)                                       │ │
│  │ 2. 获取历史上下文 (Redis, 最近 8 轮)                         │ │
│  └──────────────────────────┬──────────────────────────────────┘ │
│                             │                                    │
│  ┌──────────────────────────▼──────────────────────────────────┐ │
│  │ 3. 混合检索                                                  │ │
│  │    ┌──────────────┐    ┌──────────────┐                     │ │
│  │    │ BM25 检索    │    │ 向量检索      │                     │ │
│  │    │ (PostgreSQL  │    │ (Qdrant      │                     │ │
│  │    │  full-text)  │    │  cosine sim) │                     │ │
│  │    │ top-50       │    │ top-50       │                     │ │
│  │    └──────┬───────┘    └──────┬───────┘                     │ │
│  │           │                   │                              │ │
│  │           └─────────┬─────────┘                              │ │
│  │                     │                                        │ │
│  │              ┌──────▼──────┐                                 │ │
│  │              │ RRF 融合    │  score = Σ 1/(60 + rank_i)     │ │
│  │              │ top-20      │                                 │ │
│  │              └──────┬──────┘                                 │ │
│  └─────────────────────┼────────────────────────────────────────┘ │
│                        │                                          │
│  ┌─────────────────────▼────────────────────────────────────────┐ │
│  │ 4. Rerank 重排序 (bge-reranker-base)                         │ │
│  │    input: query + top-20 chunks                              │ │
│  │    output: 重排序后的 top-5                                   │ │
│  └─────────────────────┬────────────────────────────────────────┘ │
│                        │                                          │
│  ┌─────────────────────▼────────────────────────────────────────┐ │
│  │ 5. Prompt 构建                                                │ │
│  │    - 系统提示词 + 参考资料 (top-5 chunks) + 历史对话          │ │
│  │    - Token 估算 & 截断 (≤ 4096 tokens)                       │ │
│  └─────────────────────┬────────────────────────────────────────┘ │
│                        │                                          │
│  ┌─────────────────────▼────────────────────────────────────────┐ │
│  │ 6. LLM 生成 (ModelRouter)                                    │ │
│  │    ┌──────────────────────────────────────────────────────┐  │ │
│  │    │  ModelRouter.select(preferred_model)                  │  │ │
│  │    │    ↓                                                  │  │ │
│  │    │  选择健康 Provider → 流式生成 → SSE 推送              │  │ │
│  │    │    ↓ (失败时)                                        │  │ │
│  │    │  Fallback 到下一个健康 Provider                       │  │ │
│  │    └──────────────────────────────────────────────────────┘  │ │
│  └─────────────────────┬────────────────────────────────────────┘ │
│                        │                                          │
│  ┌─────────────────────▼────────────────────────────────────────┐ │
│  │ 7. 后处理                                                     │ │
│  │    - 引用解析 (parse_references)                             │ │
│  │    - 保存 assistant 消息到 DB                                │ │
│  │    - 保存到 Redis 会话上下文                                  │ │
│  │    - 发送 done 事件 (含 references)                          │ │
│  └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

#### 反馈闭环数据流

```
用户操作
    │
    ├── 点赞/点踩 → POST /api/v1/chat/messages/{id}/feedback
    │                    │
    │                    ▼
    │              ┌──────────────┐
    │              │  feedback 表  │
    │              └──────┬───────┘
    │                     │
    │                     ▼
    │              ┌──────────────┐
    │              │ 定时分析任务  │
    │              │ (Celery Beat)│
    │              └──────┬───────┘
    │                     │
    │                     ▼
    │              ┌──────────────────────────────┐
    │              │ 反馈分析报告                  │
    │              │ - 满意度趋势                  │
    │              │ - 低分回答聚类               │
    │              │ - 问题类型分布               │
    │              │ - 优化建议                    │
    │              └──────────────────────────────┘
    │
    └── 评估触发 → POST /api/v1/evaluation/runs
                        │
                        ▼
                  ┌──────────────────────┐
                  │ RAGAS 四维评估        │
                  │ - Faithfulness       │
                  │ - Answer Relevancy   │
                  │ - Context Precision  │
                  │ - Context Recall     │
                  └──────────────────────┘
```

---

## 14. 扩展性设计

### 14.1 水平扩展架构

```
                    ┌──────────────┐
                    │   Nginx LB   │
                    │  (Round Robin)│
                    └──────┬───────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
    ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
    │  Backend-1  │ │  Backend-2  │ │  Backend-N  │
    │  (FastAPI)  │ │  (FastAPI)  │ │  (FastAPI)  │
    └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
           │               │               │
           └───────────────┼───────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──────┐ ┌──▼────┐ ┌─────▼──────┐
       │ PostgreSQL  │ │ Redis│ │  Qdrant    │
       │  (主从)     │ │(Cluster)│ │(分布式)   │
       └─────────────┘ └──────┘ └────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──────┐ ┌──▼──────┐ ┌───▼──────┐
       │ Celery W-1  │ │Celery W-2│ │Celery W-N│
       │ (文档解析)  │ │(文档解析)│ │(文档解析)│
       └─────────────┘ └─────────┘ └──────────┘
```

### 14.2 无状态设计

所有后端实例均为无状态设计：
- 会话状态存储在 Redis 中（`session:{id}:context`）
- JWT Token 自包含认证信息，无需服务端 Session
- 文件存储使用共享卷（NFS / S3 / MinIO）
- 限流计数器基于 Redis，跨实例共享

### 14.3 数据库扩展策略

| 组件 | 当前方案 | 扩展方案 |
|------|----------|----------|
| PostgreSQL | 单实例 | 主从复制 + 读写分离 + PgBouncer 连接池 |
| Redis | 单实例 | Redis Cluster / Sentinel 高可用 |
| Qdrant | 单实例 | Qdrant 分布式模式（Raft 共识） |
| Celery | 多 Worker | 按队列分片：文档解析 / 评估 / 统计 |

### 14.4 新增 LLM Provider 接口

通过 `ModelRegistry` 接口，添加新 Provider 只需：

```python
# 1. 实现 BaseLLMProvider
class MyNewProvider(BaseLLMProvider):
    @property
    def provider_name(self) -> str:
        return "my-provider"

    async def chat_stream(self, messages):
        # 实现流式聊天
        ...

# 2. 在配置中注册
# LLM_PROVIDERS='[{"name":"my-provider","type":"openai_compatible",
#   "api_base":"https://api.example.com/v1","model":"my-model","api_key":"sk-xxx"}]'
```

### 14.5 新增文档解析器

```python
# 1. 实现 BaseParser
class MyParser(BaseParser):
    @property
    def supported_extensions(self) -> list[str]:
        return [".myfmt"]

    def parse(self, file_path: str) -> str:
        # 实现解析逻辑
        ...

# 2. 在 parsers/__init__.py 中注册
PARSER_REGISTRY = {
    ".myfmt": MyParser(),
    # ...
}
```

### 14.6 插件化设计（规划中）

v0.3.0 计划引入插件机制：
- **LLM Plugin**：通过配置文件热加载新 Provider
- **Parser Plugin**：动态注册文档解析器
- **Middleware Plugin**：自定义请求/响应中间件
- **Hook Plugin**：在关键节点（上传前、检索前、生成后）注入自定义逻辑

### 14.7 性能扩展指标

| 扩展维度 | 单机上限 | 集群目标 |
|----------|----------|----------|
| 并发 WebSocket 连接 | 1,000 | 10,000+ |
| 文档解析吞吐 | 10 docs/min | 100 docs/min |
| 检索 QPS | 50 | 500+ |
| LLM 并发调用 | 5 | 50+ |
| 用户会话数 | 500 | 10,000+ |

---

## 15. 实施阶段

| 阶段 | 内容 | 产出 |
|------|------|------|
| Phase 1 | 架构基础：统一响应格式 + 错误码 + 分页规范 | 可运行的 API 骨架 |
| Phase 2 | 用户系统：认证 + 权限 + 审计日志 | 完整用户体系 |
| Phase 3 | 知识库 + 文档管理 + 异步解析管线 | 文档上传解析可用 |
| Phase 4 | RAG 引擎：混合检索 + Rerank + LLM 生成 | 检索问答可用 |
| Phase 5 | 对话系统：SSE 流式 + 会话管理 + 引用溯源 | 完整对话功能 |
| Phase 6 | 前端：所有页面 + 交互 + 状态管理 | Web 端可用 |
| Phase 7 | 安全加固：限流 + 缓存 + XSS/SQL 防护 | 安全达标 |
| Phase 8 | 管理后台 + 系统监控 | 管理员功能 |
| Phase 9 | Tauri 桌面端：Sidecar + 打包 + 托盘 | 桌面端可用 |
| Phase 10 | 测试 + 优化 + 文档 | 生产就绪 |

---
## 16. 验收标准

### 功能验收
- [ ] 用户注册/登录/修改密码正常
- [ ] 知识库 CRUD 完整
- [ ] 文档上传/解析/向量化/删除/重解析正常
- [ ] 支持 PDF/DOCX/MD/TXT 四种格式
- [ ] 混合检索 + Rerank 正常工作
- [ ] SSE 流式对话流畅
- [ ] 引用溯源准确
- [ ] 会话管理（创建/重命名/删除/列表）
- [ ] 管理员用户管理功能
- [ ] 桌面端可安装运行，功能与 Web 一致

### 性能验收
- [ ] 普通 API 响应 < 200ms (P95)
- [ ] 检索 < 500ms
- [ ] 首字延迟 < 2s
- [ ] 10MB PDF 解析 < 30s

### 安全验收
- [ ] JWT 认证正确
- [ ] 权限控制严格（越权访问失败）
- [ ] 限流生效
- [ ] SQL 注入防护
- [ ] XSS 防护
- [ ] 文件上传安全

### 部署验收
- [ ] Web 端可部署运行
- [ ] 桌面端打包成功
- [ ] 桌面端安装/卸载正常
