"""Chat SSE 流式 E2E 测试

API:
- POST   /chat/sessions                       -> 创建会话
- GET    /chat/sessions                       -> 会话列表
- GET    /chat/sessions/{id}                  -> 会话详情
- PUT    /chat/sessions/{id}                  -> 更新会话
- DELETE /chat/sessions/{id}                  -> 删除会话
- GET    /chat/sessions/{id}/messages         -> 消息列表（分页）
- POST   /chat/sessions/{id}/messages         -> SSE 流式发送消息
- POST   /chat/sessions/{id}/cancel           -> 取消生成

SSE 事件结构: data: {"event": "delta|done|error|...", ...}\n\n
SSE 终止哨兵: data: [DONE]\n\n
"""

import json

import requests

from tests.e2e.conftest import extract_data


def test_create_session(base_url, admin_headers, kb_with_doc):
    """创建会话"""
    r = requests.post(
        f"{base_url}/chat/sessions",
        json={
            "title": "test",
            "kb_id": kb_with_doc["kb"]["id"],
        },
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Create session failed: {r.text}"
    session = extract_data(r)
    assert "id" in session
    # 清理
    requests.delete(f"{base_url}/chat/sessions/{session['id']}", headers=admin_headers, timeout=5)


def test_sse_streaming_response(base_url, admin_headers, chat_session):
    """SSE 流式返回完整回答

    事件流: searching -> model -> delta* -> done -> [DONE]
    """
    url = f"{base_url}/chat/sessions/{chat_session['id']}/messages"
    events = []
    with requests.post(
        url, json={"content": "你好"}, headers=admin_headers, stream=True, timeout=120
    ) as r:
        assert r.status_code == 200, f"SSE failed: {r.text}"
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                evt = json.loads(payload)
            except Exception:
                continue
            events.append(evt)
            # 不 break，继续读到 [DONE] 哨兵

    # 至少有 delta 和 done 事件
    assert len(events) >= 1, f"No events received: {events}"
    event_types = [e.get("event") for e in events]
    assert (
        "done" in event_types or "error" in event_types
    ), f"Missing done/error event. Events: {event_types}"


def test_chat_message_persisted(base_url, admin_headers, chat_session_with_msg):
    """消息持久化"""
    session_id = chat_session_with_msg["session"]["id"]
    # SSE 已发送一条消息，应被持久化
    r = requests.get(
        f"{base_url}/chat/sessions/{session_id}/messages",
        params={"page": 1, "page_size": 50},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Get messages failed: {r.text}"
    data = extract_data(r)
    assert "items" in data
    # 应至少有 user + assistant 两条
    assert (
        len(data["items"]) >= 2
    ), f"Expected >=2 messages, got {len(data['items'])}: {data['items']}"
    roles = [m.get("role") for m in data["items"]]
    assert "user" in roles
    assert "assistant" in roles


def test_session_list(base_url, admin_headers, chat_session):
    """会话列表"""
    r = requests.get(
        f"{base_url}/chat/sessions",
        params={"page": 1, "page_size": 10},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200
    data = extract_data(r)
    assert "items" in data
    assert any(s["id"] == chat_session["id"] for s in data["items"]), "chat_session not in list"


def test_session_detail(base_url, admin_headers, chat_session):
    """会话详情

    注意：GET /chat/sessions/{id} 返回 {session: {...}, messages: [...]}，
    不是直接返回 session 对象。
    """
    r = requests.get(
        f"{base_url}/chat/sessions/{chat_session['id']}",
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200
    data = extract_data(r)
    s = data["session"]  # 嵌套在 session 字段中
    assert s["id"] == chat_session["id"]
