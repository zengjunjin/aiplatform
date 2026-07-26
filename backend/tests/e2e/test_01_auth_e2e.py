"""认证 E2E 测试 - 真实 HTTP + 真实 JWT

API:
- POST /auth/login      -> {access_token, refresh_token, token_type, expires_in, user}
- POST /auth/refresh    -> 同上
- POST /auth/logout     -> 黑名单当前 token
- POST /auth/register   -> 注册新用户（仅 user 角色）
- GET  /auth/me         -> 当前用户信息
- PUT  /auth/password   -> 修改密码（需 confirm_password）
"""

import os

import jwt
import requests

from tests.e2e.conftest import extract_data


def _admin_password() -> str:
    """获取 admin 密码（H14: 与 conftest.py 保持一致的多级回退）"""
    return (
        os.getenv("E2E_ADMIN_PASSWORD")
        or os.getenv("INITIAL_ADMIN_PASSWORD")
        or "admin123"
    )


def test_login_admin_success(admin_token):
    """admin 登录成功（复用 session 级 admin_token fixture 避免重复登录触发限流）"""
    data = admin_token
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["role"] == "admin"
    assert data["user"]["username"] == "admin"
    # expires_in 应为 ACCESS_TOKEN_EXPIRE_MINUTES * 60
    # H14 修复：支持环境配置覆盖（默认 30*60=1800，部署 .env 可能设为 60*60=3600）
    expected_expires = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")) * 60
    assert data["expires_in"] == expected_expires, (
        f"Expected expires_in={expected_expires}, got {data['expires_in']}"
    )


def test_login_wrong_password(base_url):
    """错误密码登录失败"""
    r = requests.post(
        f"{base_url}/auth/login",
        json={
            "username": "admin",
            "password": "wrong_password_xxx",
        },
        timeout=10,
    )
    assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"


def test_access_token_has_iss_aud(admin_token):
    """access_token 包含 iss/aud claims"""
    token = admin_token["access_token"]
    # 不验证签名，仅 decode payload
    payload = jwt.decode(token, options={"verify_signature": False})
    assert payload["iss"] == "rag-platform", f"iss mismatch: {payload.get('iss')}"
    assert payload["aud"] == "rag-client", f"aud mismatch: {payload.get('aud')}"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"


def test_refresh_token_flow_and_single_use(base_url):
    """refresh_token 刷新 + 单次使用验证（合并以减少登录次数，避开 5/minute 限流）

    注意：生产代码 create_refresh_token 不含 jti，同一秒登录会生成相同 token。
    这里 sleep 1.1s 确保新 token 与 admin_token fixture 的 token 不同（记录为生产 bug）。
    """
    import time

    # 等待 1.1s 确保 iat 与 admin_token fixture 不同
    time.sleep(1.1)

    # 独立登录获取新 refresh_token
    r_login = requests.post(
        f"{base_url}/auth/login",
        json={
            "username": "admin",
            "password": _admin_password(),
        },
        timeout=10,
    )
    assert r_login.status_code == 200, f"Login failed: {r_login.text}"
    refresh_token = extract_data(r_login)["refresh_token"]

    # 第一次刷新成功
    r1 = requests.post(
        f"{base_url}/auth/refresh",
        json={
            "refresh_token": refresh_token,
        },
        timeout=10,
    )
    assert r1.status_code == 200, f"First refresh should succeed: {r1.text}"
    new_data = extract_data(r1)
    assert "access_token" in new_data
    assert new_data["refresh_token"]  # 非空

    # 第二次使用旧 refresh_token 应失败（已在黑名单）
    r2 = requests.post(
        f"{base_url}/auth/refresh",
        json={
            "refresh_token": refresh_token,
        },
        timeout=10,
    )
    assert (
        r2.status_code == 401
    ), f"Old refresh token should be revoked. Got {r2.status_code}: {r2.text}"


def test_protected_endpoint_require_auth(base_url):
    """未认证访问受保护端点"""
    r = requests.get(f"{base_url}/users", timeout=10)
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


def test_logout_blacklists_token(base_url):
    """登出后 access_token 失效"""
    import time

    # 等待 1.1s 确保 iat 与前一个测试不同（refresh_token 不含 jti 的生产 bug 规避）
    time.sleep(1.1)

    # 独立登录，避免污染 session 级 admin_token
    # 注意: 这是整个 session 的第 5 次 /auth/login 调用（2 次 conftest + 2 次前面测试 + 本次），
    # 可能触发 5/minute 限流。若被限流则等待 60s 重试。
    # 限流可能 429，重试直到成功或耗尽重试次数（替代固定 sleep(60)）
    for _ in range(12):
        r_login = requests.post(
            f"{base_url}/auth/login",
            json={
                "username": "admin",
                "password": _admin_password(),
            },
            timeout=10,
        )
        if r_login.status_code != 429:
            break
        time.sleep(5)  # 限流退避：5/minute 窗口，每 5s 重试一次
    assert r_login.status_code == 200, f"Login failed: {r_login.status_code}: {r_login.text}"
    login_data = extract_data(r_login)
    headers = {"Authorization": f"Bearer {login_data['access_token']}"}

    # 登出
    r = requests.post(
        f"{base_url}/auth/logout",
        json={"refresh_token": login_data["refresh_token"]},
        headers=headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Logout failed: {r.text}"

    # 验证 access_token 已失效
    r2 = requests.get(f"{base_url}/auth/me", headers=headers, timeout=10)
    assert r2.status_code == 401, f"Token should be blacklisted after logout. Got {r2.status_code}"


def test_get_me(base_url, admin_headers):
    """GET /auth/me 返回当前用户"""
    r = requests.get(f"{base_url}/auth/me", headers=admin_headers, timeout=10)
    assert r.status_code == 200
    user = extract_data(r)
    assert user["username"] == "admin"
    assert user["role"] == "admin"
