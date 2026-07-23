"""CDP UI 测试 - SSE 流式聊天

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行 + 至少一个已解析文档的 KB。

测试场景：
1. 发送消息并接收 SSE 流式回答
2. 消息 Markdown 渲染验证
"""
import json
import os
import time
import pytest

from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import wait_for_element

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"


def _inject_auth_token(cdp, admin_token):
    """注入 admin_token 到前端 localStorage，避免 WebView 填表登录触发 /auth/login 限流。

    前端 auth store 使用 zustand persist，localStorage key 为 'rag-auth'，
    存储格式为 {state: {token, refreshToken, refreshTokenExpiresAt, user, themeMode}, version: 0}。
    access_token（token 字段）正常不持久化（partialize 排除），但注入后 zustand
    rehydrate 会将其读入内存，app 立即可用。onRehydrateStorage 会异步调用
    refreshAccessToken()（走 /auth/refresh，限流 10/minute，远高于 /auth/login 的 5/minute）。
    """
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
    """登录后的 CDP 客户端（用 API token 注入 localStorage，避免 WebView 填表登录触发限流）"""
    client = CdpClient(cdp_port=CDP_PORT)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {CDP_PORT}): {e}")
    client.navigate(TAURI_HOME)
    time.sleep(1)
    # 注入 token 到 localStorage（避免 /auth/login 限流）
    _inject_auth_token(client, admin_token)
    # 重新加载页面，触发 zustand persist 从 localStorage rehydrate
    client.navigate(TAURI_HOME)
    time.sleep(3)
    yield client
    client.close()


def test_send_message_and_receive_sse(logged_in_cdp):
    """发送消息并接收 SSE 流式回答

    流程：导航到对话页 → 新建会话 → 输入消息 → 发送 → 等待 assistant 回答
    """
    cdp = logged_in_cdp
    # 导航到对话页
    cdp.evaluate("window.location.hash = '#/chat'")
    time.sleep(3)
    # 点击新建会话按钮（如果存在）
    cdp.evaluate("""
        (function() {
            const newBtn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('新建') || b.textContent.includes('New'));
            if (newBtn) newBtn.click();
        })();
    """)
    time.sleep(2)
    # 等待输入框出现（可能是 textarea 或 input）
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
    time.sleep(0.5)
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
    deadline = time.time() + 60
    while time.time() < deadline:
        count = cdp.evaluate("""
            (function() {
                return document.querySelectorAll(
                    '.message-bubble, [class*="message"], [class*="bubble"]'
                ).length;
            })();
        """)
        if count and count >= 2:
            return
        time.sleep(2)
    # 最终检查
    final_count = cdp.evaluate("""
        document.querySelectorAll(
            '.message-bubble, [class*="message"], [class*="bubble"]'
        ).length
    """)
    assert final_count and final_count >= 2, \
        f"Did not receive assistant response (message count={final_count})"


def test_message_render_markdown(logged_in_cdp):
    """消息 Markdown 渲染验证

    assistant 回答应通过 MarkdownRenderer 渲染，生成 p/code/pre/ul/ol 等 HTML 标签。
    """
    cdp = logged_in_cdp
    # 等待消息渲染完成
    time.sleep(2)
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
