"""Settings 配置测试"""

from app.config import Settings


def test_otel_defaults(monkeypatch):
    """OTel 配置项应有正确的默认值。"""
    # 清理环境变量，确保测试独立于运行环境
    for key in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_SERVICE_NAME", "OTEL_TRACES_SAMPLER_ARG"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings()
    assert settings.OTEL_EXPORTER_OTLP_ENDPOINT == ""
    assert settings.OTEL_SERVICE_NAME == "rag-platform-backend"
    assert settings.OTEL_TRACES_SAMPLER_ARG == 0.1
