"""知识库 + 文档 集成测试 - 真实 HTTP 流程"""
import pytest
import tempfile
import os
from unittest.mock import patch, MagicMock


@pytest.fixture
async def user_token(client):
    user_data = {
        "username": "kb_test_user",
        "email": "kb_test@example.com",
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
class TestKnowledgeBaseCRUD:
    async def test_create_kb_success(self, client, auth_headers):
        r = await client.post("/api/v1/knowledge-bases", json={
            "name": "我的知识库",
            "description": "测试知识库",
        }, headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["name"] == "我的知识库"
        assert data["description"] == "测试知识库"
        assert "id" in data

    async def test_list_kbs_pagination(self, client, auth_headers):
        for i in range(3):
            await client.post("/api/v1/knowledge-bases", json={
                "name": f"kb-{i}",
                "description": f"desc-{i}",
            }, headers=auth_headers)
        r = await client.get("/api/v1/knowledge-bases?page=1&page_size=2", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 3
        assert len(data["items"]) == 2
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["total_pages"] == 2

    async def test_get_kb_detail(self, client, auth_headers):
        create_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "detail-kb",
            "description": "detail desc",
        }, headers=auth_headers)
        kb_id = create_r.json()["data"]["id"]

        r = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["id"] == kb_id
        assert data["name"] == "detail-kb"

    async def test_update_kb(self, client, auth_headers):
        create_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "old-name",
            "description": "old-desc",
        }, headers=auth_headers)
        kb_id = create_r.json()["data"]["id"]

        r = await client.put(f"/api/v1/knowledge-bases/{kb_id}", json={
            "name": "new-name",
            "description": "new-desc",
        }, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["data"]["name"] == "new-name"

    async def test_delete_kb(self, client, auth_headers):
        create_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "to-delete",
            "description": "",
        }, headers=auth_headers)
        kb_id = create_r.json()["data"]["id"]

        r = await client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)
        assert r.status_code == 200

        r2 = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers)
        assert r2.status_code == 404

    async def test_get_kb_not_found_404(self, client, auth_headers):
        r = await client.get("/api/v1/knowledge-bases/99999", headers=auth_headers)
        assert r.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
class TestDocumentAPI:
    async def test_list_documents_empty(self, client, auth_headers):
        kb_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "docs-kb",
            "description": "",
        }, headers=auth_headers)
        kb_id = kb_r.json()["data"]["id"]

        r = await client.get(f"/api/v1/documents?kb_id={kb_id}", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 0
        assert data["items"] == []

    async def test_upload_text_document(self, client, auth_headers):
        kb_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "upload-kb",
            "description": "",
        }, headers=auth_headers)
        kb_id = kb_r.json()["data"]["id"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         encoding="utf-8") as f:
            f.write("这是一个测试文档的内容。\nHello world!")
            path = f.name

        try:
            with open(path, "rb") as f:
                r = await client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("test.txt", f, "text/plain")},
                    data={"kb_id": str(kb_id)},
                    headers=auth_headers,
                )
            assert r.status_code == 200
            data = r.json()["data"]
            assert "document_id" in data
            assert data["status"] == "pending"
            assert "task_id" in data
        finally:
            os.unlink(path)

    async def test_get_document_detail(self, client, auth_headers):
        kb_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "detail-doc-kb",
            "description": "",
        }, headers=auth_headers)
        kb_id = kb_r.json()["data"]["id"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         encoding="utf-8") as f:
            f.write("测试文档")
            path = f.name

        try:
            with open(path, "rb") as f:
                upload_r = await client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("mydoc.txt", f, "text/plain")},
                    data={"kb_id": str(kb_id)},
                    headers=auth_headers,
                )
            doc_id = upload_r.json()["data"]["document_id"]

            r = await client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
            assert r.status_code == 200
            data = r.json()["data"]
            assert data["id"] == doc_id
            assert data["filename"] == "mydoc.txt"
        finally:
            os.unlink(path)

    async def test_get_document_not_found(self, client, auth_headers):
        r = await client.get("/api/v1/documents/99999", headers=auth_headers)
        assert r.status_code == 404

    async def test_delete_document(self, client, auth_headers):
        kb_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "del-doc-kb",
            "description": "",
        }, headers=auth_headers)
        kb_id = kb_r.json()["data"]["id"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         encoding="utf-8") as f:
            f.write("todelete")
            path = f.name

        try:
            # Mock Celery 任务派发, 防止真实 worker 在删除前将文档状态
            # 从 "pending" 改为 "parsing" 导致 409 Conflict
            with patch(
                "app.tasks.document_task.parse_document_task.delay",
                return_value=MagicMock(id="test-task-id"),
            ):
                with open(path, "rb") as f:
                    upload_r = await client.post(
                        "/api/v1/documents/upload",
                        files={"file": ("del.txt", f, "text/plain")},
                        data={"kb_id": str(kb_id)},
                        headers=auth_headers,
                    )
            doc_id = upload_r.json()["data"]["document_id"]

            r = await client.delete(f"/api/v1/documents/{doc_id}", headers=auth_headers)
            assert r.status_code == 200

            r2 = await client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
            assert r2.status_code == 404
        finally:
            os.unlink(path)

    async def test_upload_unsupported_extension(self, client, auth_headers):
        kb_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "bad-kb",
            "description": "",
        }, headers=auth_headers)
        kb_id = kb_r.json()["data"]["id"]

        with tempfile.NamedTemporaryFile(mode="wb", suffix=".exe", delete=False) as f:
            f.write(b"\x00\x00")
            path = f.name

        try:
            with open(path, "rb") as f:
                r = await client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("bad.exe", f, "application/octet-stream")},
                    data={"kb_id": str(kb_id)},
                    headers=auth_headers,
                )
            assert r.status_code == 400
        finally:
            os.unlink(path)
