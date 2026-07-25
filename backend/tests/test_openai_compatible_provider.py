"""Tests for app.models.openai_compatible_provider.OpenAICompatibleProvider"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.models.openai_compatible_provider import (
    OpenAICompatibleProvider,
    _is_retryable_error,
    _resolve_env_vars,
)


def _make_provider(transport: httpx.MockTransport, **kwargs) -> OpenAICompatibleProvider:
    """创建使用 MockTransport 的 provider，避免真实网络请求"""
    defaults = {
        "api_base": "http://test-api.example.com",
        "api_key": "test-key",
        "model": "test-model",
        "provider_name": "test_provider",
        "max_retries": 3,
        "timeout": 30.0,
    }
    defaults.update(kwargs)
    provider = OpenAICompatibleProvider(**defaults)
    # 替换内部 httpx client 为使用 MockTransport 的 client
    provider._client = httpx.AsyncClient(transport=transport)
    return provider


class TestResolveEnvVars:
    def test_resolve_env_vars_replaces_placeholder(self, monkeypatch):
        """${VAR} 替换为环境变量值"""
        monkeypatch.setenv("MY_API_KEY", "secret123")
        result = _resolve_env_vars("Bearer ${MY_API_KEY}")
        assert result == "Bearer secret123"

    def test_resolve_env_vars_multiple_placeholders(self, monkeypatch):
        """多个 ${VAR} 都被替换"""
        monkeypatch.setenv("HOST", "example.com")
        monkeypatch.setenv("PORT", "8080")
        result = _resolve_env_vars("${HOST}:${PORT}")
        assert result == "example.com:8080"

    def test_resolve_env_vars_unset_var_becomes_empty(self, monkeypatch):
        """未设置的环境变量替换为空字符串"""
        monkeypatch.delenv("UNSET_VAR", raising=False)
        result = _resolve_env_vars("key-${UNSET_VAR}-end")
        assert result == "key--end"

    def test_resolve_env_vars_empty_string(self):
        """空字符串原样返回"""
        assert _resolve_env_vars("") == ""

    def test_resolve_env_vars_no_placeholders(self):
        """无占位符的字符串原样返回"""
        assert _resolve_env_vars("plain text") == "plain text"


class TestIsRetryableError:
    def test_5xx_is_retryable(self):
        """500 错误可重试"""
        request = httpx.Request("POST", "http://test")
        response = httpx.Response(500, request=request)
        exc = httpx.HTTPStatusError("500", request=request, response=response)
        assert _is_retryable_error(exc) is True

    def test_429_is_retryable(self):
        """429 错误可重试"""
        request = httpx.Request("POST", "http://test")
        response = httpx.Response(429, request=request)
        exc = httpx.HTTPStatusError("429", request=request, response=response)
        assert _is_retryable_error(exc) is True

    def test_4xx_not_retryable(self):
        """400 错误不可重试"""
        request = httpx.Request("POST", "http://test")
        response = httpx.Response(400, request=request)
        exc = httpx.HTTPStatusError("400", request=request, response=response)
        assert _is_retryable_error(exc) is False

    def test_network_error_retryable(self):
        """网络错误可重试"""
        exc = httpx.ConnectError("connection refused")
        assert _is_retryable_error(exc) is True


class TestRetryOn5xx:
    @pytest.mark.asyncio
    async def test_retry_on_5xx(self):
        """500 重试 3 次（tenacity stop_after_attempt=3），最终抛出 HTTPStatusError"""
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(500, text="Internal Server Error")

        transport = httpx.MockTransport(handler)
        provider = _make_provider(transport)

        # patch asyncio.sleep 避免 tenacity 真实等待
        with patch("asyncio.sleep", new=AsyncMock()):
            with pytest.raises(httpx.HTTPStatusError):
                await provider.chat([{"role": "user", "content": "hi"}])

        # tenacity stop_after_attempt(3) → 共 3 次请求
        assert call_count == 3
        await provider._client.aclose()


class TestRetryOn429:
    @pytest.mark.asyncio
    async def test_retry_on_429(self):
        """429 重试 3 次，最终抛出 HTTPStatusError"""
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(429, text="Rate Limited")

        transport = httpx.MockTransport(handler)
        provider = _make_provider(transport)

        with patch("asyncio.sleep", new=AsyncMock()):
            with pytest.raises(httpx.HTTPStatusError):
                await provider.chat([{"role": "user", "content": "hi"}])

        assert call_count == 3
        await provider._client.aclose()


class TestNoRetryOn4xx:
    @pytest.mark.asyncio
    async def test_no_retry_on_4xx(self):
        """400 不重试，仅 1 次请求后抛出"""
        call_count = 0

        def handler(request):
            nonlocal call_count
            call_count += 1
            return httpx.Response(400, text="Bad Request")

        transport = httpx.MockTransport(handler)
        provider = _make_provider(transport)

        with pytest.raises(httpx.HTTPStatusError):
            await provider.chat([{"role": "user", "content": "hi"}])

        # 400 不可重试 → 仅 1 次请求
        assert call_count == 1
        await provider._client.aclose()


class TestSseParse:
    @pytest.mark.asyncio
    async def test_sse_parse(self):
        """data: 行解析 + [DONE] 终止"""
        sse_body = (
            'data: {"choices":[{"delta":{"content":"Hello"}}]}\n'
            "\n"
            'data: {"choices":[{"delta":{"content":" world"}}]}\n'
            "\n"
            "data: [DONE]\n"
            "\n"
        )

        def handler(request):
            return httpx.Response(200, text=sse_body)

        transport = httpx.MockTransport(handler)
        provider = _make_provider(transport)

        result = await provider.chat([{"role": "user", "content": "hi"}], stream=True)

        tokens = []
        async for token in result:
            tokens.append(token)

        assert tokens == ["Hello", " world"]
        await provider._client.aclose()

    @pytest.mark.asyncio
    async def test_sse_parse_finish_reason_terminates(self):
        """finish_reason 出现时终止流"""
        sse_body = (
            'data: {"choices":[{"delta":{"content":"Hi"}}]}\n'
            "\n"
            'data: {"choices":[{"delta":{"content":"!"},"finish_reason":"stop"}]}\n'
            "\n"
            'data: {"choices":[{"delta":{"content":"should not appear"}}]}\n'
            "\n"
        )

        def handler(request):
            return httpx.Response(200, text=sse_body)

        transport = httpx.MockTransport(handler)
        provider = _make_provider(transport)

        result = await provider.chat([{"role": "user", "content": "hi"}], stream=True)
        tokens = []
        async for token in result:
            tokens.append(token)

        # finish_reason 终止后不再 yield
        assert tokens == ["Hi", "!"]
        await provider._client.aclose()

    @pytest.mark.asyncio
    async def test_sse_skips_invalid_json(self):
        """非法 JSON 行被跳过，不中断流"""
        sse_body = (
            "data: not json\n"
            "\n"
            'data: {"choices":[{"delta":{"content":"ok"}}]}\n'
            "\n"
            "data: [DONE]\n"
        )

        def handler(request):
            return httpx.Response(200, text=sse_body)

        transport = httpx.MockTransport(handler)
        provider = _make_provider(transport)

        result = await provider.chat([{"role": "user", "content": "hi"}], stream=True)
        tokens = []
        async for token in result:
            tokens.append(token)

        assert tokens == ["ok"]
        await provider._client.aclose()


class TestHealthCheckFallback:
    @pytest.mark.asyncio
    async def test_health_check_models_success(self):
        """/models 返回 200 → health_check 返回 True"""

        def handler(request):
            if request.url.path == "/models":
                return httpx.Response(200, json={"data": []})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        provider = _make_provider(transport)

        result = await provider.health_check()
        assert result is True
        await provider._client.aclose()

    @pytest.mark.asyncio
    async def test_health_check_fallback_to_chat_completions(self):
        """/models 失败 fallback 到 /chat/completions"""

        def handler(request):
            if request.url.path == "/models":
                return httpx.Response(404, text="Not Found")
            if request.url.path == "/chat/completions":
                return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        provider = _make_provider(transport)

        result = await provider.health_check()
        assert result is True
        await provider._client.aclose()

    @pytest.mark.asyncio
    async def test_health_check_both_fail_returns_false(self):
        """/models 和 /chat/completions 都失败 → 返回 False"""

        def handler(request):
            if request.url.path == "/models":
                return httpx.Response(500, text="Server Error")
            if request.url.path == "/chat/completions":
                return httpx.Response(500, text="Server Error")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        provider = _make_provider(transport)

        result = await provider.health_check()
        assert result is False
        await provider._client.aclose()

    @pytest.mark.asyncio
    async def test_health_check_chat_completions_4xx_still_true(self):
        """/chat/completions 返回 4xx（< 500）→ health_check 仍返回 True"""

        def handler(request):
            if request.url.path == "/models":
                return httpx.Response(404)
            if request.url.path == "/chat/completions":
                return httpx.Response(400, text="Bad Request")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        provider = _make_provider(transport)

        result = await provider.health_check()
        # 4xx < 500 → True
        assert result is True
        await provider._client.aclose()
