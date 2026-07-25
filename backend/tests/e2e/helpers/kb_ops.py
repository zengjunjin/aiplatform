"""KB 操作共用 helper

统一协作者管理、文档上传、文档状态轮询的实现。
消除 test_32/test_43/test_47/conftest 中 4 处重复定义。
"""

import io
import uuid

import requests

from tests.e2e.helpers import config
from tests.e2e.helpers.waiters import wait_for


def set_collaborator(
    base_url: str, admin_headers: dict, kb_id: int, user_id: int, permission: str
) -> dict:
    """admin 设置/升级协作者权限（POST upsert 语义）。

    Args:
        base_url: API base URL
        admin_headers: admin 的 Authorization headers
        kb_id: 知识库 ID
        user_id: 被授权用户 ID
        permission: read / write / admin

    Returns:
        响应 JSON 的 data 字段

    Raises:
        AssertionError: 状态码非 200
    """
    r = requests.post(
        f"{base_url}/knowledge-bases/{kb_id}/collaborators",
        json={"user_id": user_id, "permission": permission},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, (
        f"Set collaborator ({permission}) failed: " f"{r.status_code} {r.text[:200]}"
    )
    return r.json().get("data", {})


def remove_collaborator(base_url: str, headers: dict, kb_id: int, user_id: int) -> int:
    """移除协作者，返回状态码。"""
    r = requests.delete(
        f"{base_url}/knowledge-bases/{kb_id}/collaborators/{user_id}",
        headers=headers,
        timeout=10,
    )
    return r.status_code


def upload_doc(
    base_url: str, token: str, kb_id: int, filename: str = "test.txt", content: bytes = None
) -> tuple:
    """上传文档到指定 KB。

    每次上传使用唯一内容（含 uuid），避免同一 KB 中 file_hash 重复
    触发 409 ConflictError。

    Args:
        base_url: API base URL
        token: Bearer token
        kb_id: 知识库 ID
        filename: 文件名
        content: 文件内容；None 时自动生成唯一内容

    Returns:
        (status_code, doc_id) — doc_id 在非 200 时为 None
    """
    if content is None:
        content = f"test content {uuid.uuid4().hex}".encode()
    files = {"file": (filename, io.BytesIO(content), "text/plain")}
    data = {"kb_id": str(kb_id)}
    r = requests.post(
        f"{base_url}/documents/upload",
        files=files,
        data=data,
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    doc_id = None
    if r.status_code == 200:
        doc_id = r.json().get("data", {}).get("document_id")
    return r.status_code, doc_id


def wait_doc_status(base_url: str, token: str, doc_id: int, timeout: int = None) -> str:
    """轮询文档状态直到终态（done/failed）或超时。

    Args:
        base_url: API base URL
        token: Bearer token
        doc_id: 文档 ID
        timeout: 超时秒数；None 时用 config.DOC_WAIT_TIMEOUT

    Returns:
        "done" / "failed" / "timeout"
    """
    if timeout is None:
        timeout = config.DOC_WAIT_TIMEOUT
    headers = {"Authorization": f"Bearer {token}"}

    def _poll():
        r = requests.get(
            f"{base_url}/documents/{doc_id}",
            headers=headers,
            timeout=10,
        )
        if r.status_code == 200:
            status = r.json().get("data", {}).get("status")
            if status in ("done", "failed"):
                return status
        return None

    try:
        return wait_for(
            _poll,
            timeout=timeout,
            interval=2,
            message=f"Document {doc_id} to reach terminal status",
        )
    except TimeoutError:
        return "timeout"


def wait_doc_done(base_url: str, token: str, doc_id: int, timeout: int = None) -> bool:
    """轮询文档状态直到 done 或超时。

    Returns:
        True 如果 done，False 如果 failed/timeout
    """
    return wait_doc_status(base_url, token, doc_id, timeout) == "done"
