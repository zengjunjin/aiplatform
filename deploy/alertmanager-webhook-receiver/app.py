"""Alertmanager Webhook Receiver

接收 Alertmanager 转发的告警 webhook，写入本地文件并打印到控制台。

设计要点：
1. 接收 POST /webhook，body 为 Alertmanager webhook payload（JSON）
2. 将每条告警以 JSON Lines 格式追加到 /data/alerts.log
3. 控制台打印告警摘要（severity + alertname + status + summary）
4. 暴露 GET /healthz 供 docker healthcheck 使用
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request

app = Flask(__name__)

# 告警日志文件路径（docker volume 挂载点）
LOG_DIR = Path(os.getenv("LOG_DIR", "/data"))
LOG_FILE = LOG_DIR / "alerts.log"


def write_alert(alert: dict, status: str) -> None:
    """将告警以 JSON Lines 格式写入日志文件。

    Args:
        alert: Alertmanager 告警对象（alerts[i]）
        status: firing | resolved
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "alertname": alert.get("labels", {}).get("alertname", ""),
        "severity": alert.get("labels", {}).get("severity", ""),
        "instance": alert.get("labels", {}).get("instance", ""),
        "summary": alert.get("annotations", {}).get("summary", ""),
        "description": alert.get("annotations", {}).get("description", ""),
        "starts_at": alert.get("startsAt", ""),
        "ends_at": alert.get("endsAt", ""),
        "raw": alert,  # 保留原始告警数据，便于审计
    }
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def print_alert(alert: dict, status: str) -> None:
    """控制台打印告警摘要，便于 docker logs 查看。

    格式：[2026-07-25 10:00:00] [CRITICAL] [firing] DbPoolExhaustion - DB pool usage 85% > 80%
    """
    severity = alert.get("labels", {}).get("severity", "unknown").upper()
    alertname = alert.get("labels", {}).get("alertname", "unknown")
    summary = alert.get("annotations", {}).get("summary", "")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{severity}] [{status}] {alertname} - {summary}", flush=True)


@app.route("/webhook", methods=["POST"])
def webhook():
    """接收 Alertmanager webhook。

    Alertmanager webhook payload 格式：
    {
        "version": "4",
        "groupKey": "...",
        "status": "firing",
        "receiver": "default",
        "groupLabels": {...},
        "commonLabels": {...},
        "commonAnnotations": {...},
        "externalURL": "...",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "...", "severity": "..."},
                "annotations": {"summary": "...", "description": "..."},
                "startsAt": "...",
                "endsAt": "...",
                "generatorURL": "...",
                "fingerprint": "..."
            }
        ]
    }
    """
    payload = request.get_json(silent=True)
    if not payload or "alerts" not in payload:
        return jsonify({"error": "invalid payload"}), 400

    alerts = payload["alerts"]
    for alert in alerts:
        status = alert.get("status", "unknown")
        try:
            write_alert(alert, status)
            print_alert(alert, status)
        except Exception as e:
            print(f"[ERROR] Failed to process alert: {e}", file=sys.stderr, flush=True)

    return jsonify({"received": len(alerts)}), 200


@app.route("/healthz", methods=["GET"])
def healthz():
    """健康检查端点。"""
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=False)
