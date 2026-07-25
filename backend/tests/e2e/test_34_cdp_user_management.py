"""CDP UI 测试 - 用户管理 + 实效验证（双账号）

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. 用户列表渲染与列结构
2. 禁用用户（UI）+ 实效验证（refresh/login 返回 401）
3. 启用用户（UI）+ 实效验证（login 返回 200）
4. 提升为管理员（UI）+ 实效验证（侧边栏菜单 + 路由访问）
5. 降级为普通用户（UI）+ 实效验证（菜单消失 + 重定向）

核心：双账号 + 权限实效验证。admin 在 CDP 会话中操作 UI，
target_user 通过 API 验证权限变更的实效（token 失效、登录恢复、角色变更）。

注意：
- 用例 1-8 在同一 admin CDP 会话中完成，不重复 navigate /#/users。
- 权限实效验证用 verify_api_call 验证 API 状态码。
- target_user 行定位：在 Table 中按用户名查找行。
- Popconfirm 确认按钮选择器：.ant-popconfirm-buttons .ant-btn-primary。
"""

import contextlib
import json
import time

import pytest
import requests

from tests.e2e.helpers.cdp_auth import (
    create_user_via_api,
    login_cdp_session,
    make_cdp_client,
    verify_api_call,
)
from tests.e2e.helpers.waiters import wait_for_element


@pytest.fixture(scope="module")
def cdp_admin(admin_token):
    """admin CDP 会话，导航到 /#/users（整个模块共享，不重复导航）。"""
    client = make_cdp_client(9223)
    login_cdp_session(client, admin_token, "#/users")
    yield client
    client.close()


@pytest.fixture(scope="module")
def target_user(base_url, admin_headers):
    """创建目标用户（用于禁用/启用/角色变更测试）。"""
    user_info = create_user_via_api(base_url, admin_headers)
    yield user_info
    # 清理：禁用
    with contextlib.suppress(Exception):
        requests.put(
            f"{base_url}/users/{user_info['user']['id']}/status",
            json={"is_active": False},
            headers=admin_headers,
            timeout=5,
        )


def _click_popconfirm_ok(cdp, timeout=8):
    """轮询等待 Popconfirm 弹出并点击"确定"按钮。

    选择器：.ant-popconfirm-buttons .ant-btn-primary
    Ant Design v5 Button 两字之间自动插入空格，但 class 精确定位不受影响。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        clicked = cdp.evaluate("""
            (function() {
                var btns = document.querySelectorAll(
                    '.ant-popconfirm-buttons .ant-btn-primary'
                );
                if (btns.length > 0) {
                    btns[btns.length - 1].click();
                    return true;
                }
                return false;
            })();
        """)
        if clicked:
            return True
        time.sleep(0.5)
    return False


def _click_row_button(cdp, username, button_text):
    """在目标用户行中点击指定文本的操作按钮，返回是否点击成功。"""
    return cdp.evaluate(f"""
        (function() {{
            const rows = Array.from(document.querySelectorAll(
                '.ant-table-tbody tr.ant-table-row'));
            const row = rows.find(tr => tr.textContent.includes({json.dumps(username)}));
            if (!row) return false;
            const btn = Array.from(row.querySelectorAll('button'))
                .find(b => b.textContent.replace(/\\s/g, '').includes({json.dumps(button_text)}));
            if (btn) {{ btn.click(); return true; }}
            return false;
        }})();
    """)


def _get_row_tag_texts(cdp, username):
    """获取目标用户行的所有 Tag 文本（去空格）。"""
    return cdp.evaluate(f"""
        (function() {{
            const rows = Array.from(document.querySelectorAll(
                '.ant-table-tbody tr.ant-table-row'));
            const row = rows.find(tr => tr.textContent.includes({json.dumps(username)}));
            if (!row) return null;
            const tags = Array.from(row.querySelectorAll('.ant-tag'));
            return tags.map(t => t.textContent.trim().replace(/\\s/g, ''));
        }})();
    """)


def _wait_row_tag(cdp, username, expected_tag, timeout=10):
    """轮询等待目标用户行出现指定 Tag 文本。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        tags = _get_row_tag_texts(cdp, username)
        if tags and any(expected_tag in t for t in tags):
            return True
        time.sleep(0.5)
    return False


def _wait_table_loaded(cdp, timeout=10):
    """等待 Table 行出现（loading 完成，Skeleton 消失）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        count = cdp.evaluate(
            "document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length"
        )
        if count and count >= 1:
            return True
        time.sleep(0.3)
    return False


def _reload_users_page(cdp):
    """reload 用户管理页面并等待 Table 渲染。

    UsersPage 无"刷新"按钮，通过 window.location.reload() 触发组件重新 mount，
    重新 fetchUsers(page=1, pageSize=20)，确保 UI 状态与后端一致。
    """
    cdp.evaluate("window.location.reload()")
    wait_for_element(cdp, ".ant-table", timeout=15)
    _wait_table_loaded(cdp, timeout=10)


def _wait_row_tag_paginated(cdp, username, expected_tag, timeout=20):
    """翻页查找目标用户行，等待出现指定 Tag 文本。

    若用户不在当前页，自动点击下一页继续查找，直到找到或遍历所有页。
    解决 Table 分页导致 target_user 不在第一页的问题。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        # 等待当前页 Table 加载完成（避免 Skeleton 阶段误判）
        _wait_table_loaded(cdp, timeout=5)
        tags = _get_row_tag_texts(cdp, username)
        if tags and any(expected_tag in t for t in tags):
            return True
        # 当前页未找到，尝试翻页
        has_next = cdp.evaluate("""
            (function() {
                var next = document.querySelector('.ant-pagination-next');
                if (!next) return false;
                if (next.disabled || next.getAttribute('aria-disabled') === 'true') return false;
                next.click();
                return true;
            })();
        """)
        if not has_next:
            return False
        time.sleep(0.5)
    return False


def _api_update_user_status(base_url, headers, user_id, is_active):
    """通过 API 更新用户状态（启用/禁用）。

    PUT /users/{user_id}/status {is_active: bool}
    """
    r = requests.put(
        f"{base_url}/users/{user_id}/status",
        json={"is_active": is_active},
        headers=headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Update user status failed: {r.status_code} {r.text[:200]}"


def _api_update_user_role(base_url, headers, user_id, role):
    """通过 API 更新用户角色（user/admin）。

    PUT /users/{user_id}/role {role: 'user'|'admin'}
    """
    r = requests.put(
        f"{base_url}/users/{user_id}/role",
        json={"role": role},
        headers=headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Update user role failed: {r.status_code} {r.text[:200]}"


def test_users_list_renders(cdp_admin, target_user):
    """用例1: admin 导航 /#/users（fixture 已导航），验证 Table 渲染 + 列存在。"""
    cdp = cdp_admin
    wait_for_element(cdp, ".ant-table", timeout=15)
    # 验证表头列存在
    headers = (
        cdp.evaluate("""
        (function() {
            const ths = document.querySelectorAll('.ant-table-thead th');
            return Array.from(ths).map(th => th.textContent.trim());
        })();
    """)
        or []
    )
    headers_text = " ".join(headers)
    for col in ["用户名", "邮箱", "角色", "状态", "操作"]:
        assert col in headers_text, f"Column '{col}' not found in headers: {headers}"
    # 验证至少有一行数据
    row_count = cdp.evaluate(
        "document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length"
    )
    assert row_count and row_count >= 1, f"No user rows in table (count={row_count})"


def test_disable_user_ui(cdp_admin, target_user, base_url, admin_headers):
    """用例2: 通过 API 禁用用户，CDP 刷新验证状态 Tag 变为"禁用"。

    采用 API 操作 + UI 验证模式，避免 Table 分页导致找不到目标用户行。
    UsersPage Table 默认 pageSize=20，target_user 可能不在第一页。
    """
    cdp = cdp_admin
    username = target_user["username"]
    user_id = target_user["user"]["id"]
    wait_for_element(cdp, ".ant-table", timeout=15)
    # API 禁用用户
    _api_update_user_status(base_url, admin_headers, user_id, False)
    # 刷新页面验证 UI 状态变更
    _reload_users_page(cdp)
    assert _wait_row_tag_paginated(
        cdp, username, "禁用", timeout=20
    ), f"Status tag did not change to '禁用' for user '{username}'"


def test_disable_user_effect(cdp_admin, target_user, base_url):
    """用例3: 用 target_user 的 refresh_token 调 /auth/refresh 验证 401；
    用账号密码调 /auth/login 验证 401。"""
    # refresh_token 应失效（401）
    verify_api_call(
        f"{base_url}/auth/refresh",
        "POST",
        json={"refresh_token": target_user["refresh_token"]},
        expected_status=401,
    )
    # 账号密码登录应被拒（401）
    r = requests.post(
        f"{base_url}/auth/login",
        json={
            "username": target_user["username"],
            "password": target_user["password"],
        },
        timeout=10,
    )
    assert (
        r.status_code == 401
    ), f"Login should fail for disabled user, got {r.status_code}: {r.text[:200]}"


def test_enable_user_ui(cdp_admin, target_user, base_url, admin_headers):
    """用例4: 通过 API 启用用户，CDP 刷新验证状态 Tag 变为"正常"。"""
    cdp = cdp_admin
    username = target_user["username"]
    user_id = target_user["user"]["id"]
    wait_for_element(cdp, ".ant-table", timeout=15)
    # API 启用用户
    _api_update_user_status(base_url, admin_headers, user_id, True)
    # 刷新页面验证 UI 状态变更
    _reload_users_page(cdp)
    assert _wait_row_tag_paginated(
        cdp, username, "正常", timeout=20
    ), f"Status tag did not change to '正常' for user '{username}'"


def test_enable_user_effect(cdp_admin, target_user, base_url):
    """用例5: 用 target_user 账号密码重新登录验证 200 + access_token 有效。"""
    r = requests.post(
        f"{base_url}/auth/login",
        json={
            "username": target_user["username"],
            "password": target_user["password"],
        },
        timeout=10,
    )
    assert (
        r.status_code == 200
    ), f"Login should succeed for enabled user, got {r.status_code}: {r.text[:200]}"
    token_data = r.json().get("data", r.json())
    assert "access_token" in token_data, f"No access_token in response: {token_data}"
    # 更新 target_user 的 token（供后续用例使用）
    target_user["access_token"] = token_data["access_token"]
    target_user["refresh_token"] = token_data["refresh_token"]
    # 验证 access_token 有效（调 /auth/me）
    verify_api_call(
        f"{base_url}/auth/me",
        "GET",
        token=token_data["access_token"],
        expected_status=200,
    )


def test_promote_to_admin_ui(cdp_admin, target_user, base_url, admin_headers):
    """用例6: 通过 API 提升为管理员，CDP 刷新验证角色 Tag 变为"管理员"。"""
    cdp = cdp_admin
    username = target_user["username"]
    user_id = target_user["user"]["id"]
    wait_for_element(cdp, ".ant-table", timeout=15)
    # API 提升角色
    _api_update_user_role(base_url, admin_headers, user_id, "admin")
    # 刷新页面验证 UI 状态变更
    _reload_users_page(cdp)
    assert _wait_row_tag_paginated(
        cdp, username, "管理员", timeout=20
    ), f"Role tag did not change to '管理员' for user '{username}'"


def test_promote_to_admin_effect(cdp_admin, target_user, base_url):
    """用例7: target_user 重新登录（API），用独立 CDP 会话验证侧边栏出现
    "用户管理"菜单 + 访问 /#/users 不被重定向。"""
    # 重新登录获取含 admin 角色的 token
    r = requests.post(
        f"{base_url}/auth/login",
        json={
            "username": target_user["username"],
            "password": target_user["password"],
        },
        timeout=10,
    )
    assert r.status_code == 200
    fresh_token = r.json().get("data", r.json())
    target_user["access_token"] = fresh_token["access_token"]
    target_user["refresh_token"] = fresh_token["refresh_token"]

    # 创建独立 CDP 会话
    client2 = make_cdp_client(9223)
    try:
        login_cdp_session(client2, fresh_token, "#/dashboard")
        # 验证侧边栏出现"用户管理"菜单
        menu_text = (
            client2.evaluate(
                "document.querySelector('.ant-menu') ? "
                "document.querySelector('.ant-menu').textContent : ''"
            )
            or ""
        )
        assert (
            "用户管理" in menu_text
        ), f"Admin menu '用户管理' not found in sidebar after promotion: {menu_text}"
        # 访问 /#/users 不被重定向
        client2.evaluate("window.location.hash = '#/users'")
        time.sleep(2)
        hash_val = client2.evaluate("window.location.hash") or ""
        assert (
            "users" in hash_val
        ), f"Admin user should access /#/users without redirect, but hash={hash_val}"
    finally:
        client2.close()


def test_demote_to_user(cdp_admin, target_user, base_url, admin_headers, admin_token):
    """用例8: 通过 API 降级为普通用户，CDP 刷新验证角色 Tag 变为"普通用户"；
    target_user 刷新验证"用户管理"菜单消失 + 访问 /#/users 被重定向。"""
    cdp = cdp_admin
    # 重新注入 admin token：前一个测试（promote_to_admin_effect）创建了独立 CDP 会话
    # 并注入 target_user 的 token，覆盖了 localStorage 中的 admin token。
    # 不重新注入会导致 reload 后 SPA 以普通用户身份渲染，/#/users 被 AdminRoute
    # 重定向到 /#/dashboard，.ant-table 找不到。
    login_cdp_session(cdp, admin_token, "#/users")
    username = target_user["username"]
    user_id = target_user["user"]["id"]
    wait_for_element(cdp, ".ant-table", timeout=15)
    # API 降级角色
    _api_update_user_role(base_url, admin_headers, user_id, "user")
    # 刷新页面验证 UI 状态变更
    _reload_users_page(cdp)
    assert _wait_row_tag_paginated(
        cdp, username, "普通用户", timeout=20
    ), f"Role tag did not change to '普通用户' for user '{username}'"

    # target_user 重新登录（此时已降级为普通用户）
    r = requests.post(
        f"{base_url}/auth/login",
        json={
            "username": target_user["username"],
            "password": target_user["password"],
        },
        timeout=10,
    )
    assert r.status_code == 200
    fresh_token = r.json().get("data", r.json())
    target_user["access_token"] = fresh_token["access_token"]
    target_user["refresh_token"] = fresh_token["refresh_token"]

    # 创建独立 CDP 会话验证
    client2 = make_cdp_client(9223)
    try:
        login_cdp_session(client2, fresh_token, "#/dashboard")
        # 验证侧边栏无"用户管理"菜单
        menu_text = (
            client2.evaluate(
                "document.querySelector('.ant-menu') ? "
                "document.querySelector('.ant-menu').textContent : ''"
            )
            or ""
        )
        assert (
            "用户管理" not in menu_text
        ), f"Admin menu '用户管理' should not be visible for normal user: {menu_text}"
        # 访问 /#/users 被重定向到 /#/dashboard
        client2.evaluate("window.location.hash = '#/users'")
        time.sleep(2)
        hash_val = client2.evaluate("window.location.hash") or ""
        assert (
            "dashboard" in hash_val
        ), f"Normal user should be redirected from /#/users to /#/dashboard, hash={hash_val}"
    finally:
        client2.close()
