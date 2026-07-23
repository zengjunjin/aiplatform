"""系统模块 E2E 测试

API:
- GET /system/status   -> 系统组件状态（admin only）
- GET /system/models   -> 可用模型列表（任意已认证用户）
- GET /metrics         -> Prometheus 指标（admin only，根路径而非 /api/v1）

注意：API 没有 /system/health 端点
"""
import os
import pytest
import requests

from tests.e2e.conftest import extract_data, BASE_URL


def test_system_status_requires_admin(base_url, test_user_headers):
    """非 admin 不能访问 /system/status"""
    r = requests.get(f"{base_url}/system/status",
                     headers=test_user_headers, timeout=10)
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"


def test_system_status_admin_ok(base_url, admin_headers):
    """admin 可访问 /system/status"""
    r = requests.get(f"{base_url}/system/status",
                     headers=admin_headers, timeout=15)
    assert r.status_code == 200, f"System status failed: {r.text}"
    data = extract_data(r)
    # 应包含各服务状态
    assert "postgresql" in data
    assert "redis" in data
    assert "ollama" in data
    assert "qdrant" in data
    assert "celery" in data


def test_system_models(base_url, admin_headers):
    """获取可用模型列表"""
    r = requests.get(f"{base_url}/system/models",
                     headers=admin_headers, timeout=10)
    assert r.status_code == 200, f"List models failed: {r.text}"
    data = extract_data(r)
    assert "models" in data
    assert isinstance(data["models"], list)


def test_metrics_requires_admin(base_url, test_user_headers):
    """非 admin 不能访问 /metrics"""
    # /metrics 在根路径，非 /api/v1
    metrics_url = base_url.replace("/api/v1", "") + "/metrics"
    r = requests.get(metrics_url, headers=test_user_headers, timeout=10)
    assert r.status_code in (401, 403), f"Expected 401/403, got {r.status_code}"


def test_metrics_admin_ok(base_url, admin_headers):
    """admin 可访问 /metrics"""
    metrics_url = base_url.replace("/api/v1", "") + "/metrics"
    r = requests.get(metrics_url, headers=admin_headers, timeout=10)
    assert r.status_code == 200, f"Metrics failed: {r.text}"
    # 应包含 Prometheus 格式
    assert "# HELP" in r.text or "# TYPE" in r.text, \
        "Response is not Prometheus format"
