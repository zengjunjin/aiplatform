"""CDP 双账号认证辅助

提供创建用户、注入 token、验证 API 调用等辅助函数，
支持双账号交叉验证场景（admin 操作 + 普通用户验证权限实效）。
"""

import json
import time
import uuid

import requests

from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import wait_for, wait_for_dom_ready

TAURI_HOME = "http://tauri.localhost/"


def create_user_via_api(
    base_url: str, admin_headers: dict, username: str = None, password: str = "Test@123456"
) -> dict:
    """通过 API 创建普通用户并登录，返回用户信息 + token。

    Args:
        base_url: API base URL (e.g. http://localhost:8000/api/v1)
        admin_headers: admin 的 Authorization headers（注册不需要，但保留接口一致）
        username: 可选用户名，默认自动生成
        password: 密码，默认 Test@123456

    Returns:
        {user, password, access_token, refresh_token, username}
    """
    if not username:
        username = f"e2e_cdp_{uuid.uuid4().hex[:8]}"
    email = f"{username}@test.com"

    r = requests.post(
        f"{base_url}/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
        },
        timeout=10,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Register user failed: {r.status_code} {r.text}")
    user_data = r.json().get("data", r.json())

    r2 = requests.post(
        f"{base_url}/auth/login",
        json={
            "username": username,
            "password": password,
        },
        timeout=10,
    )
    if r2.status_code != 200:
        raise RuntimeError(f"Login user failed: {r2.status_code} {r2.text}")
    token_data = r2.json().get("data", r2.json())

    return {
        "user": user_data,
        "password": password,
        "username": username,
        "access_token": token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
    }


def login_cdp_session(cdp: CdpClient, token_data: dict, route: str = "#/dashboard") -> None:
    """注入 token 到 CDP 客户端的 localStorage 并导航到指定路由。

    前端 auth store 使用 zustand persist，localStorage key 为 'rag-auth'，
    存储格式为 {state: {token, refreshToken, refreshTokenExpiresAt, user, themeMode}, version: 0}。

    关键：写入 localStorage 后必须触发整页重载（cross-document navigation），
    否则 zustand persist 不会重新 rehydrate，内存中仍是上一个用户的 token，
    导致权限边界测试误用错误账号的 token 调用 API。仅靠 Page.navigate
    指向仅 hash 不同的 URL 会被当作 same-document 导航（不重置 JS 上下文），
    因此先设置 hash 再用 Page.reload 强制整页加载。

    多个 CDP 测试文件共用同一个 WebView2 target（9223 端口只有一个 page target），
    一个测试创建独立 CdpClient 并注入普通用户 token 时会覆盖 localStorage 中的
    admin token，导致后续使用 admin token 的测试失败。本函数在 reload 后验证
    登录是否成功（hash 不含 'login'），若失败则重试一次。

    Args:
        cdp: CdpClient 实例
        token_data: 包含 access_token/refresh_token/user 的 dict
        route: 导航路由（如 #/dashboard, #/knowledge-bases）
    """
    auth_data = {
        "state": {
            "token": token_data["access_token"],
            "refreshToken": token_data["refresh_token"],
            "refreshTokenExpiresAt": int(time.time() * 1000) + 7 * 24 * 3600 * 1000,
            "user": token_data.get("user", token_data),
            "themeMode": "light",
        },
        "version": 0,
    }
    auth_json = json.dumps(auth_data)

    def _inject_and_reload():
        # 导航到 tauri 根域，确保可访问 localStorage（跨域时 localStorage 隔离）
        cdp.navigate(TAURI_HOME)
        wait_for_dom_ready(cdp, timeout=5)
        cdp.evaluate(f"""
            try {{
                localStorage.setItem('rag-auth', JSON.stringify({auth_json}));
            }} catch(e) {{}}
        """)
        # 强制整页重载：zustand persist 从新写入的 localStorage 重新 rehydrate。
        # 不能在 reload 前设置 window.location.hash：
        # 设置 hash 会触发 SPA 路由，此时 store 还是上一个用户的 rehydrate 状态
        # （localStorage 已更新但 store 不会自动重新 rehydrate），AdminRoute 检查
        # store 中的 user 仍是旧用户 → 非 admin 被重定向到 #/dashboard → hash 改变
        # → Page.reload 时 URL 已变成 #/dashboard，目标路由丢失。
        # 正确流程：先 reload 让 store rehydrate 新 token，再设置 hash 导航到目标路由。
        cdp.send("Page.reload")
        # reload 后需等待整页加载完成；readyState 轮询在 reload 提交瞬间可能读到
        # 旧页面的 "complete"，无法可靠轮询，保留固定等待确保 rehydrate 完成。
        time.sleep(3)
        # reload 后 store 已 rehydrate 新用户，安全设置 hash 导航到目标路由
        cdp.evaluate(f"window.location.hash = {json.dumps(route)}")
        wait_for(
            lambda: route in (cdp.evaluate("window.location.hash") or ""),
            timeout=5,
            interval=0.3,
            message=f"hash route set to {route}",
        )

    _inject_and_reload()
    # 验证登录是否成功：hash 不应包含 'login'。
    # 若仍在 login 页，说明 token 注入或 rehydrate 失败——重试一次。
    hash_val = cdp.evaluate("window.location.hash") or ""
    if "login" in hash_val:
        _inject_and_reload()


def logout_cdp_session(cdp: CdpClient) -> None:
    """清除 localStorage 中的 rag-auth，导航到登录页。"""
    cdp.evaluate("localStorage.removeItem('rag-auth')")
    cdp.navigate(TAURI_HOME + "#/login")
    wait_for_dom_ready(cdp, timeout=5)


def switch_cdp_user(cdp: CdpClient, new_token_data: dict, route: str = "#/dashboard") -> None:
    """在同一个 CDP 会话内切换用户（登出 + 登入）。

    Args:
        cdp: CdpClient 实例
        new_token_data: 新用户的 token 数据
        route: 导航路由
    """
    logout_cdp_session(cdp)
    login_cdp_session(cdp, new_token_data, route)


def verify_api_call(
    url: str, method: str = "GET", token: str = None, expected_status: int = None, **kwargs
) -> requests.Response:
    """用指定 token 调用 API，可选验证状态码。

    Args:
        url: 完整 API URL
        method: HTTP 方法
        token: Bearer token
        expected_status: 期望状态码（如 403, 200）
        **kwargs: 传给 requests 的额外参数

    Returns:
        requests.Response
    """
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.request(method, url, headers=headers, timeout=10, **kwargs)
    if expected_status is not None:
        assert (
            r.status_code == expected_status
        ), f"API {method} {url} expected {expected_status}, got {r.status_code}: {r.text[:200]}"
    return r


def make_cdp_client(cdp_port: int = 9223) -> CdpClient:
    """创建并连接 CDP 客户端，连接失败时 pytest.skip。"""
    import pytest

    client = CdpClient(cdp_port=cdp_port)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {cdp_port}): {e}")
    return client
