"""OpenTelemetry 初始化逻辑测试

验证 _setup_opentelemetry() 的关键行为：
1. endpoint 为空时不初始化 tracer provider
2. sampler 使用 settings.OTEL_TRACES_SAMPLER_ARG
3. RedisInstrumentor 被调用
4. service_name 来自 settings.OTEL_SERVICE_NAME
5. 初始化失败时不阻断应用启动

注意：main.py 中 OTel 组件是在 _setup_opentelemetry() 函数内部 import 的，
因此不能用 patch("app.main.XXX")——必须 patch 源模块的属性，
这样函数内的 `from opentelemetry.X import Y` 才会拿到 mock。
"""

from unittest.mock import patch

# OTel 各组件的完整模块路径（patch 源模块而非 app.main，因为 import 在函数内部）
_TRACE = "opentelemetry.trace"
_TRACE_PROVIDER = "opentelemetry.sdk.trace.TracerProvider"
_RESOURCE = "opentelemetry.sdk.resources.Resource"
_BATCH_PROCESSOR = "opentelemetry.sdk.trace.export.BatchSpanProcessor"
_PARENT_BASED = "opentelemetry.sdk.trace.sampling.ParentBased"
_RATIO_BASED = "opentelemetry.sdk.trace.sampling.TraceIdRatioBased"
_OTLP_EXPORTER = "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter"
_SQLALCHEMY = "opentelemetry.instrumentation.sqlalchemy.SQLAlchemyInstrumentor"
_HTTPX = "opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor"
_CELERY = "opentelemetry.instrumentation.celery.CeleryInstrumentor"
_REDIS = "opentelemetry.instrumentation.redis.RedisInstrumentor"


def test_otel_disabled_when_endpoint_empty(monkeypatch):
    """endpoint 为空时应直接 return，不初始化 tracer provider。"""
    from app.config import settings
    from app.main import _setup_opentelemetry

    monkeypatch.setattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "")

    with patch(f"{_TRACE}.set_tracer_provider") as mock_set_provider:
        _setup_opentelemetry()
        # set_tracer_provider 不应被调用
        mock_set_provider.assert_not_called()


def test_otel_sampler_ratio_from_settings(monkeypatch):
    """sampler 应使用 settings.OTEL_TRACES_SAMPLER_ARG 的值。"""
    from app.config import settings
    from app.main import _setup_opentelemetry

    monkeypatch.setattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318")
    monkeypatch.setattr(settings, "OTEL_TRACES_SAMPLER_ARG", 0.5)

    with (
        patch(f"{_TRACE}.set_tracer_provider"),
        patch(_OTLP_EXPORTER),
        patch(_BATCH_PROCESSOR),
        patch(_TRACE_PROVIDER) as mock_provider_cls,
        patch(_RESOURCE),
        patch(_PARENT_BASED) as mock_parent_based,
        patch(_RATIO_BASED) as mock_ratio_based,
        patch(_SQLALCHEMY),
        patch(_HTTPX),
        patch(_CELERY),
        patch(_REDIS),
    ):
        _setup_opentelemetry()
        # TraceIdRatioBased 应使用 0.5
        mock_ratio_based.assert_called_once_with(0.5)
        # ParentBased 包装 TraceIdRatioBased
        mock_parent_based.assert_called_once_with(mock_ratio_based.return_value)
        # TracerProvider 应接收 sampler 参数
        mock_provider_cls.assert_called_once()
        _, kwargs = mock_provider_cls.call_args
        assert "sampler" in kwargs


def test_otel_redis_instrumentor_registered(monkeypatch):
    """RedisInstrumentor().instrument() 应被调用。"""
    from app.config import settings
    from app.main import _setup_opentelemetry

    monkeypatch.setattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318")

    with (
        patch(f"{_TRACE}.set_tracer_provider"),
        patch(_OTLP_EXPORTER),
        patch(_BATCH_PROCESSOR),
        patch(_TRACE_PROVIDER),
        patch(_RESOURCE),
        patch(_PARENT_BASED),
        patch(_RATIO_BASED),
        patch(_SQLALCHEMY),
        patch(_HTTPX),
        patch(_CELERY),
        patch(_REDIS) as mock_redis_instr,
    ):
        _setup_opentelemetry()
        mock_redis_instr.return_value.instrument.assert_called_once()


def test_otel_service_name_from_settings(monkeypatch):
    """Resource 应使用 settings.OTEL_SERVICE_NAME。"""
    from app.config import settings
    from app.main import _setup_opentelemetry

    monkeypatch.setattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318")
    monkeypatch.setattr(settings, "OTEL_SERVICE_NAME", "my-custom-service")

    with (
        patch(f"{_TRACE}.set_tracer_provider"),
        patch(_OTLP_EXPORTER),
        patch(_BATCH_PROCESSOR),
        patch(_TRACE_PROVIDER),
        patch(_RESOURCE) as mock_resource,
        patch(_PARENT_BASED),
        patch(_RATIO_BASED),
        patch(_SQLALCHEMY),
        patch(_HTTPX),
        patch(_CELERY),
        patch(_REDIS),
    ):
        _setup_opentelemetry()
        # Resource.create 应被调用，参数包含 service.name
        mock_resource.create.assert_called_once()
        args, _ = mock_resource.create.call_args
        assert args[0] == {"service.name": "my-custom-service"}


def test_otel_initialization_failure_does_not_block_app(monkeypatch):
    """OTel 初始化失败时应仅 warning，不抛出异常。"""
    from app.config import settings
    from app.main import _setup_opentelemetry

    monkeypatch.setattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318")

    # 让 set_tracer_provider 抛出异常，验证 try/except 包裹
    with patch(
        f"{_TRACE}.set_tracer_provider",
        side_effect=Exception("setup failed"),
    ):
        # 不应抛出异常
        _setup_opentelemetry()
