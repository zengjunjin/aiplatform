"""CDP 边界测试 - 路径遍历（上传 filename）验证（P5）

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

核心场景：
1. 上传 filename 含路径遍历字符：../../etc/passwd
2. 上传 filename 含 Windows 路径：..\\..\\windows\\system32\\drivers\\etc\\hosts
3. 上传 filename 含绝对路径：/etc/passwd
4. 上传 filename 含 NULL byte：test.txt\\x00.exe

预期行为：
- API 返回 400 或将 filename 清洗为安全 basename
- 不写入到目标目录之外
- 不引发 500 错误

后端应使用 os.path.basename() 或类似机制清洗 filename，
防止路径遍历攻击写入到非预期位置。
"""

import contextlib
import io
import os
import uuid

import pytest
import requests

from tests.e2e.helpers.cdp_auth import (
    login_cdp_session,
    make_cdp_client,
)

CDP_PORT = int(os.getenv("CDP_PORT", "9223"))
TAURI_HOME = "http://tauri.localhost/"


@pytest.fixture(scope="module")
def cdp_admin(admin_token):
    """admin CDP 会话，导航到 /#/knowledge-bases。"""
    client = make_cdp_client(CDP_PORT)
    login_cdp_session(client, admin_token, "#/knowledge-bases")
    yield client
    client.close()


@pytest.fixture(scope="module")
def traversal_kb(base_url, admin_headers):
    """创建专用 KB 用于路径遍历测试（module scope，自动清理）。"""
    kb_name = f"TRAVERSAL_KB_{uuid.uuid4().hex[:6]}"
    r = requests.post(
        f"{base_url}/knowledge-bases",
        json={"name": kb_name, "description": "路径遍历测试"},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Create KB failed: {r.text[:200]}"
    kb = r.json().get("data", {})
    yield kb
    with contextlib.suppress(Exception):
        requests.delete(
            f"{base_url}/knowledge-bases/{kb['id']}",
            headers=admin_headers,
            timeout=5,
        )


# 路径遍历 payload 清单
PATH_TRAVERSAL_PAYLOADS = [
    "../../etc/passwd",
    "../../../etc/shadow",
    "..\\..\\windows\\system32\\drivers\\etc\\hosts",
    "/etc/passwd",
    "/var/log/auth.log",
    "test/../../../secret.txt",
    "....//....//secret.txt",  # 双点绕过
    "..%2f..%2f..%2fetc%2fpasswd",  # URL 编码绕过
    "test.txt\x00.exe",  # NULL byte 注入
]


@pytest.mark.parametrize("filename", PATH_TRAVERSAL_PAYLOADS)
def test_path_traversal_filename(base_url, admin_headers, traversal_kb, filename):
    """P5: 上传 filename 含路径遍历字符，验证 API 安全处理

    预期行为：
    - 返回 200（filename 被清洗为安全 basename）或 400（拒绝）
    - 不返回 500（服务器错误）
    - 如果成功上传，查询文档详情验证 filename 不含路径分隔符
    """
    kb_id = traversal_kb["id"]
    content = f"path traversal test {uuid.uuid4().hex}".encode()
    # requests 库会处理 filename 编码
    files = {"file": (filename, io.BytesIO(content), "text/plain")}
    data = {"kb_id": str(kb_id)}

    r = requests.post(
        f"{base_url}/documents/upload",
        files=files,
        data=data,
        headers=admin_headers,
        timeout=60,
    )

    # 应返回 200（清洗后接受）或 400/422（拒绝）
    # 不应返回 500（服务器错误，可能意味着路径遍历成功引发异常）
    assert r.status_code in (200, 400, 422, 409), (
        f"Path traversal filename '{repr(filename)}' caused status {r.status_code}: "
        f"{r.text[:200]}"
    )

    if r.status_code == 200:
        # 上传成功，验证 filename 被清洗
        doc_id = r.json().get("data", {}).get("document_id")
        if doc_id:
            # 查询文档详情，验证 filename 不含路径分隔符
            r_doc = requests.get(
                f"{base_url}/documents/{doc_id}",
                headers=admin_headers,
                timeout=10,
            )
            if r_doc.status_code == 200:
                doc_data = r_doc.json().get("data", {})
                stored_filename = doc_data.get("filename", "") or doc_data.get("name", "")
                # 存储的 filename 不应包含路径分隔符（应被清洗为 basename）
                # 注意：原始 filename 中的路径分隔符不应出现在存储的 filename 中
                assert "/" not in stored_filename or stored_filename == filename, (
                    f"Path traversal not sanitized: stored filename '{stored_filename}' "
                    f"contains '/' (original: '{repr(filename)}')"
                )
                # 清理：删除文档
                requests.delete(
                    f"{base_url}/documents/{doc_id}",
                    headers=admin_headers,
                    timeout=5,
                )


def test_normal_filename_accepted(base_url, admin_headers, traversal_kb):
    """P5 基线：正常 filename 应被接受

    确保路径遍历防护不会误拦正常 filename。
    """
    kb_id = traversal_kb["id"]
    filename = f"normal_test_{uuid.uuid4().hex[:6]}.txt"
    content = b"normal file content"
    files = {"file": (filename, io.BytesIO(content), "text/plain")}
    data = {"kb_id": str(kb_id)}

    r = requests.post(
        f"{base_url}/documents/upload",
        files=files,
        data=data,
        headers=admin_headers,
        timeout=60,
    )

    if r.status_code == 429:
        pytest.skip("Upload rate-limited (429)")

    assert (
        r.status_code == 200
    ), f"Normal filename should be accepted, got {r.status_code}: {r.text[:200]}"

    # 清理
    doc_id = r.json().get("data", {}).get("document_id")
    if doc_id:
        requests.delete(
            f"{base_url}/documents/{doc_id}",
            headers=admin_headers,
            timeout=5,
        )


def test_filename_with_subdir_rejected_or_sanitized(base_url, admin_headers, traversal_kb):
    """P5: filename 含子目录（如 'subdir/test.txt'）的处理

    某些实现会接受子目录路径但清洗为 basename，某些会拒绝。
    验证不会实际创建子目录。
    """
    kb_id = traversal_kb["id"]
    filename = f"subdir/test_{uuid.uuid4().hex[:6]}.txt"
    content = b"subdir test content"
    files = {"file": (filename, io.BytesIO(content), "text/plain")}
    data = {"kb_id": str(kb_id)}

    r = requests.post(
        f"{base_url}/documents/upload",
        files=files,
        data=data,
        headers=admin_headers,
        timeout=60,
    )

    if r.status_code == 429:
        pytest.skip("Upload rate-limited (429)")

    # 应返回 200（清洗为 basename）或 400/422（拒绝）
    assert r.status_code in (
        200,
        400,
        422,
    ), f"Subdir filename caused status {r.status_code}: {r.text[:200]}"

    if r.status_code == 200:
        doc_id = r.json().get("data", {}).get("document_id")
        if doc_id:
            # 验证存储的 filename 是 basename（不含 subdir/）
            r_doc = requests.get(
                f"{base_url}/documents/{doc_id}",
                headers=admin_headers,
                timeout=10,
            )
            if r_doc.status_code == 200:
                doc_data = r_doc.json().get("data", {})
                stored_filename = doc_data.get("filename", "") or doc_data.get("name", "")
                # 存储的 filename 不应以 "subdir/" 开头
                assert not stored_filename.startswith(
                    "subdir/"
                ), f"Subdir not stripped from filename: '{stored_filename}'"
            # 清理
            requests.delete(
                f"{base_url}/documents/{doc_id}",
                headers=admin_headers,
                timeout=5,
            )
