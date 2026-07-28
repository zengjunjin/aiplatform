"""用户管理 E2E 测试

API:
- GET    /users                  -> admin only, paginated
- GET    /users/search?q=xxx     -> 任意已认证用户
- PUT    /users/{id}/role        -> admin only
- PUT    /users/{id}/status      -> admin only
- 注意：API 没有 POST /users、DELETE /users/{id}、GET /users/{id}、GET /users/me
        用户创建走 /auth/register，用户信息走 /auth/me
"""

import contextlib
import uuid

import pytest
import requests

from tests.e2e.conftest import extract_data


@pytest.fixture(scope="function")
def temp_disable_user(base_url, admin_headers):
    """P0-C4: 禁用/启用测试专用的独立用户 fixture（function scope）。

    创建临时用户 → 供 test_admin_can_disable_user / test_admin_can_enable_user 使用 → 测试后清理。
    不污染 session 级 test_user，保证测试隔离。

    之前 test_admin_can_disable_user 直接禁用 session 级 test_user，
    若测试失败或顺序变化，后续依赖 test_user_headers 的测试全部 401 连锁失败。
    """
    username = f"temp_disable_{uuid.uuid4().hex[:8]}"
    email = f"{username}@test.local"
    password = "Test@123456"

    # 注册临时用户
    r = requests.post(
        f"{base_url}/auth/register",
        json={"username": username, "email": email, "password": password},
        timeout=10,
    )
    assert r.status_code == 200, f"Register temp user failed: {r.text}"
    user_id = extract_data(r)["id"]

    yield user_id

    # 清理：软禁用临时用户（API 无 DELETE /users/{id}）
    with contextlib.suppress(Exception):
        requests.put(
            f"{base_url}/users/{user_id}/status",
            json={"is_active": False},
            headers=admin_headers,
            timeout=5,
        )


def test_admin_can_list_users(base_url, admin_headers):
    """admin 列出用户"""
    r = requests.get(
        f"{base_url}/users", params={"page": 1, "page_size": 10}, headers=admin_headers, timeout=10
    )
    assert r.status_code == 200, f"List users failed: {r.text}"
    data = extract_data(r)
    # 分页结构
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "total_pages" in data
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert len(data["items"]) >= 1  # 至少有 admin


def test_normal_user_cannot_list_users(base_url, test_user_headers):
    """普通用户不能列出用户"""
    r = requests.get(f"{base_url}/users", headers=test_user_headers, timeout=10)
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"


def test_search_users(base_url, admin_headers):
    """搜索用户"""
    r = requests.get(
        f"{base_url}/users/search", params={"q": "admin"}, headers=admin_headers, timeout=10
    )
    assert r.status_code == 200, f"Search users failed: {r.text}"
    data = extract_data(r)
    assert isinstance(data, list)
    assert any(u.get("username") == "admin" for u in data)


def test_admin_can_update_role(base_url, admin_headers, test_user):
    """admin 更新用户角色为 admin，测试后改回 user 以保证后续测试正常"""
    r = requests.put(
        f"{base_url}/users/{test_user['user']['id']}/role",
        json={"role": "admin"},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Update role failed: {r.text}"
    updated = extract_data(r)
    assert updated["role"] == "admin"

    # 改回 user，避免影响后续 test_normal_user_cannot_update_role 等测试
    requests.put(
        f"{base_url}/users/{test_user['user']['id']}/role",
        json={"role": "user"},
        headers=admin_headers,
        timeout=10,
    )


def test_admin_can_disable_user(base_url, admin_headers, temp_disable_user):
    """admin 禁用用户

    P0-C4: 使用 function 级独立 fixture（temp_disable_user），不污染 session 级 test_user。
    即使本测试失败，后续依赖 test_user_headers 的测试也不会受影响。
    """
    user_id = temp_disable_user
    r = requests.put(
        f"{base_url}/users/{user_id}/status",
        json={"is_active": False},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Disable user failed: {r.text}"
    updated = extract_data(r)
    assert updated["is_active"] is False


def test_admin_can_enable_user(base_url, admin_headers, temp_disable_user):
    """admin 启用用户

    P0-C4: 使用 function 级独立 fixture（temp_disable_user），不污染 session 级 test_user。
    """
    user_id = temp_disable_user
    # 先禁用
    requests.put(
        f"{base_url}/users/{user_id}/status",
        json={"is_active": False},
        headers=admin_headers,
        timeout=10,
    )
    # 再启用
    r = requests.put(
        f"{base_url}/users/{user_id}/status",
        json={"is_active": True},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Enable user failed: {r.text}"
    updated = extract_data(r)
    assert updated["is_active"] is True


def test_normal_user_cannot_update_role(base_url, test_user_headers):
    """普通用户不能修改角色

    使用不存在的用户 ID（999999）避免污染真实用户数据。
    权限检查应在用户存在性检查之前，因此返回 403 而非 404。
    """
    r = requests.put(
        f"{base_url}/users/999999/role",
        json={"role": "user"},
        headers=test_user_headers,
        timeout=10,
    )
    assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"
