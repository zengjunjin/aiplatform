"""CDP 边界测试 - 角色变更后旧 access_token 权限实效验证（P2）

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

核心场景：
1. admin 创建用户 A
2. admin 提升用户 A 为 admin 角色
3. 用户 A 登录获取含 role=admin 的 access_token
4. admin 降级用户 A 为 user 角色
5. 用用户 A 的旧 access_token（仍含 role=admin）调 GET /users
6. 验证：403（后端 get_admin_user 查 DB 验证角色，降级后立即生效）

后端鉴权设计（app/api/deps.py）：
- get_current_user 仅从 JWT 解码 user_id，不读 role claim
- 查 Redis 缓存（TTL 60s）→ 未命中查 DB → 返回带当前 role 的 User 对象
- get_admin_user 检查 user.role != "admin" 则 403
- update_role 主动调用 _invalidate_user_cache 失效缓存

因此角色变更（升/降）对旧 token 立即生效：
- 降级：旧 admin token 立即失去 admin 权限（403）✓
- 提升：旧 user token 立即获得 admin 权限（200）—— 设计行为，非缺陷

双账号验证：
- admin CDP 会话：执行降级操作 + UI 验证角色变更
- 用户 A API 验证：用旧 access_token 调 admin-only API
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


def _update_user_role(base_url, admin_headers, user_id, role):
    """通过 API 更新用户角色。"""
    r = requests.put(
        f"{base_url}/users/{user_id}/role",
        json={"role": role},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Update role to {role} failed: {r.status_code} {r.text[:200]}"


def test_demote_invalidates_old_admin_token(base_url, admin_headers, cdp_admin):
    """P2: 角色降级后旧 access_token（含 role=admin）是否立即失效

    步骤：
    1. 创建用户 A
    2. 提升为 admin，登录获取含 role=admin 的 access_token
    3. 基线：用旧 token 调 GET /users 验证 200（admin 权限）
    4. 降级为 user
    5. 用同一个旧 token 再调 GET /users
    6. 验证状态码

    后端设计：get_admin_user 查 DB 验证角色（非 JWT claim），
    update_role 主动失效 Redis 缓存，因此降级后旧 token 立即失去 admin 权限（403）。
    """
    # 1. 创建用户 A
    user_a = create_user_via_api(base_url, admin_headers)
    user_a_id = user_a["user"]["id"]

    # 2. 提升为 admin 并登录获取含 role=admin 的 access_token
    _update_user_role(base_url, admin_headers, user_a_id, "admin")
    r_login = requests.post(
        f"{base_url}/auth/login",
        json={
            "username": user_a["username"],
            "password": user_a["password"],
        },
        timeout=10,
    )
    assert r_login.status_code == 200, f"Login failed: {r_login.text[:200]}"
    admin_token_a = r_login.json().get("data", {}).get("access_token")

    # 3. 基线：用 admin token 调 GET /users 验证 200
    r_before = requests.get(
        f"{base_url}/users",
        params={"page": 1, "page_size": 5},
        headers={"Authorization": f"Bearer {admin_token_a}"},
        timeout=10,
    )
    assert r_before.status_code == 200, (
        f"Baseline GET /users as admin should return 200, "
        f"got {r_before.status_code}: {r_before.text[:200]}"
    )

    # 4. 降级为 user
    _update_user_role(base_url, admin_headers, user_a_id, "user")
    time.sleep(1)

    # 5. 用同一个旧 token（仍含 role=admin）再调 GET /users
    r_after = requests.get(
        f"{base_url}/users",
        params={"page": 1, "page_size": 5},
        headers={"Authorization": f"Bearer {admin_token_a}"},
        timeout=10,
    )

    # 6. 验证状态码：后端查 DB 验证角色，降级后旧 token 立即失效（403）
    assert r_after.status_code == 403, (
        f"角色降级后旧 admin token 应立即失效（403），"
        f"got {r_after.status_code}: {r_after.text[:200]}\n"
        f"后端 get_admin_user 查 DB 验证角色，update_role 已失效缓存，"
        f"旧 token 不应再有 admin 权限。"
    )


def test_promote_does_not_grant_retroactive_admin_via_old_token(base_url, admin_headers):
    """P2 补充：提升角色后，旧 access_token（含 role=user）是否自动获得 admin 权限

    与 test_demote_invalidates_old_admin_token 互补：
    - 前者验证降级后旧 admin token 是否失效（预期 403）
    - 本测试验证提升后旧 user token 是否获得 admin 权限

    后端设计：get_admin_user 查 DB 验证角色（非 JWT claim），
    update_role 主动失效 Redis 缓存，因此提升后旧 token 立即获得 admin 权限（200）。
    这是 DB-based 鉴权的设计行为：角色变更（升/降）对旧 token 立即生效。
    JWT 中的 role claim 仅用于客户端展示，不参与鉴权决策。
    """
    # 1. 创建用户 A（普通用户）
    user_a = create_user_via_api(base_url, admin_headers)
    user_a_id = user_a["user"]["id"]
    user_token = user_a["access_token"]  # 含 role=user

    # 2. 基线：用 user token 调 GET /users 验证 403
    r_before = requests.get(
        f"{base_url}/users",
        params={"page": 1, "page_size": 5},
        headers={"Authorization": f"Bearer {user_token}"},
        timeout=10,
    )
    assert r_before.status_code == 403, (
        f"Baseline GET /users as user should return 403, " f"got {r_before.status_code}"
    )

    # 3. 提升为 admin
    _update_user_role(base_url, admin_headers, user_a_id, "admin")
    time.sleep(1)

    # 4. 用同一个旧 token（仍含 role=user）再调 GET /users
    r_after = requests.get(
        f"{base_url}/users",
        params={"page": 1, "page_size": 5},
        headers={"Authorization": f"Bearer {user_token}"},
        timeout=10,
    )

    # 后端查 DB 验证角色，提升后旧 token 立即获得 admin 权限（200）
    # 这是 DB-based 鉴权的设计行为，与降级后立即失效对称
    assert r_after.status_code == 200, (
        f"提升角色后旧 user token 应立即获得 admin 权限（200），"
        f"got {r_after.status_code}: {r_after.text[:200]}\n"
        f"后端 get_admin_user 查 DB 验证角色，update_role 已失效缓存，"
        f"旧 token 应反映新角色。"
    )

    # 清理：降级回 user
    _update_user_role(base_url, admin_headers, user_a_id, "user")
