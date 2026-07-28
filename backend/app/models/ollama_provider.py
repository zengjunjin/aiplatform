import asyncio
import json
from collections.abc import AsyncIterator

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.models.base import BaseEmbeddingProvider, BaseLLMProvider


def _is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code >= 500 or status_code == 429
    return bool(isinstance(exc, httpx.NetworkError | httpx.TimeoutException | httpx.ConnectError))


def _build_client(timeout: float = 60.0) -> httpx.AsyncClient:
    """长生命周期的 httpx.AsyncClient，复用连接池以提升性能。"""
    return httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=30,
        ),
        timeout=httpx.Timeout(timeout, connect=10.0),
    )


class OllamaLLMProvider(BaseLLMProvider):
    def __init__(self, model: str | None = None, host: str | None = None, provider_name: str | None = None):
        self.model = model or settings.LLM_MODEL
        self.host = host or settings.OLLAMA_HOST
        self._provider_name = provider_name or "ollama"
        self._healthy = True
        # 长生命周期 httpx client：复用连接池，避免每次请求都重新建立 TCP/TLS
        self._client = _build_client(timeout=300.0)

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    async def close(self) -> None:
        """关闭底层 httpx 连接池，应用 shutdown 时调用。"""
        await self._client.aclose()

    async def chat_stream(
        self, messages: list[dict], temperature: float = 0.7
    ) -> AsyncIterator[str]:
        async with self._client.stream(
            "POST",
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": True,
                "options": {"temperature": temperature},
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if chunk.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable_error),
        reraise=True,
        before_sleep=lambda retry_state: logger.warning(
            f"Ollama LLM chat retry attempt {retry_state.attempt_number} after error: {retry_state.outcome.exception()}"
        ),
    )
    async def chat(
        self, messages: list[dict], temperature: float = 0.7, stream: bool = False, **kwargs
    ) -> str | AsyncIterator[str]:
        if stream:
            return self.chat_stream(messages, temperature=temperature)
        resp = await self._client.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "")

    async def health_check(self) -> bool:
        """通过 Ollama 的 /api/tags 端点进行健康检查。

        仅返回检查结果，不修改 self._healthy（由 ModelHealthChecker 根据连续失败计数统一管理）。
        """
        try:
            resp = await self._client.get(f"{self.host}/api/tags")
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            return False


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, model: str | None = None, host: str | None = None):
        self.model = model or settings.EMBEDDING_MODEL
        self.host = host or settings.OLLAMA_HOST
        # 长生命周期 httpx client：复用连接池
        self._client = _build_client(timeout=60.0)

    @property
    def dim(self) -> int:
        return settings.EMBEDDING_DIM

    async def close(self) -> None:
        """关闭底层 httpx 连接池，应用 shutdown 时调用。"""
        await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable_error),
        reraise=True,
        before_sleep=lambda retry_state: logger.warning(
            f"Ollama embedding retry attempt {retry_state.attempt_number} after error: {retry_state.outcome.exception()}"
        ),
    )
    async def _embed_single(self, text: str) -> list[float]:
        resp = await self._client.post(
            f"{self.host}/api/embeddings",
            json={"model": self.model, "prompt": text},
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """并发批量 embedding。

        使用信号量限制并发数 (Ollama 默认 OLLAMA_NUM_PARALLEL=1, 过高并发无益且可能导致 OOM)。
        默认并发 4, 可通过 EMBEDDING_CONCURRENCY 环境变量调整。
        """
        if not texts:
            return []
        max_concurrency = getattr(settings, "EMBEDDING_CONCURRENCY", 4)
        semaphore = asyncio.Semaphore(max_concurrency)

        async def embed_with_limit(text: str, idx: int) -> tuple[int, list[float]]:
            async with semaphore:
                embedding = await self._embed_single(text)
                return idx, embedding

        tasks = [embed_with_limit(text, i) for i, text in enumerate(texts)]
        results = await asyncio.gather(*tasks)

        # 按原始顺序排序
        results.sort(key=lambda x: x[0])
        return [emb for _, emb in results]
