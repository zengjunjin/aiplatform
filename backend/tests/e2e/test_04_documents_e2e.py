"""文档上传与解析 E2E 测试

API:
- POST   /documents/upload         -> 上传文档（form: file + kb_id），限流 10/hour
- GET    /documents                -> 列表
- GET    /documents/{id}           -> 详情
- GET    /documents/{id}/progress  -> 进度
- DELETE /documents/{id}           -> 删除（返回 200 + message）
- POST   /documents/{id}/reparse   -> 重新解析，限流 5/hour
- GET    /documents/{id}/preview   -> 预览

文档状态: pending -> parsing -> chunking -> embedding -> done / failed
"""

import time
import uuid

import pytest
import requests

from tests.e2e.conftest import TEST_DOC_PATH, extract_data
from tests.e2e.helpers import config
from tests.e2e.helpers.kb_ops import wait_doc_status


def test_upload_document(base_url, admin_headers):
    """上传文档返回 200 + status=pending"""
    # 先建 KB
    r = requests.post(
        f"{base_url}/knowledge-bases",
        json={"name": "Upload_Test"},
        headers=admin_headers,
        timeout=10,
    )
    kb = extract_data(r)
    try:
        with open(TEST_DOC_PATH, "rb") as f:
            files = {"file": ("test_doc.txt", f, "text/plain")}
            data = {"kb_id": str(kb["id"])}
            r2 = requests.post(
                f"{base_url}/documents/upload",
                files=files,
                data=data,
                headers=admin_headers,
                timeout=60,
            )
        assert r2.status_code == 200, f"Upload failed: {r2.text}"
        doc = extract_data(r2)
        assert doc["status"] in ("pending", "parsing")  # 上传瞬间可能已开始解析
        assert doc["document_id"] > 0
    finally:
        requests.delete(f"{base_url}/knowledge-bases/{kb['id']}", headers=admin_headers, timeout=5)


def test_document_parsed_done(kb_with_doc):
    """文档解析完成"""
    doc = kb_with_doc["doc"]
    assert doc["status"] == "done", f"Expected done, got {doc['status']}"
    assert doc.get("error_message") is None, f"Unexpected error: {doc.get('error_message')}"


def test_get_document_detail(base_url, admin_headers, kb_with_doc):
    """获取文档详情"""
    r = requests.get(
        f"{base_url}/documents/{kb_with_doc['doc']['id']}", headers=admin_headers, timeout=10
    )
    assert r.status_code == 200
    doc = extract_data(r)
    assert doc["id"] == kb_with_doc["doc"]["id"]


def test_get_document_progress(base_url, admin_headers, kb_with_doc):
    """获取文档进度"""
    r = requests.get(
        f"{base_url}/documents/{kb_with_doc['doc']['id']}/progress",
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200
    prog = extract_data(r)
    assert prog["status"] == "done"
    assert prog["progress"] == 100


def test_reparse_document(base_url, admin_headers, kb_with_doc):
    """重新解析文档

    历史 Bug 已修复：document_service.py 使用 .returning() 导致
    SQLAlchemy 2.0 的 ChunkedIteratorResult 没有 rowcount 属性，
    引发 500 AttributeError。已移除 .returning() 子句，使用
    CursorResult.rowcount 判断乐观锁影响行数。
    """
    doc_id = kb_with_doc["doc"]["id"]
    r = requests.post(f"{base_url}/documents/{doc_id}/reparse", headers=admin_headers, timeout=10)
    assert r.status_code == 200, f"Reparse failed: {r.text}"
    # 等待再次完成
    deadline = time.time() + 120
    while time.time() < deadline:
        r2 = requests.get(f"{base_url}/documents/{doc_id}", headers=admin_headers, timeout=10)
        if r2.status_code == 200:
            cur = extract_data(r2)
            if cur.get("status") == "done":
                return
            if cur.get("status") == "failed":
                pytest.fail(f"Reparse failed: {cur.get('error_message')}")
        time.sleep(2)
    pytest.fail("Reparse timeout")


@pytest.fixture(scope="function")
def delete_test_doc(base_url, admin_headers):
    """创建独立 KB + 上传文档并等待解析完成，供删除测试使用。

    function scope 确保每次测试都使用全新数据，消除测试间数据依赖。
    """
    token = admin_headers["Authorization"].split(" ")[1]
    kb_name = f"Delete_Test_KB_{uuid.uuid4().hex[:6]}"
    r_kb = requests.post(
        f"{base_url}/knowledge-bases", json={"name": kb_name}, headers=admin_headers, timeout=10
    )
    assert r_kb.status_code == 200, f"Create KB failed: {r_kb.text}"
    kb = extract_data(r_kb)

    try:
        # 上传文档
        with open(TEST_DOC_PATH, "rb") as f:
            files = {"file": ("test_doc.txt", f, "text/plain")}
            data = {"kb_id": str(kb["id"])}
            r_upload = requests.post(
                f"{base_url}/documents/upload",
                files=files,
                data=data,
                headers=admin_headers,
                timeout=60,
            )
        assert r_upload.status_code == 200, f"Upload failed: {r_upload.text}"
        doc_id = extract_data(r_upload)["document_id"]

        # 等待文档解析完成（parsing/chunking/embedding 状态无法删除，会返回 409）
        status = wait_doc_status(base_url, token, doc_id)
        if status == "timeout":
            raise AssertionError(
                f"Document {doc_id} parse timeout after " f"{config.DOC_WAIT_TIMEOUT}s"
            )
        # done 或 failed 都允许删除测试继续

        yield {"doc_id": doc_id, "kb_id": kb["id"]}
    finally:
        requests.delete(f"{base_url}/knowledge-bases/{kb['id']}", headers=admin_headers, timeout=5)


def test_delete_document(base_url, admin_headers, delete_test_doc):
    """删除文档（返回 200 + message）

    使用 function-scoped fixture 创建独立 KB + 文档，消除测试间数据依赖。
    """
    doc_id = delete_test_doc["doc_id"]
    # 删除文档
    r = requests.delete(f"{base_url}/documents/{doc_id}", headers=admin_headers, timeout=10)
    assert r.status_code == 200, f"Delete failed: {r.text}"
    # 验证已删除（GET 返回 404）
    r2 = requests.get(f"{base_url}/documents/{doc_id}", headers=admin_headers, timeout=10)
    assert r2.status_code == 404


def test_list_documents(base_url, admin_headers, kb_with_doc):
    """列出文档"""
    r = requests.get(
        f"{base_url}/documents",
        params={"kb_id": kb_with_doc["kb"]["id"], "page": 1, "page_size": 10},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200
    data = extract_data(r)
    assert "items" in data
    assert any(d["id"] == kb_with_doc["doc"]["id"] for d in data["items"])
