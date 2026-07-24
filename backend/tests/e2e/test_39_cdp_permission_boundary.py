"""CDP UI 测试 - 权限边界综合验证

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. 普通用户侧边栏无 admin 菜单
2. 普通用户访问 /#/users 被重定向到 /#/dashboard
3. 普通用户调 GET /users API 返回 403
4. 知识库隔离（用户 B 看不到用户 A 的 KB）
5. 知识库隔离 API（用户 B 调 GET /knowledge-bases/{A的KB_id} 返回 403）
6. 普通用户不能删除他人 KB（DELETE 返回 403）
7. 系统页面 admin only（普通用户访问 /#/system 重定向 + API 403）

核心：双账号 + 权限实效验证。两个普通用户各一个独立 CdpClient 实例。
API 权限验证用 verify_api_call。AdminRoute 重定向验证: 导航后检查
window.location.hash 是否为 /#/dashboard。
"""
import time
import uuid

import pytest
import requests

from tests.e2e.helpers.cdp_auth import (
    make_cdp_client,
    login_cdp_session,
    create_user_via_api,
    verify_api_call,
)
from tests.e2e.helpers.waiters import wait_for_element


@pytest.fixture(scope="module")
def cdp_user_a(base_url, admin_headers):
    """普通用户 A 的 CDP 会话。"""
    user_info = create_user_via_api(base_url, admin_headers)
    client = make_cdp_client(9223)
    login_cdp_session(client, user_info, "#/dashboard")
    # 验证登录成功：hash 不应包含 'login'。若仍在 login 页，说明 token 注入失败。
    # login_cdp_session 内部已有重试，此处再检查一次确保 fixture yield 前状态正确。
    hash_val = client.evaluate("window.location.hash") or ""
    if "login" in hash_val:
        login_cdp_session(client, user_info, "#/dashboard")
    yield {"client": client, "user": user_info}
    client.close()


@pytest.fixture(scope="module")
def cdp_user_b(base_url, admin_headers):
    """普通用户 B 的 CDP 会话。"""
    user_info = create_user_via_api(base_url, admin_headers)
    client = make_cdp_client(9223)
    login_cdp_session(client, user_info, "#/dashboard")
    # 同 cdp_user_a：验证登录成功
    hash_val = client.evaluate("window.location.hash") or ""
    if "login" in hash_val:
        login_cdp_session(client, user_info, "#/dashboard")
    yield {"client": client, "user": user_info}
    client.close()


@pytest.fixture(scope="module")
def user_a_kb(base_url, cdp_user_a):
    """用户 A 创建的 KB，用于隔离测试。"""
    token = cdp_user_a["user"]["access_token"]
    kb_name = f"UserA_KB_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{base_url}/knowledge-bases", json={
        "name": kb_name,
        "description": "用户 A 隔离测试 KB",
    }, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    assert r.status_code == 200, f"Create KB failed: {r.text}"
    kb = r.json().get("data", r.json())
    yield kb
    # 清理
    try:
        requests.delete(
            f"{base_url}/knowledge-bases/{kb['id']}",
            headers={"Authorization": f"Bearer {token}"}, timeout=5,
        )
    except Exception:
        pass


def test_normal_user_no_admin_menu(cdp_user_a):
    """用例1: 用户 A 在 cdp_user_a 会话中，用 evaluate 检查侧边栏无
    "用户管理"/"反馈管理"/"评估管理"/"系统状态"菜单项。

    Layout.tsx 非 admin 用户侧边栏不显示后 4 项（条件展开
    ...(user?.role === 'admin' ? [...] : [])）。
    """
    cdp = cdp_user_a["client"]
    wait_for_element(cdp, ".ant-menu", timeout=15)
    menu_text = cdp.evaluate(
        "document.querySelector('.ant-menu') ? "
        "document.querySelector('.ant-menu').textContent : ''"
    ) or ""
    admin_menus = ["用户管理", "反馈管理", "评估管理", "系统状态"]
    for item in admin_menus:
        assert item not in menu_text, \
            f"Admin menu '{item}' should not be visible for normal user: {menu_text}"


def test_normal_user_access_users_redirected(cdp_user_a):
    """用例2: 用户 A 导航 /#/users，验证 URL 重定向到 /#/dashboard。

    AdminRoute 逻辑: 非 admin 访问 admin 路由时重定向到 / (即 /#/dashboard)。
    使用轮询等待重定向完成（AdminRoute -> / -> index -> /dashboard 两跳渲染）。
    """
    cdp = cdp_user_a["client"]
    cdp.evaluate("window.location.hash = '#/users'")
    deadline = time.time() + 10
    while time.time() < deadline:
        hash_val = cdp.evaluate("window.location.hash") or ""
        if "dashboard" in hash_val:
            return
        time.sleep(0.5)
    hash_val = cdp.evaluate("window.location.hash") or ""
    assert "dashboard" in hash_val, \
        f"Normal user should be redirected from /#/users to /#/dashboard, hash={hash_val}"


def test_normal_user_access_users_api_403(cdp_user_a, base_url):
    """用例3: 用户 A 调 GET /users API 验证 403。

    Users API list/update role/update status 均需 admin 权限（get_admin_user），
    普通用户调用返回 403 ForbiddenError。
    """
    token = cdp_user_a["user"]["access_token"]
    verify_api_call(
        f"{base_url}/users", "GET",
        token=token, expected_status=403,
    )


def test_kb_isolation(cdp_user_a, cdp_user_b, user_a_kb, base_url):
    """用例4: 用户 A 通过 API 创建 KB，用户 B 在 cdp_user_b 会话中验证
    KB 列表看不到用户 A 的 KB。

    KB API list_kbs 按 user.id 过滤，用户只能看到自己拥有/协作的 KB。
    """
    token_b = cdp_user_b["user"]["access_token"]
    # 用户 B 通过 API 获取 KB 列表
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 1, "page_size": 100},
        headers={"Authorization": f"Bearer {token_b}"}, timeout=10,
    )
    assert r.status_code == 200, f"User B list KB failed: {r.text}"
    kb_list = r.json().get("data", r.json()).get("items", [])
    kb_ids = [k["id"] for k in kb_list]
    assert user_a_kb["id"] not in kb_ids, \
        f"User B should not see User A's KB {user_a_kb['id']}, but found in list: {kb_ids}"


def test_kb_isolation_api(cdp_user_b, user_a_kb, base_url):
    """用例5: 用户 B 直接调 GET /knowledge-bases/{A的KB_id} API 验证 403。

    KB API get_kb 检查 user.id 是否为 owner 或 collaborator，
    非授权用户调用返回 403 ForbiddenError。
    """
    token = cdp_user_b["user"]["access_token"]
    verify_api_call(
        f"{base_url}/knowledge-bases/{user_a_kb['id']}", "GET",
        token=token, expected_status=403,
    )


def test_normal_user_cannot_delete_others_kb(cdp_user_b, user_a_kb, base_url):
    """用例6: 用户 B 调 DELETE /knowledge-bases/{A的KB_id} 验证 403。

    KB API delete_kb 检查 user.id 是否为 owner，
    非 owner 调用返回 403 ForbiddenError。
    """
    token = cdp_user_b["user"]["access_token"]
    verify_api_call(
        f"{base_url}/knowledge-bases/{user_a_kb['id']}", "DELETE",
        token=token, expected_status=403,
    )


def test_system_admin_only(cdp_user_a, base_url):
    """用例7: 用户 A 访问 /#/system 验证重定向；调 GET /system/status 验证 403。

    System API system_status 需 admin 权限（get_admin_user），
    普通用户调用返回 403 ForbiddenError。
    AdminRoute 重定向: 非 admin 访问 /#/system 重定向到 /#/dashboard。
    使用轮询等待重定向完成。
    """
    cdp = cdp_user_a["client"]
    # UI 重定向验证（轮询等待重定向到 dashboard）
    cdp.evaluate("window.location.hash = '#/system'")
    deadline = time.time() + 10
    hash_val = ""
    while time.time() < deadline:
        hash_val = cdp.evaluate("window.location.hash") or ""
        if "dashboard" in hash_val:
            break
        time.sleep(0.5)
    assert "dashboard" in hash_val, \
        f"Normal user should be redirected from /#/system to /#/dashboard, hash={hash_val}"
    # API 权限验证
    token = cdp_user_a["user"]["access_token"]
    verify_api_call(
        f"{base_url}/system/status", "GET",
        token=token, expected_status=403,
    )
