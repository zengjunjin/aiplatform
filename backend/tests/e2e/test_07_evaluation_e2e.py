"""评估系统 E2E 测试

API:
- POST   /evaluation/runs?kb_id=X&num_questions=Y  -> 触发评估（admin only，限流 3/hour）
- GET    /evaluation/runs                          -> 列表（admin only）
- GET    /evaluation/runs/{id}                     -> 详情
- GET    /evaluation/runs/{id}/results             -> 单题结果
- DELETE /evaluation/runs/{id}                     -> 删除

评估状态: pending -> running -> completed / failed
"""

import pytest
import requests

from tests.e2e.conftest import extract_data
from tests.e2e.helpers.waiters import wait_for


def test_trigger_evaluation(base_url, admin_headers, kb_with_doc):
    """触发评估

    历史：早期版本 evaluation_service.trigger_evaluation 调用 get_kb_for_read
    时参数顺序错误导致 500。该 bug 已修复（evaluation_service.py L202 参数顺序正确）。
    本测试从 xfail 改为严格断言 200，确保修复不被回退。
    """
    r = requests.post(
        f"{base_url}/evaluation/runs",
        params={"kb_id": kb_with_doc["kb"]["id"], "num_questions": 5},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Trigger evaluation failed: {r.text}"
    data = extract_data(r)
    assert "run_id" in data
    assert data["status"] == "pending"


def test_list_runs(base_url, admin_headers):
    """列出评估运行"""
    r = requests.get(
        f"{base_url}/evaluation/runs",
        params={"page": 1, "page_size": 10},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"List runs failed: {r.text}"
    data = extract_data(r)
    assert "items" in data


def test_get_run_detail(base_url, admin_headers):
    """获取评估详情"""
    r = requests.get(
        f"{base_url}/evaluation/runs",
        params={"page_size": 1},
        headers=admin_headers,
        timeout=10,
    )
    items = extract_data(r).get("items", [])
    if not items:
        pytest.skip("No evaluation runs exist")
    run_id = items[0]["id"]
    r2 = requests.get(f"{base_url}/evaluation/runs/{run_id}", headers=admin_headers, timeout=10)
    assert r2.status_code == 200
    run = extract_data(r2)
    assert run["id"] == run_id


def test_normal_user_cannot_trigger(base_url, test_user_headers, kb_with_doc):
    """普通用户不能触发评估"""
    r = requests.post(
        f"{base_url}/evaluation/runs",
        params={"kb_id": kb_with_doc["kb"]["id"], "num_questions": 5},
        headers=test_user_headers,
        timeout=10,
    )
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"


def test_evaluation_complete_with_metrics(base_url, admin_headers, kb_with_doc):
    """评估完成并返回 metrics（耗时较长，最长等 10 分钟）

    历史：同 test_trigger_evaluation，早期版本 get_kb_for_read 参数顺序错误导致 500。
    该 bug 已修复。本测试从 xfail 改为严格断言。
    """
    # 触发评估
    r = requests.post(
        f"{base_url}/evaluation/runs",
        params={"kb_id": kb_with_doc["kb"]["id"], "num_questions": 5},
        headers=admin_headers,
        timeout=10,
    )
    # 限流可能 429
    if r.status_code == 429:
        pytest.skip("Evaluation rate limit (3/hour) reached, skip metrics test")
    assert r.status_code == 200, f"Trigger failed: {r.text}"
    run_id = extract_data(r)["run_id"]

    # 轮询直到 completed 或 failed（替代固定 sleep(10) 手写循环）
    def _poll_status():
        r2 = requests.get(f"{base_url}/evaluation/runs/{run_id}", headers=admin_headers, timeout=10)
        if r2.status_code == 200:
            status = extract_data(r2).get("status")
            if status in ("completed", "failed"):
                return status
        return None

    try:
        final_status = wait_for(
            _poll_status,
            timeout=600,
            interval=10,
            message="Evaluation run to reach terminal status",
        )
    except TimeoutError:
        final_status = None

    assert final_status == "completed", f"Evaluation did not complete. Final status: {final_status}"

    # 获取详情，验证 metrics
    r3 = requests.get(f"{base_url}/evaluation/runs/{run_id}", headers=admin_headers, timeout=10)
    run = extract_data(r3)
    assert run.get("metrics") is not None, "metrics is None"

    # 获取详细结果
    r4 = requests.get(
        f"{base_url}/evaluation/runs/{run_id}/results", headers=admin_headers, timeout=10
    )
    assert r4.status_code == 200
    results = extract_data(r4)
    assert "items" in results
    assert len(results["items"]) > 0, "No evaluation results"
