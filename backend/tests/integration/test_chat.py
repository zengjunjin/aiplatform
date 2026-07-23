"""Chat API 集成测试 - 真实 HTTP 流程（session CRUD）"""
import pytest


@pytest.fixture
async def user_token(client):
    user_data = {
        "username": "chat_test_user",
        "email": "chat_test@example.com",
        "password": "Test@123456",
    }
    await client.post("/api/v1/auth/register", json=user_data)
    login_r = await client.post("/api/v1/auth/login", json={
        "username": user_data["username"],
        "password": user_data["password"],
    })
    return login_r.json()["data"]["access_token"]


@pytest.fixture
def auth_headers(user_token):
    return {"Authorization": f"Bearer {user_token}"}


@pytest.mark.asyncio
@pytest.mark.integration
class TestChatSessionCRUD:
    async def test_create_session_default_title(self, client, auth_headers):
        r = await client.post("/api/v1/chat/sessions", json={
            "title": "新对话",
            "kb_id": None,
        }, headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert "id" in data
        assert data["title"] == "新对话"
        assert data["kb_id"] is None

    async def test_create_session_with_kb(self, client, auth_headers):
        kb_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "chat-kb",
            "description": "",
        }, headers=auth_headers)
        kb_id = kb_r.json()["data"]["id"]

        r = await client.post("/api/v1/chat/sessions", json={
            "title": "RAG 对话",
            "kb_id": kb_id,
        }, headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["kb_id"] == kb_id
        assert data["title"] == "RAG 对话"

    async def test_list_sessions(self, client, auth_headers):
        for i in range(3):
            await client.post("/api/v1/chat/sessions", json={
                "title": f"session-{i}",
                "kb_id": None,
            }, headers=auth_headers)
        r = await client.get("/api/v1/chat/sessions?page=1&page_size=10", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 3
        assert len(data["items"]) == 3

    async def test_get_session_detail(self, client, auth_headers):
        create_r = await client.post("/api/v1/chat/sessions", json={
            "title": "detail session",
            "kb_id": None,
        }, headers=auth_headers)
        session_id = create_r.json()["data"]["id"]

        r = await client.get(f"/api/v1/chat/sessions/{session_id}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["session"]["id"] == session_id
        assert "messages" in data

    async def test_update_session(self, client, auth_headers):
        kb_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "update-kb",
            "description": "",
        }, headers=auth_headers)
        kb_id = kb_r.json()["data"]["id"]

        create_r = await client.post("/api/v1/chat/sessions", json={
            "title": "old title",
            "kb_id": None,
        }, headers=auth_headers)
        session_id = create_r.json()["data"]["id"]

        r = await client.put(f"/api/v1/chat/sessions/{session_id}", json={
            "title": "new title",
            "kb_id": kb_id,
        }, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["data"]["title"] == "new title"
        assert r.json()["data"]["kb_id"] == kb_id

    async def test_delete_session(self, client, auth_headers):
        create_r = await client.post("/api/v1/chat/sessions", json={
            "title": "to delete",
            "kb_id": None,
        }, headers=auth_headers)
        session_id = create_r.json()["data"]["id"]

        r = await client.delete(f"/api/v1/chat/sessions/{session_id}", headers=auth_headers)
        assert r.status_code == 200

        r2 = await client.get(f"/api/v1/chat/sessions/{session_id}", headers=auth_headers)
        assert r2.status_code == 404

    async def test_get_session_not_found_404(self, client, auth_headers):
        r = await client.get("/api/v1/chat/sessions/99999", headers=auth_headers)
        assert r.status_code == 404

    async def test_access_other_user_session_403(self, client):
        user1 = {"username": "user1_c", "email": "u1@c.com", "password": "Test@123456"}
        await client.post("/api/v1/auth/register", json=user1)
        login1 = await client.post("/api/v1/auth/login", json={
            "username": user1["username"], "password": user1["password"]
        })
        token1 = login1.json()["data"]["access_token"]

        create_r = await client.post("/api/v1/chat/sessions", json={
            "title": "user1's session", "kb_id": None,
        }, headers={"Authorization": f"Bearer {token1}"})
        session_id = create_r.json()["data"]["id"]

        user2 = {"username": "user2_c", "email": "u2@c.com", "password": "Test@123456"}
        await client.post("/api/v1/auth/register", json=user2)
        login2 = await client.post("/api/v1/auth/login", json={
            "username": user2["username"], "password": user2["password"]
        })
        token2 = login2.json()["data"]["access_token"]

        r = await client.get(f"/api/v1/chat/sessions/{session_id}",
                            headers={"Authorization": f"Bearer {token2}"})
        assert r.status_code == 403
