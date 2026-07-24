"""CDP UI 测试 - 会话列表页

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

注意：SessionsPage 的实际路由是 /#/chat（不是 /#/sessions），/chat/:sessionId 才是聊天页。

测试场景：
1. 会话列表页加载
2. 列表项内容验证（标题/KB/创建时间）
3. 按 KB 验证（SessionsPage 无 KB 筛选器，验证列表项 KB 标签显示）
4. 删除会话（点击删除 → 确认 → 列表更新）
5. 点击会话跳转到聊天页并加载历史消息
"""
import json
import os
import time
import uuid
import pytest
import requests

from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import wait_for_element

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"


def _inject_auth_token(cdp, admin_token):
    """注入 admin_token 到前端 localStorage，避免 WebView 填表登录触发 /auth/login 限流。"""
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
    """登录后的 CDP 客户端（用 API token 注入 localStorage，避免 WebView 填表登录触发限流）

    必须用 Page.reload 触发整页重载，否则 zustand persist 不会重新 rehydrate，
    内存 store 仍是旧状态（修复 auth.ts onRehydrateStorage 后必须 reload）。
    """
    client = CdpClient(cdp_port=CDP_PORT)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {CDP_PORT}): {e}")
    client.navigate(TAURI_HOME)
    time.sleep(1)
    _inject_auth_token(client, admin_token)
    client.send("Page.reload")
    time.sleep(3)
    yield client
    client.close()


@pytest.fixture(scope="module")
def test_session(base_url, admin_headers, kb_with_doc):
    """通过 API 创建一条测试会话，用于列表渲染和点击跳转测试。

    使用 module scope 避免重复创建。测试结束后不清理（用户选择保留数据）。
    """
    token = admin_headers["Authorization"].split(" ")[1]
    headers = {"Authorization": f"Bearer {token}"}
    title = f"CDP会话_{uuid.uuid4().hex[:6]}"
    try:
        r = requests.post(f"{base_url}/chat/sessions", json={
            "title": title,
            "kb_id": kb_with_doc["kb"]["id"],
        }, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        return r.json().get("data", {})
    except Exception:
        return None


@pytest.fixture(scope="function")
def delete_test_session(base_url, admin_headers, kb_with_doc):
    """为删除测试创建专用会话（function scope，每个测试独立会话）。

    测试结束后不清理（已被 UI 删除或保留）。
    """
    token = admin_headers["Authorization"].split(" ")[1]
    headers = {"Authorization": f"Bearer {token}"}
    title = f"CDP删除_{uuid.uuid4().hex[:6]}"
    try:
        r = requests.post(f"{base_url}/chat/sessions", json={
            "title": title,
            "kb_id": kb_with_doc["kb"]["id"],
        }, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        return r.json().get("data", {})
    except Exception:
        return None


def _reset_sessions_page(cdp):
    """重置会话列表页：重新加载并导航到 /#/chat（SessionsPage 路由）"""
    cdp.navigate(TAURI_HOME)
    time.sleep(2)
    cdp.evaluate("window.location.hash = '#/chat'")
    time.sleep(3)


def test_sessions_page_loads(logged_in_cdp, test_session):
    """会话列表页加载：导航到 /#/chat，验证列表渲染（List 或 Empty 空状态）"""
    cdp = logged_in_cdp
    _reset_sessions_page(cdp)
    # SessionsPage 有"新建会话"按钮 + List 或 Empty
    has_content = cdp.evaluate("""
        (function() {
            const buttons = Array.from(document.querySelectorAll('button'));
            const hasNewBtn = buttons.some(b =>
                b.textContent.includes('新建') || b.textContent.includes('New'));
            const hasList = !!document.querySelector('.ant-list');
            const hasEmpty = !!document.querySelector('.ant-empty');
            return hasNewBtn && (hasList || hasEmpty);
        })();
    """)
    assert has_content, "Sessions page did not render new button or list/empty"


def test_session_list_columns(logged_in_cdp, test_session):
    """列表项内容验证：标题/KB 标签/创建时间

    SessionsPage 用 ant List 渲染，每项含 List.Item.Meta（title + description）。
    description 包含 KB Tag 和相对时间。注意：无消息数列。
    """
    cdp = logged_in_cdp
    _reset_sessions_page(cdp)
    time.sleep(2)
    # 验证列表项存在且有 Meta 结构
    list_state = cdp.evaluate("""
        (function() {
            const items = document.querySelectorAll('.ant-list-item');
            if (items.length === 0) return {hasItems: false};
            const firstItem = items[0];
            // List.Item.Meta 包含 title 和 description
            const meta = firstItem.querySelector('.ant-list-item-meta');
            const title = firstItem.querySelector('.ant-list-item-meta-title');
            const desc = firstItem.querySelector('.ant-list-item-meta-description');
            // description 中有 KB Tag
            const tags = firstItem.querySelectorAll('.ant-tag');
            return {
                hasItems: true,
                itemCount: items.length,
                hasMeta: !!meta,
                hasTitle: !!title,
                hasDesc: !!desc,
                tagCount: tags.length
            };
        })();
    """)
    assert list_state is not None, "Failed to evaluate session list"
    if not list_state.get("hasItems"):
        pytest.skip("No session items in list (test_session creation may have failed)")
    assert list_state.get("hasMeta"), "Session item missing List.Item.Meta"
    assert list_state.get("hasTitle"), "Session item missing title"
    assert list_state.get("hasDesc"), "Session item missing description"


def test_filter_by_kb(logged_in_cdp, test_session):
    """按 KB 验证：SessionsPage 无 KB 筛选器，验证列表项中 KB 标签正确显示。

    每个会话项的 description 包含 KB 名称的 Tag。
    """
    cdp = logged_in_cdp
    _reset_sessions_page(cdp)
    time.sleep(2)
    # 验证列表项有 KB Tag
    has_kb_tag = cdp.evaluate("""
        (function() {
            const items = document.querySelectorAll('.ant-list-item');
            if (items.length === 0) return false;
            // 至少一个项有 ant-tag（KB 标签）
            return Array.from(items).some(item => item.querySelector('.ant-tag'));
        })();
    """)
    if not has_kb_tag:
        # 无列表项时验证空状态
        has_empty = cdp.evaluate("!!document.querySelector('.ant-empty')")
        if has_empty:
            pytest.skip("No session items to verify KB tags (empty state)")
    assert has_kb_tag, "Session list items missing KB tags"


def test_delete_session(logged_in_cdp, delete_test_session):
    """删除会话：点击删除按钮 → 确认 → 验证列表更新

    使用专用会话（delete_test_session fixture）避免影响其他测试。
    """
    cdp = logged_in_cdp
    if not delete_test_session:
        pytest.skip("Failed to create test session for deletion")
    session_title = delete_test_session.get("title", "")
    _reset_sessions_page(cdp)
    time.sleep(2)
    # 查找包含目标会话标题的列表项的删除按钮
    found = cdp.evaluate(f"""
        (function() {{
            const items = document.querySelectorAll('.ant-list-item');
            for (var i = 0; i < items.length; i++) {{
                if (items[i].textContent.includes({repr(session_title)})) {{
                    // 找到删除按钮（danger text button with trash icon）
                    var delBtn = items[i].querySelector('button.ant-btn-dangerous, button[aria-label]');
                    if (!delBtn) {{
                        var btns = items[i].querySelectorAll('button');
                        for (var j = 0; j < btns.length; j++) {{
                            if (btns[j].querySelector('svg') || btns[j].classList.contains('ant-btn-dangerous')) {{
                                delBtn = btns[j];
                                break;
                            }}
                        }}
                    }}
                    if (delBtn) {{
                        delBtn.click();
                        return true;
                    }}
                    return false;
                }}
            }}
            return false;
        }})();
    """)
    if not found:
        pytest.skip(f"Could not find delete button for session '{session_title}'")
    time.sleep(1)
    # 轮询等待 Popconfirm 出现并点击确认
    confirmed = False
    deadline = time.time() + 8
    while time.time() < deadline:
        confirmed = cdp.evaluate("""
            (function() {
                // Popconfirm 的确认按钮
                var popBtns = document.querySelectorAll('.ant-popconfirm-buttons button.ant-btn-primary');
                if (popBtns.length > 0) {
                    popBtns[popBtns.length - 1].click();
                    return true;
                }
                // fallback: ant-popover 内的 primary button
                var popoverBtns = document.querySelectorAll('.ant-popover button.ant-btn-primary');
                if (popoverBtns.length > 0) {
                    popoverBtns[popoverBtns.length - 1].click();
                    return true;
                }
                return false;
            })();
        """)
        if confirmed:
            break
        time.sleep(0.5)
    assert confirmed, "Delete confirmation button not found"
    # 等待列表更新（会话被删除）
    time.sleep(3)
    # 验证目标会话从列表中消失
    still_exists = cdp.evaluate(f"""
        (function() {{
            var items = document.querySelectorAll('.ant-list-item');
            return Array.from(items).some(item =>
                item.textContent.includes({repr(session_title)}));
        }})();
    """)
    assert not still_exists, \
        f"Session '{session_title}' still in list after deletion"


def test_click_session_navigate_to_chat(logged_in_cdp, test_session):
    """点击会话跳转：点击会话项 → 跳转到 /#/chat/{sessionId} → 加载历史消息

    SessionsPage 点击 List.Item 会 navigate 到 /chat/{sessionId}（ChatPage）。
    """
    cdp = logged_in_cdp
    if not test_session:
        pytest.skip("No test session available")
    session_id = test_session["id"]
    session_title = test_session.get("title", "")
    _reset_sessions_page(cdp)
    time.sleep(2)
    # 点击目标会话项
    clicked = cdp.evaluate(f"""
        (function() {{
            var items = document.querySelectorAll('.ant-list-item');
            for (var i = 0; i < items.length; i++) {{
                if (items[i].textContent.includes({repr(session_title)})) {{
                    items[i].click();
                    return true;
                }}
            }}
            // fallback: 点击第一个会话项
            if (items.length > 0) {{
                items[0].click();
                return true;
            }}
            return false;
        }})();
    """)
    if not clicked:
        pytest.skip("No session item to click")
    # 等待导航到 ChatPage
    time.sleep(3)
    # 验证 URL 变化（hash 包含 /chat/ + sessionId）
    url_changed = cdp.evaluate(f"""
        (function() {{
            var hash = window.location.hash || '';
            return hash.includes('/chat/') && hash.includes('{session_id}');
        }})();
    """)
    if not url_changed:
        # fallback: 检查是否导航到了任意 chat session 页（非列表页）
        url_changed = cdp.evaluate("""
            (function() {
                var hash = window.location.hash || '';
                // /#/chat 是列表页, /#/chat/123 是聊天页
                return hash.match(/#\\/chat\\/\\d+/) !== null;
            })();
        """)
    assert url_changed, "Did not navigate to chat page after clicking session"
    # 验证 ChatPage 加载（有消息输入框或消息列表）
    chat_loaded = cdp.evaluate("""
        (function() {
            // ChatPage 有 textarea（输入框）或消息内容
            var hasTextarea = !!document.querySelector('textarea');
            var hasMessages = document.querySelectorAll('[class*="message"], [class*="bubble"]').length > 0;
            return hasTextarea || hasMessages;
        })();
    """)
    assert chat_loaded, "Chat page did not load input or messages after navigation"
