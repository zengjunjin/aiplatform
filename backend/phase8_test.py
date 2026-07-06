"""Phase 8 acceptance test - Comprehensive: security, performance, boundaries."""
import json
import time
import urllib.request
import urllib.error
import statistics
import pathlib

API = "http://localhost:8000/api/v1"
results = []

def check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    results.append((name, status, detail))
    print(f"[{status}] {name} - {detail}")

def api(method, path, token=None, body=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as he:
        try:
            return he.code, json.loads(he.read())
        except Exception:
            return he.code, {}
    except Exception as e:
        return 0, {"error": str(e)}

# === Setup: login as admin ===
status, resp = api("POST", "/auth/login", body={"username": "admin", "password": "admin123"})
admin_token = resp.get("data", {}).get("access_token", "")
check("0. admin login", status == 200 and admin_token, f"token_len={len(admin_token)}")

# === 1. SECURITY TESTS ===
print("\n=== Security Tests ===")

status, _ = api("GET", "/knowledge-bases")
check("1.1 unauthorized -> 401", status == 401, f"got {status}")

status, _ = api("GET", "/knowledge-bases", token="invalid.token.here")
check("1.2 invalid JWT -> 401/422", status in (401, 422), f"got {status}")

tampered = admin_token[:-1] + ("a" if admin_token[-1] != "a" else "b") if admin_token else "x"
status, _ = api("GET", "/knowledge-bases", token=tampered)
check("1.3 tampered JWT -> 401", status == 401, f"got {status}")

status, _ = api("POST", "/auth/login", body={"username": "admin OR 1=1--", "password": "x"})
check("1.4 SQL injection login blocked", status in (400, 401, 422), f"got {status}")

status, _ = api("GET", "/knowledge-bases/1 OR 1=1/documents", token=admin_token)
check("1.5 SQL injection in path blocked", status in (404, 422), f"got {status}")

status, resp = api("POST", "/knowledge-bases", token=admin_token,
                   body={"name": "<script>alert(1)</script>", "description": "xss test"})
check("1.6 XSS payload handled", status in (200, 201, 400, 422), f"got {status}")
if status in (200, 201) and isinstance(resp.get("data"), dict) and resp["data"].get("id"):
    api("DELETE", f"/knowledge-bases/{resp['data']['id']}", token=admin_token)

import random
import string
rand_suffix = "".join(random.choices(string.ascii_lowercase, k=6))
user2 = f"testuser_{rand_suffix}"
status, _ = api("POST", "/auth/register", body={"username": user2, "email": f"{user2}@test.com", "password": "Test@12345"})
check("1.7 register test user", status in (200, 201, 400), f"got {status}, user={user2}")

status, resp = api("POST", "/auth/login", body={"username": user2, "password": "Test@12345"})
user2_token = resp.get("data", {}).get("access_token", "") if status == 200 else ""
check("1.7b test user login", bool(user2_token), f"token_len={len(user2_token)}")

if user2_token:
    status, _ = api("GET", "/chat/sessions/999999", token=user2_token)
    check("1.8 cross-user resource access denied", status in (403, 404), f"got {status}")

# === 2. PERFORMANCE TESTS ===
print("\n=== Performance Tests ===")

times = []
for i in range(10):
    t0 = time.time()
    api("GET", "/auth/me", token=admin_token)
    times.append((time.time() - t0) * 1000)
p95 = sorted(times)[int(len(times) * 0.95) - 1] if len(times) >= 2 else times[0]
mean = statistics.mean(times)
check("2.1 /auth/me P95 <= 200ms", p95 <= 200, f"P95={p95:.1f}ms, mean={mean:.1f}ms")

times = []
for i in range(10):
    t0 = time.time()
    api("GET", "/knowledge-bases", token=admin_token)
    times.append((time.time() - t0) * 1000)
p95 = sorted(times)[int(len(times) * 0.95) - 1] if len(times) >= 2 else times[0]
check("2.2 /knowledge-bases P95 <= 200ms", p95 <= 200, f"P95={p95:.1f}ms, mean={statistics.mean(times):.1f}ms")

# === 3. BOUNDARY TESTS ===
print("\n=== Boundary Tests ===")

status, _ = api("POST", "/knowledge-bases", token=admin_token, body={"name": "", "description": ""})
check("3.1 empty KB name rejected", status in (400, 422), f"got {status}")

status, _ = api("GET", "/knowledge-bases/999999/documents", token=admin_token)
check("3.2 non-existent KB returns 404/200", status in (404, 200), f"got {status}")

status, _ = api("POST", "/documents/999999/reparse", token=admin_token)
check("3.3 non-existent doc reparse 404", status in (404, 422, 400), f"got {status}")

status, _ = api("DELETE", "/chat/sessions/999999", token=admin_token)
check("3.4 delete non-existent session 404", status in (404, 422), f"got {status}")

status, _ = api("POST", "/auth/register", body={"username": "admin", "email": "a@b.com", "password": "Test@12345"})
check("3.5 duplicate username blocked", status in (400, 409, 422), f"got {status}")

status, _ = api("POST", "/auth/register", body={"username": f"u_{rand_suffix}_2", "email": "x@y.com", "password": "123"})
check("3.6 short password blocked", status in (400, 422), f"got {status}")

status, _ = api("POST", "/auth/register", body={"username": f"u_{rand_suffix}_3", "email": "not-an-email", "password": "Test@12345"})
check("3.7 invalid email blocked", status in (400, 422), f"got {status}")

# === 4. RESOURCE CHECKS ===
print("\n=== Resource Checks ===")

try:
    import subprocess
    r = subprocess.run(["wmic", "process", "where", "name='python.exe'", "get", "WorkingSetSize"],
                       capture_output=True, text=True, timeout=10)
    sizes = [int(x) for x in r.stdout.split() if x.isdigit()]
    if sizes:
        total_mb = sum(sizes) / 1024 / 1024
        max_mb = max(sizes) / 1024 / 1024
        check("4.1 total python mem <= 2GB", total_mb <= 2048, f"total={total_mb:.0f}MB, max_proc={max_mb:.0f}MB")
    else:
        check("4.1 memory measurement", False, "no python processes found")
except Exception as e:
    check("4.1 memory measurement", False, f"error: {e}")

try:
    import psycopg2
    conn = psycopg2.connect("postgresql://postgres:postgres@localhost:5432/rag_platform")
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM documents")
    doc_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM document_chunks")
    chunk_count = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM users")
    user_count = cur.fetchone()[0]
    conn.close()
    check("4.2 PostgreSQL accessible", True, f"users={user_count}, docs={doc_count}, chunks={chunk_count}")
except Exception as e:
    check("4.2 PostgreSQL accessible", False, f"error: {e}")

try:
    import redis
    r = redis.from_url("redis://localhost:6379/0")
    r.ping()
    info = r.info()
    check("4.3 Redis accessible", True, f"version={info.get('redis_version', '?')}, clients={info.get('connected_clients', '?')}")
except Exception as e:
    check("4.3 Redis accessible", False, f"error: {e}")

try:
    import chromadb
    client = chromadb.PersistentClient(path=r"G:\aiplatform\backend\chroma_data")
    collections = client.list_collections()
    check("4.4 Chroma accessible", True, f"collections={[c.name for c in collections]}")
except Exception as e:
    check("4.4 Chroma accessible", False, f"error: {e}")

try:
    r = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
    data = json.loads(r.read())
    models = [m["name"] for m in data.get("models", [])]
    check("4.5 Ollama accessible", True, f"models={models}")
except Exception as e:
    check("4.5 Ollama accessible", False, f"error: {e}")

# === Summary ===
print()
print("=" * 60)
passed = sum(1 for _, s, _ in results if s == "PASS")
failed = sum(1 for _, s, _ in results if s == "FAIL")
print(f"Phase 8 验收结果: {passed}/{len(results)} PASS, {failed} FAIL")
print("=" * 60)

out = pathlib.Path(r"G:\aiplatform\backend\phase8_result.json")
out.write_text(json.dumps({
    "phase": "Phase 8 - Comprehensive (security + performance + boundaries)",
    "total": len(results),
    "passed": passed,
    "failed": failed,
    "details": [{"name": n, "status": s, "detail": d} for n, s, d in results],
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Result saved to {out}")
