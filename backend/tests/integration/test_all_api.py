import urllib.request
import urllib.parse
import json
import time
import sys

BASE_URL = "http://localhost:8001/api/v1"

def api(method, path, token=None, data=None):
    url = f"{BASE_URL}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, method=method, data=body)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")
    except Exception as e:
        return 0, {"error": str(e)}

def test(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}")
    if not condition and detail:
        print(f"         {detail}")
    return condition

def main():
    results = []
    
    print("=" * 60)
    print("Integration Testing - RAG Platform")
    print("=" * 60)
    
    print("\n[1] Basic Health Checks")
    code, data = api("GET", "/system/models")
    results.append(test("GET /system/models returns 200", code == 200, f"code={code}"))
    results.append(test("Response has models list", 
        code == 200 and "data" in data and "models" in data["data"],
        f"data={json.dumps(data, ensure_ascii=False)[:200]}"))
    if code == 200:
        models = data["data"]["models"]
        results.append(test("Ollama model in list", 
            any(m["name"] == "ollama" for m in models),
            f"models={[m['name'] for m in models]}"))
    
    print("\n[2] User Registration & Login")
    ts = int(time.time())
    username = f"testuser_{ts}"
    email = f"{username}@test.com"
    password = "Test@123456"
    
    code, data = api("POST", "/auth/register", data={
        "username": username, "email": email, 
        "password": password, "confirm_password": password
    })
    results.append(test("POST /auth/register returns 200", 
        code == 200, f"code={code}, data={json.dumps(data, ensure_ascii=False)[:200]}"))
    
    code, data = api("POST", "/auth/login", data={
        "username": username, "password": password
    })
    token = None
    if code == 200 and "data" in data and "access_token" in data["data"]:
        token = data["data"]["access_token"]
    results.append(test("POST /auth/login returns token", 
        token is not None, f"code={code}, data={json.dumps(data, ensure_ascii=False)[:200]}"))
    
    if not token:
        print("\n  [SKIP] Cannot proceed without token")
        print(f"\n{'='*60}")
        passed = sum(results)
        print(f"Result: {passed}/{len(results)} passed")
        sys.exit(0 if passed == len(results) else 1)
    
    print("\n[3] Chat API Tests")
    code, data = api("POST", "/chat/sessions", token=token, data={
        "title": "Integration Test Session",
        "knowledge_base_id": None
    })
    session_id = None
    if code == 200 and "data" in data and "id" in data["data"]:
        session_id = str(data["data"]["id"])
    results.append(test("POST /chat/sessions creates session", 
        session_id is not None, f"code={code}, data={json.dumps(data, ensure_ascii=False)[:200]}"))
    
    if session_id:
        code, data = api("GET", f"/chat/sessions/{session_id}", token=token)
        results.append(test("GET /chat/sessions/{id} returns session", 
            code == 200 and "data" in data, f"code={code}"))
    
    print("\n[4] Knowledge Base API Tests")
    code, data = api("GET", "/knowledge-bases", token=token)
    results.append(test("GET /knowledge-bases returns 200", 
        code == 200, f"code={code}, data={json.dumps(data, ensure_ascii=False)[:200]}"))
    
    code, data = api("POST", "/knowledge-bases", token=token, data={
        "name": f"Integration Test KB {ts}",
        "description": "Test KB for integration testing"
    })
    kb_id = None
    if code == 200 and "data" in data and "id" in data["data"]:
        kb_id = str(data["data"]["id"])
    results.append(test("POST /knowledge-bases creates KB", 
        kb_id is not None, f"code={code}, data={json.dumps(data, ensure_ascii=False)[:200]}"))
    
    if kb_id:
        code, data = api("GET", f"/knowledge-bases/{kb_id}/collaborators", token=token)
        results.append(test("GET /knowledge-bases/{id}/collaborators", 
            code == 200, f"code={code}, data={json.dumps(data, ensure_ascii=False)[:200]}"))
    
    print("\n[5] Document API Tests")
    if kb_id:
        code, data = api("GET", f"/knowledge-bases/{kb_id}/documents", token=token)
        results.append(test("GET /knowledge-bases/{id}/documents", 
            code == 200, f"code={code}, data={json.dumps(data, ensure_ascii=False)[:200]}"))
    
    print("\n[6] Feedback API Tests")
    if session_id:
        code, data = api("GET", f"/chat/sessions/{session_id}/messages", token=token)
        msg_id = None
        if code == 200 and "data" in data and "items" in data["data"] and len(data["data"]["items"]) > 0:
            msg_id = str(data["data"]["items"][0]["id"])
        if msg_id:
            code, data = api("POST", f"/chat/messages/{msg_id}/feedback", token=token, data={
                "rating": 1,
                "comment": "Great answer!",
                "feedback_type": None
            })
            results.append(test("POST /chat/messages/{id}/feedback (like)", 
                code == 200, f"code={code}, data={json.dumps(data, ensure_ascii=False)[:200]}"))
        else:
            print("  [SKIP] No messages available for feedback test")
    
    print("\n[7] System / Admin Tests")
    code, data = api("GET", "/system/status", token=token)
    if code == 403:
        print("  [INFO] /system/status requires admin (403 expected for regular user)")
    
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Result: {passed}/{total} passed ({passed/total*100:.1f}%)")
    print("=" * 60)
    
    if passed != total:
        sys.exit(1)

if __name__ == "__main__":
    main()
