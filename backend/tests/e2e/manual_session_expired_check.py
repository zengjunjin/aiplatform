"""手动实测：Tauri 打包形态下会话过期场景的 toast 抑制验证

场景：Dashboard（6 路并发加载）+ token 被吊销 + 整页 reload
预期：
  1. 仅出现一条 "登录已过期，请重新登录"（auth store 统一提示）
  2. 不出现 "加载失败" / "request failed" 等错误 toast
  3. 自动跳转到登录页

运行前提：
  - Tauri 打包 exe 已启动（CDP 9223）
  - 后端容器健康
  - cd backend && python -m tests.e2e.manual_session_expired_check
"""

import sys
import time

import requests

from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import wait_for, wait_for_dom_ready

TAURI_HOME = "http://tauri.localhost/"
API = "http://localhost:8000/api/v1"
ADMIN_USER = "admin"
ADMIN_PASSWORD = "AdminAcceptance2026!StrongPwd"

# toast 收集：antd message 挂载在 body 下的 .ant-message 容器
COLLECT_TOASTS_JS = """
(() => {
  const nodes = document.querySelectorAll('.ant-message-notice-content');
  return JSON.stringify(Array.from(nodes).map(n => (n.textContent || '').trim()).filter(Boolean));
})()
"""


def main() -> int:
    # 1. 连接 CDP（等待 app 启动，最多 60s）
    cdp = CdpClient(cdp_port=9223)
    print("[1] 连接 CDP 9223 ...")
    try:
        cdp.connect(timeout=60)
    except Exception as e:
        print(f"FAIL: CDP 不可用: {e}")
        return 1
    print("    OK")

    # 2. API 登录 admin
    print("[2] API 登录 admin ...")
    r = requests.post(
        f"{API}/auth/login",
        json={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    if r.status_code != 200:
        print(f"FAIL: 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    data = r.json().get("data", r.json())
    access, refresh = data["access_token"], data["refresh_token"]
    user = data.get("user", {})
    print(f"    OK user={user.get('username')}")

    # 3. 注入 token 并导航到 Dashboard
    print("[3] 注入 token → #/dashboard ...")
    import json as _json

    auth_data = {
        "state": {
            "token": access,
            "refreshToken": refresh,
            "refreshTokenExpiresAt": int(time.time() * 1000) + 7 * 24 * 3600 * 1000,
            "user": user,
            "themeMode": "light",
        },
        "version": 0,
    }
    cdp.navigate(TAURI_HOME)
    wait_for_dom_ready(cdp, timeout=10)
    cdp.evaluate(
        "localStorage.setItem('rag-auth', "
        f"JSON.stringify({_json.dumps(auth_data, ensure_ascii=False)}))"
    )
    cdp.send("Page.reload")
    time.sleep(3)
    cdp.evaluate("window.location.hash = '#/dashboard'")
    wait_for(
        lambda: "dashboard" in (cdp.evaluate("window.location.hash") or ""),
        timeout=10,
        interval=0.3,
        message="hash -> #/dashboard",
    )
    # 等待 6 路并发加载完成（数据出现或 loading 结束）
    time.sleep(3)
    hash_val = cdp.evaluate("window.location.hash") or ""
    if "login" in hash_val:
        print(f"FAIL: 注入后仍被重定向到 {hash_val}")
        return 1
    print(f"    OK 当前路由 {hash_val}")

    # 4. 吊销 token（后端 logout 将 access+refresh 拉黑）
    print("[4] API 吊销 token (POST /auth/logout) ...")
    r2 = requests.post(
        f"{API}/auth/logout",
        headers={"Authorization": f"Bearer {access}"},
        json={"refresh_token": refresh},
        timeout=10,
    )
    print(f"    logout status={r2.status_code}")
    # 验证 token 确实失效
    r3 = requests.get(
        f"{API}/users/me",
        headers={"Authorization": f"Bearer {access}"},
        timeout=10,
    )
    if r3.status_code != 401:
        print(f"WARN: 吊销后 /users/me 状态码 {r3.status_code}（预期 401），logout 请求体: {r2.text[:200]}")
    else:
        print("    OK token 已失效（401）")

    # 5. 整页 reload 触发 6 路并发加载 → 全部 401 → refresh 失败 → 统一提示
    print("[5] Page.reload 触发会话过期 ...")
    cdp.send("Page.reload")
    # toast 默认 3s 消失，300ms 间隔轮询收集 10s
    seen: list[str] = []
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            raw = cdp.evaluate(COLLECT_TOASTS_JS)
            if raw:
                for txt in _json.loads(raw):
                    if txt and txt not in seen:
                        seen.append(txt)
                        print(f"    [toast] {txt}")
        except Exception:
            pass  # reload 过程中 evaluate 可能瞬时失败
        time.sleep(0.3)

    # 6. 验证跳转登录页
    time.sleep(1)
    final_hash = cdp.evaluate("window.location.hash") or ""
    print(f"[6] 最终路由: {final_hash}")
    print(f"[6] 收集到的全部 toast ({len(seen)}): {seen}")

    # 7. 判定
    ok = True
    if not any("登录已过期" in s or "Session expired" in s for s in seen):
        print("FAIL: 未出现统一的 '登录已过期' 提示")
        ok = False
    noise = [s for s in seen if ("登录已过期" not in s and "Session expired" not in s)]
    if noise:
        print(f"FAIL: 出现了未抑制的噪音 toast: {noise}")
        ok = False
    if "login" not in final_hash:
        print("FAIL: 未跳转到登录页")
        ok = False

    print("\n===== 结果 =====")
    print("PASS: 会话过期场景 toast 抑制验证通过" if ok else "FAIL: 验证未通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
