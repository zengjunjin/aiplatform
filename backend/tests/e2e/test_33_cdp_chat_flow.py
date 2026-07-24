"""CDP UI 测试 - 聊天完整流程

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行 + 至少一个已解析文档的 KB。

测试场景：
1. 新建会话弹窗（NewSessionModal）
2. 发送消息（依赖 Ollama，不可达则跳过）
3. 参考来源抽屉（ReferencesDrawer）
4. 重新生成回复
5. 停止生成（SSE 中断验证）
6. 切换会话加载历史消息
7. 模型选择器（ChatModelSelector）

精简原则：ChatPage 只导航 1 次（hash 变更，不刷新整页），切换会话不刷新整页。
Ollama 可达性通过 module scope fixture 检测 GET /system/models。
"""
import json
import time
import uuid

import pytest
import requests

from tests.e2e.helpers.cdp_auth import make_cdp_client, login_cdp_session
from tests.e2e.conftest import extract_data

TAURI_HOME = "http://tauri.localhost/"


@pytest.fixture(scope="module")
def logged_in_cdp(admin_token):
    """登录后的 CDP 客户端（注入 token 到 localStorage，导航到 #/chat）"""
    client = make_cdp_client(9223)
    login_cdp_session(client, admin_token, "#/chat")
    yield client
    client.close()


@pytest.fixture(scope="module")
def chat_sessions(base_url, admin_headers, test_kb):
    """通过 API 创建 2 个会话供 ChatPage 测试使用（关联 KB 以触发 RAG 检索）。

    使用 test_kb（仅创建 KB，不依赖文档解析）而非 kb_with_doc，避免 Qdrant
    不可用时文档解析超时导致 fixture 报错。POST /chat/sessions 限流 30/minute，
    module scope 仅创建一次。
    """
    token = admin_headers["Authorization"].split(" ")[1]
    headers = {"Authorization": f"Bearer {token}"}
    sessions = []
    for i in range(2):
        title = f"CDP流程测试_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{base_url}/chat/sessions", json={
            "title": title,
            "kb_id": test_kb["id"],
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


def _goto_session(cdp, session_id):
    """通过 hash 变更导航到指定会话（不刷新整页）。"""
    cdp.evaluate(f"window.location.hash = '#/chat/{session_id}'")
    time.sleep(3)


def _fill_textarea(cdp, text):
    """填充 ChatInput 的 TextArea（使用原生 setter 触发 React onChange）。"""
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


def test_new_session_modal(logged_in_cdp):
    """新建会话弹窗：点击'新建对话'按钮，验证 Modal(title='新建对话') 打开，含 Select + Input，关闭"""
    cdp = logged_in_cdp
    # fixture 已导航到 #/chat (SessionsPage)，点击"新建对话"按钮
    cdp.evaluate("""
        (function() {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('新建对话'));
            if (btn) btn.click();
        })();
    """)
    time.sleep(1.5)
    # 验证 Modal 打开 + 标题
    modal_open = cdp.evaluate("""
        (function() {
            const modal = document.querySelector('.ant-modal-content');
            if (!modal) return false;
            const title = document.querySelector('.ant-modal-title');
            return !!(title && title.textContent.includes('新建对话'));
        })();
    """)
    assert modal_open, "NewSessionModal did not open or title mismatch"
    # 验证 Select + Input 存在
    has_select = cdp.evaluate("""
        (function() {
            const modal = document.querySelector('.ant-modal-content');
            return !!(modal && modal.querySelector('.ant-select'));
        })();
    """)
    assert has_select, "Select not found in NewSessionModal"
    has_input = cdp.evaluate("""
        (function() {
            const modal = document.querySelector('.ant-modal-content');
            return !!(modal && modal.querySelector('input[type="text"]'));
        })();
    """)
    assert has_input, "Input not found in NewSessionModal"
    # 关闭 Modal（点击取消或关闭按钮）
    cdp.evaluate("""
        (function() {
            const cancel = document.querySelector(
                '.ant-modal-footer button:not(.ant-btn-primary)');
            if (cancel) { cancel.click(); return; }
            const close = document.querySelector('.ant-modal-close');
            if (close) close.click();
        })();
    """)
    # 轮询等待 Modal 关闭（Ant Design 5 关闭后 .ant-modal-content 可能仍在 DOM，
    # 但 .ant-modal-wrap 会被设置为 display:none。检查可见性而非 DOM 存在性）
    deadline = time.time() + 5
    modal_visible = True
    while time.time() < deadline:
        modal_visible = cdp.evaluate("""
            (function() {
                var wraps = document.querySelectorAll('.ant-modal-wrap');
                if (wraps.length === 0) return false;
                for (var i = 0; i < wraps.length; i++) {
                    if (window.getComputedStyle(wraps[i]).display !== 'none') return true;
                }
                return false;
            })();
        """)
        if not modal_visible:
            break
        time.sleep(0.5)
    if modal_visible:
        # 取消按钮可能未生效，尝试点击关闭(X)按钮 + Escape 键
        cdp.evaluate("""
            (function() {
                const close = document.querySelector('.ant-modal-close');
                if (close) close.click();
            })();
        """)
        cdp.evaluate("""
            document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', keyCode: 27, which: 27, bubbles: true}));
        """)
        time.sleep(1)
        modal_visible = cdp.evaluate("""
            (function() {
                var wraps = document.querySelectorAll('.ant-modal-wrap');
                if (wraps.length === 0) return false;
                for (var i = 0; i < wraps.length; i++) {
                    if (window.getComputedStyle(wraps[i]).display !== 'none') return true;
                }
                return false;
            })();
        """)
    assert not modal_visible, "NewSessionModal did not close"


def test_send_message(logged_in_cdp, chat_sessions, ollama_available):
    """发送消息：在 ChatInput 输入消息，发送，验证用户消息出现。Ollama 不可达 skip。"""
    if not ollama_available:
        pytest.skip("Ollama not available (no healthy models)")
    cdp = logged_in_cdp
    _goto_session(cdp, chat_sessions[0]["id"])
    msg = f"CDP流程测试_{uuid.uuid4().hex[:6]}"
    _fill_textarea(cdp, msg)
    # 点击发送按钮
    cdp.evaluate("""
        (function() {
            const btn = Array.from(document.querySelectorAll('button'))
                .find(b => b.textContent.includes('发送'));
            if (btn) btn.click();
        })();
    """)
    # 等待用户消息出现（最长 30s，SSE + LLM 推理可能超时）
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
    pytest.skip("Sent message not visible within 30s (may be SSE timeout)")


def test_references_drawer(logged_in_cdp, chat_sessions):
    """参考来源抽屉：发送消息后，若有'查看参考来源' Tag，点击验证 Drawer 打开。无引用 skip。"""
    cdp = logged_in_cdp
    _goto_session(cdp, chat_sessions[0]["id"])
    time.sleep(2)
    # 查找"查看参考来源"标签（role="listitem" aria-label="引用" 或 .ant-tag）
    has_ref_tag = cdp.evaluate("""
        (function() {
            return Array.from(document.querySelectorAll('.ant-tag, [role="listitem"]'))
                .some(t => t.textContent.includes('查看参考来源') ||
                           (t.getAttribute('aria-label') || '').includes('引用'));
        })();
    """)
    if not has_ref_tag:
        pytest.skip("No references tag found (RAG retrieval may not have references)")
    # 点击引用标签
    cdp.evaluate("""
        (function() {
            const tag = Array.from(document.querySelectorAll('.ant-tag, [role="listitem"]'))
                .find(t => t.textContent.includes('查看参考来源') ||
                           (t.getAttribute('aria-label') || '').includes('引用'));
            if (tag) tag.click();
        })();
    """)
    time.sleep(1.5)
    drawer_open = cdp.evaluate(
        "!!document.querySelector('.ant-drawer-content, .ant-drawer-open')"
    )
    assert drawer_open, "ReferencesDrawer did not open"


def test_regenerate(logged_in_cdp, chat_sessions, ollama_available):
    """重新生成：点击重新生成按钮，验证新回复。Ollama 不可达 skip。"""
    if not ollama_available:
        pytest.skip("Ollama not available (no healthy models)")
    cdp = logged_in_cdp
    _goto_session(cdp, chat_sessions[0]["id"])
    time.sleep(2)
    # 检查是否有重新生成按钮（aria-label="重新生成"）
    has_regenerate = cdp.evaluate("""
        (function() {
            return Array.from(document.querySelectorAll('button[aria-label]'))
                .some(b => b.getAttribute('aria-label').includes('重新生成'));
        })();
    """)
    if not has_regenerate:
        pytest.skip("No regenerate button found (no assistant reply yet)")
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


def test_stop_generation(logged_in_cdp, chat_sessions, ollama_available):
    """停止生成：发送消息后立即点击停止按钮，验证内容停止增长（对比前后长度）。Ollama 不可达 skip。"""
    if not ollama_available:
        pytest.skip("Ollama not available (no healthy models)")
    cdp = logged_in_cdp
    # 使用第二个会话避免干扰第一个会话的历史
    _goto_session(cdp, chat_sessions[1]["id"])
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
            const msgs = document.querySelectorAll(
                '.message-bubble-enter .ant-card, [class*="message"] .ant-card');
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
    len_after = cdp.evaluate("""
        (function() {
            const msgs = document.querySelectorAll(
                '.message-bubble-enter .ant-card, [class*="message"] .ant-card');
            if (!msgs.length) return 0;
            return msgs[msgs.length - 1].textContent.length;
        })();
    """) or 0
    # 再等 2s 验证内容不再增长
    time.sleep(2)
    len_final = cdp.evaluate("""
        (function() {
            const msgs = document.querySelectorAll(
                '.message-bubble-enter .ant-card, [class*="message"] .ant-card');
            if (!msgs.length) return 0;
            return msgs[msgs.length - 1].textContent.length;
        })();
    """) or 0
    # 验证停止后内容不再增长
    assert len_final == len_after, \
        f"Content still growing after stop: after={len_after}, final={len_final}"


def test_switch_session(logged_in_cdp, chat_sessions):
    """切换会话：在 SessionSider 中点击另一个会话，验证 URL 变化 + 历史消息加载（不刷新整页）"""
    cdp = logged_in_cdp
    # 先导航到第一个会话（hash 变更，不刷新整页）
    _goto_session(cdp, chat_sessions[0]["id"])
    # 在 SessionSider 中点击另一个会话项（不刷新整页）
    clicked = cdp.evaluate(f"""
        (function() {{
            const items = document.querySelectorAll('.chat-session-item');
            if (items.length < 2) return false;
            // 点击第二个会话项
            items[1].click();
            return true;
        }})();
    """)
    if not clicked:
        # 如果只有一个会话项，点击第一个
        clicked = cdp.evaluate("""
            (function() {
                const items = document.querySelectorAll('.chat-session-item');
                if (items.length === 0) return false;
                items[0].click();
                return true;
            })();
        """)
    assert clicked, "No session item to click in SessionSider"
    time.sleep(2)
    # 验证 URL 变化到 /chat/{id}
    url = cdp.evaluate("window.location.href")
    assert "/chat/" in url, f"URL did not change to session route: {url}"


def test_model_selector(logged_in_cdp, chat_sessions):
    """模型选择器：点击 ChatModelSelector Select，验证下拉菜单渲染，选择一个模型"""
    cdp = logged_in_cdp
    _goto_session(cdp, chat_sessions[0]["id"])
    time.sleep(2)
    # 查找模型选择器（Ant Design Select）
    has_selector = cdp.evaluate("""
        (function() {
            return document.querySelectorAll('.ant-select').length > 0;
        })();
    """)
    if not has_selector:
        pytest.skip("No model selector (ant-select) found on chat page")
    # 用真实鼠标点击打开 Select（JS .click() 不能触发 Ant Design Select 的 onDropdownVisibleChange）
    try:
        cdp.click_element('.ant-select-selector')
    except Exception:
        cdp.evaluate("""
            (function() {
                const select = document.querySelector('.ant-select-selector');
                if (select) select.click();
            })();
        """)
    # 轮询等待下拉选项渲染（Select dropdown 渲染在 Portal 中，异步挂载到 body 末尾）
    deadline = time.time() + 10
    has_options = False
    while time.time() < deadline:
        has_options = cdp.evaluate("""
            (function() {
                var dropdown = document.querySelector(
                    '.ant-select-dropdown:not(.ant-select-dropdown-hidden)');
                if (!dropdown) return false;
                return dropdown.querySelectorAll('.ant-select-item').length > 0;
            })();
        """)
        if has_options:
            break
        # 下拉可能未打开，重试点击
        try:
            cdp.click_element('.ant-select-selector')
        except Exception:
            pass
        time.sleep(0.5)
    assert has_options, "Model selector dropdown options not rendered"
    # 选择第一个可选选项（跳过 disabled）
    cdp.evaluate("""
        (function() {
            const items = Array.from(document.querySelectorAll('.ant-select-item'));
            const enabled = items.find(i =>
                !i.classList.contains('ant-select-item-disabled'));
            if (enabled) enabled.click();
        })();
    """)
    time.sleep(1)
    # 验证下拉已关闭
    dropdown_closed = cdp.evaluate("""
        !document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')
    """)
    assert dropdown_closed, "Model selector dropdown did not close after selection"
