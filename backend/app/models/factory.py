from app.models.base import BaseLLMProvider, BaseEmbeddingProvider, BaseRerankerProvider
from app.models.ollama_provider import OllamaLLMProvider, OllamaEmbeddingProvider
from app.models.cached_embedding import CachedEmbeddingProvider
from app.models.reranker_provider import LocalBgeRerankerProvider
from app.config import settings


class ModelFactory:
    '''根据配置创建 provider 实例'''

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
