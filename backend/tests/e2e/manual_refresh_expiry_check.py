"""手动实测：refresh token 自然过期的两条路径

场景 A（本地过期）：refreshToken 本身有效，但 refreshTokenExpiresAt 已过时。
  预期：rehydrate 检测到本地过期 → 静默清空用户态 → 跳转登录页，
  无 "XX加载失败" 噪音 toast（当前设计为静默登出，允许 0 条 toast）。

场景 B（服务端过期）：refreshTokenExpiresAt 未到，但 refresh token 已被吊销
  （等价于后端侧自然过期后 refresh 接口返回 401）。
  预期：首个 API 401 → 拦截器 refresh → 401 → isAuthExpired 标记 →
  恰好 1 条 "登录已过期，请重新登录" + 跳转登录页，无其他噪音 toast。

运行前提：Tauri 打包 exe 已启动（CDP 9223）、后端容器健康。
  cd backend && python -m tests.e2e.manual_refresh_expiry_check
"""

import json
import sys
import time

import requests

from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import wait_for, wait_for_dom_ready

TAURI_HOME = "http://tauri.localhost/"
API = "http://localhost:8000/api/v1"
ADMIN_PASSWORD = "AdminAcceptance2026!StrongPwd"

COLLECT_TOASTS_JS = """
(() => {
  const nodes = document.querySelectorAll('.ant-message-notice-content');
  return JSON.stringify(Array.from(nodes).map(n => (n.textContent || '').trim()).filter(Boolean));
})()
"""


def api_login():
    r = requests.post(
        f"{API}/auth/login",
        json={"username": "admin", "password": ADMIN_PASSWORD},
        timeout=10,
    )
    r.raise_for_status()
    return r.json().get("data", r.json())


def inject_and_reload(cdp: CdpClient, access: str, refresh: str, user: dict, expires_at_ms: int, route: str = "#/dashboard"):
    auth_data = {
        "state": {
            "token": access,
            "refreshToken": refresh,
            "refreshTokenExpiresAt": expires_at_ms,
            "user": user,
            "themeMode": "light",
        },
        "version": 0,
    }
    cdp.navigate(TAURI_HOME)
    wait_for_dom_ready(cdp, timeout=10)
    cdp.evaluate(
        "localStorage.setItem('rag-auth', "
        f"JSON.stringify({json.dumps(auth_data, ensure_ascii=False)}))"
    )
    cdp.send("Page.reload")
    time.sleep(3)
    if route is None:
        return
    cdp.evaluate(f"window.location.hash = {json.dumps(route)}")
    wait_for(
        lambda: route in (cdp.evaluate("window.location.hash") or ""),
        timeout=10,
        interval=0.3,
        message=f"hash -> {route}",
    )


def collect_toasts(cdp: CdpClient, seconds: float = 10) -> list[str]:
    seen: list[str] = []
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            raw = cdp.evaluate(COLLECT_TOASTS_JS)
            if raw:
                for txt in json.loads(raw):
                    if txt and txt not in seen:
                        seen.append(txt)
        except Exception:
            pass  # reload 瞬时 evaluate 可能失败
        time.sleep(0.3)
    return seen


def is_unified(s: str) -> bool:
    return "登录已过期" in s or "Session expired" in s


def scenario_a_local_expiry(cdp: CdpClient) -> bool:
    print("===== 场景 A：refreshTokenExpiresAt 本地过期 =====")
    data = api_login()
    print(f"[A1] 登录 OK user={data['user'].get('username')}")
    # expiresAt 设为 1 小时前 → 本地判定自然过期。
    # 注意：不设置目标路由——本地过期后路由守卫会立即重定向到 login，
    # hash 无法到达 dashboard（这正是要验证的行为）。
    inject_and_reload(
        cdp,
        data["access_token"],
        data["refresh_token"],
        data["user"],
        expires_at_ms=int(time.time() * 1000) - 3600 * 1000,
        route=None,
    )
    print("[A2] 已注入（expiresAt=1h前），reload 完成")
    toasts = collect_toasts(cdp, 8)
    final_hash = cdp.evaluate("window.location.hash") or ""
    print(f"[A3] toast ({len(toasts)}): {toasts}")
    print(f"[A3] 最终路由: {final_hash}")

    ok = True
    noise = [s for s in toasts if not is_unified(s)]
    if noise:
        print(f"FAIL: 本地过期场景出现噪音 toast: {noise}")
        ok = False
    if "login" not in final_hash:
        print("FAIL: 本地过期未跳转登录页")
        ok = False
    if not toasts:
        print("INFO: 本地过期为静默登出（当前设计：无提示直接跳登录页）")
    print(f"场景 A {'PASS' if ok else 'FAIL'}\n")
    return ok


def scenario_b_server_side_expiry(cdp: CdpClient) -> bool:
    print("===== 场景 B：服务端 refresh token 失效（等价自然过期）=====")
    data = api_login()
    print(f"[B1] 登录 OK，准备吊销 token ...")
    r = requests.post(
        f"{API}/auth/logout",
        headers={"Authorization": f"Bearer {data['access_token']}"},
        json={"refresh_token": data["refresh_token"]},
        timeout=10,
    )
    print(f"[B2] logout 吊销 status={r.status_code}")
    # 注入被吊销的 token，expiresAt 设为未来（模拟本地以为还有效、服务端已过期）。
    # 不设目标路由：被吊销 token 的首个请求 401 → refresh 401 → logout →
    # 路由守卫重定向 login，hash 到不了 dashboard（这正是要验证的行为）。
    inject_and_reload(
        cdp,
        data["access_token"],
        data["refresh_token"],
        data["user"],
        expires_at_ms=int(time.time() * 1000) + 7 * 24 * 3600 * 1000,
        route=None,
    )
    print("[B3] 已注入（被吊销 token + expiresAt=未来），reload 触发会话过期")
    toasts = collect_toasts(cdp, 10)
    final_hash = cdp.evaluate("window.location.hash") or ""
    print(f"[B4] toast ({len(toasts)}): {toasts}")
    print(f"[B4] 最终路由: {final_hash}")

    ok = True
    unified = [s for s in toasts if is_unified(s)]
    noise = [s for s in toasts if not is_unified(s)]
    if len(unified) != 1:
        print(f"FAIL: 预期恰好 1 条统一提示，实际 {len(unified)}: {unified}")
        ok = False
    if noise:
        print(f"FAIL: 出现未抑制的噪音 toast: {noise}")
        ok = False
    if "login" not in final_hash:
        print("FAIL: 未跳转登录页")
        ok = False
    print(f"场景 B {'PASS' if ok else 'FAIL'}\n")
    return ok


def main() -> int:
    cdp = CdpClient(cdp_port=9223)
    print("[0] 连接 CDP 9223 ...")
    try:
        cdp.connect(timeout=60)
    except Exception as e:
        print(f"FAIL: CDP 不可用: {e}")
        return 1
    print("    OK")

    ok_a = scenario_a_local_expiry(cdp)
    ok_b = scenario_b_server_side_expiry(cdp)

    print("===== 总结果 =====")
    print(f"场景 A（本地过期）: {'PASS' if ok_a else 'FAIL'}")
    print(f"场景 B（服务端过期）: {'PASS' if ok_b else 'FAIL'}")
    return 0 if (ok_a and ok_b) else 1


if __name__ == "__main__":
    sys.exit(main())
