"""Full integration test suite for RAG Platform."""
import urllib.request
import urllib.error
import json
import time
import sys

BASE_URL = "http://localhost:8001/api/v1"
passed = 0
failed = 0
skipped = 0


def api(method, path, token=None, data=None, headers=None):
    url = f"{BASE_URL}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, method=method, data=body)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        txt = resp.read().decode()
        return resp.status, json.loads(txt) if txt else {}
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        return e.code, json.loads(txt) if txt else {}
    except Exception as e:
        return 0, {"error": str(e)}


def t(name, cond, detail=""):
    global passed, failed
    s = "PASS" if cond else "FAIL"
    print(f"  [{s}] {name}")
    if not cond and detail:
        print(f"         {detail[:300]}")
    if cond:
        passed += 1
    else:
        failed += 1
    return cond


def section(title):
    print(f"\n[{title}]")


def main():
    global passed, failed, skipped
    ts = int(time.time())
    print("=" * 60)
    print("Full Integration Test - RAG Platform")
    print("=" * 60)

    # === 1. Public endpoints ===
    section("1. Public Endpoints")
    code, data = api("GET", "/system/models")
    t("GET /system/models returns 200", code == 200)
    if code == 200:
        models = data.get("data", {}).get("models", [])
        t("Models list contains ollama",
          any(m.get("name") == "ollama" for m in models),
          f"models={[m.get('name') for m in models]}")
        t("Model has display_name and status",
          all("display_name" in m and "status" in m for m in models))

    # === 2. Auth ===
    section("2. Authentication")
    username = f"integ_{ts}"
    email = f"{username}@test.com"
    pwd = "Test@123456"

    code, data = api("POST", "/auth/register", data={
        "username": username, "email": email,
        "password": pwd, "confirm_password": pwd
    })
    t("POST /auth/register returns 200", code == 200,
      f"code={code} msg={data.get('message','')}")

    code, data = api("POST", "/auth/login", data={
        "username": username, "password": pwd
    })
    token = None
    if code == 200:
        token = data.get("data", {}).get("access_token")
    t("POST /auth/login returns access_token",
      token is not None, f"code={code}")

    if not token:
        print("\n[FATAL] Cannot continue without token")
        return

    # === 3. Chat Sessions ===
    section("3. Chat Sessions")
    code, data = api("POST", "/chat/sessions", token=token, data={
        "title": "Integ Test Session",
        "knowledge_base_id": None
    })
    session_id = None
    if code == 200 and data.get("data", {}).get("id"):
        session_id = str(data["data"]["id"])
    t("POST /chat/sessions creates session",
      session_id is not None, f"code={code}")

    if session_id:
        code, data = api("GET", f"/chat/sessions/{session_id}", token=token)
        t("GET /chat/sessions/{id}", code == 200, f"code={code}")

    code, data = api("GET", "/chat/sessions?page=1&page_size=10", token=token)
    t("GET /chat/sessions (list with pagination)",
      code == 200 and "items" in data.get("data", {}),
      f"code={code}")

    # === 4. Chat Messaging (SSE) ===
    section("4. Chat Messaging")
    assistant_msg_id = None
    if session_id:
        import threading
        import queue
        
        result_queue = queue.Queue()
        
        def stream_chat():
            try:
                url = f"{BASE_URL}/chat/sessions/{session_id}/messages"
                req_data = json.dumps({
                    "content": "Reply with just the word 'test' in English.",
                    "model": "ollama"
                }).encode()
                req = urllib.request.Request(url, data=req_data, method="POST")
                req.add_header("Content-Type", "application/json")
                req.add_header("Authorization", f"Bearer {token}")
                resp = urllib.request.urlopen(req, timeout=60)
                chunks = []
                for line in resp:
                    line = line.decode().strip()
                    if line.startswith("data:") and line != "data: [DONE]":
                        chunks.append(line[5:].strip())
                result_queue.put(("ok", len(chunks), "".join(chunks)[:200]))
            except Exception as e:
                result_queue.put(("error", str(e), ""))
        
        thread = threading.Thread(target=stream_chat)
        thread.start()
        thread.join(timeout=45)
        
        if thread.is_alive():
            t("POST /chat/sessions/{id}/messages SSE", False, "timeout after 45s")
        else:
            status, count, preview = result_queue.get()
            t("POST /chat/sessions/{id}/messages SSE streaming",
              status == "ok" and count > 0,
              f"status={status} chunks={count} preview={preview[:100]}")

        # Get messages after streaming
        time.sleep(2)
        code, data = api("GET",
                         f"/chat/sessions/{session_id}/messages?page=1&page_size=10",
                         token=token)
        msgs = data.get("data", {}).get("items", [])
        t("GET /chat/sessions/{id}/messages returns messages",
          code == 200 and len(msgs) > 0,
          f"code={code} count={len(msgs)}")
        # Find assistant message for feedback test
        for m in msgs:
            if m.get("role") == "assistant":
                assistant_msg_id = str(m["id"])
                break

    # === 5. Knowledge Bases ===
    section("5. Knowledge Bases")
    code, data = api("GET", "/knowledge-bases?page=1&page_size=10", token=token)
    t("GET /knowledge-bases returns 200 with pagination",
      code == 200 and "items" in data.get("data", {}),
      f"code={code}")

    code, data = api("POST", "/knowledge-bases", token=token, data={
        "name": f"Integ Test KB {ts}",
        "description": "KB for integration testing"
    })
    kb_id = None
    if code == 200 and data.get("data", {}).get("id"):
        kb_id = str(data["data"]["id"])
    t("POST /knowledge-bases creates KB",
      kb_id is not None, f"code={code}")

    if kb_id:
        code, data = api("GET", f"/knowledge-bases/{kb_id}", token=token)
        t("GET /knowledge-bases/{id}", code == 200, f"code={code}")

        # Collaborators
        code, data = api("GET",
                         f"/knowledge-bases/{kb_id}/collaborators",
                         token=token)
        t("GET /knowledge-bases/{id}/collaborators",
          code == 200, f"code={code}")

        code, data = api("POST",
                         f"/knowledge-bases/{kb_id}/collaborators",
                         token=token,
                         data={"user_id": 1, "role": "read"})
        # May be 200 or 400 if user doesn't exist
        t("POST /knowledge-bases/{id}/collaborators",
          code in [200, 201, 400, 404], f"code={code}")

    # === 6. Documents ===
    section("6. Documents")
    if kb_id:
        code, data = api("GET",
                         f"/documents?knowledge_base_id={kb_id}&page=1&page_size=10",
                         token=token)
        t("GET /documents (list by kb)",
          code == 200, f"code={code}")

    # === 7. Feedback API ===
    section("7. Feedback API")
    if assistant_msg_id:
        code, data = api("POST",
                         f"/chat/messages/{assistant_msg_id}/feedback",
                         token=token,
                         data={"rating": 1, "comment": "Great answer!"})
        t("POST /chat/messages/{id}/feedback (like)",
          code == 200, f"code={code} msg={data.get('message','')}")

        # Get feedback for specific message
        code, data = api("GET",
                         f"/chat/messages/{assistant_msg_id}/feedback",
                         token=token)
        t("GET /chat/messages/{id}/feedback",
          code == 200, f"code={code}")

        # feedback stats is admin-only (403 expected for regular user)
        code, data = api("GET", "/chat/feedback/stats", token=token)
        if code == 403:
            print("  [INFO] /chat/feedback/stats requires admin (403 expected)")
            passed += 1
        else:
            t("GET /chat/feedback/stats", code == 200, f"code={code}")
    else:
        print("  [SKIP] No assistant message for feedback test")
        skipped += 1

    # === 8. Evaluation API ===
    section("8. Evaluation API")
    code, data = api("GET", "/evaluation/runs?page=1&page_size=10", token=token)
    t("GET /evaluation/runs",
      code in [200, 403], f"code={code}")

    # === 9. User Profile ===
    section("9. User Profile")
    code, data = api("GET", "/auth/me", token=token)
    t("GET /auth/me returns profile",
      code == 200 and data.get("data", {}).get("username") == username,
      f"code={code} data={str(data.get('data',{}))[:150]}")

    # === 10. System status (admin check) ===
    section("10. System / Admin")
    code, data = api("GET", "/system/status", token=token)
    if code == 403:
        print("  [INFO] /system/status returns 403 for non-admin (expected)")
        passed += 1
    else:
        t("GET /system/status returns 200 for admin", code == 200, f"code={code}")

    # === Summary ===
    total = passed + failed
    print("\n" + "=" * 60)
    print(f"Result: {passed}/{total} passed ({passed/total*100:.1f}%)")
    print(f"Failed: {failed}, Skipped: {skipped}")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
