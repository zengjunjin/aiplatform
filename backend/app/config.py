import json
import sys
from typing import Any, ClassVar

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProviderConfig(BaseModel):
    name: str
    type: str = "ollama"
    model: str
    api_base: str = ""
    api_key: str = ""
    priority: int = 99
    max_retries: int = 3
    timeout: int = 300
    fallback_to: str | None = None
    is_free: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "RAG Platform"
    DEBUG: bool = False
    ENABLE_DOCS: bool = False

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "rag"
    POSTGRES_PASSWORD: str = "rag_dev_pwd"
    POSTGRES_DB: str = "rag_platform"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_GRPC_PORT: int = 6334

    OLLAMA_HOST: str = "http://localhost:11434"

    JWT_SECRET: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # JWT iss/aud 校验（Task 25：BREAKING - 旧 token 全部失效需重新登录）
    JWT_ISSUER: str = "rag-platform"
    JWT_AUDIENCE: str = "rag-client"

    LLM_PROVIDER: str = "ollama"
    LLM_MODEL: str = "qwen2.5:7b"

    # LLM 提供商配置（JSON 格式）
    LLM_PROVIDERS_JSON: str = (
        '[{"name":"ollama","type":"ollama","api_base":"http://localhost:11434/v1","model":"qwen2.5:7b",'
        '"priority":99,"max_retries":1,"timeout":300,"fallback_to":null,"is_free":true}]'
    )

    @property
    def LLM_PROVIDERS(self) -> list[LLMProviderConfig]:
        try:
            raw = json.loads(self.LLM_PROVIDERS_JSON)
            return [LLMProviderConfig(**item) for item in raw]
        except (json.JSONDecodeError, TypeError):
            return []

    # 默认路由策略
    LLM_ROUTING_STRATEGY: str = "round_robin"

    # 是否启用 Fallback
    LLM_FALLBACK_ENABLED: bool = True

    # 模型健康检查间隔（秒）
    LLM_HEALTH_CHECK_INTERVAL: int = 30

    EMBEDDING_PROVIDER: str = "ollama"
    EMBEDDING_MODEL: str = "bge-m3"
    EMBEDDING_DIM: int = 1024
    EMBEDDING_CONCURRENCY: int = 4

    # 嵌入向量缓存（供 Task 7 使用：减少对 Ollama 重复嵌入请求）
    EMBEDDING_CACHE_ENABLED: bool = True
    EMBEDDING_CACHE_TTL: int = 604800  # 7 天（秒）

    RERANKER_MODEL: str = "BAAI/bge-reranker-base"

    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 50
    RETRIEVAL_TOP_K: int = 10
    RERANK_TOP_K: int = 5
    # Task 2.7: BM25/向量融合 alpha 权重（1.0 纯向量，0.0 纯 BM25，0.5 等权加权）
    # alpha=None 时回退 RRF 融合；KB 级覆盖由 Task 2.8 接入
    RETRIEVAL_ALPHA: float = 0.5

    # Task 11: 上下文窗口 token 预算配置化（从 context_manager.py 类属性迁移）
    HISTORY_TOKEN_BUDGET: int = 6000
    RETRIEVAL_TOKEN_BUDGET: int = 4000

    # Task 13: 检索结果 score 阈值过滤（低于此分数的 chunks 不进入 prompt）
    RETRIEVAL_SCORE_THRESHOLD: float = 0.3

    # 查询扩展开关：开启后检索前生成多个查询变体并行检索（默认关闭以保持现有行为）
    QUERY_EXPANSION_ENABLED: bool = False

    # BM25 检索 score 阈值过滤（BM25 score 数值范围与 vector 不同，0.01 为合理下限）
    # 低于此分数的 chunks 不进入 RRF 融合
    BM25_SCORE_THRESHOLD: float = 0.01

    # Task 2.1: 聊天历史上下文长度统一（消除 chat.py / chat_service.py / context_manager.py 中的魔法数字）
    CHAT_HISTORY_LIMIT: int = 20
    CHAT_HISTORY_KEEP_RECENT: int = 4

    # Task 13: Redis 聊天上下文缓存配置（TTL + 保留条数）
    CHAT_HISTORY_TTL_SECONDS: int = 86400
    CHAT_HISTORY_REDIS_KEEP_RECENT: int = 20

    # Task 2.2: 评估管线并发度统一（消除 evaluation.py / evaluation_task.py / evaluation_service.py 中的魔法数字）
    EVAL_CONCURRENCY: int = 8

    # Task 36: Celery 任务重试策略配置化（消除 document_task / evaluation_task 中的魔法数字）
    # 文档解析任务重试次数（解析失败可重试，避免瞬时网络/模型抖动导致永久失败）
    TASK_MAX_RETRIES_PARSING: int = 3
    # 评估任务重试次数（评估较重，重试次数较少避免浪费资源）
    TASK_MAX_RETRIES_EVALUATION: int = 2

    PASSWORD_MIN_LENGTH: int = 8
    PASSWORD_REQUIRE_UPPER: bool = True
    PASSWORD_REQUIRE_LOWER: bool = True
    PASSWORD_REQUIRE_DIGIT: bool = True
    PASSWORD_REQUIRE_SPECIAL: bool = True

    MAX_FILE_SIZE_MB: int = 20
    MAX_DOCUMENTS_PER_KB: int = 100

    # BM25 缓存安全
    BM25_CACHE_MAX_KB: int = 8
    BM25_CACHE_MAX_CHUNKS_PER_KB: int = 50000

    # retriever singleflight 锁 LRU 上限（防 KB 增多后锁字典无界增长导致内存泄漏）
    RETRIEVER_LOCKS_MAX_SIZE: int = 100

    CORS_ORIGINS: str = "tauri://localhost,https://tauri.localhost,http://tauri.localhost,http://localhost:1420,http://localhost:5173"

    # WebSocket 允许的 Origin 白名单（逗号分隔）。
    # 空字符串 Origin（非浏览器客户端）允许通过；浏览器 Origin 必须在白名单内。
    # 包含 Tauri 2 Windows release 模式所需的 https://tauri.localhost / http://tauri.localhost。
    WEBSOCKET_ALLOWED_ORIGINS: str = (
        "tauri://localhost,"
        "https://tauri.localhost,"
        "http://tauri.localhost,"
        "http://localhost:1420,"
        "http://localhost:5173,"
        "http://localhost:8000,"
        "http://127.0.0.1:8000"
    )

    # WebSocket 单用户最大并发连接数
    WEBSOCKET_MAX_CONNECTIONS_PER_USER: int = 5

    # WebSocket 接收循环 ping/pong 超时（秒，无消息则关闭）
    WEBSOCKET_RECV_TIMEOUT: int = 30

    # WebSocket 单用户消息频率限制（每分钟消息数，超过则关闭）
    WEBSOCKET_RATE_LIMIT_PER_MINUTE: int = 10

    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 30
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_PRE_PING: bool = True
    # Task 26: 连接池获取超时（秒），避免请求无限等待连接
    DB_POOL_TIMEOUT: int = 10

    LOG_LEVEL: str = "info"

    # Task 46: 是否启用 loguru JSON sink（结构化日志）
    # true 时日志以 JSON 格式输出，便于 ELK/Loki 等日志采集系统解析；
    # false 时保持原有人类可读格式不变
    LOG_JSON: bool = False

    # 限流
    RATE_LIMIT_ENABLED: bool = True

    # Prometheus 抓取端点 (/internal/metrics) 的 Bearer token
    # 未配置时该端点返回 503；生产环境用 `openssl rand -hex 32` 生成强随机值
    METRICS_TOKEN: str | None = None

    # Task 20: SSE 流式接口的并发与取消控制参数（从 chat.py 魔法数字迁移而来）
    # 单用户最大并发 SSE 连接数（防止滥用）
    SSE_MAX_CONCURRENT: int = 3
    # SSE 计数器 Redis key 的 TTL（秒，10 分钟过期保护，防止计数器泄漏）
    SSE_COUNT_TTL: int = 600
    # 流式生成时每 N 个 token 检查一次取消标志（平衡 RTT 与响应灵敏度）
    CANCEL_CHECK_INTERVAL: int = 16

    # Task 47: 从各模块硬编码值迁移而来的配置项（默认值与原硬编码一致）
    # 摘要触发的历史长度阈值（历史消息超过此长度时触发摘要压缩）
    SUMMARY_TRIGGER_HISTORY_LEN: int = 10
    # 评估增量提交批次大小（每 N 个问题提交一次，避免全部结果丢失）
    EVAL_INCREMENTAL_COMMIT_BATCH: int = 10
    # RRF（Reciprocal Rank Fusion）融合参数 k
    RRF_K: int = 60
    # BM25 索引在 Redis 中的 TTL（秒，86400 = 1 天）
    BM25_INDEX_TTL: int = 86400
    # 反馈分析报告保留数量（清理旧报告时保留最近 N 个）
    FEEDBACK_REPORT_KEEP_COUNT: int = 12
    # 业务指标采集循环间隔（秒）
    METRICS_COLLECTOR_INTERVAL: int = 60
    # 文件存储根目录（空字符串表示自动使用 backend/ 目录）
    STORAGE_DIR: str = ""

    # Task 40: 散落常量迁移——TTL/上限/超时配置化（默认值与原硬编码一致）
    # 对话摘要缓存 TTL（秒，1 小时）——原 redis_client.py SUMMARY_TTL
    CHAT_SUMMARY_TTL: int = 3600
    # 通用缓存默认 TTL（秒，5 分钟）——原 cache.py cache_set 默认参数
    CACHE_DEFAULT_TTL: int = 300
    # WebSocket 离线消息 TTL（秒，7 天）——原 notification_manager.py _OFFLINE_TTL
    WEBSOCKET_OFFLINE_MESSAGE_TTL: int = 604800
    # LLM 健康检查：连续失败多少次后标记为 unhealthy——原 model_health.py MAX_FAILURES
    LLM_HEALTH_CHECK_MAX_FAILURES: int = 3
    # LLM 健康检查：单个 Provider 检查超时（秒）——原 model_health.py CHECK_TIMEOUT
    LLM_HEALTH_CHECK_TIMEOUT: int = 10
    # WebSocket 进程内频率计数器 LRU 上限——原 ws.py _INPROC_RATE_LRU_MAX
    WEBSOCKET_INPROC_RATE_LRU_MAX: int = 10000
    # WebSocket 心跳间隔（秒）——原 ws.py _heartbeat sleep(30)
    WEBSOCKET_HEARTBEAT_INTERVAL: int = 30
    # WebSocket 心跳 pong 等待超时（秒）——原 ws.py _heartbeat wait_for timeout=10.0
    WEBSOCKET_HEARTBEAT_PONG_TIMEOUT: int = 10
    # WebSocket 心跳连续未响应次数上限——原 ws.py _heartbeat missed >= 3
    WEBSOCKET_HEARTBEAT_MAX_MISSED: int = 3
    # WebSocket 频率限制窗口（秒）——原 ws.py _check_rate_limit window=60
    WEBSOCKET_RATE_LIMIT_WINDOW: int = 60
    # 流式生成取消标志 TTL（秒，5 分钟自动清理）——原 chat_service.py request_cancel ttl=300
    CHAT_CANCEL_TTL: int = 300
    # 文档处理进度缓存 TTL（秒，1 小时）——原 document_task.py setex 3600
    DOC_PROGRESS_CACHE_TTL: int = 3600

    # Task 3.6: 硬编码值配置化（默认值与原硬编码一致，可通过环境变量覆盖）
    # 用户信息缓存 TTL（秒）——原 deps.py USER_CACHE_TTL
    USER_CACHE_TTL: int = 60
    # 优雅关闭超时（秒）——原 main.py lifespan timeout=30
    GRACEFUL_SHUTDOWN_TIMEOUT: int = 30
    # 内存黑名单上限（Redis 不可用降级时防无限增长）——原 auth_service.py _memory_blacklist_max
    TOKEN_BLACKLIST_MAX: int = 10000

    @property
    def database_url_async(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def websocket_allowed_origins_list(self) -> list[str]:
        """WebSocket 允许的 Origin 列表（解析自 WEBSOCKET_ALLOWED_ORIGINS）"""
        return [o.strip() for o in self.WEBSOCKET_ALLOWED_ORIGINS.split(",") if o.strip()]

    # ---- 弱密钥黑名单（用于 model_post_init 校验） ----
    # 已知弱 JWT_SECRET：包括代码默认值、示例值、常见占位符
    _WEAK_JWT_SECRETS: ClassVar[tuple[str, ...]] = (
        "change-me-in-production",
        "dev-secret-key-change-in-production-2026",
        "please_change_this_to_a_long_random_string_at_least_32_chars",
        "change_me",
        "secret",
        "",
    )
    # 已知弱 POSTGRES_PASSWORD：包括代码默认值、示例值、常见占位符
    _WEAK_PG_PASSWORDS: ClassVar[tuple[str, ...]] = (
        "rag_dev_pwd",
        "rag_password",
        "change_this_password",
        "postgres",
        "password",
    )

    def model_post_init(self, __context: Any) -> None:
        """Pydantic v2 钩子：实例化完成后执行密钥/密码强度校验。

        - 校验不通过抛出 ValueError 阻止启动（DEBUG 模式同样阻止）；
        - pytest 环境下完全跳过，避免污染单元测试。
        """
        super().model_post_init(__context)

        # pytest 环境跳过校验，便于测试使用任意配置
        if "pytest" in sys.modules:
            return

        problems: list[str] = []

        # --- JWT_SECRET 校验 ---
        if len(self.JWT_SECRET) < 32:
            problems.append(
                "JWT_SECRET 长度不足（最少 32 字符，当前 " f"{len(self.JWT_SECRET)} 字符）。"
            )
        if self.JWT_SECRET in self._WEAK_JWT_SECRETS:
            problems.append("JWT_SECRET 命中已知弱值黑名单。")

        # --- POSTGRES_PASSWORD 校验 ---
        if self.POSTGRES_PASSWORD in self._WEAK_PG_PASSWORDS:
            problems.append("POSTGRES_PASSWORD 命中已知弱值黑名单。")

        if not problems:
            return

        message = (
            "配置校验失败：\n  - " + "\n  - ".join(problems) + "\n"
            "请通过环境变量或 .env 文件设置强随机值后再启动。"
        )

        # Task 31: 即使 DEBUG 模式也阻止启动（移除 warning 分支），
        # 避免 JWT_SECRET 弱密钥在开发环境被误用导致生产泄漏。
        # Pydantic 会将 ValueError 包装为 ValidationError。
        raise ValueError(message)


settings = Settings()
