"""
RAG Platform 文档管理全流程 API 测试

测试覆盖：
  1. 用户注册 & 登录获取 token
  2. 创建知识库获取 kb_id
  3. 文档上传（正常/空文件/不支持格式）
  4. 文档处理状态检查
  5. 文档预览
  6. 重新解析
  7. 删除文档
  8. 文档列表（分页/过滤）
"""

import sys
import time
import uuid
from pathlib import Path

import requests

BASE_URL = "http://localhost:8002/api/v1"

pass_count = 0
fail_count = 0
test_results = []


def print_header(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def assert_pass(test_name, condition, detail=""):
    global pass_count, fail_count
    if condition:
        print(f"  [PASS] {test_name}")
        if detail:
            print(f"         {detail}")
        pass_count += 1
        test_results.append(("PASS", test_name, detail))
    else:
        print(f"  [FAIL] {test_name}")
        if detail:
            print(f"         {detail}")
        fail_count += 1
        test_results.append(("FAIL", test_name, detail))


def api_post(path, json=None, data=None, files=None, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{BASE_URL}{path}"
    try:
        if files:
            resp = requests.post(url, data=data, files=files, headers=headers, timeout=30)
        elif json is not None:
            resp = requests.post(url, json=json, headers=headers, timeout=30)
        else:
            resp = requests.post(url, data=data, headers=headers, timeout=30)
        return resp
    except Exception as e:
        print(f"  [ERROR] POST {path} failed: {e}")
        return None


def api_get(path, params=None, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        return resp
    except Exception as e:
        print(f"  [ERROR] GET {path} failed: {e}")
        return None


def api_delete(path, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.delete(url, headers=headers, timeout=30)
        return resp
    except Exception as e:
        print(f"  [ERROR] DELETE {path} failed: {e}")
        return None


def resp_info(resp):
    """Safe response info helper."""
    if resp is None:
        return "N/A", "N/A"
    return resp.status_code, resp.text[:200]


# ============================================================
# Phase 1: 注册新用户 & 登录
# ============================================================
print_header("Phase 1: 注册新用户 & 登录")

test_suffix = uuid.uuid4().hex[:8]
test_username = f"testdoc_{test_suffix}"
test_email = f"testdoc_{test_suffix}@test.com"
test_password = "Test@123456"

# 1.1 注册
resp = api_post(
    "/auth/register",
    json={
        "username": test_username,
        "email": test_email,
        "password": test_password,
    },
)
status, body = resp_info(resp)
assert_pass("注册新用户", resp is not None and resp.status_code == 200, f"status={status}")
if resp and resp.status_code == 200:
    user_data = resp.json().get("data", {})
    assert_pass(
        "注册返回用户 ID", user_data.get("id") is not None, f"user_id={user_data.get('id')}"
    )

# 1.2 登录
resp = api_post(
    "/auth/login",
    json={
        "username": test_username,
        "password": test_password,
    },
)
status, body = resp_info(resp)
assert_pass("登录获取 token", resp is not None and resp.status_code == 200, f"status={status}")
token = None
if resp and resp.status_code == 200:
    token = resp.json().get("data", {}).get("access_token")
    assert_pass("access_token 不为空", token is not None, f"token={'***' if token else 'None'}")

if not token:
    print("\nFATAL: 无法获取 token，后续测试无法继续")
    sys.exit(1)


# ============================================================
# Phase 2: 创建知识库
# ============================================================
print_header("Phase 2: 创建知识库")

resp = api_post(
    "/knowledge-bases",
    json={
        "name": f"测试知识库_{test_suffix}",
        "description": "用于文档管理 API 测试",
    },
    token=token,
)
status, body = resp_info(resp)
assert_pass("创建知识库", resp is not None and resp.status_code == 200, f"status={status}")
kb_id = None
if resp and resp.status_code == 200:
    kb_id = resp.json().get("data", {}).get("id")
    assert_pass("获取 kb_id", kb_id is not None, f"kb_id={kb_id}")

if not kb_id:
    print("\nFATAL: 无法创建知识库，后续测试无法继续")
    sys.exit(1)


# ============================================================
# Phase 3: 文档上传测试
# ============================================================
print_header("Phase 3: 文档上传测试")

script_dir = Path(__file__).parent
test_txt_path = script_dir / "test_doc.txt"
empty_txt_path = script_dir / "empty_test.txt"
fake_exe_path = script_dir / "fake_test.exe"

# 创建测试文件
if not test_txt_path.exists():
    print(f"  [ERROR] 测试文件不存在: {test_txt_path}")
    sys.exit(1)

empty_txt_path.write_text("", encoding="utf-8")
fake_exe_path.write_bytes(b"MZ\x00\x00FAKE EXE FILE FOR TESTING")

# 3.1 正常上传 TXT
with open(test_txt_path, "rb") as f:
    resp = api_post(
        "/documents/upload",
        data={"kb_id": str(kb_id)},
        files={"file": ("test_doc.txt", f, "text/plain")},
        token=token,
    )
status, body = resp_info(resp)
assert_pass(
    "上传 TXT 文件（正常）", resp is not None and resp.status_code == 200, f"status={status}"
)
doc_id = None
if resp and resp.status_code == 200:
    data = resp.json().get("data", {})
    doc_id = data.get("document_id")
    task_id = data.get("task_id")
    assert_pass("返回 document_id", doc_id is not None, f"doc_id={doc_id}")
    assert_pass("返回 task_id", task_id is not None, f"task_id={task_id}")

# 3.2 空文件上传
with open(empty_txt_path, "rb") as f:
    resp = api_post(
        "/documents/upload",
        data={"kb_id": str(kb_id)},
        files={"file": ("empty_test.txt", f, "text/plain")},
        token=token,
    )
status, body = resp_info(resp)
if resp is not None:
    print(f"  [INFO] 空文件上传响应 status={status}, body={body}")
    assert_pass("空文件上传（应被拒绝或接受）", status in (200, 400, 422), f"status={status}")
    if status == 200:
        empty_doc_id = resp.json().get("data", {}).get("document_id")
        print(f"  [INFO] 空文件被接受，doc_id={empty_doc_id}")
else:
    assert_pass("空文件上传（请求发送失败）", False, "request returned None")

# 3.3 不支持格式上传 (.exe)
with open(fake_exe_path, "rb") as f:
    resp = api_post(
        "/documents/upload",
        data={"kb_id": str(kb_id)},
        files={"file": ("fake_test.exe", f, "application/octet-stream")},
        token=token,
    )
status, body = resp_info(resp)
assert_pass(
    "上传 .exe 文件（应被拒绝）",
    resp is not None and resp.status_code == 400,
    f"status={status}, body={body}",
)

if not doc_id:
    print("\nFATAL: 无法上传文档，部分后续测试无法继续")


# ============================================================
# Phase 4: 文档处理状态检查
# ============================================================
print_header("Phase 4: 文档处理状态检查")

if doc_id:
    # 4.1 检查进度
    resp = api_get(f"/documents/{doc_id}/progress", token=token)
    status, body = resp_info(resp)
    assert_pass(
        "获取文档处理进度", resp is not None and resp.status_code == 200, f"status={status}"
    )
    if resp and resp.status_code == 200:
        progress = resp.json().get("data", {})
        doc_status = progress.get("status", "")
        assert_pass(
            "状态为 pending/parsing/chunking/embedding/done",
            doc_status in ("pending", "parsing", "chunking", "embedding", "done"),
            f"status={doc_status}",
        )

    # 4.2 等待处理完成
    max_wait = 30
    doc_status = ""
    chunk_count = 0
    for i in range(max_wait):
        resp = api_get(f"/documents/{doc_id}/progress", token=token)
        if resp and resp.status_code == 200:
            data = resp.json().get("data", {})
            doc_status = data.get("status", "")
            chunk_count = data.get("chunk_count", 0)
            print(f"  [WAIT] ({i+1}/{max_wait}) status={doc_status}, chunk_count={chunk_count}")
            if doc_status == "done":
                break
            elif doc_status == "failed":
                print(f"  [INFO] 文档处理失败: {data.get('error_message', '')}")
                break
        time.sleep(1)

    assert_pass(
        "文档处理完成（status=done）",
        doc_status == "done",
        f"status={doc_status}, chunk_count={chunk_count}",
    )
    assert_pass("分块数 > 0", chunk_count > 0, f"chunk_count={chunk_count}")

    # 4.3 检查不存在的文档进度
    resp = api_get("/documents/99999/progress", token=token)
    status, body = resp_info(resp)
    assert_pass(
        "不存在的文档进度（应返回 404）",
        resp is not None and resp.status_code == 404,
        f"status={status}",
    )
else:
    print("  [SKIP] 没有 doc_id，跳过状态检查相关测试")


# ============================================================
# Phase 5: 文档预览
# ============================================================
print_header("Phase 5: 文档预览")

if doc_id and doc_status == "done":
    # 5.1 正常预览
    resp = api_get(f"/documents/{doc_id}/preview", params={"page": 1, "page_size": 10}, token=token)
    status, body = resp_info(resp)
    assert_pass("正常预览文档", resp is not None and resp.status_code == 200, f"status={status}")
    if resp and resp.status_code == 200:
        data = resp.json().get("data", {})
        content = data.get("content", "")
        total_lines = data.get("total_lines", 0)
        assert_pass(
            "预览返回内容不为空",
            len(content) > 0,
            f"total_lines={total_lines}, content_len={len(content)}",
        )
        assert_pass(
            "预览返回 filename",
            data.get("filename") is not None,
            f"filename={data.get('filename')}",
        )

    # 5.2 不存在的文档预览
    resp = api_get("/documents/99999/preview", token=token)
    status, body = resp_info(resp)
    assert_pass(
        "不存在的文档预览（应返回 404）",
        resp is not None and resp.status_code == 404,
        f"status={status}",
    )
else:
    print("  [SKIP] 文档未处理完成，跳过预览相关测试")
    # 仍然测试 404 场景
    resp = api_get("/documents/99999/preview", token=token)
    status, body = resp_info(resp)
    assert_pass(
        "不存在的文档预览（应返回 404）",
        resp is not None and resp.status_code == 404,
        f"status={status}",
    )


# ============================================================
# Phase 6: 重新解析
# ============================================================
print_header("Phase 6: 重新解析")

if doc_id and doc_status == "done":
    # 6.1 正常重新解析
    resp = api_post(f"/documents/{doc_id}/reparse", token=token)
    status, body = resp_info(resp)
    assert_pass("正常重新解析", resp is not None and resp.status_code == 200, f"status={status}")
    if resp and resp.status_code == 200:
        reparse_data = resp.json().get("data", {})
        assert_pass(
            "重新解析返回 task_id",
            reparse_data.get("task_id") is not None,
            f"task_id={reparse_data.get('task_id')}",
        )

    # 6.2 重新解析不存在的文档
    resp = api_post("/documents/99999/reparse", token=token)
    status, body = resp_info(resp)
    assert_pass(
        "重新解析不存在的文档（应返回 404）",
        resp is not None and resp.status_code == 404,
        f"status={status}",
    )

    # 等待重新解析完成
    print("  [INFO] 等待重新解析完成...")
    for _i in range(30):
        resp = api_get(f"/documents/{doc_id}/progress", token=token)
        if resp and resp.status_code == 200:
            s = resp.json().get("data", {}).get("status", "")
            if s == "done":
                print("  [INFO] 重新解析完成")
                break
            elif s == "failed":
                print("  [INFO] 重新解析失败")
                break
        time.sleep(1)
else:
    print("  [SKIP] 文档未处理完成，跳过重新解析相关测试")
    resp = api_post("/documents/99999/reparse", token=token)
    status, body = resp_info(resp)
    assert_pass(
        "重新解析不存在的文档（应返回 404）",
        resp is not None and resp.status_code == 404,
        f"status={status}",
    )


# ============================================================
# Phase 7: 删除文档
# ============================================================
print_header("Phase 7: 删除文档")

if doc_id:
    # 确认文档状态不是 processing
    resp = api_get(f"/documents/{doc_id}/progress", token=token)
    if resp and resp.status_code == 200:
        current_status = resp.json().get("data", {}).get("status", "")
        if current_status in ("parsing", "chunking", "embedding"):
            print(f"  [INFO] 文档正在处理中 (status={current_status})，等待完成...")
            for _i in range(30):
                time.sleep(1)
                resp = api_get(f"/documents/{doc_id}/progress", token=token)
                if resp and resp.status_code == 200:
                    current_status = resp.json().get("data", {}).get("status", "")
                    if current_status in ("done", "failed"):
                        break

    # 7.1 正常删除
    resp = api_delete(f"/documents/{doc_id}", token=token)
    status, body = resp_info(resp)
    assert_pass("正常删除文档", resp is not None and resp.status_code == 200, f"status={status}")

    # 7.2 删除不存在的文档
    resp = api_delete("/documents/99999", token=token)
    status, body = resp_info(resp)
    assert_pass(
        "删除不存在的文档（应返回 404）",
        resp is not None and resp.status_code == 404,
        f"status={status}",
    )
else:
    print("  [SKIP] 没有 doc_id，跳过删除相关测试")


# ============================================================
# Phase 8: 文档列表
# ============================================================
print_header("Phase 8: 文档列表")

# 8.1 分页正常
resp = api_get("/documents", params={"page": 1, "page_size": 10}, token=token)
status, body = resp_info(resp)
assert_pass("文档列表分页查询", resp is not None and resp.status_code == 200, f"status={status}")
if resp and resp.status_code == 200:
    data = resp.json().get("data", {})
    items = data.get("items", [])
    total = data.get("total", 0)
    assert_pass("返回 items 列表", isinstance(items, list), f"items_count={len(items)}")
    assert_pass("返回 total 字段", isinstance(total, int), f"total={total}")

# 8.2 按 kb_id 过滤
resp = api_get("/documents", params={"kb_id": kb_id, "page": 1, "page_size": 10}, token=token)
status, body = resp_info(resp)
assert_pass(
    "按 kb_id 过滤文档列表", resp is not None and resp.status_code == 200, f"status={status}"
)
if resp and resp.status_code == 200:
    data = resp.json().get("data", {})
    items = data.get("items", [])
    total = data.get("total", 0)
    assert_pass(
        "按 kb_id 过滤返回结果", isinstance(items, list), f"total={total}, items_count={len(items)}"
    )
    all_same_kb = all(item.get("kb_id") == kb_id for item in items)
    assert_pass("所有返回文档都属于指定 kb_id", all_same_kb, f"kb_id={kb_id}")

# 8.3 不存在的 kb_id 过滤（后端返回 404 因为 kb 不存在）
resp = api_get("/documents", params={"kb_id": 99999, "page": 1, "page_size": 10}, token=token)
status, body = resp_info(resp)
assert_pass(
    "不存在的 kb_id 过滤（应返回 404）",
    resp is not None and resp.status_code == 404,
    f"status={status}",
)


# ============================================================
# Phase 9: Cleanup
# ============================================================
print_header("Phase 9: 清理")

for p in [empty_txt_path, fake_exe_path]:
    try:
        if p.exists():
            p.unlink()
            print(f"  [INFO] 已删除: {p.name}")
    except Exception as e:
        print(f"  [WARN] 无法删除 {p.name}: {e}")

if kb_id:
    resp = api_delete(f"/knowledge-bases/{kb_id}", token=token)
    if resp:
        print(f"  [INFO] 已删除知识库 kb_id={kb_id} (status={resp.status_code})")


# ============================================================
# Summary
# ============================================================
print_header("测试结果汇总")

total = pass_count + fail_count
print(f"\n  PASS: {pass_count}")
print(f"  FAIL: {fail_count}")
print(f"  总计: {total}")

if fail_count > 0:
    print("\n  失败测试详情:")
    for result_type, name, detail in test_results:
        if result_type == "FAIL":
            print(f"    - {name}: {detail}")

print(f"\n{'='*60}")
if fail_count == 0:
    print("  全部测试通过!")
else:
    print(f"  有 {fail_count} 个测试失败")
print(f"{'='*60}\n")
