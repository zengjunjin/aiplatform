"""CDP 边界测试 - 禁用用户 access_token 立即失效验证（P1）

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

核心场景：
1. admin 创建用户 A 并登录获取 access_token
2. admin 禁用用户 A
3. 用用户 A 的 access_token（禁用前签发）调 GET /auth/me
4. 验证立即失效（401）

历史背景：
早期版本存在安全设计缺陷——禁用用户后 access_token 仍可使用直到自然过期。
该缺陷已修复：deps.py get_current_user L104-105 现已检查 user.is_active，
禁用后立即返回 401。本测试从 xfail 改为严格断言 401，确保修复不被回退。

双账号验证：
- admin CDP 会话：执行禁用操作 + UI 验证状态变更
- 用户 A API 验证：用旧 access_token 调 API 验证是否失效
"""

import os
import time

import pytest
import requests

from tests.e2e.helpers.cdp_auth import (
    create_user_via_api,
    login_cdp_session,
    make_cdp_client,
)

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"


@pytest.fixture(scope="module")
def cdp_admin(admin_token):
    """admin CDP 会话，导航到 /#/users。"""
    client = make_cdp_client(CDP_PORT)
    login_cdp_session(client, admin_token, "#/users")
    yield client
    client.close()


def _disable_user_via_api(base_url, admin_headers, user_id):
    """通过 API 禁用用户。"""
    r = requests.put(
        f"{base_url}/users/{user_id}/status",
        json={"is_active": False},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Disable user failed: {r.status_code} {r.text[:200]}"


def _enable_user_via_api(base_url, admin_headers, user_id):
    """通过 API 启用用户。"""
    r = requests.put(
        f"{base_url}/users/{user_id}/status",
        json={"is_active": True},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Enable user failed: {r.status_code} {r.text[:200]}"


def test_disabled_user_access_token_invalidation(base_url, admin_headers, cdp_admin):
    """P1: 禁用用户后，其 access_token 立即失效（401）

    步骤：
    1. 创建用户 A，登录获取 access_token
    2. 用 access_token 调 GET /auth/me 验证 200（基线）
    3. admin 禁用用户 A
    4. 用同一个 access_token 再调 GET /auth/me
    5. 断言 401（deps.py get_current_user L104 检查 is_active）

    历史：早期版本 access_token 不检查 is_active，禁用后仍可用。
    现已修复，本测试从 xfail 改为严格断言确保不被回退。
    """
    # 1. 创建用户 A 并登录获取 access_token
    user_a = create_user_via_api(base_url, admin_headers)
    user_a_id = user_a["user"]["id"]
    user_a_token = user_a["access_token"]

    # 2. 基线验证：access_token 有效
    r_before = requests.get(
        f"{base_url}/auth/me",
        headers={"Authorization": f"Bearer {user_a_token}"},
        timeout=10,
    )
    assert r_before.status_code == 200, (
        f"Baseline /auth/me should return 200 for active user, "
        f"got {r_before.status_code}: {r_before.text[:200]}"
    )

    # 3. admin 禁用用户 A
    _disable_user_via_api(base_url, admin_headers, user_a_id)

    # 等待 1 秒确保禁用生效（数据库事务提交 + 用户缓存失效）
    time.sleep(1)

    # 4. 用同一个 access_token 再调 GET /auth/me
    r_after = requests.get(
        f"{base_url}/auth/me",
        headers={"Authorization": f"Bearer {user_a_token}"},
        timeout=10,
    )

    # 5. 严格断言 401（不再使用 xfail）
    assert r_after.status_code == 401, (
        f"Disabled user's access_token should be invalidated immediately (401), "
        f"got {r_after.status_code}: {r_after.text[:200]}. "
        f"Check deps.py get_current_user is_active check."
    )

    # 清理：重新启用用户（避免影响后续测试）
    _enable_user_via_api(base_url, admin_headers, user_a_id)


def test_disabled_user_cannot_access_protected_resource(base_url, admin_headers):
    """P1 补充：禁用用户调用受保护资源（GET /knowledge-bases）的权限验证

    与 test_disabled_user_access_token_invalidation 互补：
    - 前者验证 /auth/me（身份端点）
    - 本测试验证业务端点（GET /knowledge-bases）

    同样严格断言 401（不再使用 xfail）。
    """
    # 创建用户 A
    user_a = create_user_via_api(base_url, admin_headers)
    user_a_id = user_a["user"]["id"]
    user_a_token = user_a["access_token"]

    # 基线：用户 A 可访问 KB 列表
    r_before = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 1, "page_size": 5},
        headers={"Authorization": f"Bearer {user_a_token}"},
        timeout=10,
    )
    assert (
        r_before.status_code == 200
    ), f"Baseline KB list should return 200, got {r_before.status_code}"

    # 禁用用户 A
    _disable_user_via_api(base_url, admin_headers, user_a_id)
    time.sleep(1)

    # 禁用后调用业务端点
    r_after = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 1, "page_size": 5},
        headers={"Authorization": f"Bearer {user_a_token}"},
        timeout=10,
    )

    # 严格断言 401（不再使用 xfail）
    assert r_after.status_code == 401, (
        f"Disabled user's access_token should be invalidated for business endpoints too (401), "
        f"got {r_after.status_code}: {r_after.text[:200]}"
    )

    # 清理
    _enable_user_via_api(base_url, admin_headers, user_a_id)
