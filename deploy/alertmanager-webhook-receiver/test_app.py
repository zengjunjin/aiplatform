"""webhook receiver 单元测试"""

import json
import os
import sys

import pytest

# 通过环境变量指定 LOG_DIR 之前 import app
sys.path.insert(0, os.path.dirname(__file__))


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask 测试客户端，使用临时目录。"""
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    # 重新 import app 以使新的 LOG_DIR 生效
    import importlib

    if "app" in sys.modules:
        importlib.reload(sys.modules["app"])
    from app import app

    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_healthz(client):
    """健康检查端点应返回 200。"""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_webhook_invalid_payload(client):
    """无效 payload 应返回 400。"""
    resp = client.post("/webhook", json={"foo": "bar"})
    assert resp.status_code == 400


def test_webhook_valid_payload(client, tmp_path):
    """有效 payload 应写入日志文件并返回 200。"""
    payload = {
        "version": "4",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "DbPoolExhaustion", "severity": "critical"},
                "annotations": {"summary": "DB pool exhaustion", "description": "85% > 80%"},
                "startsAt": "2026-07-25T10:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
            }
        ],
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    assert resp.get_json() == {"received": 1}

    # 验证日志文件已写入
    log_file = tmp_path / "alerts.log"
    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["alertname"] == "DbPoolExhaustion"
    assert record["severity"] == "critical"
    assert record["status"] == "firing"
    assert record["summary"] == "DB pool exhaustion"


def test_webhook_multiple_alerts(client, tmp_path):
    """多条告警应全部写入日志文件。"""
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "Alert1", "severity": "critical"},
                "annotations": {"summary": "First"},
            },
            {
                "status": "resolved",
                "labels": {"alertname": "Alert2", "severity": "warning"},
                "annotations": {"summary": "Second"},
            },
        ],
    }
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    assert resp.get_json() == {"received": 2}

    log_file = tmp_path / "alerts.log"
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
