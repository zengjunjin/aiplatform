# API 错误码对照表

## 概述

本文档列出平台所有 API 错误码及其含义，供前端、客户端与后端联调时对照使用。错误码统一定义在 `backend/app/core/errors.py` 的 `ErrorCode` 枚举中，配套异常类定义在 `backend/app/core/exceptions.py`。

## 错误码格式

错误码采用 **5 位整数** 编码，按业务模块分段：

```
[模块段] [具体错误编号]
  1xxxx  认证模块      (10xxx)
  2xxxx  请求/参数模块 (20xxx)
  3xxxx  业务模块      (30xxx) —— 知识库 / 文档 / 用户
  4xxxx  限流/存储模块 (40xxx)
  5xxxx  服务器模块    (50xxx)
```

- `0` 表示成功
- 同一模块内的错误码保持连续编号，便于扩展

## 统一响应格式

所有错误响应均遵循以下 JSON 结构：

```json
{
  "code": 30001,
  "message": "知识库名称已存在",
  "data": null
}
```

HTTP 状态码与业务错误码一一对应（见下表），客户端可同时依据 HTTP 状态码与 `code` 字段判断错误类型。

## 错误码列表

| 错误码常量 | 错误码值 | HTTP 状态码 | 含义 | 触发场景 |
|------------|----------|-------------|------|----------|
| `SUCCESS` | 0 | 200 | success | 请求成功 |
| `AUTH_FAILED` | 10001 | 401 | 认证失败 | Token 缺失、无效、已被吊销或用户不存在/被禁用 |
| `TOKEN_EXPIRED` | 10002 | 401 | Token 已过期 | Access Token 已过期（预留，当前归入 AUTH_FAILED） |
| `PERMISSION_DENIED` | 10003 | 403 | 权限不足 | 普通用户访问管理员接口、无知识库协作权限 |
| `INVALID_CREDENTIALS` | 10004 | 401 | 用户名或密码错误 | 登录时用户名不存在或密码不匹配 |
| `TOKEN_REFRESH_FAILED` | 10005 | 401 | Token 刷新失败 | Refresh Token 无效、已吊销或用户已被禁用（预留） |
| `VALIDATION_ERROR` | 20001 | 400 | 参数错误 | 请求体校验失败（Pydantic）、密码强度校验不通过 |
| `RESOURCE_NOT_FOUND` | 20002 | 404 | 资源不存在 | 知识库/文档/用户不存在，或无权访问 |
| `METHOD_NOT_ALLOWED` | 20003 | 405 | 请求方法不支持 | 对某接口使用了不支持的 HTTP 方法（预留） |
| `PAYLOAD_TOO_LARGE` | 20004 | 413 | 内容过大 | 请求体超过服务端限制（预留） |
| `KB_NAME_EXISTS` | 30001 | 409 | 知识库名称已存在 | 创建知识库时名称重复 |
| `DOC_PARSE_FAILED` | 30002 | 400 | 文档解析失败 | 文档预览时解析失败 |
| `UNSUPPORTED_FILE_TYPE` | 30003 | 400 | 不支持的文件格式 | 上传/预览的文件扩展名不在白名单 |
| `FILE_TOO_LARGE` | 30004 | 400 | 文件大小超限 | 上传文件超过 `MAX_FILE_SIZE_MB` 限制 |
| `KB_LIMIT_EXCEEDED` | 30005 | 409 | 知识库数量超出限制 | 用户创建的知识库数量超过上限（预留） |
| `DOC_LIMIT_EXCEEDED` | 30006 | 400 | 文档数量超出限制 | 单个知识库文档数超过 `MAX_DOCUMENTS_PER_KB` |
| `OLD_PASSWORD_WRONG` | 30007 | 400 | 旧密码错误 | 修改密码时旧密码校验失败（预留，当前使用 code=400） |
| `RATE_LIMITED` | 40001 | 429 | 请求过于频繁 | 触发限流中间件（IP 维度） |
| `STORAGE_LIMIT_EXCEEDED` | 40002 | 413 | 存储空间不足 | 存储空间不足（预留） |
| `INTERNAL_ERROR` | 50001 | 500 | 服务器内部错误 | 未捕获异常、文档记录创建/上传失败 |
| `SERVICE_UNAVAILABLE` | 50002 | 503 | 第三方服务不可用 | 第三方依赖不可用（预留） |
| `DB_CONNECTION_FAILED` | 50003 | 503 | 数据库连接失败 | 数据库连接异常（预留） |

> 标注「预留」的错误码已在 `ErrorCode` 中定义，但当前业务代码尚未通过对应异常类直接抛出，便于后续扩展使用。

## 按模块分组

### 认证模块（10xxx）

| 错误码常量 | 错误码值 | HTTP 状态码 | 含义 | 触发场景 |
|------------|----------|-------------|------|----------|
| `AUTH_FAILED` | 10001 | 401 | 认证失败 | Token 缺失、无效、已吊销、用户不存在或被禁用 |
| `TOKEN_EXPIRED` | 10002 | 401 | Token 已过期 | Access Token 已过期（预留） |
| `PERMISSION_DENIED` | 10003 | 403 | 权限不足 | 普通用户访问管理员接口、无知识库协作权限 |
| `INVALID_CREDENTIALS` | 10004 | 401 | 用户名或密码错误 | 登录失败 |
| `TOKEN_REFRESH_FAILED` | 10005 | 401 | Token 刷新失败 | Refresh Token 无效/已吊销（预留） |

### 请求/参数模块（20xxx）

| 错误码常量 | 错误码值 | HTTP 状态码 | 含义 | 触发场景 |
|------------|----------|-------------|------|----------|
| `VALIDATION_ERROR` | 20001 | 400 | 参数错误 | Pydantic 校验失败、密码强度不达标 |
| `RESOURCE_NOT_FOUND` | 20002 | 404 | 资源不存在 | 资源不存在或无权访问 |
| `METHOD_NOT_ALLOWED` | 20003 | 405 | 请求方法不支持 | HTTP 方法不支持（预留） |
| `PAYLOAD_TOO_LARGE` | 20004 | 413 | 内容过大 | 请求体过大（预留） |

### 业务模块（30xxx）—— 知识库 / 文档 / 用户

| 错误码常量 | 错误码值 | HTTP 状态码 | 含义 | 触发场景 |
|------------|----------|-------------|------|----------|
| `KB_NAME_EXISTS` | 30001 | 409 | 知识库名称已存在 | 创建知识库时名称重复 |
| `DOC_PARSE_FAILED` | 30002 | 400 | 文档解析失败 | 文档预览解析失败 |
| `UNSUPPORTED_FILE_TYPE` | 30003 | 400 | 不支持的文件格式 | 文件扩展名不在白名单 |
| `FILE_TOO_LARGE` | 30004 | 400 | 文件大小超限 | 上传文件超过 `MAX_FILE_SIZE_MB` |
| `KB_LIMIT_EXCEEDED` | 30005 | 409 | 知识库数量超出限制 | 知识库数超过上限（预留） |
| `DOC_LIMIT_EXCEEDED` | 30006 | 400 | 文档数量超出限制 | 单知识库文档数超过 `MAX_DOCUMENTS_PER_KB` |
| `OLD_PASSWORD_WRONG` | 30007 | 400 | 旧密码错误 | 修改密码时旧密码错误（预留） |

### 限流/存储模块（40xxx）

| 错误码常量 | 错误码值 | HTTP 状态码 | 含义 | 触发场景 |
|------------|----------|-------------|------|----------|
| `RATE_LIMITED` | 40001 | 429 | 请求过于频繁 | 触发限流中间件 |
| `STORAGE_LIMIT_EXCEEDED` | 40002 | 413 | 存储空间不足 | 存储空间不足（预留） |

### 服务器模块（50xxx）

| 错误码常量 | 错误码值 | HTTP 状态码 | 含义 | 触发场景 |
|------------|----------|-------------|------|----------|
| `INTERNAL_ERROR` | 50001 | 500 | 服务器内部错误 | 未捕获异常、上传/记录创建失败 |
| `SERVICE_UNAVAILABLE` | 50002 | 503 | 第三方服务不可用 | 第三方依赖不可用（预留） |
| `DB_CONNECTION_FAILED` | 50003 | 503 | 数据库连接失败 | 数据库连接异常（预留） |

## 异常类映射

业务代码通过 `backend/app/core/exceptions.py` 中定义的异常类抛出错误，每个异常类已绑定默认错误码与 HTTP 状态码：

| 异常类 | 默认错误码 | HTTP 状态码 | 说明 |
|--------|-----------|-------------|------|
| `AppException` | 自定义 | 400（默认） | 基类，可携带任意 `code` / `message` / `status_code` |
| `NotFoundError` | `RESOURCE_NOT_FOUND` (20002) | 404 | 资源不存在 |
| `AuthError` | `AUTH_FAILED` (10001) | 401 | 认证失败，可在构造时传入其它认证类错误码 |
| `ForbiddenError` | `PERMISSION_DENIED` (10003) | 403 | 权限不足 |
| `ConflictError` | `KB_NAME_EXISTS` (30001) | 409 | 资源冲突（默认为知识库名称冲突） |
| `RateLimitError` | `RATE_LIMITED` (40001) | 429 | 限流 |
| `ValidationError` | `VALIDATION_ERROR` (20001) | 400 | 参数校验失败 |

### 全局异常处理器

`backend/app/core/exceptions.py` 注册了三个全局异常处理器：

1. `app_exception_handler`：捕获 `AppException`，按异常携带的 `status_code` 与 `code` 返回。
2. `validation_exception_handler`：捕获 FastAPI `RequestValidationError`，固定返回 HTTP 400 + `VALIDATION_ERROR` (20001)，`message` 中拼接所有字段错误。
3. `generic_exception_handler`：捕获未处理的 `Exception`，固定返回 HTTP 500 + `INTERNAL_ERROR` (50001)。

## 错误码使用示例

```python
from app.core.exceptions import AuthError, NotFoundError, ConflictError
from app.core.errors import ErrorCode

# 1. 使用默认错误码
raise NotFoundError("Knowledge base not found")          # -> 20002 / 404
raise ConflictError("同名知识库已存在")                  # -> 30001 / 409

# 2. 指定具体错误码（AuthError 支持传入 code）
raise AuthError("用户名或密码错误", code=ErrorCode.INVALID_CREDENTIALS)  # -> 10004 / 401

# 3. 直接使用基类（不推荐，建议优先使用子类）
from app.core.exceptions import AppException
raise AppException(code=ErrorCode.FILE_TOO_LARGE, message="文件过大")    # -> 30004 / 400
```

## 维护说明

- 新增错误码时，必须在 `backend/app/core/errors.py` 的 `ErrorCode` 枚举中登记，并遵循模块分段规则。
- 新增错误码后，请同步更新本文档「错误码列表」与「按模块分组」两张表。
- 错误码一经发布不可复用/重定义，仅可扩展，以保持客户端兼容性。
