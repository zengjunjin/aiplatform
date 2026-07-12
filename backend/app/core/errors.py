from enum import IntEnum


class ErrorCode(IntEnum):
    SUCCESS = 0, "success"
    AUTH_FAILED = 10001, "认证失败"
    TOKEN_EXPIRED = 10002, "Token 已过期"
    PERMISSION_DENIED = 10003, "权限不足"
    INVALID_CREDENTIALS = 10004, "用户名或密码错误"
    TOKEN_REFRESH_FAILED = 10005, "Token 刷新失败"
    VALIDATION_ERROR = 20001, "参数错误"
    RESOURCE_NOT_FOUND = 20002, "资源不存在"
    METHOD_NOT_ALLOWED = 20003, "请求方法不支持"
    PAYLOAD_TOO_LARGE = 20004, "内容过大"
    KB_NAME_EXISTS = 30001, "知识库名称已存在"
    DOC_PARSE_FAILED = 30002, "文档解析失败"
    UNSUPPORTED_FILE_TYPE = 30003, "不支持的文件格式"
    FILE_TOO_LARGE = 30004, "文件大小超限"
    KB_LIMIT_EXCEEDED = 30005, "知识库数量超出限制"
    DOC_LIMIT_EXCEEDED = 30006, "文档数量超出限制"
    OLD_PASSWORD_WRONG = 30007, "旧密码错误"
    RATE_LIMITED = 40001, "请求过于频繁"
    STORAGE_LIMIT_EXCEEDED = 40002, "存储空间不足"
    INTERNAL_ERROR = 50001, "服务器内部错误"
    SERVICE_UNAVAILABLE = 50002, "第三方服务不可用"
    DB_CONNECTION_FAILED = 50003, "数据库连接失败"

    def __new__(cls, value, message):
        obj = int.__new__(cls, value)
        obj._value_ = value
        obj.message = message
        return obj


def get_error_message(code: int) -> str:
    try:
        return ErrorCode(code).message
    except ValueError:
        return "未知错误"
