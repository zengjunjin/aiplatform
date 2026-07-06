"""Tests for app.core.middleware: RequestLogMiddleware + PrometheusMiddleware"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.middleware import RequestLogMiddleware, PrometheusMiddleware, rate_limit_exceeded_handler


def _make_request(method="GET", path="/api/v1/test", client_ip="127.0.0.1"):
    request = MagicMock()
    request.method = method
    request.url.path = path
    request.client = MagicMock(host=client_ip)
    return request


def _make_response(status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.headers = {}
    return response


class TestRequestLogMiddleware:
    @pytest.mark.asyncio
    async def test_dispatch_adds_request_id_header(self):
        """Response 应添加 X-Request-ID 和 X-Process-Time header"""
        middleware = RequestLogMiddleware(app=MagicMock())

        request = _make_request()
        response = _make_response(200)

        async def call_next(req):
            return response

        result = await middleware.dispatch(request, call_next)
        assert "X-Request-ID" in result.headers
        assert "X-Process-Time" in result.headers
        assert "ms" in result.headers["X-Process-Time"]

    @pytest.mark.asyncio
    async def test_dispatch_handles_no_client(self):
        """request.client 为 None 时不报错"""
        middleware = RequestLogMiddleware(app=MagicMock())
        request = _make_request()
        request.client = None

        async def call_next(req):
            return _make_response()

        result = await middleware.dispatch(request, call_next)
        assert "X-Request-ID" in result.headers

    @pytest.mark.asyncio
    async def test_dispatch_logs_start_and_end(self):
        middleware = RequestLogMiddleware(app=MagicMock())
        request = _make_request(method="POST", path="/api/v1/auth/login")

        async def call_next(req):
            return _make_response(201)

        with patch("app.core.middleware.logger") as mock_logger:
            await middleware.dispatch(request, call_next)
            # 应有 2 次 info 日志：start + end
            assert mock_logger.info.call_count == 2

    @pytest.mark.asyncio
    async def test_dispatch_generates_unique_request_id(self):
        """每次请求生成不同的 request_id"""
        middleware = RequestLogMiddleware(app=MagicMock())
        ids = set()

        for _ in range(5):
            request = _make_request()

            async def call_next(req):
                return _make_response()

            result = await middleware.dispatch(request, call_next)
            ids.add(result.headers["X-Request-ID"])
        # 5 次应有至少 4 个不同 id（极小概率冲突）
        assert len(ids) >= 4


class TestPrometheusMiddleware:
    @pytest.mark.asyncio
    async def test_dispatch_increments_request_total(self):
        """正常请求 → REQUEST_TOTAL + REQUEST_LATENCY 记录"""
        middleware = PrometheusMiddleware(app=MagicMock())
        request = _make_request(path="/api/v1/docs")

        async def call_next(req):
            return _make_response(200)

        with patch("app.core.middleware.REQUEST_TOTAL") as mock_total, \
             patch("app.core.middleware.REQUEST_LATENCY") as mock_latency, \
             patch("app.core.middleware.REQUEST_IN_PROGRESS") as mock_inprogress:
            result = await middleware.dispatch(request, call_next)

        mock_in_progress_inc_calls = mock_inprogress.inc.call_count
        assert mock_inprogress.inc.call_count >= 1
        assert mock_inprogress.dec.call_count >= 1
        mock_total.labels.assert_called_with(method="GET", path="/api/v1/docs", status_code="200")
        mock_total.labels.return_value.inc.assert_called_once()
        mock_latency.labels.assert_called_with(method="GET", path="/api/v1/docs")

    @pytest.mark.asyncio
    async def test_dispatch_excludes_metrics_and_health_paths(self):
        """/metrics 和 /health 路径跳过 Prometheus 统计"""
        middleware = PrometheusMiddleware(app=MagicMock())

        for excluded in ["/metrics", "/health"]:
            request = _make_request(path=excluded)
            called = False

            async def call_next(req):
                nonlocal called
                called = True
                return _make_response()

            with patch("app.core.middleware.REQUEST_TOTAL") as mock_total, \
                 patch("app.core.middleware.REQUEST_IN_PROGRESS") as mock_inprogress:
                await middleware.dispatch(request, call_next)
                # EXCLUDE_PATHS 路径不统计
                mock_total.labels.assert_not_called()
                mock_inprogress.inc.assert_not_called()
            assert called

    @pytest.mark.asyncio
    async def test_dispatch_decrements_in_progress_on_exception(self):
        """即使 call_next 抛异常，REQUEST_IN_PROGRESS 仍要 dec"""
        middleware = PrometheusMiddleware(app=MagicMock())
        request = _make_request(path="/api/v1/error")

        async def call_next(req):
            raise RuntimeError("oops")

        with patch("app.core.middleware.REQUEST_IN_PROGRESS") as mock_inprogress, \
             patch("app.core.middleware.REQUEST_TOTAL"), \
             patch("app.core.middleware.REQUEST_LATENCY"):
            with pytest.raises(RuntimeError):
                await middleware.dispatch(request, call_next)

        # finally 块保证 dec 被调用
        assert mock_inprogress.dec.call_count >= 1


class TestRateLimitExceededHandler:
    @pytest.mark.asyncio
    async def test_rate_limit_handler_returns_429(self):
        """限流触发 → 429 + Retry-After header"""
        from slowapi.errors import RateLimitExceeded
        # RateLimitExceeded 构造复杂，用 mock 替代
        exc = MagicMock(spec=RateLimitExceeded)
        request = _make_request(path="/api/v1/auth/login")

        response = await rate_limit_exceeded_handler(request, exc)
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "60"
        import json
        body = json.loads(response.body)
        from app.core.errors import ErrorCode
        assert body["code"] == ErrorCode.RATE_LIMITED


class TestLimiterInstance:
    def test_limiter_exists(self):
        """limiter 单例已导出"""
        from app.core.middleware import limiter
        assert limiter is not None

    def test_limiter_key_func_uses_remote_address(self):
        """limiter 的 key_func 应基于 remote address"""
        from app.core.middleware import limiter
        # 构造一个 request
        request = MagicMock()
        request.client = MagicMock(host="1.2.3.4")
        key = limiter._key_func(request)
        assert "1.2.3.4" in key
