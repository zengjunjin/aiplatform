"""用户管理 E2E 测试

API:
- GET    /users                  -> admin only, paginated
- GET    /users/search?q=xxx     -> 任意已认证用户
- PUT    /users/{id}/role        -> admin only
- PUT    /users/{id}/status      -> admin only
- 注意：API 没有 POST /users、DELETE /users/{id}、GET /users/{id}、GET /users/me
        用户创建走 /auth/register，用户信息走 /auth/me
"""

import requests

from tests.e2e.conftest import extract_data


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


def test_admin_can_disable_user(base_url, admin_headers, test_user):
    """admin 禁用用户"""
    r = requests.put(
        f"{base_url}/users/{test_user['user']['id']}/status",
        json={"is_active": False},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Disable user failed: {r.text}"
    updated = extract_data(r)
    assert updated["is_active"] is False


def test_admin_can_enable_user(base_url, admin_headers, test_user):
    """admin 启用用户"""
    # 先禁用
    requests.put(
        f"{base_url}/users/{test_user['user']['id']}/status",
        json={"is_active": False},
        headers=admin_headers,
        timeout=10,
    )
    # 再启用
    r = requests.put(
        f"{base_url}/users/{test_user['user']['id']}/status",
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
