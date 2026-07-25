"""Tests for app.core.middleware: RequestLogMiddleware + PrometheusMiddleware"""

from unittest.mock import MagicMock, patch

import pytest

from app.core.middleware import (
    PrometheusMiddleware,
    RequestLogMiddleware,
    rate_limit_exceeded_handler,
)


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


async def _run_middleware(
    middleware,
    method="GET",
    path="/api/v1/test",
    client_ip="127.0.0.1",
    status_code=200,
    raise_exc=None,
):
    """运行纯 ASGI 中间件, 捕获 http.response.start 消息。

    返回 dict: {headers, status, app_called}
    - headers: 响应 header 列表 [(bytes, bytes), ...]
    - status: 响应状态码 int
    - app_called: 内部 app 是否被调用
    """
    captured = {"headers": [], "status": None, "app_called": False}

    async def mock_app(scope, receive, send):
        captured["app_called"] = True
        if raise_exc:
            raise raise_exc
        await send({"type": "http.response.start", "status": status_code, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware.app = mock_app

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
    }
    if client_ip is not None:
        scope["client"] = (client_ip, 12345)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["headers"] = message.get("headers", [])
            captured["status"] = message["status"]

    await middleware(scope, receive, send)
    return captured


def _headers_to_dict(headers):
    """把 [(bytes, bytes), ...] 转为 {lower_str: str} 字典, 便于断言"""
    return {k.decode().lower(): v.decode() for k, v in headers}


class TestRequestLogMiddleware:
    @pytest.mark.asyncio
    async def test_dispatch_adds_request_id_header(self):
        """Response 应添加 X-Request-ID 和 X-Process-Time header"""
        middleware = RequestLogMiddleware(app=None)
        captured = await _run_middleware(middleware, path="/api/v1/test")
        headers = _headers_to_dict(captured["headers"])
        assert "x-request-id" in headers
        assert "x-process-time" in headers
        assert "ms" in headers["x-process-time"]

    @pytest.mark.asyncio
    async def test_dispatch_handles_no_client(self):
        """request.client 为 None 时不报错"""
        middleware = RequestLogMiddleware(app=None)
        captured = await _run_middleware(middleware, client_ip=None)
        headers = _headers_to_dict(captured["headers"])
        assert "x-request-id" in headers

    @pytest.mark.asyncio
    async def test_dispatch_logs_start_and_end(self):
        middleware = RequestLogMiddleware(app=None)
        with patch("app.core.middleware.logger") as mock_logger:
            await _run_middleware(
                middleware, method="POST", path="/api/v1/auth/login", status_code=201
            )
            # 应有 2 次 info 日志：start + end
            assert mock_logger.info.call_count == 2

    @pytest.mark.asyncio
    async def test_dispatch_generates_unique_request_id(self):
        """每次请求生成不同的 request_id"""
        middleware = RequestLogMiddleware(app=None)
        ids = set()
        for _ in range(5):
            captured = await _run_middleware(middleware)
            headers = _headers_to_dict(captured["headers"])
            ids.add(headers["x-request-id"])
        # 5 次应有至少 4 个不同 id（极小概率冲突）
        assert len(ids) >= 4


class TestPrometheusMiddleware:
    @pytest.mark.asyncio
    async def test_dispatch_increments_request_total(self):
        """正常请求 → REQUEST_TOTAL + REQUEST_LATENCY 记录"""
        middleware = PrometheusMiddleware(app=None)

        with (
            patch("app.core.middleware.REQUEST_TOTAL") as mock_total,
            patch("app.core.middleware.REQUEST_LATENCY") as mock_latency,
            patch("app.core.middleware.REQUEST_IN_PROGRESS") as mock_inprogress,
        ):
            await _run_middleware(middleware, method="GET", path="/api/v1/docs", status_code=200)

        assert mock_inprogress.inc.call_count >= 1
        assert mock_inprogress.dec.call_count >= 1
        mock_total.labels.assert_called_with(method="GET", path="/api/v1/docs", status_code="200")
        mock_total.labels.return_value.inc.assert_called_once()
        mock_latency.labels.assert_called_with(method="GET", path="/api/v1/docs")

    @pytest.mark.asyncio
    async def test_dispatch_excludes_metrics_and_health_paths(self):
        """/metrics 和 /healthz 路径跳过 Prometheus 统计"""
        middleware = PrometheusMiddleware(app=None)

        for excluded in ["/metrics", "/healthz"]:
            with (
                patch("app.core.middleware.REQUEST_TOTAL") as mock_total,
                patch("app.core.middleware.REQUEST_IN_PROGRESS") as mock_inprogress,
            ):
                captured = await _run_middleware(middleware, path=excluded)
                # EXCLUDE_PATHS 路径不统计
                mock_total.labels.assert_not_called()
                mock_inprogress.inc.assert_not_called()
            # 但 app 仍被调用
            assert captured["app_called"]

    @pytest.mark.asyncio
    async def test_dispatch_decrements_in_progress_on_exception(self):
        """即使 inner app 抛异常，REQUEST_IN_PROGRESS 仍要 dec"""
        middleware = PrometheusMiddleware(app=None)

        with (
            patch("app.core.middleware.REQUEST_IN_PROGRESS") as mock_inprogress,
            patch("app.core.middleware.REQUEST_TOTAL"),
            patch("app.core.middleware.REQUEST_LATENCY"),
        ):
            with pytest.raises(RuntimeError):
                await _run_middleware(
                    middleware, path="/api/v1/error", raise_exc=RuntimeError("oops")
                )

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


class TestRateLimitKeyFunc:
    """限流 key 函数: 优先 JWT sub, fallback IP"""

    def test_no_auth_header_falls_back_to_ip(self):
        """无 Authorization header → 使用 IP"""
        from app.core.middleware import _rate_limit_key

        request = MagicMock()
        request.headers = {}
        request.client = MagicMock(host="203.0.113.5")
        key = _rate_limit_key(request)
        assert key == "203.0.113.5"

    def test_invalid_bearer_token_falls_back_to_ip(self):
        """无效 Bearer token → fallback 到 IP（验证签名防伪造）"""
        from app.core.middleware import _rate_limit_key

        request = MagicMock()
        request.headers = {"authorization": "Bearer invalid.token.here"}
        request.client = MagicMock(host="198.51.100.7")
        key = _rate_limit_key(request)
        # 无效 token 会触发异常, fallback 到 IP
        assert key == "198.51.100.7"

    def test_valid_jwt_sub_used_as_key(self):
        """有效 JWT 的 sub 字段应作为 key（避免共享 IP 用户互相影响）"""
        from app.core.middleware import _rate_limit_key
        from app.core.security import create_access_token

        # 真实签发一个 token: subject 即 user_id
        token = create_access_token(subject="42")
        request = MagicMock()
        request.headers = {"authorization": f"Bearer {token}"}
        request.client = MagicMock(host="10.0.0.1")
        key = _rate_limit_key(request)
        assert key == "user:42"
        # 不应包含 IP
        assert "10.0.0.1" not in key


class TestRouteRateLimits:
    """验证 Task 23 限流策略: 每个路由配置正确的 limit"""

    EXPECTED_LIMITS = {
        # users 路由: 60/minute 默认
        "app.api.v1.users.search_users": "60 per 1 minute",
        "app.api.v1.users.list_users": "60 per 1 minute",
        "app.api.v1.users.update_role": "60 per 1 minute",
        "app.api.v1.users.update_status": "60 per 1 minute",
        # knowledge-bases 路由: 60/minute 默认
        "app.api.v1.knowledge_bases.create_kb": "60 per 1 minute",
        "app.api.v1.knowledge_bases.list_kbs": "60 per 1 minute",
        "app.api.v1.knowledge_bases.get_kb": "60 per 1 minute",
        "app.api.v1.knowledge_bases.update_kb": "60 per 1 minute",
        "app.api.v1.knowledge_bases.delete_kb": "60 per 1 minute",
        "app.api.v1.knowledge_bases.add_collaborator": "60 per 1 minute",
        "app.api.v1.knowledge_bases.remove_collaborator": "60 per 1 minute",
        "app.api.v1.knowledge_bases.get_collaborators": "60 per 1 minute",
        # documents 路由: 默认 60/minute, 高消耗端点更严格
        "app.api.v1.documents.upload_document": "10 per 1 hour",
        "app.api.v1.documents.list_documents": "60 per 1 minute",
        "app.api.v1.documents.get_document": "60 per 1 minute",
        "app.api.v1.documents.get_progress": "60 per 1 minute",
        "app.api.v1.documents.delete_document": "60 per 1 minute",
        "app.api.v1.documents.reparse_document": "5 per 1 hour",
        "app.api.v1.documents.preview_document": "30 per 1 minute",
        # evaluation 路由: 默认 60/minute, trigger 3/hour
        "app.api.v1.evaluation.trigger_evaluation": "3 per 1 hour",
        "app.api.v1.evaluation.list_evaluation_runs": "60 per 1 minute",
        "app.api.v1.evaluation.get_evaluation_run": "60 per 1 minute",
        "app.api.v1.evaluation.get_evaluation_results": "60 per 1 minute",
        "app.api.v1.evaluation.delete_evaluation_run": "60 per 1 minute",
        # system 路由: 60/minute 默认
        "app.api.v1.system.system_status": "60 per 1 minute",
        "app.api.v1.system.list_models": "60 per 1 minute",
    }

    @pytest.fixture(autouse=True)
    def _import_routes(self):
        """导入路由模块以触发 @limiter.limit 装饰器注册限流配置"""
        # noqa: F401 - 导入副作用是必要的
        from app.api.v1 import documents, evaluation, knowledge_bases, system, users  # noqa

    def test_all_expected_routes_have_limits(self):
        """所有期望的路由都已注册到 limiter._route_limits"""
        from app.core.middleware import limiter

        registered = set(limiter._route_limits.keys())
        missing = set(self.EXPECTED_LIMITS.keys()) - registered
        assert not missing, f"缺少限流配置的路由: {missing}"

    def test_each_route_has_expected_limit_value(self):
        """每个路由的 limit 值与预期一致"""
        from app.core.middleware import limiter

        mismatches = []
        for route_name, expected_limit in self.EXPECTED_LIMITS.items():
            limits = limiter._route_limits.get(route_name, [])
            if not limits:
                mismatches.append(f"{route_name}: 未注册限流")
                continue
            # limit.limit 是 RateLimitItem* 对象, 转换为 str 比较
            actual = str(limits[0].limit)
            if actual != expected_limit:
                mismatches.append(f"{route_name}: 期望 {expected_limit!r}, 实际 {actual!r}")
        assert not mismatches, "限流值不匹配:\n  " + "\n  ".join(mismatches)

    def test_high_cost_endpoints_have_stricter_limits(self):
        """高消耗端点应有比默认 60/minute 更严格的限制"""
        from app.core.middleware import limiter

        # documents/upload: 10/hour (预先存在, 不应被破坏)
        upload_limits = limiter._route_limits.get("app.api.v1.documents.upload_document", [])
        assert upload_limits and str(upload_limits[0].limit) == "10 per 1 hour"
        # documents/reparse: 5/hour
        reparse_limits = limiter._route_limits.get("app.api.v1.documents.reparse_document", [])
        assert reparse_limits and str(reparse_limits[0].limit) == "5 per 1 hour"
        # documents/preview: 30/minute
        preview_limits = limiter._route_limits.get("app.api.v1.documents.preview_document", [])
        assert preview_limits and str(preview_limits[0].limit) == "30 per 1 minute"
        # evaluation/trigger: 3/hour
        trigger_limits = limiter._route_limits.get("app.api.v1.evaluation.trigger_evaluation", [])
        assert trigger_limits and str(trigger_limits[0].limit) == "3 per 1 hour"

    def test_default_limit_count(self):
        """应有 26 个路由注册限流（5 个路由文件覆盖的所有端点）"""
        from app.core.middleware import limiter

        # users:4 + kb:8 + documents:7 + evaluation:5 + system:2 = 26
        assert len(limiter._route_limits) >= 26


class TestRateLimitEnforcement:
    """集成测试: 验证限流实际生效（使用 MemoryStorage）"""

    @pytest.fixture
    def _make_request_with_unique_ip(self):
        """工厂: 创建使用指定 IP 的 Request, 用于隔离测试间的限流计数"""
        from starlette.requests import Request

        def _make(ip: str = "127.0.0.1", path: str = "/api/v1/test"):
            scope = {
                "type": "http",
                "method": "GET",
                "path": path,
                "headers": [],
                "query_string": b"",
                "client": (ip, 8000),
            }
            return Request(scope)

        return _make

    @pytest.mark.asyncio
    async def test_rate_limit_triggers_on_exceed(self, _make_request_with_unique_ip):
        """超过 limit 时应抛出 RateLimitExceeded

        注意: slowapi 在同一 Request 对象上只检查一次（_rate_limiting_complete 标志）,
        所以每个调用必须使用新的 Request 对象。
        """
        from slowapi import Limiter
        from slowapi.errors import RateLimitExceeded
        from slowapi.util import get_remote_address

        # 使用独立 limiter 避免污染全局状态
        test_limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")

        @test_limiter.limit("2/minute")
        async def dummy(request):
            return "ok"

        # 每次调用都用新 Request（不同 IP 也可，但同一 IP 内的多次调用才会触发限流）
        # 实际 HTTP 请求每次都是新的 Request 对象，故此处模拟真实场景
        unique_ip = "192.0.2.99"
        r1 = await dummy(_make_request_with_unique_ip(ip=unique_ip))
        r2 = await dummy(_make_request_with_unique_ip(ip=unique_ip))
        assert r1 == "ok" and r2 == "ok"
        # 第三次（同 IP）应抛 RateLimitExceeded
        with pytest.raises(RateLimitExceeded):
            await dummy(_make_request_with_unique_ip(ip=unique_ip))

    @pytest.mark.asyncio
    async def test_rate_limit_does_not_trigger_within_limit(self, _make_request_with_unique_ip):
        """在 limit 范围内应正常通过"""
        from slowapi import Limiter
        from slowapi.util import get_remote_address

        test_limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")

        @test_limiter.limit("5/minute")
        async def dummy(request):
            return "ok"

        unique_ip = "198.51.100.99"
        # 调用 5 次都应成功（每次都用新 Request, 同 IP）
        for _ in range(5):
            assert await dummy(_make_request_with_unique_ip(ip=unique_ip)) == "ok"

    @pytest.mark.asyncio
    async def test_rate_limit_isolated_by_user_id(self, _make_request_with_unique_ip):
        """不同 user_id 的限流计数应独立（JWT sub 优先于 IP 的核心价值）"""

        from app.core.middleware import _rate_limit_key
        from app.core.security import create_access_token

        # 验证两个不同 user_id 生成不同的限流 key
        token1 = create_access_token(subject="100")
        token2 = create_access_token(subject="200")

        req1 = MagicMock()
        req1.headers = {"authorization": f"Bearer {token1}"}
        req1.client = MagicMock(host="10.0.0.1")

        req2 = MagicMock()
        req2.headers = {"authorization": f"Bearer {token2}"}
        req2.client = MagicMock(host="10.0.0.1")  # 同 IP

        key1 = _rate_limit_key(req1)
        key2 = _rate_limit_key(req2)
        # 同 IP 但不同 user_id → 不同 key
        assert key1 == "user:100"
        assert key2 == "user:200"
        assert key1 != key2


class TestLogPatcherTraceId:
    """Task 4: loguru patcher 注入 trace_id / span_id"""

    def test_patcher_injects_trace_id_from_active_span(self):
        """有活跃 OTel span 时，record["extra"] 应包含 trace_id / span_id"""
        # opentelemetry 是可选依赖；未安装时跳过（patcher 的 try/except 会在运行时降级）
        pytest.importorskip("opentelemetry.trace")
        from app.core.middleware import _log_patcher

        # 构造 mock span context
        mock_ctx = MagicMock()
        mock_ctx.is_valid = True
        mock_ctx.trace_id = 12345678901234567890123456789012
        mock_ctx.span_id = 9876543210987654

        mock_span = MagicMock()
        mock_span.get_span_context.return_value = mock_ctx

        record = {"extra": {}, "message": "test"}
        # INVALID_SPAN 必须 patch 为与 mock_span 不同的对象，
        # 否则 `span is not INVALID_SPAN` 判断为 False，trace_id 不会被注入
        with (
            patch("opentelemetry.trace.get_current_span", return_value=mock_span),
            patch("opentelemetry.trace.INVALID_SPAN", MagicMock()),
        ):
            _log_patcher(record)

        # trace_id 应为 32 位十六进制
        assert len(record["extra"]["trace_id"]) == 32
        assert record["extra"]["trace_id"] == f"{mock_ctx.trace_id:032x}"
        # span_id 应为 16 位十六进制
        assert len(record["extra"]["span_id"]) == 16
        assert record["extra"]["span_id"] == f"{mock_ctx.span_id:016x}"

    def test_patcher_injects_empty_trace_id_without_span(self):
        """无活跃 span 时 trace_id / span_id 为空字符串（不报错）"""
        # opentelemetry 是可选依赖；未安装时跳过（此用例验证 OTel 可用但无 span 的场景）
        pytest.importorskip("opentelemetry.trace")
        from app.core.middleware import _log_patcher

        record = {"extra": {}, "message": "test"}
        # mock get_current_span 返回 INVALID_SPAN
        invalid_span = MagicMock()
        with (
            patch("opentelemetry.trace.get_current_span", return_value=invalid_span),
            patch("opentelemetry.trace.INVALID_SPAN", invalid_span),
        ):
            _log_patcher(record)

        assert record["extra"]["trace_id"] == ""
        assert record["extra"]["span_id"] == ""

    def test_patcher_injects_empty_trace_id_when_otel_unavailable(self):
        """opentelemetry 未安装时（ImportError）patcher 不报错，注入空字符串"""
        from app.core import middleware as mw

        record = {"extra": {}, "message": "test"}
        # 模拟 import 失败：通过在 _log_patcher 内部 patch import 抛 ImportError
        # 由于 _log_patcher 内部用 from opentelemetry.trace import ...，
        # 我们 patch sys.modules 让 opentelemetry.trace 不可用
        import sys

        original = sys.modules.get("opentelemetry.trace")
        sys.modules["opentelemetry.trace"] = None  # 触发 ImportError
        try:
            mw._log_patcher(record)
        finally:
            if original is not None:
                sys.modules["opentelemetry.trace"] = original
            else:
                sys.modules.pop("opentelemetry.trace", None)

        assert record["extra"]["trace_id"] == ""
        assert record["extra"]["span_id"] == ""

    def test_patcher_always_injects_request_id(self):
        """request_id 始终被注入（来自 contextvar）"""
        from app.core.middleware import _log_patcher, request_id_var

        token = request_id_var.set("test-req-123")
        try:
            record = {"extra": {}, "message": "test"}
            _log_patcher(record)
            assert record["extra"]["request_id"] == "test-req-123"
        finally:
            request_id_var.reset(token)


class TestLogRedactFilter:
    """Task 5: loguru 日志脱敏过滤"""

    def test_redact_password(self):
        """password 字段值应被替换为 ***REDACTED***"""
        from app.core.middleware import _redact_filter

        record = {"message": "user login password='abc123' ok"}
        result = _redact_filter(record)
        assert result is True
        assert "abc123" not in record["message"]
        assert "***REDACTED***" in record["message"]

    def test_redact_token(self):
        """token 字段值应被替换"""
        from app.core.middleware import _redact_filter

        record = {"message": "auth token=eyJhbGciOiJIUzI1 failed"}
        result = _redact_filter(record)
        assert result is True
        assert "eyJhbGciOiJIUzI1" not in record["message"]
        assert "***REDACTED***" in record["message"]

    def test_redact_api_key(self):
        """api_key 字段值应被替换"""
        from app.core.middleware import _redact_filter

        record = {"message": "config api_key: sk-12345abcde"}
        result = _redact_filter(record)
        assert result is True
        assert "sk-12345abcde" not in record["message"]
        assert "***REDACTED***" in record["message"]

    def test_redact_secret(self):
        """secret 字段值应被替换"""
        from app.core.middleware import _redact_filter

        record = {"message": 'jwt secret="mysecret" loaded'}
        result = _redact_filter(record)
        assert result is True
        assert "mysecret" not in record["message"]
        assert "***REDACTED***" in record["message"]

    def test_redact_case_insensitive(self):
        """大写 PASSWORD 也应被匹配（re.I）"""
        from app.core.middleware import _redact_filter

        record = {"message": "PASSWORD=topsecret123"}
        result = _redact_filter(record)
        assert result is True
        assert "topsecret123" not in record["message"]
        assert "***REDACTED***" in record["message"]

    def test_redact_preserves_non_sensitive_fields(self):
        """非敏感字段保持不变"""
        from app.core.middleware import _redact_filter

        record = {"message": "user_id=42 action=login status=ok"}
        result = _redact_filter(record)
        assert result is True
        assert record["message"] == "user_id=42 action=login status=ok"

    def test_redact_handles_empty_message(self):
        """空 message 不报错"""
        from app.core.middleware import _redact_filter

        record = {"message": ""}
        result = _redact_filter(record)
        assert result is True
        assert record["message"] == ""

    def test_redact_handles_missing_message(self):
        """record 无 message 字段时不报错"""
        from app.core.middleware import _redact_filter

        record = {}
        result = _redact_filter(record)
        assert result is True
