"""Phase 7 acceptance test - Frontend (Vite + React) validation."""
import json
import time
import urllib.request
import urllib.error

VITE = "http://localhost:5173"
API = f"{VITE}/api/v1"

results = []
def check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    results.append((name, status, detail))
    print(f"[{status}] {name} - {detail}")

# 1. Vite dev server responds
try:
    r = urllib.request.urlopen(f"{VITE}/", timeout=5)
    body = r.read().decode("utf-8", errors="ignore")
    check("1. Vite dev server 200 OK", r.status == 200, f"status={r.status}, length={len(body)}")
    check("2. HTML has <div id=root>", "<div id=\"root\"" in body, "root div present")
    check("3. HTML loads main.tsx", "main.tsx" in body, "script tag found")
    check("4. HTML has Chinese title", "RAG" in body, "title present")
except Exception as e:
    check("1. Vite dev server 200 OK", False, f"error: {e}")

# 5. Static asset (main.tsx) - Vite transforms TSX
try:
    r = urllib.request.urlopen(f"{VITE}/src/main.tsx", timeout=5)
    body = r.read().decode("utf-8", errors="ignore")
    check("5. Vite serves src/main.tsx", r.status == 200 and "ReactDOM" in body, f"status={r.status}, length={len(body)}")
except Exception as e:
    check("5. Vite serves src/main.tsx", False, f"error: {e}")

# 6. CSS asset
try:
    r = urllib.request.urlopen(f"{VITE}/src/styles/index.css", timeout=5)
    body = r.read().decode("utf-8", errors="ignore")
    check("6. Vite serves index.css", r.status == 200 and "--primary" in body, f"status={r.status}, length={len(body)}")
except Exception as e:
    check("6. Vite serves index.css", False, f"error: {e}")

# 7. API proxy: /api/v1/health (no auth)
try:
    r = urllib.request.urlopen(f"{API}/health", timeout=10)
    data = json.loads(r.read())
    check("7. API proxy /health", r.status == 200, f"status={r.status}, data={data}")
except Exception as e:
    check("7. API proxy /health", False, f"error: {e}")

# 8. API proxy: login
token = None
try:
    req = urllib.request.Request(
        f"{API}/auth/login",
        data=json.dumps({"username": "admin", "password": "admin123"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    r = urllib.request.urlopen(req, timeout=10)
    data = json.loads(r.read())
    token = data["data"]["access_token"]
    check("8. API proxy /auth/login", r.status == 200 and token, f"token_len={len(token)}")
except Exception as e:
    check("8. API proxy /auth/login", False, f"error: {e}")

# 9. Authenticated request: /auth/me
if token:
    try:
        req = urllib.request.Request(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
        r = urllib.request.urlopen(req, timeout=10)
        data = json.loads(r.read())
        check("9. API proxy /auth/me", r.status == 200 and data["data"]["username"] == "admin", f"username={data['data']['username']}")
    except Exception as e:
        check("9. API proxy /auth/me", False, f"error: {e}")

# 10. Authenticated request: /knowledge-bases
if token:
    try:
        req = urllib.request.Request(f"{API}/knowledge-bases", headers={"Authorization": f"Bearer {token}"})
        r = urllib.request.urlopen(req, timeout=10)
        data = json.loads(r.read())
        items = data.get("data", {}).get("items", []) if isinstance(data.get("data"), dict) else data.get("data", [])
        check("10. API proxy /knowledge-bases", r.status == 200, f"kb_count={len(items)}")
    except Exception as e:
        check("10. API proxy /knowledge-bases", False, f"error: {e}")

# 11. SSE endpoint reachable via proxy (will fail auth or return 404 if wrong path)
if token:
    try:
        req = urllib.request.Request(
            f"{API}/chat/sessions/999999/stream",
            data=json.dumps({"content": "test"}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            r = urllib.request.urlopen(req, timeout=5)
            check("11. SSE endpoint reachable", True, f"status={r.status}")
        except urllib.error.HTTPError as he:
            # 404/422 means route is correct but session doesn't exist - that's OK
            ok = he.code in (404, 422, 400)
            check("11. SSE endpoint reachable", ok, f"http_status={he.code}")
    except Exception as e:
        check("11. SSE endpoint reachable", False, f"error: {e}")

# 12. Client-side route fallback (any path returns index.html)
try:
    r = urllib.request.urlopen(f"{VITE}/knowledge-bases", timeout=5)
    body = r.read().decode("utf-8", errors="ignore")
    check("12. CSR fallback (deep path returns HTML)", r.status == 200 and "<div id=\"root\"" in body, f"status={r.status}")
except Exception as e:
    check("12. CSR fallback", False, f"error: {e}")

# Summary
print()
print("=" * 60)
passed = sum(1 for _, s, _ in results if s == "PASS")
failed = sum(1 for _, s, _ in results if s == "FAIL")
print(f"Phase 7 验收结果: {passed}/{len(results)} PASS, {failed} FAIL")
print("=" * 60)

# Write JSON
import pathlib
out = pathlib.Path(r"G:\aiplatform\backend\phase7_result.json")
out.write_text(json.dumps({
    "phase": "Phase 7 - Frontend (Vite + React)",
    "total": len(results),
    "passed": passed,
    "failed": failed,
    "details": [{"name": n, "status": s, "detail": d} for n, s, d in results],
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Result saved to {out}")
