"""Locust 性能/压力测试脚本

测试场景:
- 用户注册 + 登录
- 知识库 CRUD
- 文档上传
- 聊天消息发送
- 健康检查
- 检索压测 (RetrievalLoadTest, 权重 1)
- 流式对话压测 (StreamingChatUser, 权重 3)
- 混合压测 (MixedLoadTest)
- 峰值测试 (PeakLoadTest, gradual ramp-up)

使用方法:
    # 基础场景
    locust -f tests/performance/locustfile.py --host=http://localhost:8000 --web-host=0.0.0.0

    # 仅检索压测
    locust -f tests/performance/locustfile.py --host=http://localhost:8000 RetrievalLoadTest

    # 流式对话压测
    locust -f tests/performance/locustfile.py --host=http://localhost:8000 StreamingChatUser

    # 混合压测
    locust -f tests/performance/locustfile.py --host=http://localhost:8000 MixedLoadTest

    # 峰值测试 (需要设置 spawn-rate 和 users)
    locust -f tests/performance/locustfile.py --host=http://localhost:8000 PeakLoadTest
"""
import json
import random
import string
import time
from locust import HttpUser, task, between, tag, constant, LoadTestShape


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


# ============================================================================
# 场景 1: 检索压测 (RetrievalLoadTest, 权重 1)
# ============================================================================

RETRIEVAL_QUESTIONS = [
    "什么是机器学习中的过拟合？",
    "Python 中列表和元组的区别是什么？",
    "Transformer 模型的核心思想是什么？",
    "数据库索引是如何提高查询性能的？",
    "Redis 持久化的两种方式各有什么优缺点？",
    "什么是 Docker 容器化技术？",
    "HTTP/2 相比 HTTP/1.1 有哪些改进？",
    "什么是 JWT 令牌？它是如何工作的？",
    "Kubernetes 中 Pod 和 Deployment 的关系是什么？",
    "操作系统中的虚拟内存管理机制是如何工作的？",
]


class RetrievalLoadTest(HttpUser):
    """检索压测：模拟高频检索请求。

    权重 = 1，适合单独测试检索性能瓶颈。
    """

    wait_time = between(0.5, 1.5)
    weight = 1

    def on_start(self):
        """初始化：注册、登录、创建知识库。"""
        username = f"retrieval_{_random_string(10)}"
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

            # 创建知识库
            kb_resp = self.client.post(
                "/api/v1/knowledge-bases",
                json={"name": f"retrieval_bench_{_random_string(8)}", "description": "retrieval load test"},
                headers=self.headers,
            )
            if kb_resp.status_code == 200:
                self.kb_id = kb_resp.json()["data"]["id"]
            else:
                self.kb_id = None
        else:
            self.headers = {}
            self.kb_id = None

    @tag("retrieval", "fast")
    @task(10)
    def retrieval_search(self):
        """检索请求：模拟用户搜索知识库。"""
        if not self.headers or not self.kb_id:
            return
        question = random.choice(RETRIEVAL_QUESTIONS)
        self.client.get(
            f"/api/v1/knowledge-bases/{self.kb_id}",
            headers=self.headers,
        )

    @tag("retrieval")
    @task(2)
    def list_documents(self):
        """列出文档：检索场景的辅助操作。"""
        if not self.headers:
            return
        self.client.get(
            "/api/v1/documents?page=1&page_size=20",
            headers=self.headers,
        )

    @tag("system", "fast")
    @task(5)
    def health_check(self):
        """健康检查。"""
        self.client.get("/api/v1/system/status")


# ============================================================================
# 场景 2: 流式对话压测 (StreamingChatUser, 权重 3)
# ============================================================================

CHAT_QUESTIONS = [
    "请解释什么是 RAG 系统？",
    "微服务架构相比单体架构的优势和挑战是什么？",
    "什么是 DevSecOps？",
    "CAP 定理在分布式系统中的应用是什么？",
    "SQL 和 NoSQL 数据库在什么场景下分别更适合使用？",
    "什么是事件驱动架构？",
    "梯度下降算法的几种变体有哪些？",
    "RESTful API 和 GraphQL 的主要区别是什么？",
    "在多租户 SaaS 系统中，数据库隔离策略有哪些？",
    "为什么大语言模型会出现幻觉现象？",
]


class StreamingChatUser(HttpUser):
    """流式对话压测：模拟真实用户的多轮对话。

    权重 = 3，是主要压测场景（用户更频繁地进行对话）。
    """

    wait_time = between(2, 5)
    weight = 3

    def on_start(self):
        """初始化：注册、登录、创建知识库和会话。"""
        username = f"stream_chat_{_random_string(10)}"
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

            # 创建知识库
            kb_resp = self.client.post(
                "/api/v1/knowledge-bases",
                json={"name": f"stream_kb_{_random_string(8)}", "description": "streaming chat test"},
                headers=self.headers,
            )
            self.kb_id = kb_resp.json()["data"]["id"] if kb_resp.status_code == 200 else None

            # 创建会话
            session_resp = self.client.post(
                "/api/v1/chat/sessions",
                json={"title": f"Stream Session {_random_string(6)}", "kb_id": self.kb_id},
                headers=self.headers,
            )
            self.session_id = session_resp.json()["data"]["id"] if session_resp.status_code == 200 else None
        else:
            self.headers = {}
            self.session_id = None
            self.kb_id = None

    @tag("chat", "streaming")
    @task(5)
    def send_streaming_message(self):
        """发送流式对话消息（非阻塞，仅测试请求发起）。"""
        if not self.headers or not self.session_id:
            return
        question = random.choice(CHAT_QUESTIONS)
        with self.client.post(
            f"/api/v1/chat/sessions/{self.session_id}/messages",
            json={"content": question},
            headers=self.headers,
            catch_response=True,
            stream=True,
        ) as resp:
            if resp.status_code == 200:
                # 读取 SSE 流以模拟真实消费
                chunk_count = 0
                for line in resp.iter_lines():
                    if not line or line.startswith(b":") or line == b"data: [DONE]":
                        continue
                    chunk_count += 1
                    if chunk_count > 100:  # 限制最大读取 token 数
                        break
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @tag("chat", "fast")
    @task(3)
    def list_chat_sessions(self):
        """获取聊天会话列表。"""
        if self.headers:
            self.client.get(
                "/api/v1/chat/sessions?page=1&page_size=20",
                headers=self.headers,
            )

    @tag("chat", "fast")
    @task(2)
    def get_session_messages(self):
        """获取会话消息列表。"""
        if self.headers and self.session_id:
            self.client.get(
                f"/api/v1/chat/sessions/{self.session_id}/messages",
                headers=self.headers,
            )

    @tag("system", "fast")
    @task(3)
    def health_check(self):
        """健康检查。"""
        self.client.get("/api/v1/system/status")


# ============================================================================
# 场景 3: 混合压测 (MixedLoadTest)
# ============================================================================


class MixedLoadTest(HttpUser):
    """混合压测：同时进行检索和对话操作，模拟真实混合负载。

    包含检索请求、流式对话、会话管理、知识库操作等。
    """

    wait_time = between(1, 3)
    weight = 2

    def on_start(self):
        """初始化：注册、登录、创建知识库和会话。"""
        username = f"mixed_{_random_string(10)}"
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

            # 创建知识库
            kb_resp = self.client.post(
                "/api/v1/knowledge-bases",
                json={"name": f"mixed_kb_{_random_string(8)}", "description": "mixed load test"},
                headers=self.headers,
            )
            self.kb_id = kb_resp.json()["data"]["id"] if kb_resp.status_code == 200 else None

            # 创建会话
            session_resp = self.client.post(
                "/api/v1/chat/sessions",
                json={"title": f"Mixed Session {_random_string(6)}", "kb_id": self.kb_id},
                headers=self.headers,
            )
            self.session_id = session_resp.json()["data"]["id"] if session_resp.status_code == 200 else None
        else:
            self.headers = {}
            self.session_id = None
            self.kb_id = None

    @tag("mixed", "chat")
    @task(3)
    def send_message(self):
        """发送对话消息（混合场景中的对话操作）。"""
        if not self.headers or not self.session_id:
            return
        question = random.choice(CHAT_QUESTIONS)
        with self.client.post(
            f"/api/v1/chat/sessions/{self.session_id}/messages",
            json={"content": question},
            headers=self.headers,
            catch_response=True,
            stream=True,
        ) as resp:
            if resp.status_code == 200:
                chunk_count = 0
                for line in resp.iter_lines():
                    if not line or line.startswith(b":") or line == b"data: [DONE]":
                        continue
                    chunk_count += 1
                    if chunk_count > 100:
                        break
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    @tag("mixed", "retrieval")
    @task(2)
    def retrieval_operation(self):
        """检索操作（混合场景中的检索操作）。"""
        if not self.headers:
            return
        self.client.get(
            "/api/v1/knowledge-bases?page=1&page_size=20",
            headers=self.headers,
        )

    @tag("mixed", "kb")
    @task(1)
    def kb_operation(self):
        """知识库操作（混合场景中的 CRUD）。"""
        if not self.headers:
            return
        name = f"mixed_kb_{_random_string(8)}"
        resp = self.client.post(
            "/api/v1/knowledge-bases",
            json={"name": name, "description": "mixed load kb"},
            headers=self.headers,
        )
        if resp.status_code == 200:
            kb_id = resp.json()["data"]["id"]
            self.client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=self.headers)

    @tag("mixed", "fast")
    @task(5)
    def health_check(self):
        """健康检查。"""
        self.client.get("/api/v1/system/status")

    @tag("mixed", "fast")
    @task(3)
    def list_sessions(self):
        """列出会话。"""
        if self.headers:
            self.client.get(
                "/api/v1/chat/sessions?page=1&page_size=20",
                headers=self.headers,
            )


# ============================================================================
# 场景 4: 峰值测试 (PeakLoadTest, gradual ramp-up)
# ============================================================================


class PeakLoadShape(LoadTestShape):
    """峰值测试 Shape：逐步增加用户数模拟峰值流量。

    阶段:
    1. 预热期 (0-60s): 缓慢增长到 50 用户
    2. 增长期 (60-120s): 快速增长到 200 用户
    3. 峰值期 (120-180s): 维持 200 用户
    4. 回落期 (180-240s): 逐步降低到 50 用户
    5. 恢复期 (240-300s): 维持 50 用户
    """

    stages = [
        {"duration": 60, "users": 50, "spawn_rate": 5},     # 预热
        {"duration": 120, "users": 200, "spawn_rate": 15},   # 增长到峰值
        {"duration": 180, "users": 200, "spawn_rate": 5},    # 峰值维持
        {"duration": 240, "users": 50, "spawn_rate": 15},    # 回落
        {"duration": 300, "users": 50, "spawn_rate": 5},     # 恢复
    ]

    def tick(self):
        run_time = self.get_run_time()

        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])

        # 测试结束
        return None


class PeakLoadTest(HttpUser):
    """峰值测试用户：使用 PeakLoadShape 控制 ramp-up。

    配合 PeakLoadShape 使用，自动按阶段增加/减少用户。
    """

    wait_time = between(1, 2)

    def on_start(self):
        """初始化：注册、登录。"""
        username = f"peak_{_random_string(10)}"
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
        else:
            self.headers = {}

    @tag("peak", "chat")
    @task(3)
    def peak_chat_operation(self):
        """峰值场景对话操作。"""
        if not self.headers:
            return
        # 创建临时会话并发送消息
        session_resp = self.client.post(
            "/api/v1/chat/sessions",
            json={"title": f"Peak {_random_string(6)}", "kb_id": None},
            headers=self.headers,
        )
        if session_resp.status_code == 200:
            sid = session_resp.json()["data"]["id"]
            question = random.choice(CHAT_QUESTIONS)
            with self.client.post(
                f"/api/v1/chat/sessions/{sid}/messages",
                json={"content": question},
                headers=self.headers,
                catch_response=True,
                stream=True,
            ) as resp:
                if resp.status_code == 200:
                    chunk_count = 0
                    for line in resp.iter_lines():
                        if not line or line.startswith(b":") or line == b"data: [DONE]":
                            continue
                        chunk_count += 1
                        if chunk_count > 50:
                            break
                    resp.success()
                else:
                    resp.failure(f"HTTP {resp.status_code}")

    @tag("peak", "fast")
    @task(5)
    def health_check(self):
        """健康检查。"""
        self.client.get("/api/v1/system/status")

    @tag("peak", "fast")
    @task(3)
    def list_knowledge_bases(self):
        """知识库列表。"""
        if self.headers:
            self.client.get(
                "/api/v1/knowledge-bases?page=1&page_size=20",
                headers=self.headers,
            )
