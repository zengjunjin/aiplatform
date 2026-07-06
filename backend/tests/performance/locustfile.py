"""Locust 性能/压力测试脚本

测试场景:
- 用户注册 + 登录
- 知识库 CRUD
- 文档上传
- 聊天消息发送
- 健康检查

使用方法:
    locust -f tests/performance/locustfile.py --host=http://localhost:8000 --web-host=0.0.0.0
"""
import random
import string
from locust import HttpUser, task, between, tag


def _random_string(length=8):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


class AuthenticatedUser(HttpUser):
    """已认证用户的性能测试。"""

    wait_time = between(1, 3)

    def on_start(self):
        """每个虚拟用户启动时注册并登录。"""
        username = f"perf_user_{_random_string(10)}"
        password = "Test@123456"
        email = f"{username}@example.com"

        self.client.post(
            "/api/v1/auth/register",
            json={"username": username, "email": email, "password": password},
        )

        resp = self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        if resp.status_code == 200:
            token = resp.json()["data"]["access_token"]
            self.headers = {"Authorization": f"Bearer {token}"}
            self.kb_id = None
            self.session_id = None
        else:
            self.headers = {}

    @tag("auth", "fast")
    @task(3)
    def get_me(self):
        """获取当前用户信息。"""
        if self.headers:
            self.client.get("/api/v1/auth/me", headers=self.headers)

    @tag("kb", "fast")
    @task(2)
    def list_knowledge_bases(self):
        """获取知识库列表。"""
        if self.headers:
            self.client.get(
                "/api/v1/knowledge-bases?page=1&page_size=20",
                headers=self.headers,
            )

    @tag("kb")
    @task(1)
    def create_and_delete_kb(self):
        """创建并删除知识库。"""
        if not self.headers:
            return

        name = f"perf_kb_{_random_string(8)}"
        resp = self.client.post(
            "/api/v1/knowledge-bases",
            json={"name": name, "description": "performance test"},
            headers=self.headers,
        )
        if resp.status_code == 200:
            kb_id = resp.json()["data"]["id"]
            self.client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=self.headers)
            self.client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=self.headers)

    @tag("chat", "fast")
    @task(2)
    def list_chat_sessions(self):
        """获取聊天会话列表。"""
        if self.headers:
            self.client.get(
                "/api/v1/chat/sessions?page=1&page_size=20",
                headers=self.headers,
            )

    @tag("chat")
    @task(1)
    def create_and_delete_session(self):
        """创建并删除聊天会话。"""
        if not self.headers:
            return

        resp = self.client.post(
            "/api/v1/chat/sessions",
            json={"title": f"perf_chat_{_random_string(8)}", "kb_id": None},
            headers=self.headers,
        )
        if resp.status_code == 200:
            session_id = resp.json()["data"]["id"]
            self.client.get(
                f"/api/v1/chat/sessions/{session_id}",
                headers=self.headers,
            )
            self.client.delete(
                f"/api/v1/chat/sessions/{session_id}",
                headers=self.headers,
            )

    @tag("system", "fast")
    @task(5)
    def health_check(self):
        """健康检查（高频）。"""
        self.client.get("/api/v1/system/status")


class AnonymousUser(HttpUser):
    """匿名用户的性能测试（主要测试限流）。"""

    wait_time = between(0.5, 2)
    weight = 1

    @tag("system", "fast")
    @task(10)
    def health_check(self):
        """健康检查。"""
        self.client.get("/api/v1/system/status")

    @tag("auth")
    @task(1)
    def try_login_wrong_password(self):
        """测试错误密码登录（主要看限流）。"""
        username = f"nonexist_{_random_string(8)}"
        self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": "wrongpass"},
        )
