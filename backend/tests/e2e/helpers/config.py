"""E2E 测试 timeout 集中配置

所有测试 timeout 常量在此定义，支持环境变量覆盖。
便于在 CI 慢机器上统一调大 timeout。
"""

import os


def _env_int(name: str, default: int) -> int:
    """从环境变量读取整数，失败时用默认值。"""
    try:
        return int(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        return default


# CDP 连接相关
CDP_CONNECT_TIMEOUT = _env_int("CDP_CONNECT_TIMEOUT", 30)
"""CdpClient.connect() 超时（秒）"""

CDP_COMMAND_TIMEOUT = _env_int("CDP_COMMAND_TIMEOUT", 30)
"""单个 CDP 命令响应超时（秒）"""

# 文档解析等待
DOC_WAIT_TIMEOUT = _env_int("DOC_WAIT_TIMEOUT", 60)
"""轮询文档解析完成的最大等待时间（秒）"""

# SSE 流式响应
SSE_STREAM_TIMEOUT = _env_int("SSE_STREAM_TIMEOUT", 60)
"""SSE 流式响应整体超时（秒）"""

# 评估完成
EVALUATION_TIMEOUT = _env_int("EVALUATION_TIMEOUT", 600)
"""评估运行完成的最大等待时间（秒，默认 10 分钟）"""

# 单个测试用例
TEST_CASE_TIMEOUT = _env_int("TEST_CASE_TIMEOUT", 180)
"""单个 E2E 测试用例的整体超时（秒）"""
