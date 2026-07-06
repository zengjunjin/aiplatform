import urllib.request
import json
import sys


def login():
    data = json.dumps({"username": "debuguser", "password": "Debug@123456"}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/auth/login",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read().decode())
    return result["data"]["access_token"]


def create_session(token):
    data = json.dumps({"title": "测试对话"}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/chat/sessions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read().decode())
    return result["data"]["id"]


def test_chat(token, session_id):
    data = json.dumps({"content": "灰度是什么"}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:8000/api/v1/chat/sessions/{session_id}/messages",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=60)
    print(f"Status: {resp.status}")
    print(f"Content-Type: {resp.headers.get('Content-Type')}")
    print("--- SSE events ---")

    buffer = b""
    while True:
        chunk = resp.read(1024)
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line = line.decode("utf-8", errors="replace")
            if line.startswith("data: "):
                data_str = line[6:]
                print(f"  {data_str[:200]}")
                if data_str == "[DONE]":
                    print("--- DONE received ---")
                    return


if __name__ == "__main__":
    try:
        token = login()
        print("Login OK")
        sid = create_session(token)
        print(f"Session: {sid}")
        test_chat(token, sid)
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
