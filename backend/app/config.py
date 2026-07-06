from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
import warnings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    APP_NAME: str = "RAG Platform"
    DEBUG: bool = False

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

    EMBEDDING_PROVIDER: str = "ollama"
    EMBEDDING_MODEL: str = "bge-m3"
    EMBEDDING_DIM: int = 1024

    RERANKER_MODEL: str = "BAAI/bge-reranker-base"

    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 50

    MAX_FILE_SIZE_MB: int = 20
    MAX_DOCUMENTS_PER_KB: int = 100

    CORS_ORIGINS: str = "tauri://localhost,https://tauri.localhost,http://localhost:1420,http://localhost:5173"

    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

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

# Warn if using default JWT secret in non-debug mode
if not settings.DEBUG and settings.JWT_SECRET == "change-me-in-production":
    warnings.warn(
        "JWT_SECRET is set to the default value! "
        "Set a strong secret via environment variable in production.",
        RuntimeWarning,
        stacklevel=2,
    )
