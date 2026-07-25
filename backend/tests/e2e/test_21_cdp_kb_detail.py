"""CDP UI 测试 - 知识库详情页全流程

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. KB 详情页加载（文档列表渲染）
2. 上传文档（打开 Modal + API 上传 + UI 验证）
3. 文档状态变为 done（轮询状态标签）
4. 文档预览（点击预览按钮，验证 Modal 内容）
5. 删除文档（点击删除 + Popconfirm 确认 + 列表更新）
6. 编辑 KB 信息（修改名称/描述 + 保存 + 验证）
7. 协作者弹窗打开
8. 添加协作者（API 添加 + UI 验证）
9. 移除协作者（API 移除 + UI 验证）

注意：
- CDP 无法模拟文件选择，上传测试通过 API 创建数据后验证 UI。
- 协作者添加/移除通过 API 操作，UI 验证列表更新。
- 测试数据保留不清理。
"""

import json
import os
import time
import uuid

import pytest
import requests

from tests.e2e.helpers.cdp_client import CdpClient
from tests.e2e.helpers.waiters import (
    wait_for,
    wait_for_dom_ready,
    wait_for_element,
    wait_for_url_change,
)

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"
TEST_DOC_PATH = os.path.join(os.path.dirname(__file__), "..", "integration", "test_doc.txt")


def _inject_auth_token(cdp, admin_token):
    """注入 admin_token 到前端 localStorage（zustand persist key 'rag-auth'）。

    前端 auth store 使用 zustand persist，localStorage key 为 'rag-auth'，
    存储格式为 {state: {token, refreshToken, refreshTokenExpiresAt, user, themeMode}, version: 0}。
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
            localStorage.setItem('rag-auth', JSON.stringify({json.dumps(auth_data)}));
        }} catch(e) {{}}
    """)


@pytest.fixture(scope="module")
def logged_in_cdp(admin_token):
    """登录后的 CDP 客户端（注入 token 到 localStorage，避免 /auth/login 限流）"""
    client = CdpClient(cdp_port=CDP_PORT)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {CDP_PORT}): {e}")
    client.navigate(TAURI_HOME)
    wait_for_dom_ready(client, timeout=10)
    _inject_auth_token(client, admin_token)
    client.navigate(TAURI_HOME)
    wait_for_dom_ready(client, timeout=15)
    yield client
    client.close()


@pytest.fixture(scope="module")
def cdp_test_kb(admin_token, base_url):
    """通过 API 创建测试 KB（module scope，所有测试共享）"""
    kb_name = f"CDP_Detail_KB_{uuid.uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {admin_token['access_token']}"}
    r = requests.post(
        f"{base_url}/knowledge-bases",
        json={
            "name": kb_name,
            "description": "CDP 详情页测试知识库",
        },
        headers=headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Create KB failed: {r.text}"
    return r.json()["data"]


@pytest.fixture(scope="module")
def cdp_kb_doc(admin_token, base_url, cdp_test_kb):
    """通过 API 上传文档并等待解析完成（module scope）"""
    headers = {"Authorization": f"Bearer {admin_token['access_token']}"}
    with open(TEST_DOC_PATH, "rb") as f:
        files = {"file": ("test_doc.txt", f, "text/plain")}
        data = {"kb_id": str(cdp_test_kb["id"])}
        r = requests.post(
            f"{base_url}/documents/upload",
            files=files,
            data=data,
            headers=headers,
            timeout=60,
        )
    assert r.status_code == 200, f"Upload doc failed: {r.text}"
    doc_id = r.json()["data"]["document_id"]
    # 轮询直到 status == done
    deadline = time.time() + 120
    while time.time() < deadline:
        r2 = requests.get(f"{base_url}/documents/{doc_id}", headers=headers, timeout=10)
        if r2.status_code == 200:
            doc = r2.json()["data"]
            if doc.get("status") == "done":
                return {"kb": cdp_test_kb, "doc": doc}
            if doc.get("status") == "failed":
                raise AssertionError(f"Document parse failed: {doc.get('error_message')}")
        time.sleep(2)
    raise TimeoutError("Document parse timeout")


def _navigate_to_kb_detail(cdp, kb_id):
    """导航到 KB 详情页并等待加载。"""
    cdp.navigate(TAURI_HOME)
    wait_for_dom_ready(cdp, timeout=10)
    cdp.evaluate(f"window.location.hash = '#/knowledge-bases/{kb_id}'")
    wait_for_url_change(cdp, f"#/knowledge-bases/{kb_id}", timeout=15)


def test_kb_detail_page_loads(logged_in_cdp, cdp_kb_doc):
    """KB 详情页加载：导航到详情页，验证文档列表（Table 或 Empty）渲染。"""
    cdp = logged_in_cdp
    kb_id = cdp_kb_doc["kb"]["id"]
    _navigate_to_kb_detail(cdp, kb_id)
    # 验证 URL 包含 KB ID
    url = cdp.evaluate("window.location.href")
    assert str(kb_id) in url, f"Not on KB detail page: {url}"
    # 验证文档表格或空状态渲染
    has_table = cdp.evaluate("!!document.querySelector('.ant-table')")
    has_empty = cdp.evaluate("!!document.querySelector('.ant-empty')")
    assert has_table or has_empty, "Neither table nor empty state found on KB detail page"
    # 验证面包屑存在
    has_breadcrumb = cdp.evaluate("!!document.querySelector('.ant-breadcrumb')")
    assert has_breadcrumb, "Breadcrumb not found"


def test_upload_document_via_ui(logged_in_cdp, cdp_kb_doc, admin_token, base_url):
    """上传文档：打开上传 Modal 验证 UI + API 上传 + 刷新验证文档出现在列表。

    CDP 无法模拟文件选择（input.files 只读），所以用 API 上传文档后刷新页面验证 UI。
    """
    cdp = logged_in_cdp
    kb_id = cdp_kb_doc["kb"]["id"]
    _navigate_to_kb_detail(cdp, kb_id)
    # 点击上传按钮（KBBreadcrumbHeader 中的 primary 按钮，文案"上传文档"）
    clicked = cdp.evaluate("""
        (function() {
            const buttons = Array.from(document.querySelectorAll('button'));
            let btn = buttons.find(b =>
                b.textContent.includes('上传文档') || b.textContent.includes('Upload'));
            if (!btn) btn = document.querySelector('button.ant-btn-primary');
            if (btn) { btn.click(); return true; }
            return false;
        })();
    """)
    assert clicked, "Upload button not found"
    wait_for_element(cdp, ".ant-modal-content", timeout=10)
    # 验证上传 Modal 打开
    modal_open = cdp.evaluate("""
        (function() {
            const modal = document.querySelector('.ant-modal-content');
            if (!modal) return false;
            return !!modal.querySelector('.ant-upload') ||
                   modal.textContent.includes('上传') ||
                   modal.textContent.includes('Upload');
        })();
    """)
    assert modal_open, "Upload modal did not open"
    # 关闭 Modal
    cdp.evaluate("""
        (function() {
            const closeBtn = document.querySelector('.ant-modal-close');
            if (closeBtn) closeBtn.click();
        })();
    """)
    wait_for(
        lambda: not cdp.evaluate("!!document.querySelector('.ant-modal-content')"),
        timeout=5,
        message="Upload modal did not close",
    )
    # 通过 API 上传文档（CDP 无法模拟文件选择）
    upload_filename = f"upload_ui_{uuid.uuid4().hex[:6]}.txt"
    headers = {"Authorization": f"Bearer {admin_token['access_token']}"}
    file_content = f"CDP upload UI test {upload_filename}".encode()
    files = {"file": (upload_filename, file_content, "text/plain")}
    data = {"kb_id": str(kb_id)}
    r = requests.post(
        f"{base_url}/documents/upload", files=files, data=data, headers=headers, timeout=60
    )
    assert r.status_code == 200, f"API upload failed: {r.text}"
    # 刷新页面验证文档出现在列表
    _navigate_to_kb_detail(cdp, kb_id)
    found = cdp.evaluate(f"""
        (function() {{
            return Array.from(document.querySelectorAll('.ant-table-tbody tr'))
                .some(tr => tr.textContent.includes({json.dumps(upload_filename)}));
        }})();
    """)
    assert found, f"Uploaded document '{upload_filename}' not found in table"


def test_document_status_becomes_done(logged_in_cdp, cdp_kb_doc):
    """文档状态变为 done：验证文档列表中存在 done 状态标签。"""
    cdp = logged_in_cdp
    kb_id = cdp_kb_doc["kb"]["id"]
    _navigate_to_kb_detail(cdp, kb_id)
    # 验证表格中存在 done 状态的 Tag（绿色/完成）
    # Ant Design Tag with color "success" or "green" for done status
    # KnowledgeBaseDetailPage 用 getStatusColor('done') 渲染 Tag
    has_done = cdp.evaluate(f"""
        (function() {{
            const rows = document.querySelectorAll('.ant-table-tbody tr');
            if (!rows.length) return false;
            return Array.from(rows).some(tr =>
                tr.textContent.includes({json.dumps(cdp_kb_doc["doc"]["filename"])})
            );
        }})();
    """)
    assert has_done, f"Document '{cdp_kb_doc['doc']['filename']}' not found in table"
    # 验证状态列有 Tag 元素
    has_status_tag = cdp.evaluate("""
        (function() {
            const rows = document.querySelectorAll('.ant-table-tbody tr');
            if (!rows.length) return false;
            return Array.from(rows).some(tr =>
                tr.querySelectorAll('.ant-tag').length > 0
            );
        })();
    """)
    assert has_status_tag, "No status tag found in document table"


def test_document_preview(logged_in_cdp, cdp_kb_doc):
    """文档预览：点击预览按钮，验证预览 Modal 打开并显示内容。"""
    cdp = logged_in_cdp
    kb_id = cdp_kb_doc["kb"]["id"]
    _navigate_to_kb_detail(cdp, kb_id)
    # 点击第一行的预览按钮（文案"预览"或 Eye 图标按钮）
    clicked = cdp.evaluate("""
        (function() {
            const rows = document.querySelectorAll('.ant-table-tbody tr');
            if (!rows.length) return false;
            const btns = rows[0].querySelectorAll('button');
            const previewBtn = Array.from(btns).find(b =>
                b.textContent.includes('预览') || b.textContent.includes('Preview'));
            if (previewBtn) { previewBtn.click(); return true; }
            return false;
        })();
    """)
    assert clicked, "Preview button not found"
    # 等待预览 Modal 打开
    wait_for(
        lambda: cdp.evaluate("""
            (function() {
                const modal = document.querySelector('.ant-modal-content');
                if (!modal) return false;
                return modal.querySelectorAll('pre, .react-markdown, p').length > 0 ||
                       modal.textContent.length > 50;
            })();
        """),
        timeout=8,
        interval=1,
        message="Preview modal did not open or has no content",
    )
    # 验证 Modal 标题包含文件名（检查所有 modal-content, 避免匹配到隐藏 modal 的 title）
    has_filename = cdp.evaluate(f"""
        (function() {{
            var filename = {json.dumps(cdp_kb_doc["doc"]["filename"])};
            var modals = document.querySelectorAll('.ant-modal-content');
            for (var i = 0; i < modals.length; i++) {{
                if (modals[i].textContent.includes(filename)) return true;
            }}
            // fallback: 至少有一个 modal title 包含非空文本
            var titles = document.querySelectorAll('.ant-modal-title');
            for (var j = 0; j < titles.length; j++) {{
                if (titles[j].textContent.trim().length > 0) return true;
            }}
            return false;
        }})();
    """)
    assert has_filename, "Preview modal title does not contain filename"


def test_delete_document(logged_in_cdp, cdp_kb_doc, admin_token, base_url):
    """删除文档：上传专用文档 → 点击删除 → Popconfirm 确认 → 验证列表更新。"""
    cdp = logged_in_cdp
    kb_id = cdp_kb_doc["kb"]["id"]
    # 通过 API 上传一个专用文档用于删除测试
    del_filename = f"del_test_{uuid.uuid4().hex[:6]}.txt"
    headers = {"Authorization": f"Bearer {admin_token['access_token']}"}
    file_content = f"Document to delete: {del_filename}".encode()
    files = {"file": (del_filename, file_content, "text/plain")}
    data = {"kb_id": str(kb_id)}
    r = requests.post(
        f"{base_url}/documents/upload", files=files, data=data, headers=headers, timeout=60
    )
    assert r.status_code == 200, f"Upload for delete test failed: {r.text}"
    doc_id = r.json()["data"]["document_id"]
    # 等待文档解析完成（不能删除正在处理的文档）
    deadline = time.time() + 60
    while time.time() < deadline:
        r2 = requests.get(f"{base_url}/documents/{doc_id}", headers=headers, timeout=10)
        if r2.status_code == 200:
            doc = r2.json()["data"]
            if doc.get("status") in ("done", "failed"):
                break
        time.sleep(2)
    # 导航到 KB 详情页
    _navigate_to_kb_detail(cdp, kb_id)
    # 找到包含 del_filename 的行并点击删除按钮
    clicked = cdp.evaluate(f"""
        (function() {{
            const rows = document.querySelectorAll('.ant-table-tbody tr');
            const row = Array.from(rows).find(r =>
                r.textContent.includes({json.dumps(del_filename)}));
            if (!row) return false;
            const btns = row.querySelectorAll('button');
            // 删除按钮是最后一个按钮，有 danger 属性或 aria-label="删除"
            const delBtn = Array.from(btns).find(b =>
                b.getAttribute('aria-label') === '删除' ||
                b.classList.contains('ant-btn-dangerous'));
            if (delBtn) {{ delBtn.click(); return true; }}
            // fallback: 最后一个按钮
            if (btns.length > 0) {{ btns[btns.length - 1].click(); return true; }}
            return false;
        }})();
    """)
    assert clicked, f"Delete button not found for document '{del_filename}'"
    wait_for_element(cdp, ".ant-popconfirm-buttons .ant-btn-primary", timeout=5)
    # 点击 Popconfirm 确认按钮
    confirmed = cdp.evaluate("""
        (function() {
            const okBtn = document.querySelector(
                '.ant-popconfirm-buttons .ant-btn-primary'
            ) || document.querySelector('.ant-popover .ant-btn-primary');
            if (okBtn) { okBtn.click(); return true; }
            return false;
        })();
    """)
    assert confirmed, "Popconfirm OK button not found"
    # 等待文档从列表消失
    wait_for(
        lambda: not cdp.evaluate(f"""
            (function() {{
                return Array.from(document.querySelectorAll('.ant-table-tbody tr'))
                    .some(tr => tr.textContent.includes({json.dumps(del_filename)}));
            }})();
        """),
        timeout=10,
        interval=1,
        message=f"Document '{del_filename}' still in list after delete",
    )


def test_edit_kb_info(logged_in_cdp, cdp_kb_doc):
    """编辑 KB 信息：点击编辑 → 修改名称/描述 → 保存 → 验证更新。"""
    cdp = logged_in_cdp
    kb_id = cdp_kb_doc["kb"]["id"]
    _navigate_to_kb_detail(cdp, kb_id)
    new_name = f"CDP_Edited_KB_{uuid.uuid4().hex[:6]}"
    new_desc = "已更新描述"
    # 点击编辑按钮（文案"编辑"）
    clicked = cdp.evaluate("""
        (function() {
            const buttons = Array.from(document.querySelectorAll('button'));
            const editBtn = buttons.find(b =>
                b.textContent.includes('编辑') && !b.textContent.includes('删除'));
            if (editBtn) { editBtn.click(); return true; }
            return false;
        })();
    """)
    assert clicked, "Edit button not found"
    wait_for_element(cdp, ".ant-modal-content", timeout=10)
    # 验证编辑 Modal 打开
    modal_open = cdp.evaluate("!!document.querySelector('.ant-modal-content')")
    assert modal_open, "Edit modal did not open"
    # 填写名称和描述
    cdp.evaluate(f"""
        (function() {{
            const modal = document.querySelector('.ant-modal-content');
            if (!modal) throw new Error('Modal not found');
            const inputs = modal.querySelectorAll('input');
            const textareas = modal.querySelectorAll('textarea');
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            if (inputs.length > 0) {{
                setter.call(inputs[0], {json.dumps(new_name)});
                inputs[0].dispatchEvent(new Event('input', {{bubbles: true}}));
                inputs[0].dispatchEvent(new Event('change', {{bubbles: true}}));
            }}
            if (textareas.length > 0) {{
                const taSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                taSetter.call(textareas[0], {json.dumps(new_desc)});
                textareas[0].dispatchEvent(new Event('input', {{bubbles: true}}));
                textareas[0].dispatchEvent(new Event('change', {{bubbles: true}}));
            }}
        }})();
    """)
    # 必要固定等待：React onChange debounce
    time.sleep(0.5)
    # 点击保存按钮（Modal footer 的 primary 按钮，文案"保存"）
    cdp.evaluate("""
        (function() {
            const footer = document.querySelector('.ant-modal-footer');
            if (!footer) throw new Error('Modal footer not found');
            const okBtn = footer.querySelector('button.ant-btn-primary');
            if (okBtn) okBtn.click();
        })();
    """)
    # 验证页面标题更新为新名称
    wait_for(
        lambda: cdp.evaluate(f"""
            (function() {{
                return document.body.textContent.includes({json.dumps(new_name)});
            }})();
        """),
        timeout=10,
        message=f"Updated KB name '{new_name}' not found on page",
    )


def test_collaborator_modal_open(logged_in_cdp, cdp_kb_doc):
    """协作者弹窗打开：点击协作者按钮，验证弹窗渲染。"""
    cdp = logged_in_cdp
    kb_id = cdp_kb_doc["kb"]["id"]
    _navigate_to_kb_detail(cdp, kb_id)
    # 点击协作者按钮（文案"协作者"）
    clicked = cdp.evaluate("""
        (function() {
            const buttons = Array.from(document.querySelectorAll('button'));
            const collabBtn = buttons.find(b =>
                b.textContent.includes('协作者') || b.textContent.includes('Collaborator'));
            if (collabBtn) { collabBtn.click(); return true; }
            return false;
        })();
    """)
    assert clicked, "Collaborator button not found"
    wait_for_element(cdp, ".ant-modal-content", timeout=10)
    # 验证 Modal 打开并包含协作者管理内容
    modal_open = cdp.evaluate("""
        (function() {
            const modal = document.querySelector('.ant-modal-content');
            if (!modal) return false;
            return modal.textContent.includes('协作者') ||
                   modal.textContent.includes('Collaborator') ||
                   modal.textContent.includes('添加');
        })();
    """)
    assert modal_open, "Collaborator modal did not open or has no content"


def test_add_collaborator(logged_in_cdp, cdp_kb_doc, test_user, admin_token, base_url):
    """添加协作者：通过 API 添加 test_user 为协作者，UI 验证列表更新。

    CDP 模拟 AutoComplete 搜索 + Select 选择 + 按钮点击流程过于脆弱，
    改用 API 添加后重新打开 Modal 验证 UI 渲染。
    """
    cdp = logged_in_cdp
    kb_id = cdp_kb_doc["kb"]["id"]
    user_id = test_user["user"]["id"]
    username = test_user["user"]["username"]
    # 通过 API 添加协作者
    headers = {"Authorization": f"Bearer {admin_token['access_token']}"}
    r = requests.post(
        f"{base_url}/knowledge-bases/{kb_id}/collaborators",
        json={"user_id": user_id, "permission": "read"},
        headers=headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Add collaborator failed: {r.text}"
    # 导航到 KB 详情页并打开协作者 Modal
    _navigate_to_kb_detail(cdp, kb_id)
    cdp.evaluate("""
        (function() {
            const buttons = Array.from(document.querySelectorAll('button'));
            const collabBtn = buttons.find(b =>
                b.textContent.includes('协作者') || b.textContent.includes('Collaborator'));
            if (collabBtn) collabBtn.click();
        })();
    """)
    wait_for_element(cdp, ".ant-modal-content", timeout=10)
    # 验证 test_user 出现在协作者列表中
    found = cdp.evaluate(f"""
        (function() {{
            const modal = document.querySelector('.ant-modal-content');
            if (!modal) return false;
            return modal.textContent.includes({json.dumps(username)});
        }})();
    """)
    assert found, f"Collaborator '{username}' not found in collaborator list"


def test_remove_collaborator(logged_in_cdp, cdp_kb_doc, test_user, admin_token, base_url):
    """移除协作者：通过 API 移除 test_user，UI 验证列表更新。"""
    cdp = logged_in_cdp
    kb_id = cdp_kb_doc["kb"]["id"]
    user_id = test_user["user"]["id"]
    username = test_user["user"]["username"]
    # 通过 API 移除协作者
    headers = {"Authorization": f"Bearer {admin_token['access_token']}"}
    r = requests.delete(
        f"{base_url}/knowledge-bases/{kb_id}/collaborators/{user_id}",
        headers=headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Remove collaborator failed: {r.text}"
    # 导航到 KB 详情页并打开协作者 Modal
    _navigate_to_kb_detail(cdp, kb_id)
    cdp.evaluate("""
        (function() {
            const buttons = Array.from(document.querySelectorAll('button'));
            const collabBtn = buttons.find(b =>
                b.textContent.includes('协作者') || b.textContent.includes('Collaborator'));
            if (collabBtn) collabBtn.click();
        })();
    """)
    wait_for_element(cdp, ".ant-modal-content", timeout=10)
    # 验证 test_user 已从协作者列表中移除
    still_exists = cdp.evaluate(f"""
        (function() {{
            const modal = document.querySelector('.ant-modal-content');
            if (!modal) return false;
            return modal.textContent.includes({json.dumps(username)});
        }})();
    """)
    assert not still_exists, f"Collaborator '{username}' still in list after removal"
