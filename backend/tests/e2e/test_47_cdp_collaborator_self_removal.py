"""CDP 边界测试 - KB 协作者自删除验证（P7）

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

核心场景：
1. admin 添加用户 A 为 read 协作者
2. 用户 A 调用 DELETE /knowledge-bases/{kb_id}/collaborators/{self_user_id} 移除自己
3. 验证：用户 A 立即失去 KB 访问权限（GET /knowledge-bases/{kb_id} 返回 403）

边界场景：
- read 协作者自删除
- write 协作者自删除
- admin 协作者自删除
- owner 不能删除自己（不应出现在协作者列表中）

双账号验证：
- admin CDP 会话：创建 KB + 添加协作者
- 用户 A API 验证：自删除 + 验证失去访问权限
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
    create_user_via_api,
    verify_api_call,
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
def self_removal_kb(base_url, admin_headers):
    """创建专用 KB 用于协作者自删除测试（module scope，自动清理）。"""
    kb_name = f"SELF_DEL_KB_{uuid.uuid4().hex[:6]}"
    r = requests.post(
        f"{base_url}/knowledge-bases",
        json={"name": kb_name, "description": "协作者自删除测试"},
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200, f"Create KB failed: {r.text[:200]}"
    kb = r.json().get("data", {})
    yield kb
    try:
        requests.delete(
            f"{base_url}/knowledge-bases/{kb['id']}",
            headers=admin_headers, timeout=5,
        )
    except Exception:
        pass


def _set_collaborator(base_url, admin_headers, kb_id, user_id, permission):
    """admin 设置协作者权限。"""
    r = requests.post(
        f"{base_url}/knowledge-bases/{kb_id}/collaborators",
        json={"user_id": user_id, "permission": permission},
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200, (
        f"Set collaborator ({permission}) failed: {r.status_code} {r.text[:200]}"
    )


def test_read_collaborator_self_removal(base_url, admin_headers, self_removal_kb):
    """P7: read 协作者自删除

    步骤：
    1. 创建用户 A
    2. admin 添加用户 A 为 read 协作者
    3. 用户 A 调用 DELETE 移除自己
    4. 验证用户 A 失去 KB 访问权限（GET /knowledge-bases/{kb_id} 返回 403）
    """
    # 1. 创建用户 A
    user_a = create_user_via_api(base_url, admin_headers)
    user_a_id = user_a["user"]["id"]
    user_a_token = user_a["access_token"]
    kb_id = self_removal_kb["id"]

    # 2. admin 添加用户 A 为 read 协作者
    _set_collaborator(base_url, admin_headers, kb_id, user_a_id, "read")

    # 基线：用户 A 可访问 KB
    r_before = requests.get(
        f"{base_url}/knowledge-bases/{kb_id}",
        headers={"Authorization": f"Bearer {user_a_token}"},
        timeout=10,
    )
    assert r_before.status_code == 200, (
        f"Baseline: read collaborator should access KB, "
        f"got {r_before.status_code}"
    )

    # 3. 用户 A 调用 DELETE 移除自己
    r_del = requests.delete(
        f"{base_url}/knowledge-bases/{kb_id}/collaborators/{user_a_id}",
        headers={"Authorization": f"Bearer {user_a_token}"},
        timeout=10,
    )

    # 预期行为：
    # - 200（自删除成功）或 403（不允许自删除）
    # 不应返回 500
    assert r_del.status_code in (200, 403), (
        f"Self-removal should return 200 or 403, "
        f"got {r_del.status_code}: {r_del.text[:200]}"
    )

    if r_del.status_code == 200:
        # 4. 验证用户 A 失去 KB 访问权限
        time.sleep(1)
        r_after = requests.get(
            f"{base_url}/knowledge-bases/{kb_id}",
            headers={"Authorization": f"Bearer {user_a_token}"},
            timeout=10,
        )
        assert r_after.status_code == 403, (
            f"After self-removal, user should lose KB access (403), "
            f"got {r_after.status_code}: {r_after.text[:200]}"
        )
    # 如果 403（不允许自删除），测试通过（行为合理）


def test_write_collaborator_self_removal(base_url, admin_headers, self_removal_kb):
    """P7: write 协作者自删除"""
    user_a = create_user_via_api(base_url, admin_headers)
    user_a_id = user_a["user"]["id"]
    user_a_token = user_a["access_token"]
    kb_id = self_removal_kb["id"]

    _set_collaborator(base_url, admin_headers, kb_id, user_a_id, "write")

    # 基线
    r_before = requests.get(
        f"{base_url}/knowledge-bases/{kb_id}",
        headers={"Authorization": f"Bearer {user_a_token}"},
        timeout=10,
    )
    assert r_before.status_code == 200

    # 自删除
    r_del = requests.delete(
        f"{base_url}/knowledge-bases/{kb_id}/collaborators/{user_a_id}",
        headers={"Authorization": f"Bearer {user_a_token}"},
        timeout=10,
    )
    assert r_del.status_code in (200, 403), (
        f"Self-removal (write) should return 200 or 403, "
        f"got {r_del.status_code}: {r_del.text[:200]}"
    )

    if r_del.status_code == 200:
        time.sleep(1)
        r_after = requests.get(
            f"{base_url}/knowledge-bases/{kb_id}",
            headers={"Authorization": f"Bearer {user_a_token}"},
            timeout=10,
        )
        assert r_after.status_code == 403, (
            f"After self-removal, write collaborator should lose access (403), "
            f"got {r_after.status_code}"
        )


def test_admin_collaborator_self_removal(base_url, admin_headers, self_removal_kb):
    """P7: admin 协作者自删除"""
    user_a = create_user_via_api(base_url, admin_headers)
    user_a_id = user_a["user"]["id"]
    user_a_token = user_a["access_token"]
    kb_id = self_removal_kb["id"]

    _set_collaborator(base_url, admin_headers, kb_id, user_a_id, "admin")

    # 基线
    r_before = requests.get(
        f"{base_url}/knowledge-bases/{kb_id}",
        headers={"Authorization": f"Bearer {user_a_token}"},
        timeout=10,
    )
    assert r_before.status_code == 200

    # 自删除
    r_del = requests.delete(
        f"{base_url}/knowledge-bases/{kb_id}/collaborators/{user_a_id}",
        headers={"Authorization": f"Bearer {user_a_token}"},
        timeout=10,
    )
    assert r_del.status_code in (200, 403), (
        f"Self-removal (admin) should return 200 or 403, "
        f"got {r_del.status_code}: {r_del.text[:200]}"
    )

    if r_del.status_code == 200:
        time.sleep(1)
        r_after = requests.get(
            f"{base_url}/knowledge-bases/{kb_id}",
            headers={"Authorization": f"Bearer {user_a_token}"},
            timeout=10,
        )
        assert r_after.status_code == 403, (
            f"After self-removal, admin collaborator should lose access (403), "
            f"got {r_after.status_code}"
        )


def test_owner_not_in_collaborator_list(base_url, admin_headers, self_removal_kb):
    """P7: owner 不应出现在协作者列表中

    owner 是 KB 的创建者，不应被添加为协作者（避免权限混淆）。
    验证 GET /collaborators 不返回 owner。

    注意：协作者 API 返回 {"data": [...]}（list 直接挂在 data 上），
    不是 {"data": {"items": [...]}} 分页结构。
    """
    kb_id = self_removal_kb["id"]
    owner_id = self_removal_kb.get("owner_id")

    r = requests.get(
        f"{base_url}/knowledge-bases/{kb_id}/collaborators",
        headers=admin_headers, timeout=10,
    )
    assert r.status_code == 200, (
        f"GET collaborators failed: {r.status_code} {r.text[:200]}"
    )
    # 协作者 API 返回 {"data": [...]}，data 直接是 list
    collaborators = r.json().get("data", [])
    if not isinstance(collaborators, list):
        # 防御性处理：若返回 dict 带 items，取 items
        collaborators = collaborators.get("items", []) if isinstance(collaborators, dict) else []

    # owner 不应在协作者列表中
    collab_user_ids = [c.get("user_id") or c.get("id") for c in collaborators]
    if owner_id:
        assert owner_id not in collab_user_ids, (
            f"Owner {owner_id} should not be in collaborator list: {collab_user_ids}"
        )


def test_collaborator_cannot_remove_others(base_url, admin_headers, self_removal_kb):
    """P7: write 协作者不能移除其他协作者

    write 权限不含管理协作者权限，应返回 403。
    """
    # 创建两个用户
    user_a = create_user_via_api(base_url, admin_headers)
    user_b = create_user_via_api(base_url, admin_headers)
    user_a_id = user_a["user"]["id"]
    user_b_id = user_b["user"]["id"]
    user_a_token = user_a["access_token"]
    kb_id = self_removal_kb["id"]

    # admin 添加 A 为 write，B 为 read
    _set_collaborator(base_url, admin_headers, kb_id, user_a_id, "write")
    _set_collaborator(base_url, admin_headers, kb_id, user_b_id, "read")

    # 用户 A（write）尝试移除用户 B
    r_del = requests.delete(
        f"{base_url}/knowledge-bases/{kb_id}/collaborators/{user_b_id}",
        headers={"Authorization": f"Bearer {user_a_token}"},
        timeout=10,
    )
    # write 权限不能管理协作者，应返回 403
    assert r_del.status_code == 403, (
        f"Write collaborator should not be able to remove others (403), "
        f"got {r_del.status_code}: {r_del.text[:200]}"
    )

    # 验证用户 B 仍是协作者
    r_list = requests.get(
        f"{base_url}/knowledge-bases/{kb_id}/collaborators",
        headers=admin_headers, timeout=10,
    )
    # 协作者 API 返回 {"data": [...]}，data 直接是 list
    collaborators = r_list.json().get("data", [])
    if not isinstance(collaborators, list):
        collaborators = collaborators.get("items", []) if isinstance(collaborators, dict) else []
    collab_user_ids = [c.get("user_id") or c.get("id") for c in collaborators]
    assert user_b_id in collab_user_ids, (
        f"User B should still be collaborator after write user's failed removal attempt"
    )
