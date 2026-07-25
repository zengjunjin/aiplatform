"""Settings 配置测试"""

from app.config import Settings


def test_otel_defaults():
    """OTel 配置项应有正确的默认值。"""
    settings = Settings()
    assert settings.OTEL_EXPORTER_OTLP_ENDPOINT == ""
    assert settings.OTEL_SERVICE_NAME == "rag-platform-backend"
    assert settings.OTEL_TRACES_SAMPLER_ARG == 0.1
