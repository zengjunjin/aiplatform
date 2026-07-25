# RAG 知识库平台 — API 使用指南

> 版本：v0.2.0
> 更新日期：2026-07-11
> Base URL：`http://localhost:8000`

---

## 1. 认证方式

### 1.1 JWT Bearer Token

所有需要认证的 API 请求必须在 Header 中携带 JWT Token：

```http
Authorization: Bearer <access_token>
```

### 1.2 Token 获取与刷新

**获取 Token**：通过 `/api/v1/auth/login` 端点获取 `access_token` 和 `refresh_token`。

**Token 有效期**：
- `access_token`：60 分钟（默认，可通过 `ACCESS_TOKEN_EXPIRE_MINUTES` 配置）
- `refresh_token`：7 天（默认，可通过 `REFRESH_TOKEN_EXPIRE_DAYS` 配置）

**刷新 Token**：`access_token` 过期后，使用 `/api/v1/auth/refresh` 端点获取新 Token。

### 1.3 角色与权限

| 角色 | 权限范围 |
|------|----------|
| `user` | 操作自己的知识库、文档、会话；使用聊天功能 |
| `admin` | 用户管理（列表/角色/状态）、系统监控、评估管理、反馈分析 |

### 1.4 统一响应格式

**成功响应**：
```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
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

**错误响应**：
```json
{
  "code": 10001,
  "message": "用户名或密码错误",
  "data": null
}
```

---

## 2. 端点列表

### 2.1 认证模块 (`/api/v1/auth`)

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/v1/auth/register` | 否 | 注册新用户 |
| POST | `/api/v1/auth/login` | 否 | 用户登录 |
| POST | `/api/v1/auth/refresh` | 否 | 刷新 Token |
| GET | `/api/v1/auth/me` | 是 | 获取当前用户信息 |
| POST | `/api/v1/auth/logout` | 是 | 登出（Token 加入黑名单） |
| PUT | `/api/v1/auth/password` | 是 | 修改密码 |

#### POST /api/v1/auth/register

请求体：
```json
{
  "username": "zhangsan",
  "email": "zhangsan@example.com",
  "password": "SecureP@ss123"
}
```

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": 1,
    "username": "zhangsan",
    "email": "zhangsan@example.com",
    "role": "user",
    "is_active": true,
    "created_at": "2026-07-11T10:00:00"
  }
}
```

#### POST /api/v1/auth/login

请求体：
```json
{
  "username": "zhangsan",
  "password": "SecureP@ss123"
}
```

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer",
    "expires_in": 3600,
    "user": {
      "id": 1,
      "username": "zhangsan",
      "email": "zhangsan@example.com",
      "role": "user",
      "is_active": true,
      "created_at": "2026-07-11T10:00:00"
    }
  }
}
```

#### POST /api/v1/auth/refresh

请求体：
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

#### GET /api/v1/auth/me

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": 1,
    "username": "zhangsan",
    "email": "zhangsan@example.com",
    "role": "user",
    "is_active": true,
    "created_at": "2026-07-11T10:00:00"
  }
}
```

#### PUT /api/v1/auth/password

请求体：
```json
{
  "old_password": "SecureP@ss123",
  "new_password": "NewSecureP@ss456"
}
```

---

### 2.2 知识库模块 (`/api/v1/knowledge-bases`)

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/v1/knowledge-bases` | 是 | 创建知识库 |
| GET | `/api/v1/knowledge-bases` | 是 | 知识库列表（分页） |
| GET | `/api/v1/knowledge-bases/{id}` | 是 | 知识库详情 |
| PUT | `/api/v1/knowledge-bases/{id}` | 是 | 更新知识库 |
| DELETE | `/api/v1/knowledge-bases/{id}` | 是 | 删除知识库 |

#### POST /api/v1/knowledge-bases

请求体：
```json
{
  "name": "技术文档库",
  "description": "公司内部技术文档和规范"
}
```

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": 1,
    "name": "技术文档库",
    "description": "公司内部技术文档和规范",
    "user_id": 1,
    "doc_count": 0,
    "chunk_count": 0,
    "is_public": false,
    "created_at": "2026-07-11T10:00:00",
    "updated_at": "2026-07-11T10:00:00"
  }
}
```

#### GET /api/v1/knowledge-bases

查询参数：
- `page` (int, 默认 1)
- `page_size` (int, 默认 20, 最大 100)
- `keyword` (string, 可选)

---

### 2.3 文档模块 (`/api/v1/documents`)

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/v1/documents/upload` | 是 | 上传文档（multipart/form-data） |
| GET | `/api/v1/documents` | 是 | 文档列表（分页） |
| GET | `/api/v1/documents/{id}` | 是 | 文档详情 |
| GET | `/api/v1/documents/{id}/progress` | 是 | 解析进度 |
| DELETE | `/api/v1/documents/{id}` | 是 | 删除文档 |
| POST | `/api/v1/documents/{id}/reparse` | 是 | 重新解析 |

#### POST /api/v1/documents/upload

请求（multipart/form-data）：
```
file: example.pdf (binary)
kb_id: 1
```

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "document_id": 42,
    "status": "pending",
    "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }
}
```

限制：
- 支持格式：`.pdf`, `.docx`, `.md`, `.markdown`, `.txt`
- 单文件最大：50MB（可配置 `MAX_FILE_SIZE_MB`）
- 单知识库最多：100 个文档（可配置 `MAX_DOCUMENTS_PER_KB`）

#### GET /api/v1/documents/{id}/progress

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "status": "embedding",
    "progress": 60,
    "chunk_count": 0,
    "error_message": null
  }
}
```

状态枚举及进度映射：
- `pending` → 0%
- `parsing` → 10%
- `chunking` → 30%
- `embedding` → 60%
- `done` → 100%
- `failed` → 100%（含 `error_message`）

---

### 2.4 对话模块 (`/api/v1/chat`)

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/v1/chat/sessions` | 是 | 创建会话 |
| GET | `/api/v1/chat/sessions` | 是 | 会话列表（分页） |
| GET | `/api/v1/chat/sessions/{id}` | 是 | 会话详情（含消息） |
| PUT | `/api/v1/chat/sessions/{id}` | 是 | 更新会话（重命名） |
| DELETE | `/api/v1/chat/sessions/{id}` | 是 | 删除会话 |
| GET | `/api/v1/chat/sessions/{id}/messages` | 是 | 消息列表（分页） |
| POST | `/api/v1/chat/sessions/{id}/messages` | 是 | 发送消息（SSE 流式） |
| POST | `/api/v1/chat/sessions/{id}/cancel` | 是 | 取消当前生成 |
| POST | `/api/v1/chat/messages/{id}/feedback` | 是 | 提交反馈 |
| GET | `/api/v1/chat/messages/{id}/feedback` | 是 | 获取反馈 |
| GET | `/api/v1/chat/feedback/stats` | admin | 反馈统计 |
| GET | `/api/v1/chat/feedback/analysis` | admin | 反馈分析 |
| GET | `/api/v1/chat/feedback/low-rated` | admin | 低分反馈列表 |

#### POST /api/v1/chat/sessions

请求体：
```json
{
  "kb_id": 1,
  "title": "关于 API 设计的讨论"
}
```

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": 1,
    "user_id": 1,
    "kb_id": 1,
    "title": "关于 API 设计的讨论",
    "message_count": 0,
    "created_at": "2026-07-11T10:00:00",
    "updated_at": "2026-07-11T10:00:00"
  }
}
```

#### POST /api/v1/chat/sessions/{id}/messages

请求体：
```json
{
  "content": "RESTful API 设计的最佳实践是什么？",
  "model": "ollama"
}
```

SSE 事件流示例：

```
event: model
data: {"event":"model","model_name":"ollama","display_name":"qwen2.5:7b (本地)"}

event: searching
data: {"event":"searching","chunks_found":0}

event: searching
data: {"event":"searching","chunks_found":15}

event: delta
data: {"event":"delta","content":"RESTful"}

event: delta
data: {"event":"delta","content":" API"}

event: delta
data: {"event":"delta","content":" 设计"}

... (更多 delta 事件)

event: done
data: {
  "event": "done",
  "message_id": 123,
  "references": [
    {
      "doc_id": 42,
      "doc_name": "API设计规范.pdf",
      "chunk_index": 3,
      "score": 0.92,
      "snippet": "RESTful API 应遵循以下设计原则..."
    }
  ]
}

data: [DONE]
```

SSE 事件类型：
| 事件 | 说明 |
|------|------|
| `model` | 告知当前使用的模型（含 `fallback` 字段表示是否触发 Fallback） |
| `searching` | 检索进行中，`chunks_found` 为检索到的片段数 |
| `delta` | 增量回答内容 |
| `done` | 生成完成，包含 `message_id` 和 `references` |
| `cancelled` | 用户取消了生成 |
| `error` | 发生错误 |

#### POST /api/v1/chat/messages/{id}/feedback

请求体：
```json
{
  "rating": "positive",
  "comment": "回答准确且有条理",
  "feedback_type": "accuracy"
}
```

`rating` 枚举：`positive` / `negative`
`feedback_type` 枚举：`accuracy` / `relevance` / `completeness` / `formatting` / `other`

---

### 2.5 系统模块 (`/api/v1/system`)

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/v1/system/status` | admin | 系统组件健康状态 |
| GET | `/api/v1/system/models` | 否 | 可用模型列表 |

#### GET /api/v1/system/status

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "postgresql": "up",
    "redis": "up",
    "ollama": "up",
    "ollama_models": ["qwen2.5:7b", "nomic-embed-text"],
    "qdrant": "up",
    "qdrant_collections": 5,
    "celery": "up",
    "celery_workers": ["celery@worker1"]
  }
}
```

#### GET /api/v1/system/models

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "models": [
      {
        "name": "ollama",
        "display_name": "qwen2.5:7b (本地)",
        "source": "local",
        "status": "healthy"
      },
      {
        "name": "openai",
        "display_name": "gpt-4o (云端)",
        "source": "cloud",
        "status": "healthy"
      }
    ],
    "default_model": "ollama"
  }
}
```

---

### 2.6 用户管理模块 (`/api/v1/users`) — Admin Only

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/v1/users` | admin | 用户列表（分页） |
| PUT | `/api/v1/users/{id}/role` | admin | 修改用户角色 |
| PUT | `/api/v1/users/{id}/status` | admin | 修改用户状态 |

#### PUT /api/v1/users/{id}/role

请求体：
```json
{
  "role": "admin"
}
```

#### PUT /api/v1/users/{id}/status

请求体：
```json
{
  "is_active": false
}
```

---

### 2.7 评估模块 (`/api/v1/evaluation`) — Admin Only

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| POST | `/api/v1/evaluation/runs` | admin | 触发评估 |
| GET | `/api/v1/evaluation/runs` | admin | 评估运行列表 |
| GET | `/api/v1/evaluation/runs/{id}` | admin | 评估详情 |
| GET | `/api/v1/evaluation/runs/{id}/results` | admin | 逐题评估结果 |
| DELETE | `/api/v1/evaluation/runs/{id}` | admin | 删除评估 |

#### POST /api/v1/evaluation/runs

请求体：
```json
{
  "kb_id": 1,
  "num_questions": 50
}
```

响应：
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "run_id": 1,
    "status": "completed",
    "metrics": {
      "faithfulness": 0.85,
      "answer_relevancy": 0.82,
      "context_precision": 0.88,
      "context_recall": 0.79
    },
    "total_questions": 50
  }
}
```

---

### 2.8 API v2 模块 (`/api/v2`)

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/api/v2/version` | 否 | v2 API 版本信息 |

---

### 2.9 全局端点

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/` | 否 | 根路径，返回应用信息 |
| GET | `/healthz` | 否 | 存活探针 (liveness) |
| GET | `/readyz` | 否 | 就绪探针 (readiness) |
| GET | `/metrics` | 否 | Prometheus 指标 |
| GET | `/docs` | 否 | Swagger UI 文档 |
| GET | `/redoc` | 否 | ReDoc 文档 |

---

## 3. 完整使用流程示例

### 3.1 注册 → 创建知识库 → 上传文档 → 对话

```bash
BASE_URL="http://localhost:8000"

# 1. 注册
curl -X POST "$BASE_URL/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","email":"demo@example.com","password":"Demo@123"}'

# 2. 登录（保存 access_token）
TOKEN=$(curl -s -X POST "$BASE_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"demo","password":"Demo@123"}' \
  | jq -r '.data.access_token')

# 3. 创建知识库
KB_ID=$(curl -s -X POST "$BASE_URL/api/v1/knowledge-bases" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"我的知识库","description":"测试知识库"}' \
  | jq -r '.data.id')

# 4. 上传文档
curl -X POST "$BASE_URL/api/v1/documents/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/document.pdf" \
  -F "kb_id=$KB_ID"

# 5. 等待文档处理完成（轮询进度）
curl -s "$BASE_URL/api/v1/documents/1/progress" \
  -H "Authorization: Bearer $TOKEN"

# 6. 创建会话
SESSION_ID=$(curl -s -X POST "$BASE_URL/api/v1/chat/sessions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"kb_id\":$KB_ID,\"title\":\"测试对话\"}" \
  | jq -r '.data.id')

# 7. 发送消息（SSE 流式）
curl -N -X POST "$BASE_URL/api/v1/chat/sessions/$SESSION_ID/messages" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"文档的主要内容是什么？"}'
```

### 3.2 管理员：系统监控 + 用户管理

```bash
# 1. 管理员登录
ADMIN_TOKEN=$(curl -s -X POST "$BASE_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Admin@123"}' \
  | jq -r '.data.access_token')

# 2. 查看系统状态
curl -s "$BASE_URL/api/v1/system/status" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 3. 查看所有用户
curl -s "$BASE_URL/api/v1/users?page=1&page_size=20" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 4. 提升某用户为管理员
curl -s -X PUT "$BASE_URL/api/v1/users/2/role" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role":"admin"}'

# 5. 触发评估
curl -s -X POST "$BASE_URL/api/v1/evaluation/runs?kb_id=1&num_questions=50" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 6. 查看反馈统计
curl -s "$BASE_URL/api/v1/chat/feedback/stats" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## 4. 常见错误码参考

### 4.1 认证授权 (10000-19999)

| 错误码 | 说明 | HTTP 状态码 |
|--------|------|-------------|
| 10001 | 认证失败（Token 无效或缺失） | 401 |
| 10002 | Token 已过期 | 401 |
| 10003 | 权限不足（非管理员访问管理接口） | 403 |
| 10004 | 用户名或密码错误 | 401 |
| 10005 | Token 刷新失败 | 400 |

### 4.2 参数校验 (20000-29999)

| 错误码 | 说明 | HTTP 状态码 |
|--------|------|-------------|
| 20001 | 参数错误（缺少必填字段或格式不正确） | 400 |
| 20002 | 资源不存在 | 404 |
| 20003 | 请求方法不支持 | 405 |
| 20004 | 内容过大 | 413 |

### 4.3 业务逻辑 (30000-39999)

| 错误码 | 说明 | HTTP 状态码 |
|--------|------|-------------|
| 30001 | 知识库名称已存在 | 409 |
| 30002 | 文档解析失败 | 422 |
| 30003 | 不支持的文件格式 | 400 |
| 30004 | 文件大小超限 | 413 |
| 30005 | 知识库数量超出限制 | 429 |
| 30006 | 文档数量超出限制 | 429 |
| 30007 | 旧密码错误 | 400 |

### 4.4 限流配额 (40000-49999)

| 错误码 | 说明 | HTTP 状态码 |
|--------|------|-------------|
| 40001 | 请求过于频繁 | 429 |
| 40002 | 存储空间不足 | 507 |

### 4.5 系统错误 (50000-59999)

| 错误码 | 说明 | HTTP 状态码 |
|--------|------|-------------|
| 50001 | 服务器内部错误 | 500 |
| 50002 | 第三方服务不可用（LLM/Embedding/Qdrant） | 502 |
| 50003 | 数据库连接失败 | 503 |

---

## 5. 分页规范

所有列表接口统一使用以下查询参数：

| 参数 | 类型 | 默认值 | 范围 | 说明 |
|------|------|--------|------|------|
| `page` | int | 1 | ≥ 1 | 页码 |
| `page_size` | int | 20 | 1-100 | 每页数量 |
| `keyword` | string | "" | — | 搜索关键词（可选） |
| `sort_by` | string | "created_at" | — | 排序字段（可选） |
| `sort_order` | string | "desc" | asc/desc | 排序方向（可选） |

---

## 6. 速率限制

| 接口 | 粒度 | 阈值 |
|------|------|------|
| 登录/注册 | IP | 5 次/分钟 |
| 聊天消息 | 用户 | 20 次/分钟 |
| 文档上传 | 用户 | 10 次/小时 |
| 全局 API | 用户 | 1000 次/分钟 |

超出限制返回 HTTP 429 状态码和 `Retry-After` 响应头。