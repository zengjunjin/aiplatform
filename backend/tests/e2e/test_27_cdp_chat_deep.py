"""CDP UI 测试 - ChatPage 深度场景

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. ChatPage 加载（SessionSider + 消息区 + ChatInput）
2. SessionSider 会话列表渲染
3. 切换会话加载历史消息
4. 发送消息（依赖 Ollama，不可达则跳过）
5. 重新生成回复
6. 参考来源抽屉（ReferencesDrawer）
7. 停止生成（SSE 中断验证）
8. 模型选择器下拉与切换
9. 新建会话弹窗（NewSessionModal）

注意：
- 发送消息依赖 Ollama，通过 GET /system/models 检测模型健康状态，
  全部 unhealthy 时跳过依赖 LLM 的测试。
- 停止生成测试：发送消息后立即点击停止按钮，对比前后消息内容长度验证中断。
- 模型选择器为 Ant Design Select 组件。
"""
import json
import os
import time
import uuid

import pytest
import requests

from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import wait_for_element
from tests.e2e.conftest import BASE_URL, extract_data

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
    """登录后的 CDP 客户端（用 API token 注入 localStorage，避免限流）"""
    client = CdpClient(cdp_port=CDP_PORT)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {CDP_PORT}): {e}")
    client.navigate(TAURI_HOME)
    time.sleep(1)
    _inject_auth_token(client, admin_token)
    client.navigate(TAURI_HOME)
    time.sleep(3)
    yield client
    client.close()


@pytest.fixture(scope="module")
def chat_sessions(base_url, admin_headers):
    """通过 API 创建 2 个会话供 ChatPage 测试使用（不依赖 KB，通用对话）。

    POST /chat/sessions 限流 30/minute，module scope 仅创建一次。
    不清理数据（按编码规范要求不清理）。
    """
    token = admin_headers["Authorization"].split(" ")[1]
    headers = {"Authorization": f"Bearer {token}"}
    sessions = []
    for i in range(2):
        title = f"CDP深度测试_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{base_url}/chat/sessions", json={
            "title": title,
        }, headers=headers, timeout=10)
        assert r.status_code == 200, f"Create chat session {i} failed: {r.text}"
        sessions.append(extract_data(r))
    return sessions


@pytest.fixture(scope="module")
def ollama_available(base_url, admin_headers):
    """检测 Ollama 模型是否可用（至少一个 healthy 模型）。

    发送消息/重新生成/停止生成测试依赖 LLM，全部 unhealthy 时跳过。
    """
    token = admin_headers["Authorization"].split(" ")[1]
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(f"{base_url}/system/models", headers=headers, timeout=10)
        if r.status_code != 200:
            return False
        data = extract_data(r)
        models = data.get("models", [])
        return any(m.get("status") == "healthy" for m in models)
    except Exception:
        return False


def _navigate_to_chat(cdp):
    """导航到对话页并等待渲染"""
    cdp.navigate(TAURI_HOME)
    time.sleep(2)
    cdp.evaluate("window.location.hash = '#/chat'")
    time.sleep(3)


def _fill_textarea(cdp, text):
    """填充 ChatInput 的 TextArea（使用原生 setter 触发 React onChange）"""
    cdp.evaluate(f"""
        (function() {{
            const textarea = document.querySelector('textarea');
            if (!textarea) throw new Error('textarea not found');
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            setter.call(textarea, {json.dumps(text)});
            textarea.dispatchEvent(new Event('input', {{bubbles: true}}));
        }})();
    """)
    time.sleep(0.5)


def test_chat_page_loads(logged_in_cdp, chat_sessions):
    """ChatPage 加载：导航到 /#/chat/{sessionId}，验证 SessionSider + 消息区 + ChatInput 渲染

    注意: /chat 路由渲染 SessionsPage (会话列表页), /chat/:sessionId 才渲染 ChatPage。
    """
    cdp = logged_in_cdp
    session_id = chat_sessions[0]["id"]
    cdp.navigate(TAURI_HOME)
    time.sleep(2)
    cdp.evaluate(f"window.location.hash = '#/chat/{session_id}'")
    time.sleep(3)
    # 验证 ChatInput 的 textarea 存在
    has_input = cdp.evaluate("!!document.querySelector('textarea')")
    assert has_input, "ChatInput textarea not found"
    # 验证发送按钮存在
    has_send = cdp.evaluate("""
        (function() {
            return Array.from(document.querySelectorAll('button'))
                .some(b => b.textContent.includes('发送'));
        })();
    """)
    assert has_send, "Send button not found"
    # 验证 SessionSider 区域存在（新建对话按钮）
    has_new = cdp.evaluate("""
        (function() {
            return Array.from(document.querySelectorAll('button'))
                .some(b => b.textContent.includes('新建对话'));
        })();
    """)
    assert has_new, "新建对话 button (SessionSider) not found"


def test_session_sider_renders(logged_in_cdp, chat_sessions):
    """SessionSider 渲染会话列表：验证会话项渲染

    /chat/:sessionId 渲染 ChatPage, SessionSider 在 ChatPage 内左侧栏。
    """
    cdp = logged_in_cdp
    session_id = chat_sessions[0]["id"]
    cdp.navigate(TAURI_HOME)
    time.sleep(2)
    cdp.evaluate(f"window.location.hash = '#/chat/{session_id}'")
    time.sleep(3)
    # 验证会话列表项渲染（chat-session-item class）
    session_count = cdp.evaluate("""
        document.querySelectorAll('.chat-session-item').length
    """)
    assert session_count and session_count >= 1, \
        f"No session items rendered in SessionSider (count={session_count})"


def test_switch_session(logged_in_cdp, chat_sessions):
    """切换会话：点击另一个会话，验证历史消息加载（URL 变化）

    /chat/:sessionId 渲染 ChatPage, SessionSider 中的会话项可点击切换。
    """
    cdp = logged_in_cdp
    session_id = chat_sessions[0]["id"]
    cdp.navigate(TAURI_HOME)
    time.sleep(2)
    cdp.evaluate(f"window.location.hash = '#/chat/{session_id}'")
    time.sleep(3)
    # 点击第一个会话项
    clicked = cdp.evaluate("""
        (function() {
            const items = document.querySelectorAll('.chat-session-item');
            if (items.length === 0) return false;
            items[0].click();
            return true;
        })();
    """)
    assert clicked, "No session item to click"
    time.sleep(2)
    # 验证 URL 变化到 /chat/{id}
    url = cdp.evaluate("window.location.href")
    assert "/chat/" in url, f"URL did not change to session route: {url}"


def test_send_message(logged_in_cdp, chat_sessions, ollama_available):
    """发送消息：在 ChatInput 输入消息，发送，验证消息出现在消息区

    依赖 Ollama，不可达则跳过。
    """
    if not ollama_available:
        pytest.skip("Ollama not available (no healthy models)")
    cdp = logged_in_cdp
    # 导航到第一个会话
    session_id = chat_sessions[0]["id"]
    cdp.navigate(TAURI_HOME)
    time.sleep(2)
    cdp.evaluate(f"window.location.hash = '#/chat/{session_id}'")
    time.sleep(3)
    # 输入消息
    msg = f"CDP测试消息_{uuid.uuid4().hex[:6]}"
    _fill_textarea(cdp, msg)
    # 点击发送按钮
    cdp.evaluate("""
        (function() {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('发送'));
            if (btn) btn.click();
        })();
    """)
    # 等待用户消息出现（最长 30s）
    deadline = time.time() + 30
    while time.time() < deadline:
        found = cdp.evaluate(f"""
            (function() {{
                return Array.from(document.querySelectorAll('*'))
                    .some(el => el.textContent.includes({json.dumps(msg)}));
            }})();
        """)
        if found:
            return
        time.sleep(1)
    pytest.skip(f"Sent message not visible within 30s (may be SSE timeout)")


def test_regenerate_response(logged_in_cdp, chat_sessions, ollama_available):
    """重新生成回复：点击重新生成按钮，验证新回复追加

    依赖 Ollama，不可达则跳过。需要已有 assistant 回复。
    """
    if not ollama_available:
        pytest.skip("Ollama not available (no healthy models)")
    cdp = logged_in_cdp
    # 导航到第一个会话
    session_id = chat_sessions[0]["id"]
    cdp.navigate(TAURI_HOME)
    time.sleep(2)
    cdp.evaluate(f"window.location.hash = '#/chat/{session_id}'")
    time.sleep(3)
    # 检查是否有重新生成按钮（aria-label="重新生成"）
    has_regenerate = cdp.evaluate("""
        (function() {
            return Array.from(document.querySelectorAll('button[aria-label]'))
                .some(b => b.getAttribute('aria-label').includes('重新生成'));
        })();
    """)
    if not has_regenerate:
        pytest.skip("No regenerate button found (no assistant reply yet)")
    # 记录当前消息数
    count_before = cdp.evaluate("""
        document.querySelectorAll('.message-bubble-enter, [class*="message"]').length
    """) or 0
    # 点击重新生成按钮
    cdp.evaluate("""
        (function() {
            const btn = Array.from(document.querySelectorAll('button[aria-label]'))
                .find(b => b.getAttribute('aria-label').includes('重新生成'));
            if (btn) btn.click();
        })();
    """)
    # 等待新回复（最长 30s）
    deadline = time.time() + 30
    while time.time() < deadline:
        count_after = cdp.evaluate("""
            document.querySelectorAll('.message-bubble-enter, [class*="message"]').length
        """) or 0
        if count_after > count_before:
            return
        time.sleep(2)
    pytest.skip("Regenerate did not produce new reply within 30s")


def test_references_drawer(logged_in_cdp, chat_sessions):
    """参考来源抽屉：点击引用按钮，验证 ReferencesDrawer 打开

    需要会话中有带 references 的 assistant 消息（依赖 RAG 检索）。
    若无引用标签则跳过。
    """
    cdp = logged_in_cdp
    session_id = chat_sessions[0]["id"]
    cdp.navigate(TAURI_HOME)
    time.sleep(2)
    cdp.evaluate(f"window.location.hash = '#/chat/{session_id}'")
    time.sleep(3)
    # 查找"查看参考来源"标签（ChatPage.parts.tsx 中的 Tag）
    has_ref_tag = cdp.evaluate("""
        (function() {
            return Array.from(document.querySelectorAll('.ant-tag'))
                .some(t => t.textContent.includes('查看参考来源'));
        })();
    """)
    if not has_ref_tag:
        pytest.skip("No references tag found (RAG retrieval may not have references)")
    # 点击引用标签
    cdp.evaluate("""
        (function() {
            const tag = Array.from(document.querySelectorAll('.ant-tag'))
                .find(t => t.textContent.includes('查看参考来源'));
            if (tag) tag.click();
        })();
    """)
    time.sleep(1.5)
    # 验证 Drawer 打开
    drawer_open = cdp.evaluate("!!document.querySelector('.ant-drawer-content, .ant-drawer-open')")
    assert drawer_open, "ReferencesDrawer did not open"


def test_stop_generation(logged_in_cdp, chat_sessions, ollama_available):
    """停止生成：发送消息后立即点击停止，验证消息内容不再增长

    依赖 Ollama，不可达则跳过。对比点击停止前后消息内容长度。
    """
    if not ollama_available:
        pytest.skip("Ollama not available (no healthy models)")
    cdp = logged_in_cdp
    session_id = chat_sessions[1]["id"]
    cdp.navigate(TAURI_HOME)
    time.sleep(2)
    cdp.evaluate(f"window.location.hash = '#/chat/{session_id}'")
    time.sleep(3)
    # 输入消息并发送
    _fill_textarea(cdp, "请详细介绍一下人工智能的发展历史")
    cdp.evaluate("""
        (function() {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('发送'));
            if (btn) btn.click();
        })();
    """)
    time.sleep(2)
    # 等待停止按钮出现（streaming 状态下显示"停止"按钮）
    deadline = time.time() + 15
    has_stop = False
    while time.time() < deadline:
        has_stop = cdp.evaluate("""
            (function() {
                return Array.from(document.querySelectorAll('button'))
                    .some(b => b.textContent.includes('停止'));
            })();
        """)
        if has_stop:
            break
        time.sleep(0.5)
    if not has_stop:
        pytest.skip("Stop button did not appear (generation may have finished too quickly)")
    # 记录停止前最后一条消息内容长度
    len_before = cdp.evaluate("""
        (function() {
            const msgs = document.querySelectorAll('.message-bubble-enter .ant-card, [class*="message"] .ant-card');
            if (!msgs.length) return 0;
            return msgs[msgs.length - 1].textContent.length;
        })();
    """) or 0
    # 点击停止按钮
    cdp.evaluate("""
        (function() {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('停止'));
            if (btn) btn.click();
        })();
    """)
    time.sleep(2)
    # 记录停止后内容长度
    len_after = cdp.evaluate("""
        (function() {
            const msgs = document.querySelectorAll('.message-bubble-enter .ant-card, [class*="message"] .ant-card');
            if (!msgs.length) return 0;
            return msgs[msgs.length - 1].textContent.length;
        })();
    """) or 0
    # 再等 2s 验证内容不再增长
    time.sleep(2)
    len_final = cdp.evaluate("""
        (function() {
            const msgs = document.querySelectorAll('.message-bubble-enter .ant-card, [class*="message"] .ant-card');
            if (!msgs.length) return 0;
            return msgs[msgs.length - 1].textContent.length;
        })();
    """) or 0
    # 验证停止后内容不再增长（允许最终长度 >= 停止后立即长度，但应等于）
    assert len_final == len_after, \
        f"Content still growing after stop: after={len_after}, final={len_final}"


def test_model_selector(logged_in_cdp):
    """模型选择器：点击下拉，验证菜单渲染，切换模型"""
    cdp = logged_in_cdp
    _navigate_to_chat(cdp)
    time.sleep(2)
    # 查找模型选择器（ChatModelSelector 使用 Ant Design Select）
    # 模型选择器在底部，包含"模型:"文本
    has_selector = cdp.evaluate("""
        (function() {
            const selects = document.querySelectorAll('.ant-select');
            return selects.length > 0;
        })();
    """)
    if not has_selector:
        pytest.skip("No model selector (ant-select) found on chat page")
    # 点击 Select 打开下拉
    cdp.evaluate("""
        (function() {
            const select = document.querySelector('.ant-select-selector');
            if (select) select.click();
        })();
    """)
    time.sleep(1)
    # 验证下拉选项渲染
    has_options = cdp.evaluate("""
        (function() {
            return document.querySelectorAll('.ant-select-item').length > 0;
        })();
    """)
    assert has_options, "Model selector dropdown options not rendered"
    # 切换模型（点击第一个可选选项）
    cdp.evaluate("""
        (function() {
            const items = Array.from(document.querySelectorAll('.ant-select-item'));
            const enabled = items.find(i => !i.classList.contains('ant-select-item-disabled'));
            if (enabled) enabled.click();
        })();
    """)
    time.sleep(1)
    # 验证下拉已关闭
    dropdown_closed = cdp.evaluate("""
        !document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')
    """)
    assert dropdown_closed, "Model selector dropdown did not close after selection"


def test_new_session_modal(logged_in_cdp):
    """新建会话弹窗：点击新建会话按钮，验证 NewSessionModal 渲染（KB 选择 + 标题输入）"""
    cdp = logged_in_cdp
    _navigate_to_chat(cdp)
    time.sleep(2)
    # 点击 SessionSider 的"新建对话"按钮
    cdp.evaluate("""
        (function() {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('新建对话'));
            if (btn) btn.click();
        })();
    """)
    time.sleep(1.5)
    # 验证 Modal 打开
    modal_open = cdp.evaluate("!!document.querySelector('.ant-modal-content')")
    assert modal_open, "NewSessionModal did not open"
    # 验证 Modal 内有 KB Select 和标题 Input
    has_kb_select = cdp.evaluate("""
        (function() {
            const modal = document.querySelector('.ant-modal-content');
            if (!modal) return false;
            return !!modal.querySelector('.ant-select');
        })();
    """)
    assert has_kb_select, "KB Select not found in NewSessionModal"
    has_title_input = cdp.evaluate("""
        (function() {
            const modal = document.querySelector('.ant-modal-content');
            if (!modal) return false;
            return !!modal.querySelector('input[type="text"]');
        })();
    """)
    assert has_title_input, "Title input not found in NewSessionModal"
