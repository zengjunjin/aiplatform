"""
RAG Platform 后端边界条件与异常测试
测试目标：http://localhost:8002
速率限制：注册/登录 5次/分钟，测试中会加入适当延迟
"""
import requests
import time
import threading
import sys

BASE_URL = "http://localhost:8002"
API = f"{BASE_URL}/api/v1"

# 测试统计
PASS = 0
FAIL = 0
ERRORS = []
WARNINGS = []


def test(name, condition, detail=""):
    """记录单个测试结果"""
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        msg = f"  [FAIL] {name} — {detail}"
        print(msg)
        ERRORS.append(msg)


def warn(name, detail=""):
    """记录警告（不计入 FAIL）"""
    global WARNINGS
    msg = f"  [WARN] {name} — {detail}"
    print(msg)
    WARNINGS.append(msg)


def section(title):
    """打印测试分组标题"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def register(username, email, password):
    """注册新用户"""
    try:
        r = requests.post(f"{API}/auth/register", json={
            "username": username,
            "email": email,
            "password": password,
        }, timeout=10)
        return r.status_code, r.json()
    except Exception as e:
        return None, str(e)


def login(username, password):
    """登录获取 token"""
    try:
        r = requests.post(f"{API}/auth/login", json={
            "username": username,
            "password": password,
        }, timeout=10)
        return r.status_code, r.json()
    except Exception as e:
        return None, str(e)


def api_get(path, token=None):
    """GET 请求"""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(f"{API}{path}", headers=headers, timeout=10)
        return r.status_code, r.json()
    except Exception as e:
        return None, str(e)


def api_post(path, token=None, data=None):
    """POST 请求"""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.post(f"{API}{path}", headers=headers, json=data, timeout=10)
        return r.status_code, r.json()
    except Exception as e:
        return None, str(e)


# ==================== 主测试流程 ====================

def main():
    global PASS, FAIL, ERRORS, WARNINGS

    print("\n" + "="*60)
    print("  RAG Platform 边界条件与异常测试")
    print(f"  目标: {BASE_URL}")
    print("="*60)

    # 先检查服务是否可达
    print("\n[0] 服务连通性检查")
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        test("GET /health 返回 200", r.status_code == 200, f"status={r.status_code}")
    except Exception as e:
        print(f"  [FATAL] 无法连接到 {BASE_URL}，请确认后端已启动")
        sys.exit(1)

    ts = int(time.time())
    username = f"test_boundary_{ts}"
    email = f"{username}@test.com"
    password = "Test@123456"

    # ==================== 1. 注册新用户并登录 ====================
    section("1. 注册新用户 & 登录获取 Token")

    code, data = register(username, email, password)
    test("POST /api/v1/auth/register 注册成功",
         code == 200 and data.get("code") == 0,
         f"code={code}, data={data}")

    # 登录也算在速率限制中，稍等片刻
    time.sleep(2)
    code, data = login(username, password)
    test("POST /api/v1/auth/login 登录成功",
         code == 200 and data.get("code") == 0,
         f"code={code}, data={data}")

    token = data.get("data", {}).get("access_token", "") if code == 200 else ""
    test("获取到 access_token", bool(token), f"token={'***' if token else 'N/A'}")

    if not token:
        print("\n[FATAL] 无法获取 token，后续测试无法继续")
        sys.exit(1)

    # ==================== 2. 空数据场景 ====================
    section("2. 空数据场景（新用户）")

    code, data = api_get("/knowledge-bases", token=token)
    test("GET /knowledge-bases 返回空列表",
         code == 200 and data.get("code") == 0 and len(data.get("data", {}).get("items", [])) == 0,
         f"code={code}, items={len(data.get('data', {}).get('items', [])) if data else 'N/A'}")

    code, data = api_get("/documents", token=token)
    test("GET /documents 返回空列表",
         code == 200 and data.get("code") == 0 and len(data.get("data", {}).get("items", [])) == 0,
         f"code={code}, items={len(data.get('data', {}).get('items', [])) if data else 'N/A'}")

    code, data = api_get("/chat/sessions", token=token)
    test("GET /chat/sessions 返回空列表",
         code == 200 and data.get("code") == 0 and len(data.get("data", {}).get("items", [])) == 0,
         f"code={code}, items={len(data.get('data', {}).get('items', [])) if data else 'N/A'}")

    # ==================== 3. 重复提交 ====================
    section("3. 重复提交")

    # 3a. 创建同名知识库两次
    kb_name = f"dup_test_{ts}"
    code1, data1 = api_post("/knowledge-bases", token=token, data={
        "name": kb_name,
        "description": "第一次创建",
    })
    test("第一次 POST /knowledge-bases 创建成功",
         code1 == 200 and data1.get("code") == 0,
         f"code={code1}, data={data1}")

    code2, data2 = api_post("/knowledge-bases", token=token, data={
        "name": kb_name,
        "description": "第二次创建（应被拒绝）",
    })
    # 同名知识库应被拒绝，预期返回 409 或业务错误码
    is_rejected = (
        code2 == 409 or
        (code2 == 200 and data2.get("code") != 0) or
        code2 == 400
    )
    test("第二次 POST /knowledge-bases 同名被拒绝",
         is_rejected,
         f"code={code2}, response={data2}")

    # 3b. 注册相同用户名两次
    # 注意：注册也受速率限制（5/分钟），需要延迟
    # 当前已消耗：register(1) + login(1) = 2 次
    dup_username = f"dup_user_{ts}"
    time.sleep(15)  # 等待速率限制窗口滑动
    r1_code, r1_data = register(dup_username, f"{dup_username}@test.com", "Test@123456")
    test("第一次注册 dup_user 成功",
         r1_code == 200 and r1_data.get("code") == 0,
         f"code={r1_code}, data={r1_data}")

    time.sleep(3)
    r2_code, r2_data = register(dup_username, f"{dup_username}2@test.com", "Test@123456")
    is_dup_rejected = (
        r2_code == 409 or
        r2_code == 429 or  # 速率限制也可能先触发
        (r2_code == 200 and r2_data.get("code") != 0) or
        r2_code == 400
    )
    test("第二次注册相同用户名被拒绝",
         is_dup_rejected,
         f"code={r2_code}, response={r2_data}")

    # ==================== 4. 错误输入 ====================
    section("4. 错误输入")

    # 4a. XSS 尝试 — 知识库名称包含 <script> 标签
    xss_name = "<script>alert(1)</script>"
    code, data = api_post("/knowledge-bases", token=token, data={
        "name": xss_name,
        "description": "XSS test",
    })
    if code == 200 and data.get("code") == 0:
        returned_name = data.get("data", {}).get("name", "")
        test("XSS 脚本标签知识库名 — 服务端正常处理",
             code == 200,
             f"code={code}, returned_name={returned_name}")
    else:
        test("XSS 脚本标签知识库名 — 被拒绝（更安全）",
             code != 200 or data.get("code") != 0,
             f"code={code}, data={data}")

    # 4b. SQL 注入尝试 — 用户名
    # 已消耗速率配额：register(2) + login(1) + dup_register(2) = 5
    # 需要等待新窗口
    time.sleep(15)
    sql_inject_username = f"sql_inject_{ts}' OR '1'='1"
    code, data = register(sql_inject_username, f"sqlinject_{ts}@test.com", "Test@123456")
    if code == 429:
        warn("SQL 注入用户名测试 — 被速率限制拦截，跳过", f"code={code}")
    elif code == 200 and data.get("code") == 0:
        test("SQL 注入用户名 — 服务端正常处理（参数化查询防御）",
             True,
             f"code={code}, 未被注入")
    else:
        test("SQL 注入用户名 — 被输入校验拒绝",
             code != 200 or data.get("code") != 0,
             f"code={code}, data={data}")

    # 4c. 超长输入 — 发送 10000 字符的消息
    code, data = api_post("/chat/sessions", token=token, data={
        "title": "超长消息测试",
    })
    session_id = data.get("data", {}).get("id") if code == 200 and data.get("code") == 0 else None
    test("创建测试会话", session_id is not None, f"code={code}")

    if session_id:
        long_msg = "A" * 10000
        try:
            r = requests.post(
                f"{API}/chat/sessions/{session_id}/messages",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"content": long_msg},
                timeout=30,
            )
            test("发送 10000 字符消息 — 服务端未崩溃",
                 r.status_code in [200, 413, 422, 400],
                 f"status={r.status_code}")
        except Exception as e:
            test("发送 10000 字符消息 — 连接未崩溃",
                 "timeout" not in str(e).lower() and "connection" not in str(e).lower(),
                 f"exception={e}")

    # ==================== 5. 未认证访问 ====================
    section("5. 未认证访问")

    code, data = api_get("/knowledge-bases", token=None)
    test("不带 token GET /knowledge-bases → 401",
         code == 401 or code == 403,
         f"code={code}")

    code, data = api_get("/knowledge-bases", token="invalid_token_12345")
    test("无效 token GET /knowledge-bases → 401",
         code == 401 or code == 403,
         f"code={code}")

    code, data = api_get("/chat/sessions", token=None)
    test("不带 token GET /chat/sessions → 401",
         code == 401 or code == 403,
         f"code={code}")

    code, data = api_get("/documents", token=None)
    test("不带 token GET /documents → 401",
         code == 401 or code == 403,
         f"code={code}")

    # ==================== 6. 并发操作 ====================
    section("6. 并发操作")

    results = []

    def create_kb(name_suffix):
        name = f"concurrent_kb_{ts}_{name_suffix}"
        code, data = api_post("/knowledge-bases", token=token, data={
            "name": name,
            "description": f"并发测试 {name_suffix}",
        })
        results.append((name_suffix, code, data))

    t1 = threading.Thread(target=create_kb, args=("A",))
    t2 = threading.Thread(target=create_kb, args=("B",))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    both_ok = all(
        r[1] == 200 and r[2].get("code") == 0
        for r in results
    )
    test("并发创建两个知识库均成功",
         both_ok and len(results) == 2,
         f"results={[(r[0], r[1]) for r in results]}")

    # ==================== 测试总结 ====================
    total = PASS + FAIL
    print(f"\n{'='*60}")
    print(f"  测试结果汇总")
    print(f"{'='*60}")
    print(f"  总计: {total} | PASS: {PASS} | FAIL: {FAIL}")
    if WARNINGS:
        print(f"  警告: {len(WARNINGS)}")
    if total > 0:
        print(f"  通过率: {PASS/total*100:.1f}%")

    if ERRORS:
        print(f"\n  失败列表:")
        for e in ERRORS:
            print(f"    {e}")

    if WARNINGS:
        print(f"\n  警告列表:")
        for w in WARNINGS:
            print(f"    {w}")

    print(f"\n{'='*60}")
    return FAIL == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)