"""
RAG Platform 用户认证全流程 API 测试
测试后端运行在 http://localhost:8002
"""

import json
import random
import string
import sys
import time

import requests

BASE_URL = "http://localhost:8002/api/v1"
passed = 0
failed = 0
total = 0

# 存储测试过程中注册的用户信息
test_user = None
test_token = None
test_refresh_token = None


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test(name, condition, detail=""):
    global passed, failed, total
    total += 1
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}  --  {detail}")


def random_username():
    return "testusr_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


def api(method, path, json_data=None, token=None, expected_status=None, max_retries=3):
    """发起 API 请求，自动处理 429 限流重试"""
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    for attempt in range(max_retries):
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, timeout=15)
            elif method == "POST":
                resp = requests.post(url, headers=headers, json=json_data, timeout=15)
            elif method == "PUT":
                resp = requests.put(url, headers=headers, json=json_data, timeout=15)
            else:
                resp = requests.request(method, url, headers=headers, json=json_data, timeout=15)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 2))
                wait = max(retry_after, 3)
                if attempt < max_retries - 1:
                    print(f"    [限流] 等待 {wait}s 后重试... (attempt {attempt+1}/{max_retries})")
                    time.sleep(wait)
                    continue
            return resp
        except requests.exceptions.ConnectionError:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise
    return resp  # 最后一次尝试返回


# ============================================================
# 1. 注册测试
# ============================================================
section("1. 注册新用户 (POST /api/v1/auth/register)")

username = random_username()
email = f"{username}@test.com"
password = "Test@123456"

# 1.1 正常注册
resp = api(
    "POST",
    "/auth/register",
    json_data={
        "username": username,
        "email": email,
        "password": password,
    },
)
test(
    "1.1 正常注册返回 200",
    resp.status_code == 200,
    f"status={resp.status_code}, body={resp.text[:200]}",
)
if resp.status_code == 200:
    data = resp.json()
    test(
        "1.1 返回 data 中包含 username",
        data.get("data", {}).get("username") == username,
        f"data={json.dumps(data, ensure_ascii=False)[:200]}",
    )
    test(
        "1.1 返回 data 中包含 email",
        data.get("data", {}).get("email") == email,
        f"data={json.dumps(data, ensure_ascii=False)[:200]}",
    )
    test(
        "1.1 返回的 role 为 user",
        data.get("data", {}).get("role") == "user",
        f"role={data.get('data', {}).get('role')}",
    )
    test_user = data.get("data", {})
else:
    test_user = None

# 1.2 弱密码注册
resp = api(
    "POST",
    "/auth/register",
    json_data={
        "username": random_username(),
        "email": f"{random_username()}@test.com",
        "password": "123",
    },
)
test(
    "1.2 弱密码 '123' 注册被拒绝",
    resp.status_code in [400, 422],
    f"status={resp.status_code}, body={resp.text[:200]}",
)

# 1.3 重复用户名注册
if test_user:
    resp = api(
        "POST",
        "/auth/register",
        json_data={
            "username": username,
            "email": f"another_{username}@test.com",
            "password": password,
        },
    )
    test(
        "1.3 重复用户名注册被拒绝",
        resp.status_code in [400, 409],
        f"status={resp.status_code}, body={resp.text[:200]}",
    )
else:
    test("1.3 重复用户名注册被拒绝", False, "SKIP: 无注册成功的用户")

# 1.4 邮箱格式错误
resp = api(
    "POST",
    "/auth/register",
    json_data={
        "username": random_username(),
        "email": "notanemail",
        "password": password,
    },
)
test(
    "1.4 邮箱格式错误被拒绝",
    resp.status_code in [400, 422],
    f"status={resp.status_code}, body={resp.text[:200]}",
)


# ============================================================
# 2. 登录测试
# ============================================================
section("2. 登录 (POST /api/v1/auth/login)")

# 2.1 正确密码登录
resp = api(
    "POST",
    "/auth/login",
    json_data={
        "username": username,
        "password": password,
    },
)
test(
    "2.1 正确密码登录返回 200",
    resp.status_code == 200,
    f"status={resp.status_code}, body={resp.text[:200]}",
)
if resp.status_code == 200:
    data = resp.json()
    test_token = data.get("data", {}).get("access_token")
    test_refresh_token = data.get("data", {}).get("refresh_token")
    test(
        "2.1 返回 access_token", test_token is not None, f"token={'***' if test_token else 'None'}"
    )
    test(
        "2.1 返回 refresh_token",
        test_refresh_token is not None,
        f"refresh={'***' if test_refresh_token else 'None'}",
    )
    test(
        "2.1 token_type 为 bearer",
        data.get("data", {}).get("token_type") == "bearer",
        f"token_type={data.get('data', {}).get('token_type')}",
    )
    test(
        "2.1 返回 user 信息",
        data.get("data", {}).get("user") is not None,
        f"user={data.get('data', {}).get('user')}",
    )
else:
    test_token = None
    test_refresh_token = None

# 2.2 错误密码登录
resp = api(
    "POST",
    "/auth/login",
    json_data={
        "username": username,
        "password": "WrongPassword@999",
    },
)
test(
    "2.2 错误密码登录返回 401",
    resp.status_code == 401,
    f"status={resp.status_code}, body={resp.text[:200]}",
)

# 2.3 空字段 - 不传 username
resp = api(
    "POST",
    "/auth/login",
    json_data={
        "password": password,
    },
)
test(
    "2.3 不传 username 返回 422",
    resp.status_code in [400, 422],
    f"status={resp.status_code}, body={resp.text[:200]}",
)

# 2.3b 空字段 - 不传 password
resp = api(
    "POST",
    "/auth/login",
    json_data={
        "username": username,
    },
)
test(
    "2.3b 不传 password 返回 422",
    resp.status_code in [400, 422],
    f"status={resp.status_code}, body={resp.text[:200]}",
)

# 2.4 不存在的用户登录
resp = api(
    "POST",
    "/auth/login",
    json_data={
        "username": "nonexistent_user_xyz_99999",
        "password": "SomePass@123",
    },
)
test(
    "2.4 不存在的用户登录返回 401",
    resp.status_code == 401,
    f"status={resp.status_code}, body={resp.text[:200]}",
)


# ============================================================
# 3. 注销测试
# ============================================================
section("3. 注销 (POST /api/v1/auth/logout)")

if test_token:
    resp = api(
        "POST", "/auth/logout", json_data={"refresh_token": test_refresh_token}, token=test_token
    )
    test(
        "3.1 正常注销返回 200",
        resp.status_code == 200,
        f"status={resp.status_code}, body={resp.text[:200]}",
    )
else:
    test("3.1 正常注销返回 200", False, "SKIP: 无 token")


# ============================================================
# 4. 密码修改测试
# ============================================================
section("4. 密码修改 (PUT /api/v1/auth/password)")

pwd_username = random_username()
pwd_email = f"{pwd_username}@test.com"
pwd_original = "Test@123456"
pwd_new = "NewPass@999999"

# 注册
resp = api(
    "POST",
    "/auth/register",
    json_data={
        "username": pwd_username,
        "email": pwd_email,
        "password": pwd_original,
    },
)
pwd_token = None
if resp.status_code == 200:
    resp = api(
        "POST",
        "/auth/login",
        json_data={
            "username": pwd_username,
            "password": pwd_original,
        },
    )
    if resp.status_code == 200:
        pwd_token = resp.json().get("data", {}).get("access_token")

# 4.1 正确旧密码修改
if pwd_token:
    resp = api(
        "PUT",
        "/auth/password",
        json_data={
            "old_password": pwd_original,
            "new_password": pwd_new,
        },
        token=pwd_token,
    )
    test(
        "4.1 正确旧密码修改成功",
        resp.status_code == 200,
        f"status={resp.status_code}, body={resp.text[:200]}",
    )
else:
    test("4.1 正确旧密码修改成功", False, "SKIP: 无法获取 token")

# 4.2 错误旧密码修改
if pwd_token:
    resp = api(
        "PUT",
        "/auth/password",
        json_data={
            "old_password": "WrongOldP@ss1",
            "new_password": "Another@123456",
        },
        token=pwd_token,
    )
    test(
        "4.2 错误旧密码修改失败",
        resp.status_code in [400, 401],
        f"status={resp.status_code}, body={resp.text[:200]}",
    )
else:
    test("4.2 错误旧密码修改失败", False, "SKIP: 无 token")

# 4.3 新密码不一致（confirm_password 不匹配）
# 注意：后端 ChangePasswordRequest schema 没有 confirm_password 字段
# 传了 extra 字段会被 Pydantic 忽略，密码修改实际会成功（仅使用 new_password）
if pwd_token:
    resp = api(
        "PUT",
        "/auth/password",
        json_data={
            "old_password": pwd_new,  # 4.1 已改为 pwd_new
            "new_password": "Mismatch@12345",
            "confirm_password": "Different@67890",
        },
        token=pwd_token,
    )
    test(
        "4.3 新密码 confirm_password 不匹配应被拒绝",
        resp.status_code in [400, 422],
        f"status={resp.status_code}, 发现: 后端 schema 无 confirm_password 字段，extra 字段被忽略"
        f" body={resp.text[:200]}",
    )
else:
    test("4.3 新密码 confirm_password 不匹配应被拒绝", False, "SKIP: 无 token")


# ============================================================
# 5. 权限验证测试
# ============================================================
section("5. 权限验证 - 普通用户访问 admin 接口")

perm_username = random_username()
perm_email = f"{perm_username}@test.com"
perm_password = "Test@123456"

resp = api(
    "POST",
    "/auth/register",
    json_data={
        "username": perm_username,
        "email": perm_email,
        "password": perm_password,
    },
)
perm_token = None
if resp.status_code == 200:
    resp = api(
        "POST",
        "/auth/login",
        json_data={
            "username": perm_username,
            "password": perm_password,
        },
    )
    if resp.status_code == 200:
        perm_token = resp.json().get("data", {}).get("access_token")

# 5.1 普通用户访问 /chat/feedback/stats (admin only)
if perm_token:
    resp = api("GET", "/chat/feedback/stats", token=perm_token)
    test(
        "5.1 普通用户 GET /chat/feedback/stats 返回 403",
        resp.status_code == 403,
        f"status={resp.status_code}, body={resp.text[:200]}",
    )
else:
    test("5.1 普通用户 GET /chat/feedback/stats 返回 403", False, "SKIP: 无 token")

# 5.2 普通用户访问 /users (admin only)
if perm_token:
    resp = api("GET", "/users", token=perm_token)
    test(
        "5.2 普通用户 GET /users 返回 403",
        resp.status_code == 403,
        f"status={resp.status_code}, body={resp.text[:200]}",
    )
else:
    test("5.2 普通用户 GET /users 返回 403", False, "SKIP: 无 token")


# ============================================================
# 结果汇总
# ============================================================
section("测试结果汇总")
print(f"  总计: {total} 个测试")
print(f"  通过: {passed} 个")
print(f"  失败: {failed} 个")
print(f"  通过率: {passed / total * 100:.1f}%" if total > 0 else "  通过率: N/A")
print()

if failed > 0:
    sys.exit(1)
else:
    sys.exit(0)
