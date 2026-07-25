"""CDP 边界测试 - SQL 注入输入验证（P4）

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

核心场景：
1. KB name 注入 SQL：POST /knowledge-bases name="'; DROP TABLE knowledge_bases;--"
2. KB name 含 SQL 关键字：name="' OR 1=1--"
3. KB name 含特殊字符：emoji、Unicode、NULL byte
4. 超长 KB name（10000+ 字符）

预期行为：
- SQL 注入字符串被当作普通字符串处理（SQLAlchemy 参数化查询）
- 不引发 500 错误
- 不返回全表数据
- 特殊字符被正确存储和检索

后端使用 SQLAlchemy ORM + 参数化查询，SQL 注入应被天然防护。
本测试验证这一假设是否成立。
"""

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


# SQL 注入 payload 清单
SQL_INJECTION_PAYLOADS = [
    "' OR 1=1--",
    "'; DROP TABLE knowledge_bases;--",
    "' UNION SELECT * FROM users--",
    "admin'--",
    "' OR ''='",
    "1; DELETE FROM users WHERE 1=1;--",
    "' OR SLEEP(5)--",
]


@pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
def test_sql_injection_in_kb_name(base_url, admin_headers, payload):
    """P4: KB name 注入 SQL payload，验证不引发 500 且被当作普通字符串处理

    SQLAlchemy ORM 使用参数化查询，SQL 注入字符串应被当作普通字符串存储。
    """
    kb_name = f"SQLI_{uuid.uuid4().hex[:6]}_{payload}"
    r = requests.post(
        f"{base_url}/knowledge-bases",
        json={"name": kb_name, "description": "SQL 注入测试"},
        headers=admin_headers,
        timeout=10,
    )
    # 应返回 200（成功创建）或 400/422（输入校验拒绝）
    # 不应返回 500（数据库错误）
    assert r.status_code in (200, 400, 422), (
        f"SQL injection payload '{payload}' caused unexpected status {r.status_code}: "
        f"{r.text[:200]}"
    )

    if r.status_code == 200:
        kb_data = r.json().get("data", {})
        kb_id = kb_data.get("id")
        try:
            # 验证 KB 被正确创建且 name 未被篡改
            r_get = requests.get(
                f"{base_url}/knowledge-bases/{kb_id}",
                headers=admin_headers,
                timeout=10,
            )
            assert r_get.status_code == 200
            retrieved_name = r_get.json().get("data", {}).get("name", "")
            # name 应包含原始 payload（作为普通字符串）
            assert (
                payload in retrieved_name
            ), f"Payload '{payload}' not preserved in KB name: '{retrieved_name}'"
        finally:
            # 清理
            requests.delete(
                f"{base_url}/knowledge-bases/{kb_id}",
                headers=admin_headers,
                timeout=5,
            )


def test_sql_injection_no_data_leak(base_url, admin_headers):
    """P4: SQL 注入不应导致数据泄露

    创建 KB with SQL 注入 name，然后 list KBs 验证：
    - 不返回所有 KB（仅返回 admin 有权访问的）
    - 返回的 items 数量合理（不超过 page_size）
    """
    # 创建含 SQL 注入的 KB
    payload = "' OR 1=1--"
    kb_name = f"LEAK_TEST_{uuid.uuid4().hex[:6]}_{payload}"
    r = requests.post(
        f"{base_url}/knowledge-bases",
        json={"name": kb_name},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200
    kb_id = r.json().get("data", {}).get("id")

    try:
        # 列表查询 with 小 page_size
        r_list = requests.get(
            f"{base_url}/knowledge-bases",
            params={"page": 1, "page_size": 5},
            headers=admin_headers,
            timeout=10,
        )
        assert r_list.status_code == 200
        data = r_list.json().get("data", {})
        items = data.get("items", [])
        total = data.get("total", 0)

        # 验证返回的 items 数量不超过 page_size
        assert len(items) <= 5, (
            f"SQL injection may have leaked data: got {len(items)} items " f"(expected <= 5)"
        )

        # 验证 total 是合理数字（不是全表 count 错误的巨大数字）
        assert isinstance(total, int) and total >= 1, f"Unexpected total: {total}"
    finally:
        requests.delete(
            f"{base_url}/knowledge-bases/{kb_id}",
            headers=admin_headers,
            timeout=5,
        )


def test_special_chars_in_kb_name(base_url, admin_headers):
    """P4: KB name 含特殊字符（emoji、Unicode、控制字符）的验证

    验证后端能正确处理 Unicode 字符，不引发 500。
    """
    special_names = [
        f"EMOJI_{uuid.uuid4().hex[:6]}_🎉🎊🎈",
        f"UNICODE_{uuid.uuid4().hex[:6]}_中文测试_日本語_한국어",
        f"SPACES_{uuid.uuid4().hex[:6]}_  leading and trailing  ",
        f"QUOTES_{uuid.uuid4().hex[:6]}_\"single'and\"double'",
        f"BACKSLASH_{uuid.uuid4().hex[:6]}_back\\slash\\test",
    ]

    for name in special_names:
        r = requests.post(
            f"{base_url}/knowledge-bases",
            json={"name": name},
            headers=admin_headers,
            timeout=10,
        )
        # 应成功创建或被校验拒绝，不应 500
        assert r.status_code in (200, 400, 422), (
            f"Special char name '{name}' caused status {r.status_code}: " f"{r.text[:200]}"
        )

        if r.status_code == 200:
            kb_id = r.json().get("data", {}).get("id")
            # 清理
            requests.delete(
                f"{base_url}/knowledge-bases/{kb_id}",
                headers=admin_headers,
                timeout=5,
            )


def test_oversized_kb_name(base_url, admin_headers):
    """P4: 超长 KB name（10000 字符）的边界处理

    验证后端有长度限制，不引发 500 或数据库错误。
    """
    long_name = "A" * 10000
    r = requests.post(
        f"{base_url}/knowledge-bases",
        json={"name": long_name},
        headers=admin_headers,
        timeout=10,
    )
    # 应被校验拒绝（400/422），或成功创建（200，如果数据库支持）
    # 不应返回 500
    assert r.status_code in (
        200,
        400,
        422,
    ), f"Oversized name caused status {r.status_code}: {r.text[:200]}"

    if r.status_code == 200:
        kb_id = r.json().get("data", {}).get("id")
        requests.delete(
            f"{base_url}/knowledge-bases/{kb_id}",
            headers=admin_headers,
            timeout=5,
        )


def test_empty_kb_name(base_url, admin_headers):
    """P4: 空 KB name 的边界处理

    验证后端校验拒绝空 name。
    """
    r = requests.post(
        f"{base_url}/knowledge-bases",
        json={"name": ""},
        headers=admin_headers,
        timeout=10,
    )
    # 空字符串应被校验拒绝
    assert r.status_code in (
        400,
        422,
    ), f"Empty name should be rejected, got {r.status_code}: {r.text[:200]}"


def test_missing_kb_name_field(base_url, admin_headers):
    """P4: 缺失 name 字段的边界处理

    验证后端校验拒绝缺失必填字段。
    """
    r = requests.post(
        f"{base_url}/knowledge-bases",
        json={"description": "no name field"},
        headers=admin_headers,
        timeout=10,
    )
    # 缺失必填字段应被校验拒绝
    assert r.status_code in (
        400,
        422,
    ), f"Missing name field should be rejected, got {r.status_code}: {r.text[:200]}"
