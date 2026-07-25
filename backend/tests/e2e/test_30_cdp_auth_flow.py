"""CDP UI 测试 - 认证完整流程

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. 注册页加载（表单元素验证）
2. 注册成功（跳转登录页）
3. 注册重复用户名（错误提示）
4. 注册密码不匹配（表单校验错误）
5. 登录成功（token 注入 + 跳转 dashboard）
6. 登录错误密码（错误提示）
7. 登出（清除 token + 跳转登录页）
8. 刷新 token 流程（API 验证）
9. token 过期行为（修改 localStorage 触发自动刷新/登出）

精简原则：注册页前 4 个用例只导航 1 次（test_register_page_loads 导航，
后续用例在同一页面上下文操作；如有跳转再按需导航）。
"""

import os
import time
import uuid

import pytest
import requests

from tests.e2e.helpers.cdp_auth import (
    create_user_via_api,
    login_cdp_session,
    make_cdp_client,
)
from tests.e2e.helpers.waiters import (
    wait_for,
    wait_for_element,
    wait_for_url_change,
)

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"

# module 级缓存：test_logout 创建的用户供 test_token_expiry_behavior 复用，
# 避免 test_30 内 6 次 /auth/login 触发 5/minute 限流。
# 后端 logout 只撤销 access_token（前端 POST /auth/logout 不传 body，
# 后端 request.json() 抛异常跳过 refresh_token 黑名单），refresh_token 仍有效。
_shared_user = {}


@pytest.fixture(scope="module")
def cdp():
    """CDP 客户端（module scope，整个文件共享一个会话）"""
    client = make_cdp_client(CDP_PORT)
    yield client
    client.close()


def _set_form_inputs(cdp, values):
    """按顺序填写 form input（username/email/password/confirm 或 username/password）。

    Args:
        values: list[str], 按DOM顺序对应的 input 值
    """
    cdp.evaluate(f"""
        (function() {{
            const inputs = document.querySelectorAll('form input');
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            for (let i = 0; i < Math.min(inputs.length, arguments.length); i++) {{
                setter.call(inputs[i], arguments[i]);
                inputs[i].dispatchEvent(new Event('input', {{bubbles: true}}));
                inputs[i].dispatchEvent(new Event('change', {{bubbles: true}}));
            }}
        }})({', '.join(repr(v) for v in values)});
    """)


def _click_submit(cdp):
    """点击 form 内的 submit 按钮"""
    cdp.evaluate("""
        (function() {
            const btn = document.querySelector('form button[type="submit"]');
            if (btn) btn.click();
        })();
    """)


def test_register_page_loads(cdp):
    """注册页加载：导航 /#/register 一次，验证 form#register + 4 个 input + 提交按钮"""
    cdp.navigate(TAURI_HOME + "#/register")
    wait_for_url_change(cdp, "#/register", timeout=10)
    # 验证表单存在
    form_exists = cdp.evaluate("!!document.querySelector('form#register')")
    assert form_exists, "Register form#register not found"
    # 验证至少 4 个 input（username/email/password/confirm）
    input_count = cdp.evaluate("document.querySelectorAll('form#register input').length")
    assert input_count >= 4, f"Expected >=4 inputs in register form, got {input_count}"
    # 验证提交按钮文案包含"注册"
    # Ant Design 5 中文按钮会在字符间插入空格（letter-spacing 渲染），去除空格后再比较
    submit_text = cdp.evaluate("""
        (function() {
            const btn = document.querySelector('form#register button[type="submit"]');
            return btn ? btn.textContent.replace(/\\s/g, '') : null;
        })();
    """)
    assert submit_text and "注册" in submit_text, f"Submit button text: {submit_text}"


def test_register_success(cdp):
    """注册成功：填写有效信息（uuid 用户名 + Test@123456），提交，验证跳转 /#/login"""
    username = f"e2e_auth_{uuid.uuid4().hex[:8]}"
    email = f"{username}@test.com"
    password = "Test@123456"
    # 此时已在注册页（test_register_page_loads 导航过）
    _set_form_inputs(cdp, [username, email, password, password])
    # 必要固定等待：React onChange debounce
    time.sleep(0.5)
    _click_submit(cdp)
    # 等待跳转完成（注册成功后前端 navigate('/')，若 localStorage 有残留
    # refreshToken 会重定向到 #/dashboard，否则重定向到 #/login）
    wait_for(
        lambda: any(
            part in (cdp.evaluate("window.location.hash") or "")
            for part in ("#/login", "#/dashboard")
        ),
        timeout=10,
        interval=0.5,
        message="Did not navigate to #/login or #/dashboard after register",
    )
    hash_val = cdp.evaluate("window.location.hash")
    assert hash_val and (
        "#/login" in hash_val or "#/dashboard" in hash_val
    ), f"Did not navigate to #/login or #/dashboard after register, hash={hash_val}"


def test_register_duplicate(cdp):
    """注册重复用户名：用 admin 注册，验证 .ant-message-error 出现"""
    # 上一用例跳转到 login，需重新导航到注册页
    cdp.navigate(TAURI_HOME + "#/register")
    wait_for_url_change(cdp, "#/register", timeout=10)
    _set_form_inputs(cdp, ["admin", "admin_dup@test.com", "Test@123456", "Test@123456"])
    # 必要固定等待：React onChange debounce
    time.sleep(0.5)
    _click_submit(cdp)
    # 等待错误提示
    wait_for(
        lambda: cdp.evaluate("!!document.querySelector('.ant-message-error')"),
        timeout=8,
        interval=0.5,
        message="No .ant-message-error shown for duplicate username",
    )


def test_register_password_mismatch(cdp):
    """注册密码不匹配：password≠confirm，验证 .ant-form-item-explain-error 出现"""
    # 此时仍在注册页（上一用例提交失败未跳转）
    username = f"e2e_mismatch_{uuid.uuid4().hex[:6]}"
    _set_form_inputs(cdp, [username, "mismatch@test.com", "Test@123456", "Test@1234567"])
    # 触发 confirm input 的 blur 以激活校验
    cdp.evaluate("""
        (function() {
            const inputs = document.querySelectorAll('form#register input');
            if (inputs.length >= 4) {
                inputs[3].dispatchEvent(new Event('blur', {bubbles: true}));
            }
        })();
    """)
    # 必要固定等待：Ant Design 表单 blur 校验异步渲染
    time.sleep(1)
    # 点击提交触发完整校验
    _click_submit(cdp)
    wait_for_element(cdp, ".ant-form-item-explain-error", timeout=5)
    found = cdp.evaluate("!!document.querySelector('.ant-form-item-explain-error')")
    assert found, "No .ant-form-item-explain-error shown for password mismatch"


def test_login_success(cdp, base_url, admin_headers):
    """登录成功：用 API 注册+获取 token，注入 localStorage，验证跳转 /#/dashboard"""
    user_info = create_user_via_api(base_url, admin_headers)
    login_cdp_session(cdp, user_info, "#/dashboard")
    hash_val = cdp.evaluate("window.location.hash")
    assert (
        hash_val and "#/dashboard" in hash_val
    ), f"Did not navigate to #/dashboard after login, hash={hash_val}"


def test_login_wrong_password(cdp):
    """登录错误密码：导航 /#/login，填表登录 admin+错误密码，验证错误提示"""
    cdp.navigate(TAURI_HOME + "#/login")
    wait_for_url_change(cdp, "#/login", timeout=10)
    # 登录表单通常是 username + password 两个 input
    _set_form_inputs(cdp, ["admin", "WrongPassword@123"])
    # 必要固定等待：React onChange debounce
    time.sleep(0.5)
    _click_submit(cdp)
    # 等待错误提示（message 或 form 校验错误）
    wait_for(
        lambda: cdp.evaluate(
            "!!document.querySelector('.ant-message-error') || "
            "!!document.querySelector('.ant-form-item-explain-error')"
        ),
        timeout=8,
        interval=0.5,
        message="No error shown for wrong password login",
    )


def test_logout(cdp, base_url, admin_headers):
    """登出：已登录态，点击 .user-dropdown-trigger → 退出登录，验证跳转 /#/login + localStorage 清空

    必须使用独立用户 token，不能用共享 admin_token：后端 /auth/logout 会将
    access_token 加入 Redis 黑名单（add_to_blacklist），若用 admin_token 登出，
    session 作用域的 admin_token 会被永久拉黑，导致后续所有依赖 admin_headers
    的测试（test_31-test_38）全部 401 "Token has been revoked"。
    """
    # 创建独立用户，避免污染共享 admin_token
    user_info = create_user_via_api(base_url, admin_headers)
    # 缓存供 test_token_expiry_behavior 复用（refresh_token 仍有效）
    _shared_user["info"] = user_info
    login_cdp_session(cdp, user_info, "#/dashboard")
    # 等待 .user-dropdown-trigger 出现（Layout/HeaderActions 渲染可能需要时间）
    trigger_found = True
    try:
        wait_for_element(cdp, ".user-dropdown-trigger", timeout=10)
    except TimeoutError:
        # 强制整页刷新重试（zustand persist 可能未及时 rehydrate）
        cdp.send("Page.reload")
        # 必要固定等待：reload 后 zustand persist rehydrate
        time.sleep(3)
        try:
            wait_for_element(cdp, ".user-dropdown-trigger", timeout=5)
        except TimeoutError:
            trigger_found = False
    assert trigger_found, ".user-dropdown-trigger not found after login + reload"
    # 使用真实鼠标点击触发 Ant Design Dropdown（JS .click() 不能触发 Dropdown onOpenChange）
    # 注意：menu_ready 只能检查 .ant-dropdown-menu-item（不能查 [role="menuitem"]），
    # 因为侧边栏 .ant-menu-item 也有 role="menuitem"，会误判 dropdown 已打开。
    menu_ready = False
    for _attempt in range(3):
        cdp.click_element(".user-dropdown-trigger")
        # 等待 Dropdown 菜单渲染（Portal 挂载到 body）
        try:
            wait_for(
                lambda: cdp.evaluate("""
                    (function() {
                        const items = document.querySelectorAll('.ant-dropdown-menu-item');
                        return items.length > 0;
                    })();
                """),
                timeout=3,
                interval=0.3,
                message="Dropdown menu not rendered",
            )
            menu_ready = True
        except TimeoutError:
            pass
        if menu_ready:
            break
        # 必要固定等待：重试点击间隔
        time.sleep(0.5)
    assert menu_ready, "Dropdown menu did not appear after clicking trigger"
    # 诊断：打印所有菜单项的 textContent（便于排查 i18n / 渲染问题）
    menu_dump = cdp.evaluate("""
        (function() {
            const items = Array.from(document.querySelectorAll('.ant-dropdown-menu-item'));
            return items.map(i => ({
                text: i.textContent,
                stripped: i.textContent.replace(/\\s/g, ''),
                cls: i.className,
            }));
        })();
    """)
    print(f"[test_logout DEBUG] menu items: {menu_dump}")
    # 找到"退出登录"菜单项并触发 React onClick
    # 使用原生 HTMLElement.click() 创建 React 可捕获的信任事件
    # （dispatchEvent 创建的是非信任事件, React 可能不处理）
    logout_clicked = cdp.evaluate("""
        (function() {
            const items = Array.from(document.querySelectorAll('.ant-dropdown-menu-item'));
            const item = items.find(i =>
                i.textContent.replace(/\\s/g, '').includes('退出登录') ||
                i.textContent.replace(/\\s/g, '').includes('退出') ||
                i.textContent.includes('Logout') ||
                i.textContent.toLowerCase().includes('logout'));
            if (!item) return false;
            item.scrollIntoView({block: 'center'});
            // 原生 .click() 触发 React 合成事件
            item.click();
            return true;
        })();
    """)
    assert logout_clicked, f"Logout menu item not found. Menu items: {menu_dump}"
    # 等待跳转登录页
    wait_for_url_change(cdp, "#/login", timeout=8)
    hash_val = cdp.evaluate("window.location.hash")
    assert (
        hash_val and "#/login" in hash_val
    ), f"Did not navigate to #/login after logout, hash={hash_val}"
    # 验证 localStorage rag-auth 已清空（token 字段为空或整个 key 移除）
    auth_token = cdp.evaluate("""
        (function() {
            const raw = localStorage.getItem('rag-auth');
            if (!raw) return null;
            try {
                const obj = JSON.parse(raw);
                return (obj.state && obj.state.token) || null;
            } catch(e) { return 'parse_error'; }
        })();
    """)
    assert not auth_token, f"rag-auth token not cleared after logout: {auth_token}"


def test_refresh_token_flow(cdp, base_url, admin_headers):
    """刷新 token 流程：用 API 调 /auth/refresh 验证返回新 access_token

    必须使用独立用户的 refresh_token：后端 /auth/refresh 会将旧 refresh_token
    加入黑名单（refresh token rotation），若用 admin_token 的 refresh_token，
    session 作用域的 admin_token 中的 refresh_token 会被永久拉黑。
    虽然当前后续测试主要用 access_token（不是 refresh_token），但保持
    admin_token 完整性是良好实践，避免潜在的级联失败。
    """
    user_info = create_user_via_api(base_url, admin_headers)
    r = requests.post(
        f"{base_url}/auth/refresh",
        json={"refresh_token": user_info["refresh_token"]},
        timeout=10,
    )
    assert r.status_code == 200, f"Refresh failed: {r.status_code} {r.text}"
    data = r.json().get("data", r.json())
    assert "access_token" in data, f"No access_token in refresh response: {data}"
    assert data["access_token"], "Empty access_token in refresh response"


def test_token_expiry_behavior(cdp, base_url, admin_headers):
    """token 过期行为：修改 localStorage refreshTokenExpiresAt 为过去时间，Page.reload 触发 onRehydrateStorage 登出

    创建独立用户（不复用 test_logout 的用户）：前端 logout 已修复为传 refresh_token，
    test_logout 后 refresh_token 会被正确拉黑，无法复用于 refreshAccessToken 测试。
    此处创建新用户确保 refresh_token 有效，能验证 rehydrate → refresh → 登录态保持
    的正向流程，然后修改 refreshTokenExpiresAt 为过去时间验证过期登出。
    """
    user_info = create_user_via_api(base_url, admin_headers)
    login_cdp_session(cdp, user_info, "#/dashboard")
    wait_for_url_change(cdp, "#/dashboard", timeout=10)
    # 修改 refreshTokenExpiresAt 为过去时间（1 小时前）
    cdp.evaluate("""
        (function() {
            const raw = localStorage.getItem('rag-auth');
            if (!raw) return;
            try {
                const obj = JSON.parse(raw);
                obj.state.refreshTokenExpiresAt = Date.now() - 3600 * 1000;
                localStorage.setItem('rag-auth', JSON.stringify(obj));
            } catch(e) {}
        })();
    """)
    # 强制整页刷新触发 onRehydrateStorage：前端检查 refreshTokenExpiresAt 过期后
    # 清空 refreshToken + user，AuthWatcher 检测到 token/refreshToken 均为空后跳转 #/login
    cdp.send("Page.reload")
    # 必要固定等待：reload 后 onRehydrateStorage 异步执行
    time.sleep(3)
    # 等待跳转完成（AuthWatcher 异步导航可能有延迟）
    wait_for_url_change(cdp, "#/login", timeout=7)
    hash_val = cdp.evaluate("window.location.hash")
    # 验证过期后触发登出（跳转 #/login）
    assert (
        hash_val and "#/login" in hash_val
    ), f"Token expiry did not trigger logout after Page.reload, hash={hash_val}"
