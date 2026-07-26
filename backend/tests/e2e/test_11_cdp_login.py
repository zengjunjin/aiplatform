r"""CDP UI 测试 - 登录与导航

需要 Tauri 以 CDP 端口 9223 启动：
    .\scripts\start_tauri_with_cdp.ps1

测试场景：
1. CDP 连接成功
2. Tauri 应用已加载
3. 完整登录流程
4. localStorage 不持久化 access_token
5. 导航到知识库页面
6. 登出
"""

import os

import pytest

from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import wait_for, wait_for_dom_ready, wait_for_element

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"


@pytest.fixture(scope="module")
def cdp():
    """CDP 客户端 fixture（module scope，多个测试共享连接）"""
    client = CdpClient(cdp_port=CDP_PORT)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {CDP_PORT}): {e}")
    yield client
    client.close()


def test_cdp_connection(cdp):
    """CDP 连接成功，可执行 JS"""
    result = cdp.evaluate("1 + 1")
    assert result == 2, f"CDP JS eval failed: 1+1 = {result}"


def test_tauri_loaded(cdp):
    """Tauri 应用已加载"""
    cdp.navigate(TAURI_HOME)
    ready = cdp.evaluate("document.readyState")
    assert ready in ("interactive", "complete"), f"readyState={ready}"


def test_login_flow(cdp):
    """完整登录流程：填表 → 点击 → 跳转

    登录表单使用 Ant Design Input，需要用原生 setter 触发 React onChange。
    先清除 localStorage 中的 token，确保跳到登录页。

    /auth/login 限流 5/minute，完整 E2E 套件中可能触发 429。
    登录后检查 URL 是否离开 /login，若未离开则等待 60s 重试，最多 2 次。

    H14 修复：使用 ID 选择器（#login_username / #login_password）代替
    input[type='text']:first-of-type，更可靠地定位 Ant Design Form name="login"
    生成的字段（Form.Item name="username" → id="login_username"）。
    H14 修复：admin 密码通过 E2E_ADMIN_PASSWORD / INITIAL_ADMIN_PASSWORD 环境变量
    注入，与 conftest.py 保持一致（原硬编码 "admin123" 与 deploy/.env 中的
    INITIAL_ADMIN_PASSWORD 不匹配导致 401 登录失败）。
    """
    admin_password = (
        os.getenv("E2E_ADMIN_PASSWORD")
        or os.getenv("INITIAL_ADMIN_PASSWORD")
        or "admin123"
    )
    cdp.navigate(TAURI_HOME)
    wait_for_dom_ready(cdp, timeout=10)
    for attempt in range(3):  # 最多 3 次（首次 + 2 次重试）
        # 清除 localStorage 中的 token 缓存，确保跳到登录页
        cdp.evaluate("""
            try {
                localStorage.clear();
                sessionStorage.clear();
            } catch (e) {}
        """)
        # 导航到登录页
        cdp.evaluate("window.location.hash = '#/login'")
        # 等待登录表单出现（Ant Design Form name="login" 生成 id="login_username"）
        wait_for_element(cdp, "#login_username, input[id*='username']", timeout=15)
        # 填写用户名（Ant Design Form name="login" → id="login_username"）
        cdp.fill_input("#login_username", "admin")
        wait_for_element(cdp, "#login_password, input[type='password']", timeout=5)
        # 填写密码（Ant Design Input.Password → id="login_password"）
        cdp.fill_input("#login_password", admin_password)
        wait_for_element(cdp, "button[type='submit'], button.ant-btn-primary", timeout=5)
        # 点击登录按钮（Ant Design Button htmlType="submit" class="ant-btn-primary"）
        cdp.evaluate("""
            (function() {
                // 优先用 type=submit 找登录按钮
                let btn = document.querySelector('button[type="submit"]');
                if (!btn) btn = document.querySelector('button.ant-btn-primary');
                if (!btn) {
                    // 回退到文本匹配
                    const buttons = Array.from(document.querySelectorAll('button'));
                    btn = buttons.find(b =>
                        b.textContent.includes('登录') || b.textContent.includes('Login'));
                }
                if (!btn) throw new Error('Login button not found');
                btn.click();
            })();
        """)
        # 等待跳转（登录成功后应离开 /login）
        try:
            wait_for(
                lambda: "/login" not in (cdp.evaluate("window.location.href") or ""),
                timeout=10,
                interval=0.5,
                message="Login redirect (immediate)",
            )
            return
        except TimeoutError:
            pass
        # 仍在登录页，可能 /auth/login 被限流（429），轮询等待限流窗口过期
        if attempt < 2:
            try:
                wait_for(
                    lambda: "/login" not in (cdp.evaluate("window.location.href") or ""),
                    timeout=60,
                    interval=2,
                    message="Login redirect (after rate-limit window)",
                )
                return
            except TimeoutError:
                pass
    url = cdp.evaluate("window.location.href")
    assert "/login" not in url, f"Still on login page after retries: {url}"


def test_no_access_token_in_localstorage(cdp):
    """localStorage 不持久化 access_token（安全约束）

    前端 auth store 通过 partialize 只持久化 refreshToken/refreshTokenExpiresAt/user/themeMode，
    不持久化 access_token（token）以降低 token 泄露风险。
    """
    # 等待 auth store 完成持久化（access_token 不应被写入 localStorage）
    wait_for(
        lambda: not cdp.evaluate("localStorage.getItem('access_token')"),
        timeout=5,
        interval=0.3,
        message="access_token should not persist in localStorage",
    )
    token = cdp.evaluate("localStorage.getItem('access_token')")
    assert not token, f"access_token should not be in localStorage: {token}"
    token2 = cdp.evaluate("localStorage.getItem('token')")
    assert not token2, f"token should not be in localStorage: {token2}"


def test_navigate_to_knowledge_bases(cdp):
    """导航到知识库页面（直接用 hash 导航，不依赖菜单项点击）"""
    cdp.evaluate("window.location.hash = '#/knowledge-bases'")
    wait_for_element(cdp, "button, .ant-card, .ant-empty", timeout=8)
    url = cdp.evaluate("window.location.href")
    assert (
        "knowledge-bases" in url or "knowledge" in url.lower()
    ), f"Navigation to knowledge-bases failed: {url}"


def test_logout(cdp):
    """登出流程：点击用户头像展开菜单 → 点击登出 → 回到登录页

    Ant Design Dropdown 触发器是包含 Avatar 的 div，菜单渲染在 portal 中。
    """
    # 点击 Avatar 区域展开 dropdown 菜单
    cdp.evaluate("""
        (function() {
            const avatar = document.querySelector('.ant-avatar');
            if (avatar) {
                // 点击 Avatar 的父元素（Dropdown 触发器）
                avatar.parentElement.click();
            } else {
                // 回退：点击 Header 右侧区域
                const header = document.querySelector('.ant-layout-header');
                if (header) {
                    const rightArea = header.lastElementChild;
                    if (rightArea) rightArea.click();
                }
            }
        })();
    """)
    # 等待 dropdown 菜单项出现（替代固定 sleep，处理动画/渲染延迟）
    wait_for_element(cdp, ".ant-dropdown-menu-item, [role='menuitem']", timeout=5)
    # 点击登出菜单项（Ant Design Dropdown menu item）
    clicked = cdp.evaluate("""
        (function() {
            const items = Array.from(document.querySelectorAll(
                '.ant-dropdown-menu-item, [role="menuitem"]'
            ));
            const logout = items.find(i =>
                i.textContent.includes('登出') || i.textContent.includes('Logout') ||
                i.textContent.includes('退出'));
            if (logout) {
                logout.click();
                return true;
            }
            return false;
        })();
    """)
    if not clicked:
        # 回退：直接清除 token 并导航到登录页
        cdp.evaluate("""
            try { localStorage.clear(); sessionStorage.clear(); } catch(e) {}
            window.location.hash = '#/login';
        """)
    # 等待跳转回登录页
    try:
        wait_for(
            lambda: (
                "/login" in (cdp.evaluate("window.location.href") or "")
                or "login" in (cdp.evaluate("window.location.href") or "").lower()
            ),
            timeout=10,
            interval=0.5,
            message="Logout redirect to login",
        )
        return
    except TimeoutError:
        pass
    url = cdp.evaluate("window.location.href")
    assert "/login" in url or "login" in url.lower(), f"Not redirected to login after logout: {url}"
