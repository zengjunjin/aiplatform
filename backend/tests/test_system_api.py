"""Tests for app.api.v1.system - 系统状态 API"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.api.v1 import system


@pytest.fixture
def admin_user():
    u = MagicMock()
    u.id = 1
    u.role = "admin"
    return u


@pytest.fixture
def db_mock():
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


class TestSystemStatus:
    @pytest.mark.asyncio
    async def test_system_status_all_down(self, db_mock, admin_user):
        """所有组件不可用 → status 全部 'down'"""
        db_mock.execute = AsyncMock(side_effect=Exception("pg down"))

        with patch("app.redis_client.get_redis", return_value=None), \
             patch("app.rag.retriever.retriever") as mock_retriever:
            mock_retriever.qdrant.get_collections.side_effect = Exception("qdrant down")
            with patch("app.tasks.celery_app.celery_app") as mock_celery:
                mock_inspect = MagicMock()
                mock_inspect.stats.return_value = None  # 无 active worker
                mock_celery.control.inspect.return_value = mock_inspect
                with patch("httpx.AsyncClient") as mock_client_cls:
                    mock_client = AsyncMock()
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client.get = AsyncMock(side_effect=Exception("ollama down"))
                    mock_client_cls.return_value = mock_client

                    result = await system.system_status(db=db_mock, admin=admin_user)

        # PostgreSQL: down
        assert result["data"]["postgresql"] == "down"
        # Redis: down
        assert result["data"]["redis"] == "down"
        # Ollama: down
        assert result["data"]["ollama"] == "down"
        # Qdrant: down
        assert result["data"]["qdrant"] == "down"
        # Celery: no_active_workers
        assert result["data"]["celery"] == "no_active_workers"

    @pytest.mark.asyncio
    async def test_system_status_all_up(self, db_mock, admin_user):
        """所有组件正常 → status 全部 'up'"""
        # PG 正常
        db_mock.execute = AsyncMock()

        # Redis 正常
        redis_mock = MagicMock()
        redis_mock.ping = AsyncMock()

        # Ollama 正常
        ollama_response = MagicMock()
        ollama_response.status_code = 200
        ollama_response.json.return_value = {"models": [{"name": "llama3"}, {"name": "nomic"}]}

        # Qdrant 正常
        qdrant_collections = MagicMock()
        qdrant_collections.collections = [MagicMock(), MagicMock()]

        # Celery 正常
        celery_stats = {"worker1": {"pool": "prefork"}}

        with patch("app.redis_client.get_redis", return_value=redis_mock), \
             patch("app.rag.retriever.retriever") as mock_retriever:
            mock_retriever.qdrant.get_collections.return_value = qdrant_collections
            with patch("app.tasks.celery_app.celery_app") as mock_celery:
                mock_inspect = MagicMock()
                mock_inspect.stats.return_value = celery_stats
                mock_celery.control.inspect.return_value = mock_inspect
                with patch("httpx.AsyncClient") as mock_client_cls:
                    mock_client = AsyncMock()
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client.get = AsyncMock(return_value=ollama_response)
                    mock_client_cls.return_value = mock_client

                    result = await system.system_status(db=db_mock, admin=admin_user)

        assert result["data"]["postgresql"] == "up"
        assert result["data"]["redis"] == "up"
        assert result["data"]["ollama"] == "up"
        assert result["data"]["ollama_models"] == ["llama3", "nomic"]
        assert result["data"]["qdrant"] == "up"
        assert result["data"]["qdrant_collections"] == 2
        assert result["data"]["celery"] == "up"
        assert "worker1" in result["data"]["celery_workers"]

    @pytest.mark.asyncio
    async def test_system_status_ollama_non_200(self, db_mock, admin_user):
        """Ollama 返回非 200 → status 'down: HTTP xxx'"""
        ollama_response = MagicMock()
        ollama_response.status_code = 500

        with patch("app.redis_client.get_redis", return_value=MagicMock(ping=AsyncMock())), \
             patch("app.rag.retriever.retriever") as mock_retriever:
            mock_retriever.qdrant.get_collections.return_value = MagicMock(collections=[])
            with patch("app.tasks.celery_app.celery_app") as mock_celery:
                mock_inspect = MagicMock()
                mock_inspect.stats.return_value = {}
                mock_celery.control.inspect.return_value = mock_inspect
                with patch("httpx.AsyncClient") as mock_client_cls:
                    mock_client = AsyncMock()
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock(return_value=None)
                    mock_client.get = AsyncMock(return_value=ollama_response)
                    mock_client_cls.return_value = mock_client

                    result = await system.system_status(db=db_mock, admin=admin_user)
        assert "down" in result["data"]["ollama"]
        assert "500" in result["data"]["ollama"]
