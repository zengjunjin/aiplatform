"""CDP 边界测试 - 禁用用户 access_token 立即失效验证（P1）

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

核心场景：
1. admin 创建用户 A 并登录获取 access_token
2. admin 禁用用户 A
3. 用用户 A 的 access_token（禁用前签发）调 GET /auth/me
4. 验证是否立即失效（理想：401；当前已知缺陷：200）

conftest.py 第 110-112 行明确记录：
"token 在签发后即不依赖 is_active 校验（仅 /auth/login 会检查 is_active），
因此 disable 不会影响其他测试。"

这是已知的安全设计缺陷：禁用用户后，其已签发的 access_token 仍可继续使用
直到自然过期（默认 30 分钟）。本测试用 xfail 记录现状，倒逼后续修复
（引入 token 版本号或 access_token 黑名单机制）。

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
    """P1: 禁用用户后，其 access_token 是否立即失效

    步骤：
    1. 创建用户 A，登录获取 access_token
    2. 用 access_token 调 GET /auth/me 验证 200（基线）
    3. admin 禁用用户 A
    4. 用同一个 access_token 再调 GET /auth/me
    5. 验证状态码

    已知缺陷（conftest.py L110-112）：access_token 在签发后不依赖 is_active 校验，
    禁用后仍可继续使用直到自然过期。本测试用 xfail 记录此现状。

    修复方向：在 get_current_user 依赖中检查 user.is_active，
    或引入 token 版本号机制（用户状态变更时递增 token_version）。
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

    # 等待 1 秒确保禁用生效（数据库事务提交）
    time.sleep(1)

    # 4. 用同一个 access_token 再调 GET /auth/me
    r_after = requests.get(
        f"{base_url}/auth/me",
        headers={"Authorization": f"Bearer {user_a_token}"},
        timeout=10,
    )

    # 5. 验证状态码
    # 理想行为：401（access_token 立即失效）
    # 当前行为：200（已知缺陷，access_token 不检查 is_active）
    if r_after.status_code == 200:
        # 已知缺陷：access_token 仍有效，标记为 xfail
        pytest.xfail(
            "已知安全缺陷：禁用用户的 access_token 未立即失效。"
            "conftest.py L110-112 记录：token 签发后不检查 is_active。"
            "修复方向：get_current_user 依赖中检查 user.is_active，"
            "或引入 token 版本号机制。"
        )
    elif r_after.status_code == 401:
        # 已修复：access_token 立即失效
        assert r_after.status_code == 401, (
            f"Disabled user's access_token should be invalidated (401), "
            f"got {r_after.status_code}: {r_after.text[:200]}"
        )
    else:
        # 其他状态码：异常
        pytest.fail(
            f"Unexpected status code for disabled user's access_token: "
            f"{r_after.status_code}: {r_after.text[:200]}"
        )

    # 清理：重新启用用户（避免影响后续测试）
    _enable_user_via_api(base_url, admin_headers, user_a_id)


def test_disabled_user_cannot_access_protected_resource(base_url, admin_headers):
    """P1 补充：禁用用户调用受保护资源（GET /knowledge-bases）的权限验证

    与 test_disabled_user_access_token_invalidation 互补：
    - 前者验证 /auth/me（身份端点）
    - 本测试验证业务端点（GET /knowledge-bases）

    同样用 xfail 记录 access_token 不失效的现状。
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

    if r_after.status_code == 200:
        pytest.xfail(
            "已知安全缺陷：禁用用户的 access_token 仍可访问业务端点。"
            "与 test_disabled_user_access_token_invalidation 同根因。"
        )
    elif r_after.status_code == 401:
        assert True, "禁用用户的 access_token 已正确失效"
    else:
        pytest.fail(f"Unexpected status: {r_after.status_code}: {r_after.text[:200]}")

    # 清理
    _enable_user_via_api(base_url, admin_headers, user_a_id)
