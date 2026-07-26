"""CDP UI 测试 - 全局导航与布局

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. 侧边栏菜单项渲染（Dashboard/KB/Documents/Chat/Users/Feedback/Evaluation/System）
2. 侧边栏导航到各页面
3. 主题切换（data-theme 变化 + 刷新持久化）
4. 用户头像下拉菜单（修改密码/退出登录）
5. 通知铃铛 popover

注意：
- Layout.tsx 侧边栏对 admin 显示 8 个菜单项，无独立 Sessions 菜单项
  （会话管理在 ChatPage 的 SessionSider 中），test_sidebar_navigate_sessions 跳过。
- 用户头像菜单项为"修改密码"/"退出登录"（非"个人信息"）。
- 主题通过 document.documentElement data-theme 属性应用，持久化于
  localStorage 'rag-auth' key 的 state.themeMode 字段。
"""

import contextlib
import json
import os
import time

import pytest

from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import (
    wait_for,
    wait_for_dom_ready,
    wait_for_element,
    wait_for_url_change,
)

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"


def _inject_auth_token(cdp, admin_token):
    """注入 admin_token 到前端 localStorage（rag-auth key，zustand persist 格式）。"""
    auth_data = {
        "state": {
            "token": admin_token["access_token"],
            "refreshToken": admin_token["refresh_token"],
            "refreshTokenExpiresAt": int(time.time() * 1000) + 7 * 24 * 3600 * 1000,
            "user": admin_token["user"],
            "themeMode": "light",
        },
        "version": 0,
    }
    cdp.evaluate(f"""
        try {{
            const authData = {json.dumps(auth_data)};
            localStorage.setItem('rag-auth', JSON.stringify(authData));
        }} catch(e) {{}}
    """)


@pytest.fixture(scope="module")
def logged_in_cdp(admin_token):
    """登录后的 CDP 客户端（用 API token 注入 localStorage，避免限流）

    必须用 Page.reload 触发整页重载，否则 zustand persist 不会重新 rehydrate，
    内存 store 仍是旧状态（修复 auth.ts onRehydrateStorage 后必须 reload）。

    H14 修复：reload 后显式设置 hash 到 #/dashboard，确保 SPA 路由进入已认证页面。
    """
    client = CdpClient(cdp_port=CDP_PORT)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {CDP_PORT}): {e}")
    client.navigate(TAURI_HOME)
    wait_for_dom_ready(client, timeout=10)
    _inject_auth_token(client, admin_token)
    client.send("Page.reload")
    # 必要固定等待：reload 后 zustand persist rehydrate
    time.sleep(3)
    # H14: reload 后显式导航到 #/dashboard，确保进入已认证页面
    client.evaluate("window.location.hash = '#/dashboard'")
    wait_for_url_change(client, "#/dashboard", timeout=15)
    yield client
    client.close()


def _navigate_home(cdp):
    """导航到首页并等待侧边栏渲染

    H14 修复：不调用 cdp.navigate(TAURI_HOME)（全页导航会导致 zustand 重新 rehydrate，
    AdminRoute 可能在 rehydrate 完成前重定向）。改为仅用 hash 导航。
    """
    cdp.evaluate("window.location.hash = '#/dashboard'")
    wait_for_url_change(cdp, "#/dashboard", timeout=15)


def _ensure_logged_in(cdp, admin_token):
    """确保用户已登录, 若 .user-dropdown-trigger 不存在则重新注入 token 并 reload

    test_theme_toggle 等前置测试可能修改 localStorage 导致 zustand persist
    状态异常, Layout 不渲染 HeaderActions。
    """
    trigger_found = cdp.evaluate("!!document.querySelector('.user-dropdown-trigger')")
    if not trigger_found:
        _inject_auth_token(cdp, admin_token)
        cdp.send("Page.reload")
        # 必要固定等待：reload 后 zustand persist rehydrate
        time.sleep(3)
        cdp.evaluate("window.location.hash = '#/dashboard'")
        wait_for_url_change(cdp, "#/dashboard", timeout=15)


def _click_menu_item(cdp, text_keyword):
    """点击侧边栏包含指定文本的菜单项，返回是否点击成功

    Layout.tsx 菜单项 label 为 <NavLink to="...">, 渲染为 <a> 标签。
    直接点击 .ant-menu-item (li) 不会触发 NavLink 导航, 需点击内部 <a> 标签。
    """
    return cdp.evaluate(f"""
        (function() {{
            const items = document.querySelectorAll('.ant-menu-item, .ant-menu-submenu-title');
            const item = Array.from(items).find(i =>
                i.textContent.includes({json.dumps(text_keyword)}));
            if (item) {{
                const link = item.querySelector('a');
                if (link) {{ link.click(); return true; }}
                item.click(); return true;
            }}
            return false;
        }})();
    """)


def test_sidebar_renders(logged_in_cdp):
    """侧边栏菜单项渲染：验证 admin 可见的菜单项

    Layout.tsx menuItems（admin）: 仪表盘/对话/知识库/文档管理/用户管理/反馈管理/评估管理/系统状态。
    无独立 Sessions 菜单项。
    """
    cdp = logged_in_cdp
    _navigate_home(cdp)
    wait_for_element(cdp, ".ant-menu", timeout=15)
    # 验证侧边栏菜单存在
    menu_exists = cdp.evaluate("!!document.querySelector('.ant-menu')")
    assert menu_exists, "Sidebar menu not found"
    # 验证 admin 菜单项存在
    menu_text = (
        cdp.evaluate("""
        (function() {
            const menu = document.querySelector('.ant-menu');
            return menu ? menu.textContent : '';
        })();
    """)
        or ""
    )
    expected_items = ["仪表盘", "对话", "知识库", "文档管理", "用户管理", "系统状态"]
    for item in expected_items:
        assert item in menu_text, f"Menu item '{item}' not found in sidebar: {menu_text}"


def test_sidebar_navigate_dashboard(logged_in_cdp):
    """点击 Dashboard 菜单项，验证跳转 /#/dashboard"""
    cdp = logged_in_cdp
    _navigate_home(cdp)
    assert _click_menu_item(cdp, "仪表盘"), "Dashboard menu item not found"
    wait_for_url_change(cdp, "/dashboard", timeout=10)
    url = cdp.evaluate("window.location.href")
    assert "/dashboard" in url, f"Did not navigate to dashboard: {url}"


def test_sidebar_navigate_kb(logged_in_cdp):
    """点击 KB 菜单项，验证跳转 /#/knowledge-bases"""
    cdp = logged_in_cdp
    _navigate_home(cdp)
    assert _click_menu_item(cdp, "知识库"), "KB menu item not found"
    wait_for_url_change(cdp, "/knowledge-bases", timeout=10)
    url = cdp.evaluate("window.location.href")
    assert "/knowledge-bases" in url, f"Did not navigate to knowledge-bases: {url}"


def test_sidebar_navigate_documents(logged_in_cdp):
    """点击 Documents 菜单项，验证跳转 /#/documents"""
    cdp = logged_in_cdp
    _navigate_home(cdp)
    assert _click_menu_item(cdp, "文档管理"), "Documents menu item not found"
    wait_for_url_change(cdp, "/documents", timeout=10)
    url = cdp.evaluate("window.location.href")
    assert "/documents" in url, f"Did not navigate to documents: {url}"


def test_sidebar_navigate_chat(logged_in_cdp):
    """点击 Chat 菜单项，验证跳转 /#/chat"""
    cdp = logged_in_cdp
    _navigate_home(cdp)
    assert _click_menu_item(cdp, "对话"), "Chat menu item not found"
    wait_for_url_change(cdp, "/chat", timeout=10)
    url = cdp.evaluate("window.location.href")
    assert "/chat" in url, f"Did not navigate to chat: {url}"


def test_sidebar_navigate_sessions(logged_in_cdp):
    """点击 Sessions 菜单项验证跳转

    Layout.tsx 侧边栏无独立 Sessions 菜单项（会话管理在 ChatPage 的 SessionSider 中）。
    本测试在无 Sessions 菜单项时跳过。
    """
    cdp = logged_in_cdp
    _navigate_home(cdp)
    has_sessions = cdp.evaluate("""
        (function() {
            const items = document.querySelectorAll('.ant-menu-item');
            return Array.from(items).some(i => i.textContent.includes('会话'));
        })();
    """)
    if not has_sessions:
        pytest.skip("No Sessions menu item in sidebar (sessions managed in ChatPage SessionSider)")
    assert _click_menu_item(cdp, "会话"), "Sessions menu item not found"
    wait_for_url_change(cdp, "/sessions", timeout=10)
    url = cdp.evaluate("window.location.href")
    assert "/sessions" in url, f"Did not navigate to sessions: {url}"


def test_sidebar_navigate_evaluation(logged_in_cdp):
    """点击 Evaluation 菜单项，验证跳转 /#/evaluation"""
    cdp = logged_in_cdp
    _navigate_home(cdp)
    assert _click_menu_item(cdp, "评估"), "Evaluation menu item not found"
    wait_for_url_change(cdp, "/evaluation", timeout=10)
    url = cdp.evaluate("window.location.href")
    assert "/evaluation" in url, f"Did not navigate to evaluation: {url}"


def test_sidebar_navigate_feedback(logged_in_cdp):
    """点击 Feedback 菜单项，验证跳转 /#/feedback"""
    cdp = logged_in_cdp
    _navigate_home(cdp)
    assert _click_menu_item(cdp, "反馈"), "Feedback menu item not found"
    wait_for_url_change(cdp, "/feedback", timeout=10)
    url = cdp.evaluate("window.location.href")
    assert "/feedback" in url, f"Did not navigate to feedback: {url}"


def test_sidebar_navigate_users(logged_in_cdp):
    """点击 Users 菜单项，验证跳转 /#/users"""
    cdp = logged_in_cdp
    _navigate_home(cdp)
    assert _click_menu_item(cdp, "用户管理"), "Users menu item not found"
    wait_for_url_change(cdp, "/users", timeout=10)
    url = cdp.evaluate("window.location.href")
    assert "/users" in url, f"Did not navigate to users: {url}"


def test_sidebar_navigate_system(logged_in_cdp):
    """点击 System 菜单项，验证跳转 /#/system"""
    cdp = logged_in_cdp
    _navigate_home(cdp)
    assert _click_menu_item(cdp, "系统状态"), "System menu item not found"
    wait_for_url_change(cdp, "/system", timeout=10)
    url = cdp.evaluate("window.location.href")
    assert "/system" in url, f"Did not navigate to system: {url}"


def test_theme_toggle(logged_in_cdp):
    """主题切换：点击切换按钮，验证 data-theme 变化，刷新验证持久化

    App.tsx 将 themeMode 同步到 document.documentElement data-theme 属性。
    themeMode 持久化于 localStorage 'rag-auth' key 的 state.themeMode 字段。

    H14 修复：用 Page.reload 代替 cdp.navigate(TAURI_HOME)，避免全页导航导致
    zustand 重新 rehydrate 期间 SPA 被重定向到 #/login，toggle 按钮找不到。
    """
    cdp = logged_in_cdp
    _navigate_home(cdp)
    # 读取切换前 data-theme
    theme_before = cdp.evaluate("document.documentElement.getAttribute('data-theme')") or "light"
    # 点击主题切换按钮（aria-label="切换主题"）
    cdp.evaluate("""
        (function() {
            const btn = Array.from(document.querySelectorAll('button[aria-label]'))
                .find(b => b.getAttribute('aria-label').includes('切换主题'));
            if (btn) btn.click();
        })();
    """)
    # 等待 data-theme 变化
    wait_for(
        lambda: (cdp.evaluate("document.documentElement.getAttribute('data-theme')") or "light")
        != theme_before,
        timeout=5,
        message="Theme did not change after toggle",
    )
    # 读取切换后 data-theme
    theme_after = cdp.evaluate("document.documentElement.getAttribute('data-theme')") or "light"
    assert (
        theme_after != theme_before
    ), f"Theme did not change after toggle: before={theme_before}, after={theme_after}"
    # 刷新页面验证持久化（H14: 用 Page.reload 保留当前 URL 和 hash）
    cdp.send("Page.reload")
    # 必要固定等待：reload 后 zustand persist rehydrate 读取 themeMode
    time.sleep(3)
    # reload 后重新设置 hash（reload 可能丢失 hash）
    cdp.evaluate("window.location.hash = '#/dashboard'")
    wait_for_url_change(cdp, "#/dashboard", timeout=10)
    theme_persisted = cdp.evaluate("document.documentElement.getAttribute('data-theme')") or "light"
    assert (
        theme_persisted == theme_after
    ), f"Theme not persisted after reload: expected={theme_after}, got={theme_persisted}"
    # 恢复为 light 主题（避免影响后续测试）
    if theme_persisted != "light":
        # 等待 toggle 按钮渲染（reload 后 HeaderActions 可能需要时间渲染）
        wait_for_element(cdp, "button[aria-label='切换主题']", timeout=10)
        cdp.evaluate("""
            (function() {
                const btn = Array.from(document.querySelectorAll('button[aria-label]'))
                    .find(b => b.getAttribute('aria-label').includes('切换主题'));
                if (btn) btn.click();
            })();
        """)
        wait_for(
            lambda: (cdp.evaluate("document.documentElement.getAttribute('data-theme')") or "light")
            == "light",
            timeout=10,
            message="Theme did not restore to light",
        )


def test_user_avatar_menu(logged_in_cdp, admin_token):
    """用户头像下拉菜单：点击 头像，验证菜单渲染（修改密码/退出登录）

    HeaderActions.tsx 用户区域 class="user-dropdown-trigger"，Dropdown trigger=['click', 'hover']。
    Layout.tsx userMenuItems: 修改密码 / 退出登录。
    Ant Design Dropdown 菜单渲染在 portal 中, 使用 .ant-dropdown-menu-item 精确定位
    (避免 [role="menuitem"] 匹配到侧边栏 Menu item)。

    注意：JS dispatchEvent 模拟 hover 不能可靠触发 Antd Dropdown onOpenChange，
    必须用 CDP Input.dispatchMouseEvent 真实点击（HeaderActions trigger 已包含 'click'）。
    """
    cdp = logged_in_cdp
    _navigate_home(cdp)
    _ensure_logged_in(cdp, admin_token)
    # 真实鼠标点击 .user-dropdown-trigger 打开 Dropdown（JS .click() / hover 不触发 onOpenChange）
    menu_text = ""
    deadline = time.time() + 8
    while time.time() < deadline:
        # 轮询点击直到菜单出现
        with contextlib.suppress(Exception):
            cdp.click_element(".user-dropdown-trigger")
        time.sleep(0.4)
        menu_text = (
            cdp.evaluate("""
            (function() {
                const items = document.querySelectorAll('.ant-dropdown-menu-item');
                return Array.from(items).map(i => i.textContent.trim()).join(' ');
            })();
        """)
            or ""
        )
        if "退出" in menu_text or "密码" in menu_text:
            break
        time.sleep(0.3)
    assert "退出登录" in menu_text, f"Logout menu item not found in avatar dropdown: {menu_text}"
    assert (
        "修改密码" in menu_text or "密码" in menu_text
    ), f"Change password menu item not found in avatar dropdown: {menu_text}"


def test_notification_popover(logged_in_cdp, admin_token):
    """通知铃铛 popover：点击铃铛，验证 popover 渲染

    NotificationPopover.tsx 使用 Ant Design Popover，触发器为 Badge > Button（Bell 图标）。
    点击后弹出通知列表（空状态显示"暂无通知"）。

    注意：JS .click() 不能可靠触发 Antd Popover onOpenChange，
    必须用 CDP Input.dispatchMouseEvent 真实点击（通过 JS 计算 bounding box 后调用 cdp.click）。
    """
    cdp = logged_in_cdp
    _navigate_home(cdp)
    _ensure_logged_in(cdp, admin_token)
    # 通过 JS 获取铃铛按钮的 bounding box，然后用 CDP 真实鼠标点击
    # 铃铛按钮 aria-label="通知"（notification.title）
    box = cdp.evaluate("""
        (function() {
            let btn = Array.from(document.querySelectorAll('button[aria-label]'))
                .find(b => {
                    const label = b.getAttribute('aria-label') || '';
                    return label.includes('通知') || label.includes('notification') || label.includes('Notification');
                });
            if (!btn) {
                const badges = document.querySelectorAll('.ant-badge');
                for (const badge of badges) {
                    const innerBtn = badge.querySelector('button');
                    if (innerBtn) { btn = innerBtn; break; }
                }
            }
            if (!btn) return null;
            const rect = btn.getBoundingClientRect();
            return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
        })();
    """)
    assert box, "Notification bell button not found"
    # 真实鼠标点击（轮询直到 popover 打开）
    popover_open = False
    deadline = time.time() + 8
    while time.time() < deadline:
        cdp.click(int(box["x"]), int(box["y"]))
        time.sleep(0.5)
        popover_open = cdp.evaluate("""
            (function() {
                return !!document.querySelector('.ant-popover-inner, .ant-popover-content');
            })();
        """)
        if popover_open:
            break
        time.sleep(0.3)
    assert popover_open, "Notification popover did not open after clicking bell"
