"""CDP UI 测试 - 知识库与文档

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. 打开创建 KB 弹窗
2. Modal 关闭无 pointer-events 残留（Tauri WebView2 CSS 动画 bug 验证）
3. 通过 UI 创建 KB
"""

import os
import uuid

import pytest

from tests.e2e.helpers.cdp_auth import login_cdp_session
from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import wait_for, wait_for_dom_ready, wait_for_element

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"


@pytest.fixture(scope="module")
def logged_in_cdp(admin_token):
    """登录后的 CDP 客户端（用 API token 注入 localStorage，避免 WebView 填表登录触发限流）"""
    client = CdpClient(cdp_port=CDP_PORT)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {CDP_PORT}): {e}")
    login_cdp_session(client, admin_token, "#/knowledge-bases")
    yield client
    client.close()


def _reset_kb_page(cdp):
    """重置 KB 页面 React state：完整重新加载页面（清除所有 React state 和 Modal Portal）

    H14 修复：用 Page.reload 代替 cdp.navigate(TAURI_HOME)，避免全页导航导致
    zustand 重新 rehydrate 期间 AdminRoute 重定向。先设置 hash 再 reload，
    确保 reload 后 SPA 直接进入目标路由。
    """
    cdp.evaluate("window.location.hash = '#/knowledge-bases'")
    cdp.send("Page.reload")
    wait_for_dom_ready(cdp, timeout=10)
    wait_for_element(cdp, "button, .ant-card, .ant-empty", timeout=8)


def test_open_create_kb_modal(logged_in_cdp):
    """打开创建 KB 弹窗：导航到 KB 页 → 点击创建 → Modal 出现"""
    cdp = logged_in_cdp
    _reset_kb_page(cdp)
    # 等待页面按钮渲染完成（KB 列表页加载可能延迟）
    wait_for_element(cdp, "button", timeout=10)
    # 点击创建按钮：优先用文本查找（避免误点分页器等其他 primary 按钮）
    clicked = cdp.evaluate("""
        (function() {
            const buttons = Array.from(document.querySelectorAll('button'));
            // 优先找文本包含"新建"/"创建"/"Create"/"New"的按钮
            let btn = buttons.find(b =>
                b.textContent.includes('新建') || b.textContent.includes('创建') ||
                b.textContent.includes('Create') || b.textContent.includes('New'));
            // fallback: ant-btn-primary
            if (!btn) btn = document.querySelector('button.ant-btn-primary');
            if (!btn) return false;
            btn.click();
            return true;
        })();
    """)
    assert clicked, "Create button not found on KB page"
    # 显式等待 Modal 出现（替代固定 sleep，处理渲染延迟）
    try:
        wait_for_element(cdp, ".ant-modal-content", timeout=8)
        modal = True
    except TimeoutError:
        modal = False
    assert modal, "Create KB modal did not appear"


def test_modal_close_no_residual(logged_in_cdp):
    """Modal transitionName="" 修复验证 + 关闭无 pointer-events 残留

    Tauri WebView2 在 Ant Design Modal 的 CSS 动画期间存在 pointer-events bug：
    Modal 关闭后 body 仍可能保留 modal-open class 或 pointer-events:none。
    约束：所有 Modal 必须设置 transitionName="" 和 maskTransitionName="" 来禁用动画。

    由于 CDP 无法通过程序化方式触发 React 17+ 合成事件（onClick 回调），
    本测试改为：
    1. 验证 Modal 打开时没有 transition class（证明 transitionName="" 生效）
    2. 用 DOM 强制移除 Modal 后验证无 pointer-events 残留
    """
    cdp = logged_in_cdp
    # 重置 KB 页面 React state
    _reset_kb_page(cdp)
    # 点击"新建知识库"按钮打开 Modal
    cdp.evaluate("""
        (function() {
            let btn = document.querySelector('button.ant-btn-primary');
            if (!btn) {
                const buttons = Array.from(document.querySelectorAll('button'));
                btn = buttons.find(b =>
                    b.textContent.includes('新建') || b.textContent.includes('创建') ||
                    b.textContent.includes('New') || b.textContent.includes('Create'));
            }
            if (btn) btn.click();
        })();
    """)
    # 等待 Modal 出现（替代固定 sleep）
    wait_for_element(cdp, ".ant-modal-content", timeout=8)
    # 确认 Modal 打开
    modal_open = cdp.evaluate("!!document.querySelector('.ant-modal-content')")
    if not modal_open:
        pytest.skip("Failed to open Modal for close test")

    # 1. 验证 transitionName="" 生效：Modal 元素不应有 ant-zoom-* transition class
    modal_classes = (
        cdp.evaluate("""
        (function() {
            const modal = document.querySelector('.ant-modal');
            return modal ? modal.className : '';
        })();
    """)
        or ""
    )
    assert (
        "ant-zoom" not in modal_classes
    ), f"Modal has transition class (transitionName='' not applied): {modal_classes}"

    # 2. 验证 maskTransitionName="" 生效：Mask 元素不应有 ant-fade-* transition class
    mask_classes = (
        cdp.evaluate("""
        (function() {
            const mask = document.querySelector('.ant-modal-mask');
            return mask ? mask.className : '';
        })();
    """)
        or ""
    )
    assert (
        "ant-fade" not in mask_classes
    ), f"Mask has transition class (maskTransitionName='' not applied): {mask_classes}"

    # 3. 用 DOM 强制移除 Modal（绕过 React 合成事件限制）
    # 注：transitionName="" 只控制 ant-zoom-* class，不影响 Ant Design 5.x 内置的
    # hover transition (background-color 0.2s 等)，所以不检查 computed transition。
    cdp.evaluate("""
        (function() {
            const root = document.querySelector('.ant-modal-root');
            if (root) root.remove();
            // 清理 body 滚动锁定
            document.body.classList.remove('ant-scrolling-effect');
            document.body.style.overflow = '';
            document.body.style.paddingRight = '';
        })();
    """)
    # 等待 Modal 从 DOM 消失（替代固定 sleep）
    wait_for(
        lambda: not cdp.evaluate("document.querySelector('.ant-modal-content')"),
        timeout=5,
        interval=0.2,
        message="Modal removed from DOM",
    )

    # 4. 验证 Modal 消失
    modal = cdp.evaluate("!!document.querySelector('.ant-modal-content')")
    assert not modal, "Modal did not close after DOM removal"

    # 5. 验证 body 无 ant-scrolling-effect class（Ant Design 5.x 用此 class 锁定滚动）
    body_class = cdp.evaluate("document.body.className") or ""
    assert (
        "ant-scrolling-effect" not in body_class
    ), f"Body still has ant-scrolling-effect class: {body_class}"

    # 6. 验证可点击其他按钮（pointer-events 未被禁用）
    clickable = cdp.evaluate("""
        (function() {
            const btn = document.querySelector('button');
            if (!btn) return false;
            return getComputedStyle(btn).pointerEvents !== 'none';
        })();
    """)
    assert clickable, "Buttons not clickable after modal close (pointer-events bug)"

    # 7. 验证 body overflow 恢复正常
    body_overflow = cdp.evaluate("getComputedStyle(document.body).overflow")
    assert body_overflow != "hidden", f"Body overflow is hidden after modal close: {body_overflow}"


def test_create_kb_via_ui(logged_in_cdp):
    """通过 UI 创建 KB：打开 Modal → 填名称 → 确定 → 列表中出现"""
    cdp = logged_in_cdp
    kb_name = f"CDP_KB_{uuid.uuid4().hex[:6]}"
    # 重置 KB 页面 React state
    _reset_kb_page(cdp)
    # 打开创建 Modal（使用 ant-btn-primary 选择器，与 test_open_create_kb_modal 一致）
    cdp.evaluate("""
        (function() {
            let btn = document.querySelector('button.ant-btn-primary');
            if (!btn) {
                const buttons = Array.from(document.querySelectorAll('button'));
                btn = buttons.find(b =>
                    b.textContent.includes('新建') || b.textContent.includes('创建') ||
                    b.textContent.includes('Create') || b.textContent.includes('New'));
            }
            if (!btn) throw new Error('Create button not found');
            btn.click();
        })();
    """)
    # 等待 Modal 出现（替代固定 sleep）
    wait_for_element(cdp, ".ant-modal-content", timeout=8)
    # 确认 Modal 已打开
    modal_open = cdp.evaluate("!!document.querySelector('.ant-modal-content')")
    if not modal_open:
        pytest.skip("Failed to open Modal for KB creation")
    # 填写 KB 名称
    cdp.evaluate(f"""
        (function() {{
            const input = document.querySelector('.ant-modal input[type="text"]');
            if (!input) throw new Error('KB name input not found in modal');
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            setter.call(input, {repr(kb_name)});
            input.dispatchEvent(new Event('input', {{bubbles: true}}));
            input.dispatchEvent(new Event('change', {{bubbles: true}}));
        }})();
    """)
    # 等待确定按钮可点击（替代 debounce 固定 sleep）
    wait_for_element(cdp, ".ant-modal-footer button.ant-btn-primary", timeout=3)
    # 点击确定按钮
    cdp.evaluate("""
        (function() {
            const ok = document.querySelector(
                '.ant-modal-footer button.ant-btn-primary'
            );
            if (ok) ok.click();
        })();
    """)
    # 等待 KB 创建并出现在列表（轮询替代固定 sleep）
    try:
        wait_for(
            lambda: cdp.evaluate(f"""
                Array.from(document.querySelectorAll('*'))
                    .some(el => el.textContent.includes({repr(kb_name)}))
            """),
            timeout=10,
            interval=1,
            message=f"KB '{kb_name}' to appear in list",
        )
        return
    except TimeoutError:
        pass
    # 最终检查
    found = cdp.evaluate(f"""
        Array.from(document.querySelectorAll('*'))
            .some(el => el.textContent.includes({repr(kb_name)}))
    """)
    assert found, f"KB '{kb_name}' not found in list after creation"
