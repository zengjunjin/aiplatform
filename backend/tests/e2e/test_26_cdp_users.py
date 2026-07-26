"""CDP UI 测试 - 用户管理页（admin 功能）

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. 用户管理页加载与列表渲染
2. 列表列结构验证（ID/用户名/邮箱/角色/状态/操作）
3. 创建用户流程（UI 无创建按钮，通过 API 注册后验证列表呈现）
4. 编辑用户角色（user → admin，Popconfirm 确认）
5. 禁用用户（Popconfirm 确认，验证状态变更）
6. 启用用户（验证状态恢复）
7. 搜索用户（UI 无搜索框时跳过）

注意：
- UsersPage.tsx 无创建用户按钮和搜索框，用户创建走 /auth/register API。
  test_create_user_button 改为通过 API 创建用户后验证 UI 列表呈现。
  test_search_user 在无搜索输入框时跳过。
- 角色变更和状态变更需要 admin 权限（已用 admin_token 登录）。
- 操作列对当前用户（admin）显示"当前用户"标签而非按钮，故需要一个非 admin
  的目标用户。通过 module fixture 注册独立目标用户，避免与 session 级
  test_user 状态冲突。
"""

import json
import os
import time
import uuid

import pytest
import requests

from tests.e2e.conftest import extract_data
from tests.e2e.helpers.cdp_auth import login_cdp_session
from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import (
    wait_for,
    wait_for_dom_ready,
    wait_for_element,
    wait_for_url_change,
)

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"


@pytest.fixture(scope="module")
def target_user(base_url, admin_headers):
    """注册独立目标用户供用户管理测试操作（避免与 session 级 test_user 状态冲突）。

    /auth/register 限流 5/minute，module scope 仅注册一次。
    不清理数据（按编码规范要求不清理）。
    """
    username = f"cdpuser_{uuid.uuid4().hex[:8]}"
    email = f"{username}@test.com"
    password = "Test@123456"
    r = requests.post(
        f"{base_url}/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
        },
        timeout=10,
    )
    assert r.status_code == 200, f"Register target user failed: {r.text}"
    user_data = extract_data(r)
    # 确保目标用户初始为启用 + 普通用户角色，保证后续操作可重复
    requests.put(
        f"{base_url}/users/{user_data['id']}/status",
        json={"is_active": True},
        headers=admin_headers,
        timeout=5,
    )
    return user_data


@pytest.fixture(scope="module")
def logged_in_cdp(admin_token):
    """登录后的 CDP 客户端（用 API token 注入 localStorage，避免限流）

    必须用 Page.reload 触发整页重载，否则 zustand persist 不会重新 rehydrate，
    内存 store 仍是旧状态（修复 auth.ts onRehydrateStorage 后必须 reload）。
    """
    client = CdpClient(cdp_port=CDP_PORT)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {CDP_PORT}): {e}")
    login_cdp_session(client, admin_token, "#/users")
    yield client
    client.close()


def _navigate_to_users(cdp):
    """导航到用户管理页并等待表格渲染

    H14 修复：不调用 cdp.navigate(TAURI_HOME)（全页导航会导致 zustand 重新 rehydrate，
    AdminRoute 可能在 rehydrate 完成前重定向到 #/dashboard）。改为仅用 hash 导航 +
    Page.reload 确保 SPA 路由正确，且 localStorage 中的 auth 状态保持不变。
    """
    cdp.evaluate("window.location.hash = '#/users'")
    wait_for_url_change(cdp, "#/users", timeout=10)
    # 等待 Table 或 Skeleton 出现（Table 渲染前可能先显示 Skeleton）
    wait_for_element(cdp, ".ant-table, .ant-skeleton, .ant-empty", timeout=15)


def _click_popconfirm_ok(cdp, timeout=8):
    """轮询等待 Popconfirm 弹出并点击"确定"按钮。

    Ant Design Popconfirm 异步渲染在 portal 中, 点击触发按钮后需要等待弹出。
    注意: Ant Design v5 Button 在两个中文字符之间自动插入空格, textContent 为 "确 定" 而非 "确定"。
    因此用 strip+replace 去除空格后再匹配, 或直接点击 primary 按钮（已通过 class 精确定位）。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        clicked = cdp.evaluate("""
            (function() {
                var btns = document.querySelectorAll(
                    '.ant-popconfirm-buttons button.ant-btn-primary, .ant-popover button.ant-btn-primary'
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
        time.sleep(0.5)  # 轮询间隔
    return False


def test_users_page_loads(logged_in_cdp, target_user):
    """用户管理页加载：导航到 /#/users，验证用户列表渲染

    验证 Card 标题含"用户管理"，Table 已渲染且至少有一行数据。
    """
    cdp = logged_in_cdp
    _navigate_to_users(cdp)
    # 等待表格出现
    wait_for_element(cdp, ".ant-table", timeout=15)
    # 验证 Card 标题包含"用户管理"
    has_title = cdp.evaluate("""
        (function() {
            return Array.from(document.querySelectorAll('.ant-card-head-title, .ant-card-head, *'))
                .some(el => el.textContent && el.textContent.includes('用户管理'));
        })();
    """)
    assert has_title, "用户管理 card title not found"
    # 验证表格至少有一行数据行（排除表头）
    row_count = cdp.evaluate("""
        (function() {
            return document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length;
        })();
    """)
    assert row_count and row_count >= 1, f"No user rows in table (count={row_count})"


def test_user_list_columns(logged_in_cdp, target_user):
    """验证列表列结构（ID/用户名/邮箱/角色/状态/操作）

    UsersPage.tsx columns: id/username/email/role/is_active/actions。
    """
    cdp = logged_in_cdp
    _navigate_to_users(cdp)
    wait_for_element(cdp, ".ant-table", timeout=15)
    # 读取表头文本
    headers = cdp.evaluate("""
        (function() {
            const ths = document.querySelectorAll('.ant-table-thead th');
            return Array.from(ths).map(th => th.textContent.trim());
        })();
    """)
    assert headers, "No table headers found"
    headers_text = " ".join(headers)
    # 验证关键列存在（中文表头）
    for col in ["用户名", "邮箱", "角色", "状态", "操作"]:
        assert col in headers_text, f"Column '{col}' not found in headers: {headers}"


def test_create_user_button(logged_in_cdp, target_user):
    """创建用户流程验证

    UsersPage.tsx 无创建用户按钮（用户创建走 /auth/register API）。
    本测试通过 API 创建目标用户后，验证该用户出现在 UI 列表中。
    """
    cdp = logged_in_cdp
    _navigate_to_users(cdp)
    wait_for_element(cdp, ".ant-table", timeout=15)
    # 验证 target_user 出现在列表中
    username = target_user["username"]
    wait_for(
        lambda: cdp.evaluate(f"""
            (function() {{
                return Array.from(document.querySelectorAll('.ant-table-tbody tr.ant-table-row'))
                    .some(tr => tr.textContent.includes({json.dumps(username)}));
            }})();
        """),
        timeout=15,
        interval=1,
        message=f"Target user '{username}' not found in user list",
    )


def test_edit_user_role(logged_in_cdp, target_user, base_url, admin_headers):
    """编辑用户角色：点击"设为管理员"按钮 → Popconfirm 确认 → 验证角色更新

    UsersPage.tsx 操作列对非当前用户显示"设为管理员"/"取消管理员"按钮（Popconfirm）。
    先确保目标用户为普通角色，再点击设为管理员。
    """
    cdp = logged_in_cdp
    username = target_user["username"]
    user_id = target_user["id"]
    # 先通过 API 确保目标用户为普通角色，保证按钮文本为"设为管理员"
    requests.put(
        f"{base_url}/users/{user_id}/role", json={"role": "user"}, headers=admin_headers, timeout=5
    )
    _navigate_to_users(cdp)
    # 点击目标用户行的"设为管理员"按钮
    clicked = cdp.evaluate(f"""
        (function() {{
            const rows = Array.from(document.querySelectorAll('.ant-table-tbody tr.ant-table-row'));
            const row = rows.find(tr => tr.textContent.includes({json.dumps(username)}));
            if (!row) return false;
            const btn = Array.from(row.querySelectorAll('button'))
                .find(b => b.textContent.includes('设为管理员'));
            if (btn) {{ btn.click(); return true; }}
            return false;
        }})();
    """)
    assert clicked, f"设为管理员 button not found for user '{username}'"
    # 轮询等待 Popconfirm 弹出并点击"确定"按钮
    assert _click_popconfirm_ok(cdp), "Popconfirm confirm button not found"

    # 验证角色已更新为管理员（通过 API 轮询确认）
    def _role_is_admin():
        r = requests.get(
            f"{base_url}/users?page=1&page_size=100", headers=admin_headers, timeout=10
        )
        if r.status_code != 200:
            return False
        users = extract_data(r).get("items", [])
        target = next((u for u in users if u["id"] == user_id), None)
        return bool(target and target.get("role") == "admin")

    wait_for(
        _role_is_admin,
        timeout=10,
        interval=1,
        message=f"User role not updated to admin for {user_id}",
    )


def test_disable_user(logged_in_cdp, target_user, base_url, admin_headers):
    """禁用用户：点击"禁用"按钮 → Popconfirm 确认 → 验证状态变更

    先通过 API 确保目标用户为启用状态，再点击禁用。
    """
    cdp = logged_in_cdp
    username = target_user["username"]
    user_id = target_user["id"]
    # 确保目标用户为启用状态
    requests.put(
        f"{base_url}/users/{user_id}/status",
        json={"is_active": True},
        headers=admin_headers,
        timeout=5,
    )
    _navigate_to_users(cdp)
    # 点击目标用户行的"禁用"按钮
    clicked = cdp.evaluate(f"""
        (function() {{
            const rows = Array.from(document.querySelectorAll('.ant-table-tbody tr.ant-table-row'));
            const row = rows.find(tr => tr.textContent.includes({json.dumps(username)}));
            if (!row) return false;
            const btn = Array.from(row.querySelectorAll('button'))
                .find(b => b.textContent.includes('禁用'));
            if (btn) {{ btn.click(); return true; }}
            return false;
        }})();
    """)
    assert clicked, f"禁用 button not found for user '{username}'"
    # 轮询等待 Popconfirm 弹出并点击"确定"按钮
    assert _click_popconfirm_ok(cdp), "Popconfirm confirm button not found"

    # 验证状态已变更为禁用（通过 API 轮询确认）
    def _is_disabled():
        r = requests.get(
            f"{base_url}/users?page=1&page_size=100", headers=admin_headers, timeout=10
        )
        if r.status_code != 200:
            return False
        users = extract_data(r).get("items", [])
        target = next((u for u in users if u["id"] == user_id), None)
        return bool(target and target.get("is_active") is False)

    wait_for(_is_disabled, timeout=10, interval=1, message=f"User not disabled for {user_id}")


def test_enable_user(logged_in_cdp, target_user, base_url, admin_headers):
    """启用用户：点击"启用"按钮 → Popconfirm 确认 → 验证状态恢复

    先通过 API 确保目标用户为禁用状态，再点击启用。
    """
    cdp = logged_in_cdp
    username = target_user["username"]
    user_id = target_user["id"]
    # 确保目标用户为禁用状态
    requests.put(
        f"{base_url}/users/{user_id}/status",
        json={"is_active": False},
        headers=admin_headers,
        timeout=5,
    )
    _navigate_to_users(cdp)
    # 点击目标用户行的"启用"按钮
    clicked = cdp.evaluate(f"""
        (function() {{
            const rows = Array.from(document.querySelectorAll('.ant-table-tbody tr.ant-table-row'));
            const row = rows.find(tr => tr.textContent.includes({json.dumps(username)}));
            if (!row) return false;
            const btn = Array.from(row.querySelectorAll('button'))
                .find(b => b.textContent.includes('启用'));
            if (btn) {{ btn.click(); return true; }}
            return false;
        }})();
    """)
    assert clicked, f"启用 button not found for user '{username}'"
    # 轮询等待 Popconfirm 弹出并点击"确定"按钮
    assert _click_popconfirm_ok(cdp), "Popconfirm confirm button not found"

    # 验证状态已恢复为启用（通过 API 轮询确认）
    def _is_enabled():
        r = requests.get(
            f"{base_url}/users?page=1&page_size=100", headers=admin_headers, timeout=10
        )
        if r.status_code != 200:
            return False
        users = extract_data(r).get("items", [])
        target = next((u for u in users if u["id"] == user_id), None)
        return bool(target and target.get("is_active") is True)

    wait_for(_is_enabled, timeout=10, interval=1, message=f"User not enabled for {user_id}")


def test_search_user(logged_in_cdp, target_user):
    """搜索用户验证

    UsersPage.tsx 当前无搜索输入框（用户搜索走 /users/search API，用于协作者添加）。
    若 UI 无搜索框则跳过本测试。
    """
    cdp = logged_in_cdp
    _navigate_to_users(cdp)
    wait_for_element(cdp, ".ant-table", timeout=15)
    # 检查是否存在搜索输入框
    has_search = cdp.evaluate("""
        (function() {
            const inputs = Array.from(document.querySelectorAll('input[type="text"], input[type="search"]'));
            return inputs.some(i => {
                const ph = (i.placeholder || '').toLowerCase();
                return ph.includes('搜索') || ph.includes('search');
            });
        })();
    """)
    if not has_search:
        pytest.skip("UsersPage has no search input (search is via /users/search API)")
    # 若存在搜索框，输入目标用户名验证过滤
    username = target_user["username"]
    cdp.evaluate(f"""
        (function() {{
            const inputs = Array.from(document.querySelectorAll('input[type="text"], input[type="search"]'));
            const input = inputs.find(i => {{
                const ph = (i.placeholder || '').toLowerCase();
                return ph.includes('搜索') || ph.includes('search');
            }});
            if (!input) return false;
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            setter.call(input, {json.dumps(username)});
            input.dispatchEvent(new Event('input', {{bubbles: true}}));
            return true;
        }})();
    """)
    wait_for(
        lambda: cdp.evaluate(f"""
            (function() {{
                return Array.from(document.querySelectorAll('.ant-table-tbody tr.ant-table-row'))
                    .some(tr => tr.textContent.includes({json.dumps(username)}));
            }})();
        """),
        timeout=8,
        interval=0.5,
        message=f"Search did not find user '{username}'",
    )
