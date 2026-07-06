"""RAG 管道集成测试 - 真实 Ollama + Qdrant + PostgreSQL + Redis

测试完整流程:
- 上传文档 -> 处理文档 (真实 embedding)
- 混合检索 (BM25 + 向量 + RRF)
- RAG 聊天 (真实 LLM)
"""
import pytest
import tempfile
import os
import asyncio

from app.tasks.document_task import _parse_and_chunk, _embed_and_store, _update_progress
from app.db.sync_session import get_sync_session
from app.db.document import Document


@pytest.fixture
async def user_token(client):
    user_data = {
        "username": "rag_test_user",
        "email": "rag_test@example.com",
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


def _process_document_sync(doc_id: int):
    """同步处理文档（模拟 Celery 任务，用于测试）。"""
    try:
        _update_progress(doc_id, "processing", 10)
        chunks = _parse_and_chunk(doc_id)
        _update_progress(doc_id, "embedding", 50, chunk_count=len(chunks))
        _embed_and_store(doc_id, chunks)

        from app.rag.bm25 import bm25_store
        session = get_sync_session()
        try:
            from sqlalchemy import text
            result = session.execute(
                text(
                    "SELECT id, doc_id, content, chunk_index "
                    "FROM document_chunks WHERE doc_id = :doc_id ORDER BY id"
                ),
                {"doc_id": doc_id},
            )
            rows = result.fetchall()
            chunk_list = [
                {
                    "chunk_id": r[0],
                    "doc_id": r[1],
                    "content": r[2],
                    "chunk_index": r[3],
                }
                for r in rows
            ]
        finally:
            session.close()

        s2 = get_sync_session()
        try:
            doc_obj = s2.get(Document, doc_id)
            if doc_obj:
                bm25_store.add_documents_sync(doc_obj.kb_id, chunk_list)
        finally:
            s2.close()

        _update_progress(doc_id, "ready", 100, chunk_count=len(chunks))
    except Exception as e:
        _update_progress(doc_id, "failed", 0, error=str(e))
        raise


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.integration
@pytest.mark.real_rag
class TestRealRAGPipeline:
    """使用真实 Ollama + Qdrant 的 RAG 全链路测试。"""

    SAMPLE_CONTENT = """Python 是一种高级编程语言，由 Guido van Rossum 于 1991 年首次发布。
Python 的设计哲学强调代码的可读性和简洁的语法。
Python 支持多种编程范式，包括面向对象、命令式、函数式和过程式编程。
Python 广泛应用于 Web 开发、数据科学、人工智能、自动化运维等领域。
Python 的标准库非常丰富，涵盖了网络、文件、GUI、数据库等各个方面。
Django 和 Flask 是 Python 最流行的 Web 框架。
NumPy、Pandas 和 Matplotlib 是数据科学领域的常用库。
TensorFlow 和 PyTorch 是深度学习领域的主流框架。
Python 是解释型语言，不需要编译即可运行。
Python 使用缩进作为代码块的分隔符，这是它最显著的特征之一。
"""

    async def test_full_rag_pipeline_upload_and_retrieve(self, client, auth_headers):
        """完整流程: 上传 -> 处理 -> 检索。"""
        kb_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "RAG 测试知识库",
            "description": "用于测试真实 RAG 管道",
        }, headers=auth_headers)
        assert kb_r.status_code == 200
        kb_id = kb_r.json()["data"]["id"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         encoding="utf-8") as f:
            f.write(self.SAMPLE_CONTENT)
            path = f.name

        try:
            with open(path, "rb") as f:
                upload_r = await client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("python_intro.txt", f, "text/plain")},
                    data={"kb_id": str(kb_id)},
                    headers=auth_headers,
                )
            assert upload_r.status_code == 200
            doc_id = upload_r.json()["data"]["document_id"]

            await asyncio.to_thread(_process_document_sync, doc_id)

            doc_r = await client.get(f"/api/v1/documents/{doc_id}", headers=auth_headers)
            assert doc_r.status_code == 200
            doc_data = doc_r.json()["data"]
            assert doc_data["status"] == "ready"
            assert doc_data["chunk_count"] > 0

            from app.rag.retriever import retriever
            results = await retriever.retrieve("Python 是什么语言？", kb_id, top_k=5)
            assert isinstance(results, list)
            assert len(results) > 0

            top_result = results[0]
            assert "content" in top_result
            assert "score" in top_result
            assert "chunk_id" in top_result

            text_lower = top_result["content"].lower()
            assert "python" in text_lower

        finally:
            os.unlink(path)

    async def test_vector_search_relevance(self, client, auth_headers):
        """验证向量检索的相关性。"""
        kb_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "向量检索测试库",
            "description": "",
        }, headers=auth_headers)
        kb_id = kb_r.json()["data"]["id"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         encoding="utf-8") as f:
            f.write(self.SAMPLE_CONTENT)
            path = f.name

        try:
            with open(path, "rb") as f:
                upload_r = await client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("vector_test.txt", f, "text/plain")},
                    data={"kb_id": str(kb_id)},
                    headers=auth_headers,
                )
            doc_id = upload_r.json()["data"]["document_id"]
            await asyncio.to_thread(_process_document_sync, doc_id)

            from app.rag.retriever import retriever
            results = await retriever.retrieve("深度学习框架", kb_id, top_k=3)
            assert len(results) >= 1

            all_content = " ".join(r["content"].lower() for r in results)
            has_topic = any(
                kw in all_content
                for kw in ["tensorflow", "pytorch", "深度学习", "deep learning"]
            )
            assert has_topic, f"Expected deep learning related content, got: {all_content[:300]}"

        finally:
            os.unlink(path)

    async def test_bm25_keyword_search(self, client, auth_headers):
        """BM25 关键词检索测试。"""
        kb_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "BM25 测试库",
            "description": "",
        }, headers=auth_headers)
        kb_id = kb_r.json()["data"]["id"]

        ai_content = """
人工智能（Artificial Intelligence，AI）是计算机科学的一个分支。
机器学习（Machine Learning）是人工智能的一个子领域。
深度学习（Deep Learning）是机器学习的一个子领域，使用神经网络。
自然语言处理（NLP）是人工智能的重要应用方向。
计算机视觉（CV）是人工智能的另一个重要应用方向。
强化学习（Reinforcement Learning）是机器学习的一种方法。
Transformer 架构是深度学习领域的重要突破。
注意力机制（Attention Mechanism）是 Transformer 的核心。
GPT 系列模型是基于 Transformer 的大语言模型。
BERT 是另一种重要的预训练语言模型。
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         encoding="utf-8") as f:
            f.write(ai_content)
            path = f.name

        try:
            with open(path, "rb") as f:
                upload_r = await client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("bm25_test.txt", f, "text/plain")},
                    data={"kb_id": str(kb_id)},
                    headers=auth_headers,
                )
            doc_id = upload_r.json()["data"]["document_id"]
            await asyncio.to_thread(_process_document_sync, doc_id)

            from app.rag.retriever import retriever
            results = await retriever.retrieve("Transformer 架构", kb_id, top_k=3)
            assert len(results) > 0

            top_content = results[0]["content"]
            has_transformer = "transformer" in top_content.lower() or "Transformer" in top_content
            assert has_transformer, f"Expected Transformer content, got: {top_content[:200]}"

        finally:
            os.unlink(path)


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.integration
@pytest.mark.e2e
class TestE2EUserJourneyFast:
    """快速 E2E 测试: 注册 -> 建库 -> 上传 -> 处理 -> 会话 CRUD -> 登出。

    不包含 LLM 生成，仅验证完整业务流程的 API 链路。
    """

    PYTHON_CONTENT = """Python 是一种高级编程语言，由 Guido van Rossum 于 1991 年首次发布。
Python 的设计哲学强调代码的可读性和简洁的语法。
Python 支持多种编程范式，包括面向对象、命令式、函数式和过程式编程。
Python 广泛应用于 Web 开发、数据科学、人工智能、自动化运维等领域。
Django 和 Flask 是 Python 最流行的 Web 框架。
NumPy、Pandas 和 Matplotlib 是数据科学领域的常用库。
TensorFlow 和 PyTorch 是深度学习领域的主流框架。
"""

    async def test_complete_user_journey_fast(self, client):
        """快速用户旅程测试（无 LLM 生成）。"""
        import time
        username = "e2e_fast_" + str(int(time.time()))
        user_data = {
            "username": username,
            "email": f"{username}@example.com",
            "password": "Test@123456",
        }

        reg_r = await client.post("/api/v1/auth/register", json=user_data)
        assert reg_r.status_code == 200

        login_r = await client.post("/api/v1/auth/login", json={
            "username": user_data["username"],
            "password": user_data["password"],
        })
        assert login_r.status_code == 200
        token = login_r.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        me_r = await client.get("/api/v1/auth/me", headers=headers)
        assert me_r.status_code == 200
        assert me_r.json()["data"]["username"] == username

        kb_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "我的第一个知识库",
            "description": "E2E 测试知识库",
        }, headers=headers)
        assert kb_r.status_code == 200
        kb_id = kb_r.json()["data"]["id"]

        list_kb_r = await client.get("/api/v1/knowledge-bases?page=1&page_size=10", headers=headers)
        assert list_kb_r.status_code == 200
        assert list_kb_r.json()["data"]["total"] == 1

        kb_detail_r = await client.get(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
        assert kb_detail_r.status_code == 200
        assert kb_detail_r.json()["data"]["name"] == "我的第一个知识库"

        update_kb_r = await client.put(f"/api/v1/knowledge-bases/{kb_id}", json={
            "name": "更新后的知识库",
            "description": "新描述",
        }, headers=headers)
        assert update_kb_r.status_code == 200
        assert update_kb_r.json()["data"]["name"] == "更新后的知识库"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         encoding="utf-8") as f:
            f.write(self.PYTHON_CONTENT)
            path = f.name

        try:
            with open(path, "rb") as f:
                upload_r = await client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("python_guide.txt", f, "text/plain")},
                    data={"kb_id": str(kb_id)},
                    headers=headers,
                )
            assert upload_r.status_code == 200
            doc_id = upload_r.json()["data"]["document_id"]
            assert upload_r.json()["data"]["status"] == "pending"

            progress_r = await client.get(f"/api/v1/documents/{doc_id}/progress", headers=headers)
            assert progress_r.status_code == 200

            doc_r = await client.get(f"/api/v1/documents/{doc_id}", headers=headers)
            assert doc_r.status_code == 200
            assert doc_r.json()["data"]["filename"] == "python_guide.txt"

            docs_r = await client.get(f"/api/v1/documents?kb_id={kb_id}", headers=headers)
            assert docs_r.status_code == 200
            assert docs_r.json()["data"]["total"] == 1

            session_r = await client.post("/api/v1/chat/sessions", json={
                "title": "关于 Python 的对话",
                "kb_id": kb_id,
            }, headers=headers)
            assert session_r.status_code == 200
            session_id = session_r.json()["data"]["id"]

            sessions_r = await client.get("/api/v1/chat/sessions?page=1&page_size=10", headers=headers)
            assert sessions_r.status_code == 200
            assert sessions_r.json()["data"]["total"] == 1

            session_detail_r = await client.get(
                f"/api/v1/chat/sessions/{session_id}", headers=headers
            )
            assert session_detail_r.status_code == 200
            assert session_detail_r.json()["data"]["session"]["id"] == session_id

            update_session_r = await client.put(
                f"/api/v1/chat/sessions/{session_id}",
                json={"title": "Python 问答", "kb_id": kb_id},
                headers=headers,
            )
            assert update_session_r.status_code == 200
            assert update_session_r.json()["data"]["title"] == "Python 问答"

            messages_r = await client.get(
                f"/api/v1/chat/sessions/{session_id}/messages?page=1&page_size=10",
                headers=headers,
            )
            assert messages_r.status_code == 200
            assert messages_r.json()["data"]["total"] == 0

            del_session_r = await client.delete(
                f"/api/v1/chat/sessions/{session_id}", headers=headers
            )
            assert del_session_r.status_code == 200

            del_doc_r = await client.delete(f"/api/v1/documents/{doc_id}", headers=headers)
            assert del_doc_r.status_code == 200

            del_kb_r = await client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=headers)
            assert del_kb_r.status_code == 200

            logout_r = await client.post("/api/v1/auth/logout", headers=headers, json={})
            assert logout_r.status_code == 200

            me_after_logout_r = await client.get("/api/v1/auth/me", headers=headers)
            assert me_after_logout_r.status_code == 401

        finally:
            os.unlink(path)


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.integration
@pytest.mark.real_rag
@pytest.mark.e2e
@pytest.mark.slow
class TestE2EUserJourneyWithLLM:
    """完整 E2E 测试（含真实 LLM 生成）: 注册 -> 建库 -> 上传 -> RAG 聊天 -> 历史。

    标记为 slow，因为需要真实 LLM 生成，耗时较长。
    """

    PYTHON_CONTENT = """Python 是一种高级编程语言，由 Guido van Rossum 于 1991 年首次发布。
Python 的设计哲学强调代码的可读性和简洁的语法。
Python 支持多种编程范式，包括面向对象、命令式、函数式和过程式编程。
Python 广泛应用于 Web 开发、数据科学、人工智能、自动化运维等领域。
Django 和 Flask 是 Python 最流行的 Web 框架。
NumPy、Pandas 和 Matplotlib 是数据科学领域的常用库。
TensorFlow 和 PyTorch 是深度学习领域的主流框架。
"""

    async def test_rag_chat_e2e(self, client):
        """RAG 聊天端到端测试（含真实 LLM）。"""
        import time
        username = "e2e_llm_" + str(int(time.time()))
        user_data = {
            "username": username,
            "email": f"{username}@example.com",
            "password": "Test@123456",
        }

        await client.post("/api/v1/auth/register", json=user_data)
        login_r = await client.post("/api/v1/auth/login", json={
            "username": user_data["username"],
            "password": user_data["password"],
        })
        token = login_r.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        kb_r = await client.post("/api/v1/knowledge-bases", json={
            "name": "LLM 测试知识库",
            "description": "",
        }, headers=headers)
        kb_id = kb_r.json()["data"]["id"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                         encoding="utf-8") as f:
            f.write(self.PYTHON_CONTENT)
            path = f.name

        try:
            with open(path, "rb") as f:
                upload_r = await client.post(
                    "/api/v1/documents/upload",
                    files={"file": ("llm_test.txt", f, "text/plain")},
                    data={"kb_id": str(kb_id)},
                    headers=headers,
                )
            doc_id = upload_r.json()["data"]["document_id"]
            await asyncio.to_thread(_process_document_sync, doc_id)

            session_r = await client.post("/api/v1/chat/sessions", json={
                "title": "RAG 测试对话",
                "kb_id": kb_id,
            }, headers=headers)
            session_id = session_r.json()["data"]["id"]

            chat_r = await client.post(
                f"/api/v1/chat/sessions/{session_id}/messages",
                json={"content": "Python 是谁创建的？"},
                headers=headers,
                timeout=300,
            )
            assert chat_r.status_code == 200
            assert chat_r.headers["content-type"].startswith("text/event-stream")

            full_answer = ""
            message_id = None
            got_searching = False
            async for line in chat_r.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        import json as _json
                        event_data = _json.loads(data_str)
                        event = event_data.get("event")
                        if event == "searching":
                            got_searching = True
                        elif event == "delta":
                            full_answer += event_data.get("content", "")
                        elif event == "done":
                            message_id = event_data.get("message_id")
                    except Exception:
                        pass

            assert got_searching, "Expected 'searching' event from RAG pipeline"
            assert len(full_answer) > 0, "Chat returned empty answer"
            assert message_id is not None, "Chat did not return message_id"

            detail_r = await client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers)
            assert detail_r.status_code == 200
            assert len(detail_r.json()["data"]["messages"]) >= 2

        finally:
            os.unlink(path)
