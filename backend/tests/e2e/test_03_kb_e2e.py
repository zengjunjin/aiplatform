"""知识库 E2E 测试

API:
- POST   /knowledge-bases                  -> 创建
- GET    /knowledge-bases                  -> 分页列表
- GET    /knowledge-bases/{id}             -> 详情
- PUT    /knowledge-bases/{id}             -> 更新（注意 PUT 不是 PATCH）
- DELETE /knowledge-bases/{id}             -> 删除（返回 200 + message）
- POST   /knowledge-bases/{id}/collaborators
- DELETE /knowledge-bases/{id}/collaborators/{user_id}
- GET    /knowledge-bases/{id}/collaborators
"""
import uuid
import pytest
import requests

from tests.e2e.conftest import extract_data


def test_create_kb(base_url, admin_headers):
    """创建 KB"""
    kb_name = f"E2E_KB_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{base_url}/knowledge-bases", json={
        "name": kb_name,
        "description": "测试创建",
    }, headers=admin_headers, timeout=10)
    assert r.status_code == 200, f"Create KB failed: {r.text}"
    kb = extract_data(r)
    assert kb["name"] == kb_name
    # 清理
    requests.delete(f"{base_url}/knowledge-bases/{kb['id']}",
                    headers=admin_headers, timeout=5)


def test_list_kbs_pagination(base_url, admin_headers, test_kb):
    """列表分页"""
    r = requests.get(f"{base_url}/knowledge-bases",
                     params={"page": 1, "page_size": 5},
                     headers=admin_headers, timeout=10)
    assert r.status_code == 200
    data = extract_data(r)
    assert "items" in data and "total" in data
    assert data["page"] == 1
    assert data["page_size"] == 5
    # 当前 test_kb 应在列表中
    assert any(kb["id"] == test_kb["id"] for kb in data["items"]), \
        "test_kb not in list"


def test_get_kb_detail(base_url, admin_headers, test_kb):
    """获取 KB 详情"""
    r = requests.get(f"{base_url}/knowledge-bases/{test_kb['id']}",
                     headers=admin_headers, timeout=10)
    assert r.status_code == 200
    kb = extract_data(r)
    assert kb["id"] == test_kb["id"]
    assert kb["name"] == test_kb["name"]


def test_update_kb(base_url, admin_headers, test_kb):
    """更新 KB（PUT）"""
    new_name = f"Updated_{uuid.uuid4().hex[:8]}"
    r = requests.put(
        f"{base_url}/knowledge-bases/{test_kb['id']}",
        json={"name": new_name, "description": "已更新"},
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200, f"Update KB failed: {r.text}"
    updated = extract_data(r)
    assert updated["name"] == new_name


def test_non_owner_cannot_write(base_url, test_user_headers, test_kb):
    """非协作者无写权限：普通用户尝试上传文档到 admin 的 KB

    实际 API：POST /documents/upload with form kb_id
    """
    import io
    files = {"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")}
    data = {"kb_id": str(test_kb["id"])}
    r = requests.post(
        f"{base_url}/documents/upload",
        files=files, data=data,
        headers=test_user_headers, timeout=10,
    )
    # 应返回 403（无写权限）或 404（KB 不可见）
    assert r.status_code in (403, 404), (
        f"Non-owner should be rejected. Got {r.status_code}: {r.text}"
    )


def test_delete_kb(base_url, admin_headers):
    """删除 KB（返回 200 + message）"""
    # 先创建
    r = requests.post(f"{base_url}/knowledge-bases", json={
        "name": f"Del_KB_{uuid.uuid4().hex[:8]}",
    }, headers=admin_headers, timeout=10)
    kb_id = extract_data(r)["id"]
    # 删除
    r2 = requests.delete(f"{base_url}/knowledge-bases/{kb_id}",
                         headers=admin_headers, timeout=10)
    assert r2.status_code == 200, f"Delete KB failed: {r2.text}"
    # 验证已删除
    r3 = requests.get(f"{base_url}/knowledge-bases/{kb_id}",
                      headers=admin_headers, timeout=10)
    assert r3.status_code == 404, f"Expected 404, got {r3.status_code}: {r3.text}"
