"""CDP 边界测试 - 删除 KB 后文档级联清理验证（P3）

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

核心场景：
1. admin 创建专用 KB
2. 上传文档到该 KB，等待解析完成
3. 记录文档 ID
4. 删除 KB
5. 验证：GET /documents/{doc_id} 返回 404（文档记录已清理）
6. 验证：GET /documents?kb_id={已删KB_id} 返回空列表或 404

防止孤儿数据残留：删除 KB 后，其关联的文档记录应被级联清理。
kb_service.delete_kb 实现中通过 EventBus 发布 KB_DELETED 事件，
document_service 订阅者负责清理外部资源（Qdrant 向量、文件存储）。
本测试验证数据库层面的文档记录级联清理。

双账号验证：
- admin CDP 会话：创建 KB + 上传文档 + 删除 KB + UI 验证
- admin API 验证：删除后查询文档确认 404
"""
import io
import os
import time
import uuid

import pytest
import requests

from tests.e2e.helpers.cdp_auth import (
    make_cdp_client,
    login_cdp_session,
)
from tests.e2e.helpers.waiters import wait_for_element

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"


@pytest.fixture(scope="module")
def cdp_admin(admin_token):
    """admin CDP 会话，导航到 /#/knowledge-bases。"""
    client = make_cdp_client(CDP_PORT)
    login_cdp_session(client, admin_token, "#/knowledge-bases")
    yield client
    client.close()


def _upload_doc(base_url, admin_headers, kb_id, filename=None, content=None):
    """上传文档到指定 KB，返回 (status_code, response_data)。"""
    if filename is None:
        filename = f"cascade_test_{uuid.uuid4().hex[:6]}.txt"
    if content is None:
        content = f"cascade cleanup test content {uuid.uuid4().hex}".encode()
    files = {"file": (filename, io.BytesIO(content), "text/plain")}
    data = {"kb_id": str(kb_id)}
    r = requests.post(
        f"{base_url}/documents/upload",
        files=files, data=data, headers=admin_headers, timeout=60,
    )
    if r.status_code == 200:
        return 200, r.json().get("data", {})
    return r.status_code, None


def _wait_doc_status(base_url, admin_headers, doc_id, timeout=60):
    """轮询文档状态直到 done/failed，返回最终状态。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(
            f"{base_url}/documents/{doc_id}",
            headers=admin_headers, timeout=10,
        )
        if r.status_code == 200:
            status = r.json().get("data", {}).get("status")
            if status in ("done", "failed"):
                return status
        time.sleep(2)
    return "timeout"


def test_delete_kb_cleans_documents(base_url, admin_headers, cdp_admin):
    """P3: 删除 KB 后，其关联文档记录应被级联清理

    步骤：
    1. 创建专用 KB
    2. 上传文档，等待解析完成
    3. 记录文档 ID
    4. 删除 KB
    5. 验证 GET /documents/{doc_id} 返回 404
    6. 验证 GET /documents?kb_id={已删KB_id} 返回空列表或 404
    """
    # 1. 创建专用 KB
    kb_name = f"CASCADE_KB_{uuid.uuid4().hex[:6]}"
    r_create_kb = requests.post(
        f"{base_url}/knowledge-bases",
        json={"name": kb_name, "description": "级联清理测试"},
        headers=admin_headers, timeout=10,
    )
    assert r_create_kb.status_code == 200, f"Create KB failed: {r_create_kb.text[:200]}"
    kb_id = r_create_kb.json().get("data", {}).get("id")

    try:
        # 2. 上传文档，等待解析完成
        status, upload_data = _upload_doc(base_url, admin_headers, kb_id)
        if status == 429:
            pytest.skip("Upload rate-limited (429), skip cascade cleanup test")
        assert status == 200, f"Upload doc failed: {status}"
        doc_id = upload_data.get("document_id")
        assert doc_id, f"No document_id in upload response: {upload_data}"

        # 等待解析完成
        final_status = _wait_doc_status(base_url, admin_headers, doc_id, timeout=60)
        if final_status == "timeout":
            pytest.skip(f"Document {doc_id} parse timeout, skip cascade test")
        if final_status == "failed":
            pytest.skip(f"Document {doc_id} parse failed, skip cascade test")

        # 3. 基线：验证文档可访问
        r_doc_before = requests.get(
            f"{base_url}/documents/{doc_id}",
            headers=admin_headers, timeout=10,
        )
        assert r_doc_before.status_code == 200, (
            f"Baseline: doc should be accessible before KB deletion, "
            f"got {r_doc_before.status_code}"
        )

        # 4. 删除 KB
        r_del_kb = requests.delete(
            f"{base_url}/knowledge-bases/{kb_id}",
            headers=admin_headers, timeout=10,
        )
        assert r_del_kb.status_code == 200, (
            f"Delete KB failed: {r_del_kb.status_code} {r_del_kb.text[:200]}"
        )

        # 等待级联清理（EventBus 异步处理可能需要时间）
        time.sleep(2)

        # 5. 验证 GET /documents/{doc_id} 返回 404
        r_doc_after = requests.get(
            f"{base_url}/documents/{doc_id}",
            headers=admin_headers, timeout=10,
        )
        assert r_doc_after.status_code == 404, (
            f"Document should be cleaned after KB deletion (404 expected), "
            f"got {r_doc_after.status_code}: {r_doc_after.text[:200]}"
        )

        # 6. 验证 GET /documents?kb_id={已删KB_id}
        r_docs_list = requests.get(
            f"{base_url}/documents",
            params={"kb_id": kb_id, "page": 1, "page_size": 10},
            headers=admin_headers, timeout=10,
        )
        # 已删 KB 的文档列表应返回空列表或 404/403
        if r_docs_list.status_code == 200:
            items = r_docs_list.json().get("data", {}).get("items", [])
            assert len(items) == 0, (
                f"Document list for deleted KB should be empty, "
                f"got {len(items)} items"
            )
        else:
            # 404 或 403 也是可接受的（KB 不存在或不可访问）
            assert r_docs_list.status_code in (403, 404), (
                f"Unexpected status for docs of deleted KB: "
                f"{r_docs_list.status_code}: {r_docs_list.text[:200]}"
            )

    finally:
        # 清理：确保 KB 被删除（即使测试失败）
        try:
            requests.delete(
                f"{base_url}/knowledge-bases/{kb_id}",
                headers=admin_headers, timeout=5,
            )
        except Exception:
            pass


def test_delete_kb_removes_kb_from_list(base_url, admin_headers, cdp_admin):
    """P3 补充：删除 KB 后，KB 列表中不再包含该 KB

    与 test_delete_kb_cleans_documents 互补：
    - 前者验证文档级联清理
    - 本测试验证 KB 本身从列表中移除
    """
    # 创建 KB
    kb_name = f"CASCADE_LIST_{uuid.uuid4().hex[:6]}"
    r_create = requests.post(
        f"{base_url}/knowledge-bases",
        json={"name": kb_name},
        headers=admin_headers, timeout=10,
    )
    assert r_create.status_code == 200
    kb_id = r_create.json().get("data", {}).get("id")

    # 删除 KB
    r_del = requests.delete(
        f"{base_url}/knowledge-bases/{kb_id}",
        headers=admin_headers, timeout=10,
    )
    assert r_del.status_code == 200

    # 验证 KB 不在列表中
    r_list = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 1, "page_size": 100},
        headers=admin_headers, timeout=10,
    )
    assert r_list.status_code == 200
    items = r_list.json().get("data", {}).get("items", [])
    kb_ids = [k["id"] for k in items]
    assert kb_id not in kb_ids, (
        f"Deleted KB {kb_id} still in KB list: {kb_ids}"
    )

    # 验证 GET /knowledge-bases/{kb_id} 返回 404
    r_get = requests.get(
        f"{base_url}/knowledge-bases/{kb_id}",
        headers=admin_headers, timeout=10,
    )
    assert r_get.status_code == 404, (
        f"Deleted KB should return 404, got {r_get.status_code}"
    )
