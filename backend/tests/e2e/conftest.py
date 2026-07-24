"""E2E 测试 conftest - 真实 HTTP 请求 + 真实服务

API 响应统一格式: {code: 0, message: "success", data: ...}
分页: {code: 0, message: "success", data: {items, total, page, page_size, total_pages}}
"""
import os
import time
import uuid
import pytest
import requests
from pathlib import Path

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000/api/v1")
REPORT_DIR = Path(__file__).parent / "reports"
REPORT_DIR.mkdir(exist_ok=True)

# 测试文档路径（复用 integration 的测试文档）
TEST_DOC_PATH = os.path.join(
    os.path.dirname(__file__), "..", "integration", "test_doc.txt"
)


@pytest.fixture(scope="session", autouse=True)
def cleanup_old_reports():
    """清理 7 天以上的旧测试报告，避免 reports 目录无限增长。"""
    if REPORT_DIR.exists():
        cutoff = time.time() - 7 * 24 * 3600  # 7 天
        for report_file in REPORT_DIR.glob("*.html"):
            try:
                if report_file.stat().st_mtime < cutoff:
                    report_file.unlink()
            except Exception:
                pass
    yield


def pytest_collection_modifyitems(config, items):
    """自动为 tests/e2e/ 目录下所有收集到的测试项添加 e2e 标记和 timeout 标记。

    使 ``-m "not e2e"`` 能正确过滤，避免 E2E 测试混入单元测试运行。
    同时为 E2E 测试设置 180s 超时（覆盖全局 60s），因为 E2E 涉及真实 HTTP
    请求和 SSE 流式响应，需要更长的等待时间。
    """
    for item in items:
        if "e2e" in str(item.fspath) or "tests" in str(item.fspath):
            # 仅对 e2e 目录下的测试项添加标记
            if os.sep + "e2e" in str(item.fspath) or "/e2e/" in str(item.fspath):
                item.add_marker(pytest.mark.e2e)
                item.add_marker(pytest.mark.timeout(180))


def extract_data(response: requests.Response) -> dict:
    """从统一响应中提取 data 字段"""
    body = response.json()
    return body.get("data", body) if isinstance(body, dict) else body


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def admin_token(base_url):
    """登录 admin 获取 token

    admin 密码通过环境变量 E2E_ADMIN_PASSWORD 注入（CI secret），
    默认值 "admin123" 仅用于本地开发环境。
    """
    admin_password = os.getenv("E2E_ADMIN_PASSWORD", "admin123")
    r = requests.post(f"{base_url}/auth/login", json={
        "username": "admin",
        "password": admin_password,
    }, timeout=10)
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    data = extract_data(r)
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "token_type": data.get("token_type", "bearer"),
        "expires_in": data.get("expires_in"),
        "user": data["user"],
    }


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token['access_token']}"}


@pytest.fixture(scope="session", autouse=True)
def _init_shared_fixtures_early(admin_token, test_user):
    """提前初始化 session 级共享 fixture，避免后续测试触发限流后无法初始化。

    单独运行 test_10_rate_limit_e2e.py 时，test_auth_login_rate_limit 会触发
    /auth/login 限流（5/minute），如果 admin_token/test_user 未提前初始化，
    后续依赖这些 fixture 的测试将因登录限流而失败。
    autouse + session scope 确保在所有测试之前完成登录和注册。
    """
    return {"admin_token": admin_token, "test_user": test_user}

@pytest.fixture(scope="session")
def test_user(base_url, admin_headers):
    """创建临时测试用户（通过 /auth/register），整个 session 共享一个用户

    使用 session scope 避免 /auth/register 限流（5/minute）。
    注意：API 没有 DELETE /users/{id} 端点，使用 PUT /users/{id}/status 软禁用清理。

    警告：test_02_users_e2e.py 中的 test_admin_can_disable_user 会修改此用户状态，
    但其他测试使用的是 access_token，token 在签发后即不依赖 is_active 校验
    （仅 /auth/login 会检查 is_active），因此 disable 不会影响其他测试。
    """
    username = f"e2e_user_{uuid.uuid4().hex[:8]}"
    email = f"{username}@test.com"
    password = "Test@123456"

    # 注册
    r = requests.post(f"{base_url}/auth/register", json={
        "username": username,
        "email": email,
        "password": password,
    }, timeout=10)
    assert r.status_code == 200, f"Register user failed: {r.text}"
    user_data = extract_data(r)

    # 登录获取 token
    r2 = requests.post(f"{base_url}/auth/login", json={
        "username": username,
        "password": password,
    }, timeout=10)
    assert r2.status_code == 200, f"Login test user failed: {r2.text}"
    user_token = extract_data(r2)

    yield {
        "user": user_data,
        "password": password,
        "access_token": user_token["access_token"],
        "refresh_token": user_token["refresh_token"],
    }

    # 清理：软禁用（API 无 DELETE /users/{id}）
    try:
        requests.put(
            f"{base_url}/users/{user_data['id']}/status",
            json={"is_active": False},
            headers=admin_headers, timeout=5,
        )
    except Exception:
        pass


@pytest.fixture(scope="session")
def test_user_headers(test_user):
    return {"Authorization": f"Bearer {test_user['access_token']}"}


# ============ 共享业务 fixtures（供多个测试文件复用）============

@pytest.fixture(scope="session")
def test_kb(base_url, admin_headers):
    """创建测试 KB，自动清理（session scope，与 kb_with_doc 配合）"""
    kb_name = f"E2E_KB_{uuid.uuid4().hex[:8]}"
    r = requests.post(f"{base_url}/knowledge-bases", json={
        "name": kb_name,
        "description": "E2E 测试知识库",
    }, headers=admin_headers, timeout=10)
    assert r.status_code == 200, f"Create KB failed: {r.text}"
    kb = extract_data(r)
    yield kb
    try:
        requests.delete(f"{base_url}/knowledge-bases/{kb['id']}",
                        headers=admin_headers, timeout=5)
    except Exception:
        pass


@pytest.fixture(scope="session")
def kb_with_doc(base_url, admin_headers, test_kb):
    """创建 KB + 上传文档，等待解析完成（session scope 共享，避免 /documents/upload 10/hour 限流）

    使用 /documents/upload 端点（form: file + kb_id）。
    上传返回 {document_id, status, task_id}，详情查询返回完整 doc 对象（含 id）。

    如果上传触发 429 限流（10/hour 耗尽），回退到查询已有 KB 中 status=done 的文档，
    避免因限流阻塞所有下游测试。
    """
    token = admin_headers["Authorization"].split(" ")[1]
    headers = {"Authorization": f"Bearer {token}"}
    # 上传文档
    with open(TEST_DOC_PATH, "rb") as f:
        files = {"file": ("test_doc.txt", f, "text/plain")}
        data = {"kb_id": str(test_kb["id"])}
        r2 = requests.post(
            f"{base_url}/documents/upload",
            files=files, data=data, headers=headers, timeout=60,
        )

    if r2.status_code == 429:
        # 限流回退：查询已有 KB 中 status=done 的文档
        r_kbs = requests.get(
            f"{base_url}/knowledge-bases", params={"page": 1, "page_size": 50},
            headers=headers, timeout=10,
        )
        existing_kbs = extract_data(r_kbs).get("items", [])
        for ekb in existing_kbs:
            r_docs = requests.get(
                f"{base_url}/documents",
                params={"kb_id": ekb["id"], "page": 1, "page_size": 50},
                headers=headers, timeout=10,
            )
            docs = extract_data(r_docs).get("items", [])
            done_doc = next((d for d in docs if d.get("status") == "done"), None)
            if done_doc:
                yield {"kb": ekb, "doc": done_doc}
                return
        raise AssertionError(
            "Upload rate-limited (429) and no existing KB with done document found"
        )

    assert r2.status_code == 200, f"Upload doc failed: {r2.text}"
    upload_resp = extract_data(r2)
    doc_id = upload_resp["document_id"]

    # 轮询 GET /documents/{doc_id} 直到 status == done
    deadline = time.time() + 120
    doc = None
    while time.time() < deadline:
        r3 = requests.get(f"{base_url}/documents/{doc_id}",
                          headers=headers, timeout=10)
        if r3.status_code == 200:
            cur = extract_data(r3)
            if cur.get("status") == "done":
                doc = cur
                break
            if cur.get("status") == "failed":
                raise AssertionError(
                    f"Document parse failed: {cur.get('error_message')}"
                )
        time.sleep(2)
    else:
        raise TimeoutError(f"Document parse timeout, last={doc}")

    yield {"kb": test_kb, "doc": doc}


@pytest.fixture(scope="function")
def chat_session(base_url, admin_headers, kb_with_doc):
    """创建聊天会话，自动清理

    SessionCreate schema 使用 kb_id 字段（不是 knowledge_base_id）。
    scope="function" 显式标注：每个测试独立会话，避免数据污染。
    """
    token = admin_headers["Authorization"].split(" ")[1]
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.post(f"{base_url}/chat/sessions", json={
        "title": "E2E 测试会话",
        "kb_id": kb_with_doc["kb"]["id"],
    }, headers=headers, timeout=10)
    assert r.status_code == 200, f"Create chat session failed: {r.text}"
    session = extract_data(r)
    yield session
    try:
        requests.delete(f"{base_url}/chat/sessions/{session['id']}",
                        headers=headers, timeout=5)
    except Exception:
        pass


@pytest.fixture(scope="function")
def chat_session_with_msg(base_url, admin_headers, chat_session):
    """创建会话并发送一条消息（SSE），返回 session + message_id

    SSE 并发限制（SSE_MAX_CONCURRENT=3）下，前一个测试的 SSE 连接
    可能在服务端生成器 finally 执行前未及时 DECR 计数器，导致本测试
    触发 429。此处添加 429 重试逻辑（等待 2s 后重试，最多 5 次）。
    scope="function" 显式标注：每个测试独立会话+消息，避免数据污染。
    """
    import json as _json
    import time as _time
    token = admin_headers["Authorization"].split(" ")[1]
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url}/chat/sessions/{chat_session['id']}/messages"
    message_id = None

    for attempt in range(6):
        with requests.post(url, json={"content": "你好"}, headers=headers,
                           stream=True, timeout=60) as r:
            if r.status_code == 429:
                # SSE 并发限制：等待前一个连接的计数器清理后重试
                _time.sleep(2)
                continue
            assert r.status_code == 200, f"SSE failed: {r.text}"
            for line in r.iter_lines(decode_unicode=True):
                if line and line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        evt = _json.loads(payload)
                    except Exception:
                        continue
                    if evt.get("event") == "done" and evt.get("message_id"):
                        message_id = evt["message_id"]
                        break
            break
    else:
        raise AssertionError(
            "SSE failed after 6 attempts (concurrent limit 429 persisted)"
        )
    yield {"session": chat_session, "message_id": message_id}


# ============ 报告生成 ============

@pytest.fixture(scope="session")
def report_collector():
    """收集所有测试结果用于报告生成"""
    results = []
    yield results
    _generate_report(results)


def _generate_report(results):
    from datetime import datetime
    from tests.e2e.helpers.reporter import generate_html_report
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = REPORT_DIR / f"e2e_report_{ts}.html"
    generate_html_report(results, report_file)
    print(f"\n\nE2E 测试报告已生成：{report_file}\n")


@pytest.fixture(autouse=True)
def _record_result(request, report_collector):
    """自动记录每个测试结果"""
    from tests.e2e.helpers.reporter import TestRecord
    start = time.time()
    record = TestRecord(
        name=request.node.nodeid,
        status="PASS",
        duration=0,
    )
    try:
        yield
        record.duration = time.time() - start
    except Exception as e:
        record.status = "FAIL"
        record.duration = time.time() - start
        record.error = str(e)
        # CDP 测试截图（如果 fixture 可用）
        cdp = request.node.funcargs.get("cdp") or request.node.funcargs.get("logged_in_cdp")
        if cdp:
            try:
                shot_path = REPORT_DIR / f"{request.node.name}_fail.png"
                cdp.screenshot(str(shot_path))
                record.screenshot = shot_path.name
            except Exception:
                pass
        raise
    finally:
        report_collector.append(record)
