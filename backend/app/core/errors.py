from enum import IntEnum


class ErrorCode(IntEnum):
    SUCCESS = 0

    AUTH_FAILED = 10001
    TOKEN_EXPIRED = 10002
    PERMISSION_DENIED = 10003
    INVALID_CREDENTIALS = 10004
    TOKEN_REFRESH_FAILED = 10005

    VALIDATION_ERROR = 20001
    RESOURCE_NOT_FOUND = 20002
    METHOD_NOT_ALLOWED = 20003
    PAYLOAD_TOO_LARGE = 20004

    KB_NAME_EXISTS = 30001
    DOC_PARSE_FAILED = 30002
    UNSUPPORTED_FILE_TYPE = 30003
    FILE_TOO_LARGE = 30004
    KB_LIMIT_EXCEEDED = 30005
    DOC_LIMIT_EXCEEDED = 30006
    OLD_PASSWORD_WRONG = 30007

    RATE_LIMITED = 40001
    STORAGE_LIMIT_EXCEEDED = 40002

    INTERNAL_ERROR = 50001
    SERVICE_UNAVAILABLE = 50002
    DB_CONNECTION_FAILED = 50003


ERROR_MESSAGES = {
    ErrorCode.SUCCESS: "success",
    ErrorCode.AUTH_FAILED: "认证失败",
    ErrorCode.TOKEN_EXPIRED: "Token 已过期",
    ErrorCode.PERMISSION_DENIED: "权限不足",
    ErrorCode.INVALID_CREDENTIALS: "用户名或密码错误",
    ErrorCode.TOKEN_REFRESH_FAILED: "Token 刷新失败",
    ErrorCode.VALIDATION_ERROR: "参数错误",
    ErrorCode.RESOURCE_NOT_FOUND: "资源不存在",
    ErrorCode.METHOD_NOT_ALLOWED: "请求方法不支持",
    ErrorCode.PAYLOAD_TOO_LARGE: "内容过大",
    ErrorCode.KB_NAME_EXISTS: "知识库名称已存在",
    ErrorCode.DOC_PARSE_FAILED: "文档解析失败",
    ErrorCode.UNSUPPORTED_FILE_TYPE: "不支持的文件格式",
    ErrorCode.FILE_TOO_LARGE: "文件大小超限",
    ErrorCode.KB_LIMIT_EXCEEDED: "知识库数量超出限制",
    ErrorCode.DOC_LIMIT_EXCEEDED: "文档数量超出限制",
    ErrorCode.OLD_PASSWORD_WRONG: "旧密码错误",
    ErrorCode.RATE_LIMITED: "请求过于频繁",
    ErrorCode.STORAGE_LIMIT_EXCEEDED: "存储空间不足",
    ErrorCode.INTERNAL_ERROR: "服务器内部错误",
    ErrorCode.SERVICE_UNAVAILABLE: "第三方服务不可用",
    ErrorCode.DB_CONNECTION_FAILED: "数据库连接失败",
}


def get_error_message(code: int) -> str:
    return ERROR_MESSAGES.get(code, "未知错误")
