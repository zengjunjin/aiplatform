from abc import ABC, abstractmethod
from typing import AsyncIterator


class BaseLLMProvider(ABC):
    '''LLM 提供方抽象基类'''

    @abstractmethod
    async def chat_stream(self, messages: list[dict], temperature: float = 0.7) -> AsyncIterator[str]:
        '''流式返回 token 片段'''
        ...

    @abstractmethod
    async def chat(self, messages: list[dict], temperature: float = 0.7, stream: bool = False, **kwargs) -> str | AsyncIterator[str]:
        '''非流式返回完整文本；stream=True 时返回 AsyncIterator[str]'''
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        '''健康检查：验证 API 是否可用'''
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        '''提供方名称标识'''
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        '''当前使用的模型名称'''
        ...

    @property
    def is_healthy(self) -> bool:
        '''是否健康（默认 True）'''
        return True


class BaseEmbeddingProvider(ABC):
    '''Embedding 提供方抽象基类'''

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        '''批量向量化'''
        ...

    @property
    @abstractmethod
    def dim(self) -> int:
        '''向量维度'''
        ...


class BaseRerankerProvider(ABC):
    '''Reranker 提供方抽象基类'''

    @abstractmethod
    async def rerank(self, query: str, documents: list[str], top_k: int = 5) -> list[tuple[int, float]]:
        '''返回 (原文索引, 分数) 列表,按相关度降序'''
        ...
