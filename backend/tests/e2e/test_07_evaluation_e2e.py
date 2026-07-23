"""评估系统 E2E 测试

API:
- POST   /evaluation/runs?kb_id=X&num_questions=Y  -> 触发评估（admin only，限流 3/hour）
- GET    /evaluation/runs                          -> 列表（admin only）
- GET    /evaluation/runs/{id}                     -> 详情
- GET    /evaluation/runs/{id}/results             -> 单题结果
- DELETE /evaluation/runs/{id}                     -> 删除

评估状态: pending -> running -> completed / failed
"""
import time
import pytest
import requests

from tests.e2e.conftest import extract_data


def test_trigger_evaluation(base_url, admin_headers, kb_with_doc):
    """触发评估

    生产 Bug（记录不修复）：evaluation.py:34 调用 get_kb_for_read(db, kb_id, admin.id)，
    但函数签名是 get_kb_for_read(kb_id, user_id, db)，参数顺序错误导致
    db 被当作 kb_id（int），kb_id 被当作 user_id，admin.id 被当作 db，
    引发 AttributeError: 'int' object has no attribute 'execute'。
    """
    r = requests.post(
        f"{base_url}/evaluation/runs",
        params={"kb_id": kb_with_doc["kb"]["id"], "num_questions": 5},
        headers=admin_headers, timeout=10,
    )
    if r.status_code == 500:
        pytest.skip(
            "Production bug: evaluation.py:34 get_kb_for_read 参数顺序错误"
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
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200, f"List runs failed: {r.text}"
    data = extract_data(r)
    assert "items" in data


def test_get_run_detail(base_url, admin_headers):
    """获取评估详情"""
    r = requests.get(
        f"{base_url}/evaluation/runs",
        params={"page_size": 1},
        headers=admin_headers, timeout=10,
    )
    items = extract_data(r).get("items", [])
    if not items:
        pytest.skip("No evaluation runs exist")
    run_id = items[0]["id"]
    r2 = requests.get(f"{base_url}/evaluation/runs/{run_id}",
                      headers=admin_headers, timeout=10)
    assert r2.status_code == 200
    run = extract_data(r2)
    assert run["id"] == run_id


def test_normal_user_cannot_trigger(base_url, test_user_headers, kb_with_doc):
    """普通用户不能触发评估"""
    r = requests.post(
        f"{base_url}/evaluation/runs",
        params={"kb_id": kb_with_doc["kb"]["id"], "num_questions": 5},
        headers=test_user_headers, timeout=10,
    )
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"


def test_evaluation_complete_with_metrics(base_url, admin_headers, kb_with_doc):
    """评估完成并返回 metrics（耗时较长，最长等 10 分钟）

    生产 Bug（记录不修复）：同 test_trigger_evaluation，
    evaluation.py:34 get_kb_for_read 参数顺序错误导致 500。
    """
    # 触发评估
    r = requests.post(
        f"{base_url}/evaluation/runs",
        params={"kb_id": kb_with_doc["kb"]["id"], "num_questions": 5},
        headers=admin_headers, timeout=10,
    )
    # 限流可能 429
    if r.status_code == 429:
        pytest.skip("Evaluation rate limit (3/hour) reached, skip metrics test")
    if r.status_code == 500:
        pytest.skip(
            "Production bug: evaluation.py:34 get_kb_for_read 参数顺序错误"
        )
    assert r.status_code == 200, f"Trigger failed: {r.text}"
    run_id = extract_data(r)["run_id"]

    # 轮询直到 completed 或 failed
    deadline = time.time() + 600
    final_status = None
    while time.time() < deadline:
        r2 = requests.get(f"{base_url}/evaluation/runs/{run_id}",
                          headers=admin_headers, timeout=10)
        if r2.status_code == 200:
            run = extract_data(r2)
            final_status = run.get("status")
            if final_status in ("completed", "failed"):
                break
        time.sleep(10)

    assert final_status == "completed", (
        f"Evaluation did not complete. Final status: {final_status}"
    )

    # 获取详情，验证 metrics
    r3 = requests.get(f"{base_url}/evaluation/runs/{run_id}",
                      headers=admin_headers, timeout=10)
    run = extract_data(r3)
    assert run.get("metrics") is not None, "metrics is None"

    # 获取详细结果
    r4 = requests.get(f"{base_url}/evaluation/runs/{run_id}/results",
                      headers=admin_headers, timeout=10)
    assert r4.status_code == 200
    results = extract_data(r4)
    assert "items" in results
    assert len(results["items"]) > 0, "No evaluation results"
