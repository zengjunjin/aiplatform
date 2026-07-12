import json
import asyncio
import httpx
from typing import AsyncIterator
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
)
from loguru import logger
from app.models.base import BaseLLMProvider, BaseEmbeddingProvider
from app.config import settings


def _is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code >= 500 or status_code == 429
    if isinstance(exc, (httpx.NetworkError, httpx.TimeoutException, httpx.ConnectError)):
        return True
    return False


class OllamaLLMProvider(BaseLLMProvider):
    def __init__(self, model: str | None = None, host: str | None = None):
        self.model = model or settings.LLM_MODEL
        self.host = host or settings.OLLAMA_HOST
        self._healthy = True

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self.model

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    async def chat_stream(self, messages: list[dict], temperature: float = 0.7) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
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
    async def chat(self, messages: list[dict], temperature: float = 0.7, stream: bool = False, **kwargs) -> str | AsyncIterator[str]:
        if stream:
            return self.chat_stream(messages, temperature=temperature)
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
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
        '''通过 Ollama 的 /api/tags 端点进行健康检查'''
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.host}/api/tags")
                if resp.status_code == 200:
                    self._healthy = True
                    return True
                self._healthy = False
                return False
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            self._healthy = False
            return False


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, model: str | None = None, host: str | None = None):
        self.model = model or settings.EMBEDDING_MODEL
        self.host = host or settings.OLLAMA_HOST

    @property
    def dim(self) -> int:
        return settings.EMBEDDING_DIM

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable_error),
        reraise=True,
        before_sleep=lambda retry_state: logger.warning(
            f"Ollama embedding retry attempt {retry_state.attempt_number} after error: {retry_state.outcome.exception()}"
        ),
    )
    async def _embed_single(self, client: httpx.AsyncClient, text: str) -> list[float]:
        resp = await client.post(
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

        async def embed_with_limit(client: httpx.AsyncClient, text: str, idx: int) -> tuple[int, list[float]]:
            async with semaphore:
                embedding = await self._embed_single(client, text)
                return idx, embedding

        async with httpx.AsyncClient(timeout=60.0) as client:
            tasks = [embed_with_limit(client, text, i) for i, text in enumerate(texts)]
            results = await asyncio.gather(*tasks)

        # 按原始顺序排序
        results.sort(key=lambda x: x[0])
        return [emb for _, emb in results]