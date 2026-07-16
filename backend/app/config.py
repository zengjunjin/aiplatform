from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
import sys
import warnings
import json


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

    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

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

    RERANKER_MODEL: str = "BAAI/bge-reranker-base"

    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 50
    RETRIEVAL_TOP_K: int = 10
    RERANK_TOP_K: int = 5

    PASSWORD_MIN_LENGTH: int = 8
    PASSWORD_REQUIRE_UPPER: bool = True
    PASSWORD_REQUIRE_LOWER: bool = True
    PASSWORD_REQUIRE_DIGIT: bool = True
    PASSWORD_REQUIRE_SPECIAL: bool = True

    MAX_FILE_SIZE_MB: int = 20
    MAX_DOCUMENTS_PER_KB: int = 100

    CORS_ORIGINS: str = "tauri://localhost,https://tauri.localhost,http://tauri.localhost,http://localhost:1420,http://localhost:5173"

    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 30
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_PRE_PING: bool = True

    LOG_LEVEL: str = "info"

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
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()

# Security: forbid default/weak JWT secret in non-debug mode (prevent token forgery)
# Skip the check under pytest so tests can run without explicit JWT_SECRET.
_IS_TESTING = "pytest" in sys.modules
_DEFAULT_JWT_SECRET = "change-me-in-production"
if not settings.DEBUG and not _IS_TESTING:
    if settings.JWT_SECRET == _DEFAULT_JWT_SECRET:
        raise RuntimeError(
            "JWT_SECRET is set to the default value! "
            "Set a strong secret via the JWT_SECRET environment variable in production, "
            "or enable DEBUG mode for local development."
        )
    if len(settings.JWT_SECRET) < 16:
        raise RuntimeError(
            "JWT_SECRET is too short (minimum 16 characters). "
            "Set a stronger secret via the JWT_SECRET environment variable."
        )
# Warn if using default JWT secret in debug mode
if settings.DEBUG and settings.JWT_SECRET == _DEFAULT_JWT_SECRET:
    warnings.warn(
        "JWT_SECRET is set to the default value! "
        "Set a strong secret via environment variable in production.",
        RuntimeWarning,
        stacklevel=2,
    )
