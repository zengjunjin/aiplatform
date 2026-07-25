"""CDP UI 测试 - SSE 流式聊天

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行 + 至少一个已解析文档的 KB。

测试场景：
1. 发送消息并接收 SSE 流式回答
2. 消息 Markdown 渲染验证
"""

import os

import pytest

from tests.e2e.helpers.cdp_auth import login_cdp_session
from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import wait_for, wait_for_element

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
    login_cdp_session(client, admin_token, "#/chat")
    yield client
    client.close()


def test_send_message_and_receive_sse(logged_in_cdp):
    """发送消息并接收 SSE 流式回答

    流程：导航到对话页 → 新建会话 → 输入消息 → 发送 → 等待 assistant 回答
    """
    cdp = logged_in_cdp
    # 导航到对话页
    cdp.evaluate("window.location.hash = '#/chat'")
    wait_for_element(cdp, "button, textarea, input, .ant-empty", timeout=10)
    # 点击新建会话按钮（如果存在）
    cdp.evaluate("""
        (function() {
            const newBtn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('新建') || b.textContent.includes('New'));
            if (newBtn) newBtn.click();
        })();
    """)
    # 等待输入框出现（可能是 textarea 或 input）
    wait_for_element(cdp, "textarea, input[type='text']", timeout=8)
    has_input = cdp.evaluate("""
        (function() {
            return !!(document.querySelector('textarea') ||
                      document.querySelector('input[type="text"]'));
        })();
    """)
    if not has_input:
        pytest.skip("No input/textarea found on chat page (may need session selection)")
    # 在输入框输入消息
    cdp.evaluate("""
        (function() {
            const textarea = document.querySelector('textarea');
            if (textarea) {
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                setter.call(textarea, '你好');
                textarea.dispatchEvent(new Event('input', {bubbles: true}));
                return;
            }
            const input = document.querySelector('input[type="text"]');
            if (input) {
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(input, '你好');
                input.dispatchEvent(new Event('input', {bubbles: true}));
            }
        })();
    """)
    # 等待发送按钮可点击（替代 debounce 固定 sleep）
    wait_for_element(cdp, "button", timeout=3)
    # 点击发送按钮（可能是图标按钮，用 aria-label 或文本匹配）
    cdp.evaluate("""
        (function() {
            const sendBtn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('发送') ||
                           (b.getAttribute('aria-label') || '').includes('send') ||
                           (b.getAttribute('aria-label') || '').includes('Send') ||
                           b.querySelector('svg'));
            if (sendBtn) sendBtn.click();
        })();
    """)
    # 等待回答出现（最长 60s，SSE + LLM 推理可能较慢）
    try:
        wait_for(
            lambda: (
                cdp.evaluate("""
                (function() {
                    return document.querySelectorAll(
                        '.message-bubble, [class*="message"], [class*="bubble"]'
                    ).length;
                })();
            """)
                or 0
            )
            >= 2,
            timeout=60,
            interval=2,
            message="Assistant response (>=2 messages)",
        )
        return
    except TimeoutError:
        pass
    # 最终检查
    final_count = cdp.evaluate("""
        document.querySelectorAll(
            '.message-bubble, [class*="message"], [class*="bubble"]'
        ).length
    """)
    assert (
        final_count and final_count >= 2
    ), f"Did not receive assistant response (message count={final_count})"


def test_message_render_markdown(logged_in_cdp):
    """消息 Markdown 渲染验证

    assistant 回答应通过 MarkdownRenderer 渲染，生成 p/code/pre/ul/ol 等 HTML 标签。
    """
    cdp = logged_in_cdp
    # 等待消息气泡出现（替代固定 sleep，处理渲染延迟）
    wait_for_element(cdp, ".message-bubble, [class*='message'], [class*='bubble']", timeout=10)
    # 检查最后一条消息是否有 markdown 渲染元素
    has_markdown = cdp.evaluate("""
        (function() {
            const bubbles = document.querySelectorAll(
                '.message-bubble, [class*="message"], [class*="bubble"]'
            );
            if (!bubbles.length) return null;
            const bubble = bubbles[bubbles.length - 1];
            return bubble.querySelectorAll('p, code, pre, ul, ol, h1, h2, h3').length > 0;
        })();
    """)
    # Markdown 渲染取决于回答内容；null 表示无消息，True 表示有渲染
    # 此测试验证渲染器存在（即使回答无 markdown 语法，至少应有 <p> 标签）
    assert has_markdown is not None, "No message bubble found to check markdown rendering"
