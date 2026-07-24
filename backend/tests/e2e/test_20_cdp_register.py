"""CDP UI 测试 - 注册流程

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. 注册页面加载（表单字段 + 提交按钮渲染）
2. 注册成功（有效信息提交后跳转离开 /register）
3. 重复用户名注册（admin 已存在，验证错误提示）
4. 密码不一致（前端表单校验拦截）
5. 弱密码（前端密码强度规则校验拦截）

注意：/auth/register 限流 5/minute，本文件最多触发 2 次注册请求
（test_register_success + test_register_duplicate_username），其余靠前端校验拦截。
"""
import json
import os
import time
import uuid
import pytest

from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import wait_for_element

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


def _navigate_to_register(cdp):
    """导航到注册页，清除 localStorage 避免已登录状态干扰。

    使用完整页面导航 (cdp.navigate) 而非 hash 变更, 确保React状态完全重置:
    清除 localStorage 后重新加载页面, zustand store 从空 localStorage 重新 hydrate,
    token 为 null, /register 作为公开路由正常渲染。
    """
    cdp.navigate(TAURI_HOME)
    time.sleep(1)
    cdp.evaluate("""
        try { localStorage.clear(); sessionStorage.clear(); } catch(e) {}
    """)
    # 完整导航到注册页 (触发页面重新加载 + React 重新初始化)
    cdp.navigate("http://tauri.localhost/#/register")
    time.sleep(3)


# Ant Design Form name="register" 不会渲染为 HTML <form> 的 name 属性,
# 而是作为内部名称生成字段 ID: register_username, register_email 等。
REGISTER_FIELD_IDS = ["register_username", "register_email", "register_password", "register_confirm"]


def _fill_register_field(cdp, index, value):
    """填写注册表单中第 index 个 input（0=用户名, 1=邮箱, 2=密码, 3=确认密码）。

    使用字段 ID 定位（Ant Design Form name 生成 ID 前缀）,
    用原生 value setter 触发 React onChange，并 dispatch blur 触发 Ant Design
    表单校验（confirm 字段 validateTrigger 包含 onBlur）。
    """
    field_id = REGISTER_FIELD_IDS[index]
    js_value = json.dumps(value)
    cdp.evaluate(f"""
        (function() {{
            const el = document.getElementById({json.dumps(field_id)});
            if (!el) throw new Error('Register field not found: ' + {json.dumps(field_id)});
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            setter.call(el, {js_value});
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            el.dispatchEvent(new Event('blur', {{bubbles: true}}));
        }})();
    """)
    time.sleep(0.5)


def _click_register_submit(cdp):
    """点击注册表单提交按钮。"""
    cdp.evaluate("""
        (function() {
            const form = document.querySelector('form');
            if (!form) throw new Error('Register form not found');
            let btn = form.querySelector('button[type="submit"]');
            if (!btn) btn = form.querySelector('button.ant-btn-primary');
            if (!btn) throw new Error('Submit button not found');
            btn.click();
        })();
    """)


def test_register_page_loads(cdp):
    """注册页面加载：表单 + 4 个输入框 + 提交按钮均渲染。"""
    _navigate_to_register(cdp)
    # 等待注册页面的第一个字段出现（Ant Design Form name 生成 ID 前缀 register_）
    wait_for_element(cdp, '#register_username', timeout=10)
    # 验证表单存在
    has_form = cdp.evaluate('!!document.querySelector("form")')
    assert has_form, "Register form not found"
    # 验证输入框数量（username + email + password + confirm = 4）
    input_count = cdp.evaluate("""
        (function() {
            const form = document.querySelector('form');
            return form ? form.querySelectorAll('input').length : 0;
        })();
    """)
    assert input_count >= 4, f"Expected at least 4 inputs, got {input_count}"
    # 验证提交按钮存在
    has_submit = cdp.evaluate("""
        (function() {
            const form = document.querySelector('form');
            if (!form) return false;
            return !!(form.querySelector('button[type="submit"]') ||
                      form.querySelector('button.ant-btn-primary'));
        })();
    """)
    assert has_submit, "Submit button not found on register form"
    # 验证密码字段存在（password + confirm = 2 个 type=password input）
    has_strength_bar = cdp.evaluate("""
        (function() {
            const form = document.querySelector('form');
            if (!form) return false;
            return form.querySelectorAll('input[type="password"]').length >= 2;
        })();
    """)
    assert has_strength_bar, "Password fields not found"


def test_register_success(cdp):
    """注册成功：填写有效信息 → 提交 → 跳转离开 /register 或显示成功提示。

    用户名用 uuid 保证唯一，密码 Test@123456 满足复杂度要求
    （8+字符 + 大小写 + 数字 + 特殊字符 @）。
    """
    _navigate_to_register(cdp)
    username = f"e2e_cdp_{uuid.uuid4().hex[:8]}"
    email = f"{username}@test.com"
    password = "Test@123456"
    _fill_register_field(cdp, 0, username)
    _fill_register_field(cdp, 1, email)
    _fill_register_field(cdp, 2, password)
    _fill_register_field(cdp, 3, password)
    time.sleep(1)
    _click_register_submit(cdp)
    # 等待跳转或成功提示（register 后 navigate('/')，未登录会重定向到 /login）
    deadline = time.time() + 15
    while time.time() < deadline:
        url = cdp.evaluate("window.location.href")
        if url and "/register" not in url:
            return
        has_success = cdp.evaluate("""
            (function() {
                const msgs = document.querySelectorAll(
                    '.ant-message-success, .ant-message-notice-success'
                );
                return msgs.length > 0;
            })();
        """)
        if has_success:
            return
        time.sleep(1)
    url = cdp.evaluate("window.location.href")
    assert "/register" not in url, f"Still on register page after submit: {url}"


def test_register_duplicate_username(cdp):
    """重复用户名注册：用已存在的 admin 注册，验证错误提示。

    后端返回 409 Conflict，前端通过 msg.error 显示错误消息。
    """
    _navigate_to_register(cdp)
    email = f"e2e_dup_{uuid.uuid4().hex[:8]}@test.com"
    password = "Test@123456"
    _fill_register_field(cdp, 0, "admin")
    _fill_register_field(cdp, 1, email)
    _fill_register_field(cdp, 2, password)
    _fill_register_field(cdp, 3, password)
    time.sleep(1)
    _click_register_submit(cdp)
    # 等待错误提示出现（msg.error 或表单校验错误）
    deadline = time.time() + 10
    while time.time() < deadline:
        has_error = cdp.evaluate("""
            (function() {
                const msgs = document.querySelectorAll(
                    '.ant-message-error, .ant-message-notice-error'
                );
                if (msgs.length > 0) return true;
                const formErrors = document.querySelectorAll('.ant-form-item-explain-error');
                return formErrors.length > 0;
            })();
        """)
        if has_error:
            return
        time.sleep(1)
    assert False, "No error message shown for duplicate username"


def test_register_password_mismatch(cdp):
    """密码不一致：password != confirm，前端表单校验拦截提交。

    confirm 字段的 validator 拒绝不匹配的值，显示 .ant-form-item-explain-error。
    表单不会提交，URL 保持在 /register。
    """
    _navigate_to_register(cdp)
    username = f"e2e_mis_{uuid.uuid4().hex[:8]}"
    email = f"{username}@test.com"
    _fill_register_field(cdp, 0, username)
    _fill_register_field(cdp, 1, email)
    _fill_register_field(cdp, 2, "Test@123456")
    _fill_register_field(cdp, 3, "Different@123456")
    time.sleep(1)
    _click_register_submit(cdp)
    time.sleep(2)
    # 验证表单校验错误出现
    has_error = cdp.evaluate("""
        (function() {
            const errors = document.querySelectorAll('.ant-form-item-explain-error');
            if (errors.length === 0) return false;
            return Array.from(errors).some(e => e.textContent.length > 0);
        })();
    """)
    assert has_error, "No validation error for password mismatch"
    # 验证仍在注册页（未提交）
    url = cdp.evaluate("window.location.href")
    assert "/register" in url, f"Should still be on register page: {url}"


def test_register_weak_password(cdp):
    """弱密码注册：密码 "123" 不满足复杂度要求（min 8 + 大小写+数字+特殊字符）。

    createPasswordRules 校验 min:8 和 PASSWORD_COMPLEXITY_PATTERN，
    validateFirst 使第一个失败规则（min 8）显示错误。
    """
    _navigate_to_register(cdp)
    username = f"e2e_weak_{uuid.uuid4().hex[:8]}"
    email = f"{username}@test.com"
    _fill_register_field(cdp, 0, username)
    _fill_register_field(cdp, 1, email)
    _fill_register_field(cdp, 2, "123")
    _fill_register_field(cdp, 3, "123")
    time.sleep(1)
    _click_register_submit(cdp)
    time.sleep(2)
    # 验证表单校验错误出现
    has_error = cdp.evaluate("""
        (function() {
            const errors = document.querySelectorAll('.ant-form-item-explain-error');
            if (errors.length === 0) return false;
            return Array.from(errors).some(e => e.textContent.length > 0);
        })();
    """)
    assert has_error, "No validation error for weak password"
    # 验证仍在注册页
    url = cdp.evaluate("window.location.href")
    assert "/register" in url, f"Should still be on register page: {url}"
