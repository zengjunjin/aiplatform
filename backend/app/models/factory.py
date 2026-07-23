import asyncio

from loguru import logger

from app.config import settings
from app.models.base import BaseEmbeddingProvider, BaseLLMProvider, BaseRerankerProvider
from app.models.cached_embedding import CachedEmbeddingProvider
from app.models.ollama_provider import OllamaEmbeddingProvider, OllamaLLMProvider
from app.models.openai_compatible_provider import OpenAICompatibleProvider
from app.models.reranker_provider import LocalBgeRerankerProvider


class ModelRegistry:
    '''模型注册表 — 管理所有 LLM Provider 实例'''

    _providers: dict[str, BaseLLMProvider] = {}
    _initialized: bool = False

    @classmethod
    def register(cls, provider: BaseLLMProvider) -> None:
        '''注册一个 Provider 实例'''
        cls._providers[provider.provider_name] = provider

    @classmethod
    def get(cls, name: str) -> BaseLLMProvider:
        '''按名称获取 Provider'''
        if name not in cls._providers:
            raise ValueError(f"Provider '{name}' not found in registry")
        return cls._providers[name]

    @classmethod
    def list_all(cls) -> list[str]:
        '''列出所有已注册的 Provider 名称'''
        return list(cls._providers.keys())

    @classmethod
    def get_available(cls) -> list[BaseLLMProvider]:
        '''获取所有健康的 Provider'''
        return [p for p in cls._providers.values() if p.is_healthy]

    @classmethod
    async def close_all(cls) -> None:
        '''关闭所有已注册 Provider 的底层连接（httpx 连接池等），应用 shutdown 时调用。'''
        if not cls._providers:
            return
        results = await asyncio.gather(
            *[p.close() for p in cls._providers.values()],
            return_exceptions=True,
        )
        for name, result in zip(cls._providers.keys(), results):
            if isinstance(result, Exception):
                logger.warning(f"Error closing provider '{name}': {result}")
        cls._providers.clear()
        cls._initialized = False

    @classmethod
    def init_from_config(cls) -> None:
        '''从 settings.LLM_PROVIDERS 配置初始化所有 Provider'''
        if cls._initialized:
            return
        cls._initialized = True

        providers_config = settings.LLM_PROVIDERS

        for cfg in providers_config:
            name = cfg.name
            provider_type = cfg.type
            model = cfg.model
            api_base = cfg.api_base
            api_key = cfg.api_key
            max_retries = cfg.max_retries
            timeout = cfg.timeout

            if not name or not model:
                logger.warning(f"Skipping invalid provider config: {cfg}")
                continue

            try:
                if provider_type == "ollama":
                    # Ollama 使用本地 host，忽略 api_base 中的 /v1 后缀
                    host = api_base.replace("/v1", "") if api_base else settings.OLLAMA_HOST
                    provider = OllamaLLMProvider(model=model, host=host)
                else:
                    provider = OpenAICompatibleProvider(
                        api_base=api_base,
                        api_key=api_key,
                        model=model,
                        provider_name=name,
                        max_retries=max_retries,
                        timeout=float(timeout),
                    )
                cls.register(provider)
                logger.info(f"Registered provider: {name} (type={provider_type}, model={model})")
            except Exception as e:
                logger.error(f"Failed to initialize provider '{name}': {e}")


class ModelFactory:
    '''根据配置创建 provider 实例（保持向后兼容）'''

    _llm: BaseLLMProvider | None = None
    _embedding: BaseEmbeddingProvider | None = None
    _reranker: BaseRerankerProvider | None = None

    @staticmethod
    def create_llm() -> BaseLLMProvider:
        if ModelFactory._llm is None:
            provider = settings.LLM_PROVIDER
            if provider == "ollama":
                ModelFactory._llm = OllamaLLMProvider()
            else:
                raise ValueError(f"Unknown LLM provider: {provider}")
        return ModelFactory._llm

    @staticmethod
    def create_embedding() -> BaseEmbeddingProvider:
        if ModelFactory._embedding is None:
            provider = settings.EMBEDDING_PROVIDER
            if provider == "ollama":
                inner = OllamaEmbeddingProvider()
            else:
                raise ValueError(f"Unknown Embedding provider: {provider}")
            if getattr(settings, "EMBEDDING_CACHE_ENABLED", False):
                ModelFactory._embedding = CachedEmbeddingProvider(inner)
            else:
                ModelFactory._embedding = inner
        return ModelFactory._embedding

    @staticmethod
    def create_reranker() -> BaseRerankerProvider:
        if ModelFactory._reranker is None:
            ModelFactory._reranker = LocalBgeRerankerProvider()
        return ModelFactory._reranker

    @staticmethod
    async def close_all() -> None:
        '''关闭所有由 ModelFactory 持有的 Provider 单例的底层连接，应用 shutdown 时调用。'''
        targets: list[BaseLLMProvider | BaseEmbeddingProvider | BaseRerankerProvider] = []
        if ModelFactory._llm is not None:
            targets.append(ModelFactory._llm)
        if ModelFactory._embedding is not None:
            # CachedEmbeddingProvider 包装的 inner provider 也可能持有 httpx 连接
            inner = getattr(ModelFactory._embedding, "inner", None)
            if inner is not None:
                targets.append(inner)
            targets.append(ModelFactory._embedding)
        if ModelFactory._reranker is not None:
            targets.append(ModelFactory._reranker)
        if not targets:
            return
        # 所有基类均提供默认 no-op close()，可直接调用
        results = await asyncio.gather(
            *[t.close() for t in targets],
            return_exceptions=True,
        )
        for target, result in zip(targets, results):
            if isinstance(result, Exception):
                logger.warning(f"Error closing {type(target).__name__}: {result}")
        ModelFactory._llm = None
        ModelFactory._embedding = None
        ModelFactory._reranker = None
