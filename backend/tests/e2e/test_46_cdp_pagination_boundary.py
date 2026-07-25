"""CDP 边界测试 - 分页边界验证（P6）

需要 Tauri 以 CDP 端口 9223 启动 + 后端服务运行。

核心场景：
1. page=0：应返回 400（Query(ge=1) 约束，全局异常处理器把 422 转 400）
2. page=-1：应返回 400
3. page=999999：应返回 200 + 空列表（不返回 500）
4. page_size=0：应返回 400（Query(ge=1) 约束）
5. page_size=-1：应返回 400
6. page_size=100000：应返回 400（Query(le=100) 约束）
7. 缺失 page/page_size：应使用默认值（page=1, page_size=20）

后端所有分页 API 使用 Query(1, ge=1) 和 Query(20, ge=1, le=100) 约束。
注意：app/core/exceptions.py 的 validation_exception_handler 把 FastAPI 默认
的 422 RequestValidationError 转换为 HTTP 400 + 统一响应体，因此非法参数
返回 400 而非 422。

测试端点：GET /knowledge-bases（代表性分页 API）
"""

import os

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


def test_page_zero_rejected(base_url, admin_headers):
    """P6: page=0 应被拒绝（400）

    FastAPI Query(1, ge=1) 约束：page 必须 >= 1。
    全局异常处理器把 422 转 400。
    """
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 0, "page_size": 5},
        headers=admin_headers,
        timeout=10,
    )
    assert (
        r.status_code == 400
    ), f"page=0 should be rejected with 400, got {r.status_code}: {r.text[:200]}"


def test_page_negative_rejected(base_url, admin_headers):
    """P6: page=-1 应被拒绝（400）"""
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": -1, "page_size": 5},
        headers=admin_headers,
        timeout=10,
    )
    assert (
        r.status_code == 400
    ), f"page=-1 should be rejected with 400, got {r.status_code}: {r.text[:200]}"


def test_page_oversized_returns_empty(base_url, admin_headers):
    """P6: page=999999 应返回 200 + 空列表（不返回 500）

    超大页码应返回空 items，total 为实际总数。
    """
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 999999, "page_size": 5},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, (
        f"page=999999 should return 200 with empty items, " f"got {r.status_code}: {r.text[:200]}"
    )
    data = r.json().get("data", {})
    items = data.get("items", [])
    assert len(items) == 0, f"page=999999 should return empty items, got {len(items)} items"


def test_page_size_zero_rejected(base_url, admin_headers):
    """P6: page_size=0 应被拒绝（400）

    FastAPI Query(20, ge=1) 约束：page_size 必须 >= 1。
    全局异常处理器把 422 转 400。
    """
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 1, "page_size": 0},
        headers=admin_headers,
        timeout=10,
    )
    assert (
        r.status_code == 400
    ), f"page_size=0 should be rejected with 400, got {r.status_code}: {r.text[:200]}"


def test_page_size_negative_rejected(base_url, admin_headers):
    """P6: page_size=-1 应被拒绝（400）"""
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 1, "page_size": -1},
        headers=admin_headers,
        timeout=10,
    )
    assert (
        r.status_code == 400
    ), f"page_size=-1 should be rejected with 400, got {r.status_code}: {r.text[:200]}"


def test_page_size_oversized_rejected(base_url, admin_headers):
    """P6: page_size=100000 应被拒绝（400）

    FastAPI Query(20, ge=1, le=100) 约束：page_size 必须 <= 100。
    全局异常处理器把 422 转 400。
    """
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 1, "page_size": 100000},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 400, (
        f"page_size=100000 should be rejected with 400 (le=100 constraint), "
        f"got {r.status_code}: {r.text[:200]}"
    )


def test_page_size_at_upper_bound(base_url, admin_headers):
    """P6: page_size=100（上限）应返回 200

    le=100 约束允许 page_size=100，应正常返回。
    """
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 1, "page_size": 100},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, (
        f"page_size=100 (upper bound) should return 200, " f"got {r.status_code}: {r.text[:200]}"
    )
    data = r.json().get("data", {})
    items = data.get("items", [])
    assert len(items) <= 100, f"items count should be <= 100, got {len(items)}"


def test_missing_page_uses_default(base_url, admin_headers):
    """P6: 缺失 page 参数应使用默认值 page=1"""
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page_size": 5},  # 不传 page
        headers=admin_headers,
        timeout=10,
    )
    assert (
        r.status_code == 200
    ), f"Missing page should use default, got {r.status_code}: {r.text[:200]}"
    data = r.json().get("data", {})
    assert data.get("page") == 1, f"Default page should be 1, got {data.get('page')}"


def test_missing_page_size_uses_default(base_url, admin_headers):
    """P6: 缺失 page_size 参数应使用默认值 page_size=20"""
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 1},  # 不传 page_size
        headers=admin_headers,
        timeout=10,
    )
    assert (
        r.status_code == 200
    ), f"Missing page_size should use default, got {r.status_code}: {r.text[:200]}"
    data = r.json().get("data", {})
    assert (
        data.get("page_size") == 20
    ), f"Default page_size should be 20, got {data.get('page_size')}"


def test_missing_both_pagination_params(base_url, admin_headers):
    """P6: 缺失 page 和 page_size 都使用默认值"""
    r = requests.get(
        f"{base_url}/knowledge-bases",
        headers=admin_headers,
        timeout=10,  # 不传 page 和 page_size
    )
    assert r.status_code == 200, f"Missing both params should use defaults, got {r.status_code}"
    data = r.json().get("data", {})
    assert data.get("page") == 1, f"Default page should be 1, got {data.get('page')}"
    assert (
        data.get("page_size") == 20
    ), f"Default page_size should be 20, got {data.get('page_size')}"


def test_non_integer_page_rejected(base_url, admin_headers):
    """P6: page="abc"（非整数）应被拒绝（400）"""
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": "abc", "page_size": 5},
        headers=admin_headers,
        timeout=10,
    )
    assert (
        r.status_code == 400
    ), f"page='abc' should be rejected with 400, got {r.status_code}: {r.text[:200]}"


def test_non_integer_page_size_rejected(base_url, admin_headers):
    """P6: page_size="xyz"（非整数）应被拒绝（400）"""
    r = requests.get(
        f"{base_url}/knowledge-bases",
        params={"page": 1, "page_size": "xyz"},
        headers=admin_headers,
        timeout=10,
    )
    assert (
        r.status_code == 400
    ), f"page_size='xyz' should be rejected with 400, got {r.status_code}: {r.text[:200]}"
