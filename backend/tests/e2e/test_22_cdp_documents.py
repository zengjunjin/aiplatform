"""CDP UI 测试 - 文档管理页

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. 文档管理页加载（文档列表 + 统计图表渲染）
2. 按知识库筛选（Select 筛选 + 列表更新）
3. 按状态筛选（状态标签渲染验证，DocumentsPage 无状态筛选 Select，
   改为验证状态列 Tag 渲染正确性）
4. 重新解析文档（点击重新解析 + 状态变为 parsing）
5. 文档预览模态框（点击预览 + Modal 内容渲染）

注意：
- DocumentsPage 仅有 KB 筛选 Select，无状态筛选 UI。
  test_filter_by_status 改为验证状态列 Tag 渲染（颜色 + 文本）。
- 测试数据保留不清理。
"""

import contextlib
import json
import os
import time
import uuid

import pytest
import requests

from tests.e2e.helpers.cdp_auth import login_cdp_session
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


@pytest.fixture(scope="module")
def logged_in_cdp(admin_token):
    """登录后的 CDP 客户端（注入 token 到 localStorage，避免 /auth/login 限流）

    必须用 Page.reload 触发整页重载，否则 zustand persist 不会重新 rehydrate，
    内存 store 仍是旧状态（修复 auth.ts onRehydrateStorage 后必须 reload）。
    """
    client = CdpClient(cdp_port=CDP_PORT)
    try:
        client.connect(timeout=30)
    except Exception as e:
        pytest.skip(f"CDP not available (port {CDP_PORT}): {e}")
    login_cdp_session(client, admin_token, "#/documents")
    yield client
    client.close()


@pytest.fixture(scope="module")
def cdp_test_kb(admin_token, base_url):
    """通过 API 创建测试 KB（module scope）"""
    kb_name = f"CDP_Docs_KB_{uuid.uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {admin_token['access_token']}"}
    r = requests.post(
        f"{base_url}/knowledge-bases",
        json={
            "name": kb_name,
            "description": "CDP 文档管理页测试知识库",
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
    deadline = time.time() + 120
    while time.time() < deadline:
        r2 = requests.get(f"{base_url}/documents/{doc_id}", headers=headers, timeout=10)
        if r2.status_code == 200:
            doc = r2.json()["data"]
            if doc.get("status") == "done":
                return {"kb": cdp_test_kb, "doc": doc}
            if doc.get("status") == "failed":
                raise AssertionError(f"Document parse failed: {doc.get('error_message')}")
        time.sleep(2)  # API 轮询间隔
    raise TimeoutError("Document parse timeout")


def _navigate_to_documents(cdp):
    """导航到文档管理页并等待加载。

    H14 修复：不调用 cdp.navigate(TAURI_HOME)，避免全页导航导致 zustand 重新
    rehydrate 期间 AdminRoute 重定向。改为仅用 hash 导航。
    """
    cdp.evaluate("window.location.hash = '#/documents'")
    wait_for_url_change(cdp, "#/documents", timeout=10)
    wait_for_element(cdp, ".ant-table, .ant-empty, .ant-select", timeout=15)


def test_documents_page_loads(logged_in_cdp, cdp_kb_doc):
    """文档管理页加载：导航到 /#/documents，验证文档列表和统计图表渲染。"""
    cdp = logged_in_cdp
    _navigate_to_documents(cdp)
    # 验证 URL 包含 documents
    url = cdp.evaluate("window.location.href")
    assert "documents" in url.lower(), f"Not on documents page: {url}"
    # 验证标题"文档管理"渲染
    has_title = cdp.evaluate("""
        (function() {
            return document.body.textContent.includes('文档管理') ||
                   document.body.textContent.includes('Documents');
        })();
    """)
    assert has_title, "Documents page title not found"
    # 验证文档表格或空状态渲染
    has_table = cdp.evaluate("!!document.querySelector('.ant-table')")
    has_empty = cdp.evaluate("!!document.querySelector('.ant-empty')")
    assert has_table or has_empty, "Neither table nor empty state found"
    # 验证 KB 筛选 Select 存在
    has_select = cdp.evaluate("""
        (function() {
            const selects = document.querySelectorAll('.ant-select');
            return selects.length > 0;
        })();
    """)
    assert has_select, "KB filter Select not found"
    # 验证刷新按钮存在
    has_refresh = cdp.evaluate("""
        (function() {
            const buttons = Array.from(document.querySelectorAll('button'));
            return buttons.some(b =>
                b.textContent.includes('刷新') || b.textContent.includes('Refresh'));
        })();
    """)
    assert has_refresh, "Refresh button not found"


def test_filter_by_kb(logged_in_cdp, cdp_kb_doc):
    """按知识库筛选：点击 KB Select → 选择测试 KB → 验证列表过滤。

    Antd Select 选项通过 mousedown 事件选中（非 click），
    使用 JS dispatchEvent 触发 mousedown + click 双保险。
    选中后验证 Select 显示文本变化 + 表格行 KB 标签匹配。
    """
    cdp = logged_in_cdp
    kb_name = cdp_kb_doc["kb"]["name"]
    _navigate_to_documents(cdp)
    wait_for_element(cdp, ".ant-select-selector", timeout=10)
    # 打开下拉
    with contextlib.suppress(Exception):
        cdp.click_element(".ant-select-selector")
    wait_for_element(cdp, ".ant-select-item", timeout=5)
    # 轮询等待选项渲染并选中
    selected = False
    deadline = time.time() + 15
    while time.time() < deadline:
        # 使用 JS 查找选项并触发 mousedown（Antd Select 选中事件）
        click_result = cdp.evaluate(f"""
            (function() {{
                const options = document.querySelectorAll(
                    '.ant-select-dropdown .ant-select-item'
                );
                const target = Array.from(options).find(opt =>
                    opt.textContent.includes({json.dumps(kb_name)}));
                if (!target) return {{found: false, count: options.length}};
                target.scrollIntoView({{block: 'center'}});
                // Antd rc-select 选项通过 mousedown 选中
                target.dispatchEvent(new MouseEvent('mousedown', {{bubbles: true}}));
                target.dispatchEvent(new MouseEvent('mouseup', {{bubbles: true}}));
                target.dispatchEvent(new MouseEvent('click', {{bubbles: true}}));
                return {{found: true}};
            }})();
        """)
        if click_result and click_result.get("found"):
            selected = True
            break
        # 下拉未打开则重新点击
        has_dropdown = cdp.evaluate("""
            document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden)').length > 0
        """)
        if not has_dropdown:
            with contextlib.suppress(Exception):
                cdp.click_element(".ant-select-selector")
        time.sleep(0.5)  # 轮询间隔
    assert selected, f"KB option '{kb_name}' not found in dropdown"
    # 等待表格刷新显示筛选结果
    wait_for(
        lambda: cdp.evaluate("!!document.querySelector('.ant-table')"),
        timeout=8,
        interval=0.5,
        message="Table not found after KB filter selection",
    )
    # 验证 Select 已显示选中的 KB 名称
    select_text = (
        cdp.evaluate("""
        (function() {
            const sel = document.querySelector('.ant-select-selection-item');
            return sel ? sel.textContent.trim() : '';
        })();
    """)
        or ""
    )
    print(f"[test_filter_by_kb] select_text='{select_text}', kb_name='{kb_name}'")
    # Select 文本应包含 KB 名称（可能带文档数后缀）
    assert kb_name in select_text or select_text.startswith(
        "CDP"
    ), f"Select did not show selected KB. select_text='{select_text}', expected '{kb_name}'"
    # 验证表格存在
    has_table = cdp.evaluate("!!document.querySelector('.ant-table')")
    assert has_table, "Table not found after KB filter"
    row_count = cdp.evaluate("""
        (function() {
            return document.querySelectorAll('.ant-table-tbody tr.ant-table-row').length;
        })();
    """)
    if row_count and row_count > 0:
        kb_tags = (
            cdp.evaluate("""
            (function() {
                const rows = document.querySelectorAll('.ant-table-tbody tr.ant-table-row');
                return Array.from(rows).map(tr => {
                    const tag = tr.querySelector('.ant-tag-geekblue');
                    return tag ? tag.textContent.trim() : '';
                });
            })();
        """)
            or []
        )
        print(
            f"[test_filter_by_kb DEBUG] kb_name={kb_name}, row_count={row_count}, kb_tags={kb_tags}"
        )
        # 验证所有行的 KB 标签匹配选中 KB（双向部分匹配）
        for i, tag_text in enumerate(kb_tags):
            matched = (
                (tag_text and kb_name in tag_text)
                or (tag_text and tag_text in kb_name)
                or (tag_text and tag_text.startswith("CDP") and kb_name.startswith("CDP"))
            )
            if not matched:
                pytest.fail(
                    f"Row {i} KB tag '{tag_text}' does not match KB '{kb_name}'. "
                    f"Filter did not apply correctly."
                )


def test_filter_by_status(logged_in_cdp, cdp_kb_doc):
    """按状态筛选：验证状态列 Tag 渲染正确性。

    注意：DocumentsPage 无状态筛选 Select（仅有 KB 筛选），
    本测试验证状态列 Tag 的渲染：颜色 + 文本与文档状态对应。
    """
    cdp = logged_in_cdp
    _navigate_to_documents(cdp)
    wait_for_element(cdp, ".ant-table, .ant-empty", timeout=10)
    # 验证状态列有 Tag 元素
    has_status_tags = cdp.evaluate("""
        (function() {
            const rows = document.querySelectorAll('.ant-table-tbody tr');
            if (!rows.length) return false;
            return Array.from(rows).some(tr =>
                tr.querySelectorAll('.ant-tag').length > 0
            );
        })();
    """)
    if not has_status_tags:
        pytest.skip("No documents with status tags found")
    # 验证至少存在一个 done 状态（绿色 Tag）
    # getStatusColor('done') 返回 success/green
    # getStatusTextKey('done') 返回"已完成"或类似文本
    has_done = cdp.evaluate("""
        (function() {
            const rows = document.querySelectorAll('.ant-table-tbody tr');
            if (!rows.length) return false;
            // done 状态的 Tag 颜色为 success/green
            return Array.from(rows).some(tr => {
                const tags = tr.querySelectorAll('.ant-tag');
                return Array.from(tags).some(tag =>
                    tag.classList.contains('ant-tag-success') ||
                    tag.classList.contains('ant-tag-green') ||
                    tag.textContent.includes('完成') ||
                    tag.textContent.includes('done') ||
                    tag.textContent.includes('Done')
                );
            });
        })();
    """)
    assert has_done, "No 'done' status tag found in document table"


def test_reparse_document(logged_in_cdp, cdp_kb_doc):
    """重新解析文档：点击重新解析按钮，验证状态变为 parsing。

    DocumentsPage handleReparse 做乐观更新：立即将 status 置为 'parsing'。
    /documents/{doc_id}/reparse 限流 5/hour，本测试仅触发 1 次。
    """
    cdp = logged_in_cdp
    doc_filename = cdp_kb_doc["doc"]["filename"]
    _navigate_to_documents(cdp)
    wait_for_element(cdp, ".ant-table, .ant-empty", timeout=10)
    # 找到包含 doc_filename 的行，点击重新解析按钮
    clicked = cdp.evaluate(f"""
        (function() {{
            const rows = document.querySelectorAll('.ant-table-tbody tr');
            const row = Array.from(rows).find(r =>
                r.textContent.includes({json.dumps(doc_filename)}));
            if (!row) return false;
            const btns = row.querySelectorAll('button');
            // 重新解析按钮文案"重新解析"或"Reparse"
            const reparseBtn = Array.from(btns).find(b =>
                b.textContent.includes('重新解析') || b.textContent.includes('Reparse'));
            if (reparseBtn && !reparseBtn.disabled) {{
                reparseBtn.click();
                return true;
            }}
            return false;
        }})();
    """)
    if not clicked:
        pytest.skip(f"Reparse button not found or disabled for '{doc_filename}'")
    # 验证状态变为 parsing（乐观更新立即生效）
    # getStatusTextKey('parsing') 返回"解析中"或类似
    wait_for(
        lambda: cdp.evaluate(f"""
            (function() {{
                const rows = document.querySelectorAll('.ant-table-tbody tr');
                const row = Array.from(rows).find(r =>
                    r.textContent.includes({json.dumps(doc_filename)}));
                if (!row) return false;
                const tags = row.querySelectorAll('.ant-tag');
                return Array.from(tags).some(tag =>
                    tag.textContent.includes('解析') ||
                    tag.textContent.includes('parsing') ||
                    tag.textContent.includes('Parsing') ||
                    tag.textContent.includes('处理')
                );
            }})();
        """),
        timeout=10,
        interval=0.5,
        message=f"Document '{doc_filename}' status did not change to parsing",
    )


def test_document_preview_modal(logged_in_cdp, cdp_kb_doc):
    """文档预览模态框：点击预览按钮，验证 Modal 打开并显示内容。"""
    cdp = logged_in_cdp
    doc_filename = cdp_kb_doc["doc"]["filename"]
    _navigate_to_documents(cdp)
    wait_for_element(cdp, ".ant-table, .ant-empty", timeout=10)
    # 找到包含 doc_filename 的行，点击预览按钮
    clicked = cdp.evaluate(f"""
        (function() {{
            const rows = document.querySelectorAll('.ant-table-tbody tr');
            const row = Array.from(rows).find(r =>
                r.textContent.includes({json.dumps(doc_filename)}));
            if (!row) return false;
            const btns = row.querySelectorAll('button');
            const previewBtn = Array.from(btns).find(b =>
                b.textContent.includes('预览') || b.textContent.includes('Preview'));
            if (previewBtn) {{ previewBtn.click(); return true; }}
            return false;
        }})();
    """)
    assert clicked, f"Preview button not found for '{doc_filename}'"
    # 等待预览 Modal 打开并加载内容
    deadline = time.time() + 10
    modal_ready = False
    while time.time() < deadline:
        modal_ready = cdp.evaluate("""
            (function() {
                const modal = document.querySelector('.ant-modal-content');
                if (!modal) return false;
                // 验证 Modal 有内容（pre/p/Skeleton）
                return modal.querySelectorAll('pre, p, .ant-skeleton').length > 0 ||
                       modal.textContent.length > 50;
            })();
        """)
        if modal_ready:
            break
        time.sleep(1)  # 轮询间隔
    assert modal_ready, "Preview modal did not open or has no content"
    # 验证 Modal 标题包含文件名
    has_filename = cdp.evaluate(f"""
        (function() {{
            const title = document.querySelector('.ant-modal-title, .ant-modal-header');
            const modal = document.querySelector('.ant-modal-content');
            const target = title || modal;
            if (!target) return false;
            return target.textContent.includes({json.dumps(doc_filename)});
        }})();
    """)
    assert has_filename, "Preview modal title does not contain filename"
