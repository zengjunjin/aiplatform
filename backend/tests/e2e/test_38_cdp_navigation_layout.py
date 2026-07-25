"""CDP UI 测试 - 全局导航与布局

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. 侧边栏菜单项存在性检查（evaluate，不点击）
2. 侧边栏导航（依次点击菜单项，验证 URL hash 变化）
3. 主题切换（data-theme 变化 + 刷新持久化）
4. 用户头像下拉菜单（修改密码/退出登录）
5. 通知铃铛 popover
6. 404 页（Result 404 + 返回首页按钮）

精简原则：用 evaluate 检查 DOM 不点击每个菜单。
"""

import json
import time

import pytest

from tests.e2e.helpers.cdp_auth import login_cdp_session, make_cdp_client
from tests.e2e.helpers.waiters import (
    wait_for,
    wait_for_dom_ready,
    wait_for_element,
    wait_for_url_change,
)

TAURI_HOME = "http://tauri.localhost/"


def _reinject_admin(cdp, admin_token, route="#/dashboard"):
    """重新注入 admin token 并导航到指定路由。

    多个 CDP 测试文件共用同一个 WebView2 target，其他测试文件的独立 CDP 会话
    可能覆盖 localStorage 中的 admin token。在每个依赖 Layout 渲染的用例开头
    调用此函数，确保 admin token 有效。
    """
    login_cdp_session(cdp, admin_token, route)


@pytest.fixture(scope="module")
def logged_in_cdp(admin_token):
    """admin 登录后的 CDP 客户端，导航到 /#/dashboard。"""
    client = make_cdp_client(9223)
    login_cdp_session(client, admin_token, "#/dashboard")
    yield client
    client.close()


def test_sidebar_menu_items(logged_in_cdp):
    """用例1: 用 evaluate 检查侧边栏菜单项存在，不实际点击。

    Layout.tsx menuItems（admin）: 仪表盘/对话/知识库/文档管理/
    用户管理/反馈管理/评估管理/系统状态。
    """
    cdp = logged_in_cdp
    wait_for_element(cdp, ".ant-menu", timeout=15)
    menu_text = (
        cdp.evaluate(
            "document.querySelector('.ant-menu') ? "
            "document.querySelector('.ant-menu').textContent : ''"
        )
        or ""
    )
    expected_items = [
        "仪表盘",
        "对话",
        "知识库",
        "文档管理",
        "用户管理",
        "反馈管理",
        "评估管理",
        "系统状态",
    ]
    for item in expected_items:
        assert item in menu_text, f"Menu item '{item}' not found in sidebar: {menu_text}"


def test_sidebar_navigate(logged_in_cdp):
    """用例2: 依次点击菜单项，验证 URL hash 变化（点击→验证→点下一个，不刷新）。

    Layout.tsx 菜单项 label 为 <NavLink to="...">, 渲染为 <a> 标签。
    直接点击 .ant-menu-item (li) 不会触发 NavLink 导航, 需点击内部 <a> 标签。
    """
    cdp = logged_in_cdp
    wait_for_element(cdp, ".ant-menu", timeout=15)
    menu_routes = [
        ("仪表盘", "/dashboard"),
        ("对话", "/chat"),
        ("知识库", "/knowledge-bases"),
        ("文档管理", "/documents"),
        ("用户管理", "/users"),
        ("反馈管理", "/feedback"),
        ("评估管理", "/evaluation"),
        ("系统状态", "/system"),
    ]
    for label, route_part in menu_routes:
        clicked = cdp.evaluate(f"""
            (function() {{
                const items = document.querySelectorAll(
                    '.ant-menu-item, .ant-menu-submenu-title');
                const item = Array.from(items).find(i =>
                    i.textContent.includes({json.dumps(label)}));
                if (item) {{
                    const link = item.querySelector('a');
                    if (link) {{ link.click(); return true; }}
                    item.click(); return true;
                }}
                return false;
            }})();
        """)
        assert clicked, f"Menu item '{label}' not found"
        wait_for_url_change(cdp, route_part, timeout=5)
        url = cdp.evaluate("window.location.href") or ""
        assert (
            route_part in url
        ), f"Did not navigate to {route_part} after clicking '{label}': {url}"


def test_theme_toggle(logged_in_cdp):
    """用例3: 点击主题切换按钮(aria-label="切换主题")，验证 data-theme 变化，
    刷新验证持久化(localStorage themeMode)。

    App.tsx 将 themeMode 同步到 document.documentElement data-theme 属性。
    themeMode 持久化于 localStorage 'rag-auth' key 的 state.themeMode 字段。
    """
    cdp = logged_in_cdp
    # 读取切换前 data-theme
    theme_before = cdp.evaluate("document.documentElement.getAttribute('data-theme')") or "light"
    # 点击主题切换按钮
    cdp.evaluate("""
        (function() {
            const btn = Array.from(document.querySelectorAll('button[aria-label]'))
                .find(b => b.getAttribute('aria-label').includes('切换主题'));
            if (btn) btn.click();
        })();
    """)
    wait_for(
        lambda: cdp.evaluate("document.documentElement.getAttribute('data-theme')") != theme_before,
        timeout=5,
        message="Theme did not change after toggle",
    )
    theme_after = cdp.evaluate("document.documentElement.getAttribute('data-theme')") or "light"
    assert (
        theme_after != theme_before
    ), f"Theme did not change: before={theme_before}, after={theme_after}"
    # 刷新验证持久化
    cdp.navigate(TAURI_HOME)
    wait_for_dom_ready(cdp, timeout=10)
    wait_for(
        lambda: cdp.evaluate("document.documentElement.getAttribute('data-theme')") is not None,
        timeout=5,
        message="data-theme attribute not set after reload",
    )
    theme_persisted = cdp.evaluate("document.documentElement.getAttribute('data-theme')") or "light"
    assert (
        theme_persisted == theme_after
    ), f"Theme not persisted: expected={theme_after}, got={theme_persisted}"
    # 恢复为 light 主题（避免影响后续测试）
    if theme_persisted != "light":
        cdp.evaluate("""
            (function() {
                const btn = Array.from(document.querySelectorAll('button[aria-label]'))
                    .find(b => b.getAttribute('aria-label').includes('切换主题'));
                if (btn) btn.click();
            })();
        """)
        wait_for(
            lambda: cdp.evaluate("document.documentElement.getAttribute('data-theme')") == "light",
            timeout=5,
            message="Theme did not restore to light",
        )


def test_user_avatar_menu(logged_in_cdp, admin_token):
    """用例4: 真实鼠标 hover .user-dropdown-trigger，验证下拉菜单（修改密码/退出登录），不实际登出。

    HeaderActions.tsx 用户区域 class="user-dropdown-trigger"，Dropdown 默认 trigger="hover"。
    Ant Design Dropdown 菜单渲染在 portal 中, 使用 .ant-dropdown-menu-item 精确定位。
    使用 CDP Input.dispatchMouseEvent(mouseMoved) 模拟真实鼠标 hover，比合成 JS
    MouseEvent 更可靠地触发 Ant Design hover trigger。
    """
    cdp = logged_in_cdp
    # 重新注入 admin token：前序测试（test_theme_toggle 的 cdp.navigate(TAURI_HOME)）
    # 触发整页加载，若 localStorage 被其他测试文件污染则 Layout 不会渲染 HeaderActions。
    _reinject_admin(cdp, admin_token, "#/dashboard")
    wait_for_element(cdp, ".user-dropdown-trigger", timeout=15)
    # 获取头像触发元素中心坐标
    coords = cdp.evaluate("""
        (function() {
            const el = document.querySelector('.user-dropdown-trigger');
            if (!el) return null;
            const rect = el.getBoundingClientRect();
            return {x: rect.x + rect.width/2, y: rect.y + rect.height/2};
        })();
    """)
    if not coords:
        pytest.fail("user-dropdown-trigger element not found or no bounding box")
    hx, hy = int(coords["x"]), int(coords["y"])
    # 真实 CDP 鼠标 hover（Input.dispatchMouseEvent mouseMoved）
    cdp.send(
        "Input.dispatchMouseEvent",
        {
            "type": "mouseMoved",
            "x": hx,
            "y": hy,
        },
    )
    # 轮询等待 Dropdown 菜单渲染（Ant Design Dropdown 异步渲染在 portal 中）
    menu_text = ""
    deadline = time.time() + 8
    while time.time() < deadline:
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
        # 持续 hover 防止 dropdown 因 mouseout 关闭
        cdp.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseMoved",
                "x": hx,
                "y": hy,
            },
        )
        time.sleep(0.5)  # 轮询间隔
    assert "退出登录" in menu_text, f"Logout menu item not found in avatar dropdown: {menu_text}"
    assert (
        "修改密码" in menu_text or "密码" in menu_text
    ), f"Change password menu item not found: {menu_text}"


def test_notification_popover(logged_in_cdp, admin_token):
    """用例5: 真实点击通知铃铛（NotificationPopover），验证 popover 渲染，关闭。

    NotificationPopover.tsx 使用 Ant Design Popover，触发器为 Badge > Button（Bell 图标）。
    点击后弹出通知列表（空状态显示"暂无通知"）。
    使用 CDP Input.dispatchMouseEvent(mousePressed/mouseReleased) 模拟真实点击。
    """
    cdp = logged_in_cdp
    # 重新注入 admin token：确保 Layout 渲染 HeaderActions（含通知铃铛）。
    _reinject_admin(cdp, admin_token, "#/dashboard")
    wait_for_element(cdp, ".ant-badge, button[aria-label]", timeout=10)
    # 查找通知铃铛按钮并获取中心坐标
    coords = cdp.evaluate("""
        (function() {
            // 优先通过 aria-label 查找
            let btn = Array.from(document.querySelectorAll('button[aria-label]'))
                .find(b => {
                    const label = b.getAttribute('aria-label') || '';
                    return label.includes('通知') || label.includes('notification');
                });
            // 回退：查找 Header 区域内含 svg 的 Badge 按钮
            if (!btn) {
                const badges = document.querySelectorAll('.ant-badge');
                for (const badge of badges) {
                    const innerBtn = badge.querySelector('button');
                    if (innerBtn) { btn = innerBtn; break; }
                }
            }
            if (!btn) return null;
            const rect = btn.getBoundingClientRect();
            return {x: rect.x + rect.width/2, y: rect.y + rect.height/2};
        })();
    """)
    if not coords:
        pytest.fail("Notification bell button not found")
    bx, by = int(coords["x"]), int(coords["y"])
    # 真实 CDP 点击（Input.dispatchMouseEvent）
    cdp.send(
        "Input.dispatchMouseEvent",
        {
            "type": "mousePressed",
            "x": bx,
            "y": by,
            "button": "left",
            "clickCount": 1,
        },
    )
    cdp.send(
        "Input.dispatchMouseEvent",
        {
            "type": "mouseReleased",
            "x": bx,
            "y": by,
            "button": "left",
            "clickCount": 1,
        },
    )
    # 轮询等待 popover 渲染
    deadline = time.time() + 5
    while time.time() < deadline:
        popover_open = cdp.evaluate(
            "!!document.querySelector('.ant-popover-inner, .ant-popover-content')"
        )
        if popover_open:
            break
        time.sleep(0.5)  # 轮询间隔
    assert popover_open, "Notification popover did not open after clicking bell"
    # 关闭 popover（点击空白处，使用 CDP 真实点击 body 区域）
    cdp.send(
        "Input.dispatchMouseEvent",
        {
            "type": "mousePressed",
            "x": 1,
            "y": 1,
            "button": "left",
            "clickCount": 1,
        },
    )
    cdp.send(
        "Input.dispatchMouseEvent",
        {
            "type": "mouseReleased",
            "x": 1,
            "y": 1,
            "button": "left",
            "clickCount": 1,
        },
    )
    wait_for(
        lambda: not cdp.evaluate(
            "!!document.querySelector('.ant-popover-inner, .ant-popover-content')"
        ),
        timeout=5,
        message="Notification popover did not close",
    )


def test_404_page(logged_in_cdp, admin_token):
    """用例6: 导航 /#/nonexistent，验证 .ant-result(404) + "返回首页"按钮，点击验证跳转。

    NotFoundPage.tsx 使用 Ant Design Result，status="404"，title="404"，
    含"返回首页"按钮（onClick navigate('/')）。
    NotFoundPage 是静态导入（非懒加载），路由 path="*" 在 ProtectedRoute 之外，
    即使未登录也会渲染。使用 wait_for_element 轮询等待 Result 组件渲染。
    """
    cdp = logged_in_cdp
    # 重新注入 admin token确保 SPA 在已知良好状态（/#/dashboard），
    # 然后再切换 hash 到 /#/nonexistent 触发 404 路由。
    _reinject_admin(cdp, admin_token, "#/dashboard")
    cdp.evaluate("window.location.hash = '#/nonexistent'")
    # 轮询等待 404 Result 渲染（hash 刬换触发 SPA 路由匹配，可能需要短暂延迟）
    wait_for_element(cdp, ".ant-result", timeout=20)
    # 验证 404 Result 渲染
    has_404 = cdp.evaluate("""
        (function() {
            return Array.from(document.querySelectorAll('.ant-result'))
                .some(el => el.textContent.includes('404'));
        })();
    """)
    assert has_404, "404 text not found in Result component"
    # 轮询等待"返回首页"按钮渲染
    deadline = time.time() + 5
    has_button = False
    while time.time() < deadline:
        has_button = cdp.evaluate("""
            (function() {
                return Array.from(document.querySelectorAll('button'))
                    .some(b => b.textContent.includes('返回首页'));
            })();
        """)
        if has_button:
            break
        time.sleep(0.5)  # 轮询间隔
    assert has_button, "返回首页 button not found on 404 page"
    # 点击"返回首页"验证跳转
    cdp.evaluate("""
        (function() {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('返回首页'));
            if (btn) btn.click();
        })();
    """)
    deadline = time.time() + 10
    while time.time() < deadline:
        url = cdp.evaluate("window.location.href") or ""
        if "/dashboard" in url:
            return
        time.sleep(0.5)  # 轮询间隔
    url = cdp.evaluate("window.location.href") or ""
    assert "/dashboard" in url, f"Did not navigate to dashboard after clicking 返回首页: {url}"
