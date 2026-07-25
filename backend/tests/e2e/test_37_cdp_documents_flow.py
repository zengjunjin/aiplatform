"""CDP UI 测试 - 文档管理完整流程

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

测试场景：
1. 文档管理页加载（Table + Select(kbFilter) + 刷新按钮）
2. 按知识库筛选（不刷新页面）
3. 状态列 Tag 颜色验证（done=绿/parsing=蓝/failed=红）
4. 重新解析文档（乐观更新：状态变为 parsing）
5. 文档预览（Modal 打开 + 内容，关闭）

精简原则：筛选不刷新页面。
"""

import json
import time
import uuid

import pytest
import requests

from tests.e2e.helpers.cdp_auth import login_cdp_session, make_cdp_client
from tests.e2e.helpers.waiters import (
    wait_for,
    wait_for_element,
    wait_for_url_change,
)

TAURI_HOME = "http://tauri.localhost/"


@pytest.fixture(scope="module")
def logged_in_cdp(admin_token):
    """登录后的 CDP 客户端（导航到 #/documents）"""
    client = make_cdp_client(9223)
    login_cdp_session(client, admin_token, "#/documents")
    yield client
    client.close()


@pytest.fixture(scope="module")
def api_kb_doc(base_url, admin_headers):
    """通过 API 查询已有的 KB + 文档（不依赖 Qdrant 解析到 done）。

    conftest 的 kb_with_doc fixture 会轮询文档 status==done，Qdrant 不可用时
    解析永远不完成导致永久超时。这里改为查询任意状态的文档，仅用于 UI 流程
    验证（筛选/重新解析/预览按钮交互），不依赖解析结果。
    """
    token = admin_headers["Authorization"].split(" ")[1]
    headers = {"Authorization": f"Bearer {token}"}
    # 查询已有 KB
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 1, "page_size": 50},
        headers=headers,
        timeout=10,
    )
    kbs = r.json().get("data", r.json()).get("items", [])
    # 查询每个 KB 的文档，找到第一个含文档的 KB
    for kb in kbs:
        r2 = requests.get(
            f"{base_url}/documents",
            params={"kb_id": kb["id"], "page": 1, "page_size": 50},
            headers=headers,
            timeout=10,
        )
        docs = r2.json().get("data", r2.json()).get("items", [])
        if docs:
            return {"kb": kb, "doc": docs[0]}
    # 无文档：返回第一个 KB 供 filter 测试，doc 相关测试将 skip
    if kbs:
        return {"kb": kbs[0], "doc": None}
    # 无任何 KB：创建一个
    kb_name = f"CDPDoc_KB_{uuid.uuid4().hex[:8]}"
    r3 = requests.post(
        f"{base_url}/knowledge-bases",
        json={"name": kb_name, "description": "CDP 文档流程测试"},
        headers=headers,
        timeout=10,
    )
    kb = r3.json().get("data", r3.json())
    return {"kb": kb, "doc": None}


def _ensure_documents_page(cdp):
    """确保在文档管理页（不重复整页刷新，仅 hash 校正）。"""
    url = cdp.evaluate("window.location.href")
    if "/documents" not in url:
        cdp.evaluate("window.location.hash = '#/documents'")
        wait_for_url_change(cdp, "#/documents", timeout=10)
        wait_for_element(cdp, ".ant-table, .ant-empty, .ant-select", timeout=15)


def test_documents_page_loads(logged_in_cdp):
    """文档管理页加载：验证 Table + Select(kbFilter) + 刷新按钮"""
    cdp = logged_in_cdp
    _ensure_documents_page(cdp)
    url = cdp.evaluate("window.location.href")
    assert "documents" in url.lower(), f"Not on documents page: {url}"
    # 验证文档表格或空状态渲染
    has_table = cdp.evaluate("!!document.querySelector('.ant-table')")
    has_empty = cdp.evaluate("!!document.querySelector('.ant-empty')")
    assert has_table or has_empty, "Neither table nor empty state found"
    # 验证 KB 筛选 Select 存在
    has_select = cdp.evaluate("""
        (function() {
            return document.querySelectorAll('.ant-select').length > 0;
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


def test_filter_by_kb(logged_in_cdp, api_kb_doc, admin_token):
    """按知识库筛选：选择 KB Select，验证列表过滤（不刷新页面）"""
    cdp = logged_in_cdp
    kb_name = api_kb_doc["kb"]["name"]
    # 重新加载文档管理页：触发 KB store 重新 fetchKBs，确保下拉选项包含测试 KB。
    # 同时重新注入 admin token，避免其他测试文件的 CDP 会话污染 localStorage。
    login_cdp_session(cdp, admin_token, "#/documents")
    # 等待 KB Select 渲染（DocumentsPage 只有 1 个 Select: KB 筛选器）
    wait_for_element(cdp, ".ant-select-selector", timeout=10)
    # 用真实鼠标点击打开 Select（JS .click() 不能触发 Ant Design Select 的 onDropdownVisibleChange）
    try:
        cdp.click_element(".ant-select-selector")
    except Exception:
        cdp.evaluate("""
            (function() {
                const select = document.querySelector('.ant-select-selector');
                if (select) select.click();
            })();
        """)
    # 轮询等待下拉选项渲染并选择目标 KB（KB store 异步加载）
    selected = False
    deadline = time.time() + 15
    while time.time() < deadline:
        selected = cdp.evaluate(f"""
            (function() {{
                const options = document.querySelectorAll(
                    '.ant-select-dropdown .ant-select-item'
                );
                const target = Array.from(options).find(opt =>
                    opt.textContent.includes({json.dumps(kb_name)}));
                if (target) {{ target.click(); return true; }}
                return false;
            }})();
        """)
        if selected:
            break
        # 如果下拉未打开，重新点击
        has_dropdown = cdp.evaluate("""
            document.querySelectorAll(
                '.ant-select-dropdown:not(.ant-select-dropdown-hidden)').length > 0
        """)
        if not has_dropdown:
            try:
                cdp.click_element(".ant-select-selector")
            except Exception:
                cdp.evaluate("""
                    (function() {
                        const select = document.querySelector('.ant-select-selector');
                        if (select) select.click();
                    })();
                """)
        time.sleep(0.5)  # 轮询间隔
    assert selected, f"KB option '{kb_name}' not found in dropdown"
    # 等待列表刷新显示筛选结果
    wait_for(
        lambda: cdp.evaluate("!!document.querySelector('.ant-table')"),
        timeout=8,
        interval=0.5,
        message="Table not found after KB filter selection",
    )
    # 验证列表已更新（表格存在）
    has_table = cdp.evaluate("!!document.querySelector('.ant-table')")
    assert has_table, "Table not found after KB filter"
    # 验证筛选后的文档属于选中的 KB
    row_count = cdp.evaluate("""
        (function() {
            return document.querySelectorAll('.ant-table-tbody tr').length;
        })();
    """)
    if row_count and row_count > 0:
        all_match = cdp.evaluate(f"""
            (function() {{
                const rows = document.querySelectorAll('.ant-table-tbody tr');
                return Array.from(rows).every(tr =>
                    tr.textContent.includes({json.dumps(kb_name)})
                );
            }})();
        """)
        assert all_match, "Not all rows match selected KB filter"


def test_document_status_tags(logged_in_cdp):
    """状态列 Tag：验证状态 Tag 颜色（done=绿/parsing=蓝/failed=红）"""
    cdp = logged_in_cdp
    _ensure_documents_page(cdp)
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
    has_done = cdp.evaluate("""
        (function() {
            const rows = document.querySelectorAll('.ant-table-tbody tr');
            if (!rows.length) return false;
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


def test_reparse_document(logged_in_cdp, api_kb_doc):
    """重新解析文档：点击重新解析按钮，验证状态变化（乐观更新）"""
    cdp = logged_in_cdp
    if not api_kb_doc.get("doc"):
        pytest.skip("No existing document available for reparse test")
    doc_filename = api_kb_doc["doc"]["filename"]
    _ensure_documents_page(cdp)
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


def test_preview_document(logged_in_cdp, api_kb_doc):
    """文档预览：点击预览按钮，验证 Modal 打开 + 内容，关闭"""
    cdp = logged_in_cdp
    if not api_kb_doc.get("doc"):
        pytest.skip("No existing document available for preview test")
    doc_filename = api_kb_doc["doc"]["filename"]
    _ensure_documents_page(cdp)
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
    # 关闭 Modal
    cdp.evaluate("""
        (function() {
            const close = document.querySelector('.ant-modal-close');
            if (close) { close.click(); return; }
            const cancel = document.querySelector(
                '.ant-modal-footer button:not(.ant-btn-primary)');
            if (cancel) cancel.click();
        })();
    """)
    # 等待 Modal 关闭
    wait_for(
        lambda: not cdp.evaluate("!!document.querySelector('.ant-modal-content')"),
        timeout=5,
        message="Preview modal did not close",
    )
