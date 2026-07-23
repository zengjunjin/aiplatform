"""反馈系统 E2E 测试

API:
- POST /chat/messages/{message_id}/feedback  -> 提交反馈
- GET  /chat/messages/{message_id}/feedback  -> 获取单条反馈
- GET  /chat/feedback/stats                  -> 反馈统计
- GET  /chat/feedback/analysis               -> 反馈分析
- GET  /chat/feedback/low-rated              -> 低分反馈列表

注意：所有反馈端点都在 /chat 前缀下，不是 /feedback
"""
import pytest
import requests

from tests.e2e.conftest import extract_data


def test_submit_positive_feedback(base_url, admin_headers, chat_session_with_msg):
    """提交好评"""
    msg_id = chat_session_with_msg["message_id"]
    if not msg_id:
        pytest.skip("No message_id from SSE (LLM may have failed)")
    r = requests.post(
        f"{base_url}/chat/messages/{msg_id}/feedback",
        json={"rating": 1, "comment": "回答准确"},
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200, f"Submit feedback failed: {r.text}"


def test_submit_negative_feedback_with_type(base_url, admin_headers, chat_session_with_msg):
    """提交差评"""
    msg_id = chat_session_with_msg["message_id"]
    if not msg_id:
        pytest.skip("No message_id from SSE (LLM may have failed)")
    r = requests.post(
        f"{base_url}/chat/messages/{msg_id}/feedback",
        json={
            "rating": -1,
            "feedback_type": "faithfulness_issue",
            "comment": "回答不准确",
        },
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200, f"Submit negative feedback failed: {r.text}"


def test_feedback_stats(base_url, admin_headers):
    """反馈统计"""
    r = requests.get(f"{base_url}/chat/feedback/stats",
                     headers=admin_headers, timeout=10)
    assert r.status_code == 200, f"Feedback stats failed: {r.text}"
    data = extract_data(r)
    # 应包含统计字段
    assert data is not None


def test_low_rated_list(base_url, admin_headers):
    """低分反馈列表"""
    r = requests.get(
        f"{base_url}/chat/feedback/low-rated",
        params={"page": 1, "page_size": 20},
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200, f"Low-rated list failed: {r.text}"
    data = extract_data(r)
    assert "items" in data
    assert "total" in data
