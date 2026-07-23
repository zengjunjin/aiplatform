import json
import os
import re
from collections.abc import AsyncIterator

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.models.base import BaseLLMProvider


def _resolve_env_vars(value: str) -> str:
    '''替换字符串中的 ${VAR_NAME} 为环境变量值'''
    if not value:
        return value

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    return re.sub(r"\$\{(\w+)\}", _replace, value)


def _is_retryable_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code >= 500 or status_code == 429
    if isinstance(exc, (httpx.NetworkError, httpx.TimeoutException, httpx.ConnectError)):
        return True
    return False


class OpenAICompatibleProvider(BaseLLMProvider):
    '''OpenAI 兼容 API 提供方（支持 Groq、DeepSeek、OpenRouter 等）'''

    def __init__(
        self,
        api_base: str,
        api_key: str = "",
        model: str = "gpt-3.5-turbo",
        provider_name: str = "openai_compatible",
        max_retries: int = 3,
        timeout: float = 300.0,
    ):
        self._api_base = api_base.rstrip("/")
        self._api_key = _resolve_env_vars(api_key)
        self._model = model
        self._provider_name = provider_name
        self._max_retries = max_retries
        self._timeout = timeout
        self._healthy = True
        # 长生命周期 httpx client：复用连接池，避免每次请求都重新建立 TCP/TLS
        self._client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
                keepalive_expiry=30,
            ),
            timeout=httpx.Timeout(self._timeout, connect=10.0),
        )

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def close(self) -> None:
        """关闭底层 httpx 连接池，应用 shutdown 时调用。"""
        await self._client.aclose()

    async def chat_stream(self, messages: list[dict], temperature: float = 0.7) -> AsyncIterator[str]:
        '''流式聊天（兼容旧接口）'''
        async for token in self.chat(messages, temperature=temperature, stream=True):
            yield token

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable_error),
        reraise=True,
        before_sleep=lambda retry_state: logger.warning(
            f"OpenAICompatibleProvider chat retry attempt {retry_state.attempt_number} "
            f"after error: {retry_state.outcome.exception()}"
        ),
    )
    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        stream: bool = False,
        **kwargs,
    ) -> str | AsyncIterator[str]:
        '''发送聊天请求，支持流式和非流式'''
        url = f"{self._api_base}/chat/completions"
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
            **kwargs,
        }

        if stream:
            return self._stream_response(url, payload)
        return await self._non_stream_response(url, payload)

    async def _stream_response(
        self,
        url: str,
        payload: dict,
    ) -> AsyncIterator[str]:
        '''处理 SSE 流式响应，逐个 yield token'''
        async with self._client.stream(
            "POST",
            url,
            json=payload,
            headers=self._headers(),
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[len("data:"):].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    # 检查是否有 finish_reason 表示结束
                    if choices and choices[0].get("finish_reason"):
                        break
                except json.JSONDecodeError:
                    continue

    async def _non_stream_response(
        self,
        url: str,
        payload: dict,
    ) -> str:
        '''处理非流式响应，返回完整文本'''
        resp = await self._client.post(url, json=payload, headers=self._headers())
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return ""

    async def health_check(self) -> bool:
        '''发送最小请求验证 API 可用性。

        仅返回检查结果，不修改 self._healthy（由 ModelHealthChecker 根据连续失败计数统一管理）。
        '''
        try:
            url = f"{self._api_base}/models"
            resp = await self._client.get(url, headers=self._headers())
            if resp.status_code == 200:
                return True
            # 部分 API 不支持 /models 端点，尝试 /chat/completions
            url2 = f"{self._api_base}/chat/completions"
            resp2 = await self._client.post(
                url2,
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                    "stream": False,
                },
                headers=self._headers(),
            )
            return resp2.status_code < 500
        except Exception as e:
            logger.warning(f"Health check failed for {self._provider_name}: {e}")
            return False
