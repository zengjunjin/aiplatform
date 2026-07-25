"""Tests for app.api.v1.system - 系统状态 API"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1 import system


@pytest.fixture
def admin_user():
    u = MagicMock()
    u.id = 1
    u.role = "admin"
    return u


@pytest.fixture
def normal_user():
    u = MagicMock()
    u.id = 2
    u.role = "user"
    return u


@pytest.fixture
def db_mock():
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


class TestSystemStatus:
    @pytest.mark.asyncio
    async def test_system_status_all_down(self, db_mock, admin_user, request_mock):
        """所有组件不可用 → status 全部 'down'"""
        db_mock.execute = AsyncMock(side_effect=Exception("pg down"))

        with (
            patch("app.redis_client.get_redis", return_value=None),
            patch("app.rag.retriever.retriever") as mock_retriever,
        ):
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

                    result = (
                        await system.system_status(
                            request=request_mock, db=db_mock, admin=admin_user
                        )
                    ).model_dump()

        # PostgreSQL: down
        assert result["data"]["postgresql"] == "down"
        # Redis: down (not initialized when get_redis returns None)
        assert result["data"]["redis"] == "down (not initialized)"
        # Ollama: down
        assert result["data"]["ollama"] == "down"
        # Qdrant: down
        assert result["data"]["qdrant"] == "down"
        # Celery: no_active_workers
        assert result["data"]["celery"] == "no_active_workers"

    @pytest.mark.asyncio
    async def test_system_status_all_up(self, db_mock, admin_user, request_mock):
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

        with (
            patch("app.redis_client.get_redis", return_value=redis_mock),
            patch("app.rag.retriever.retriever") as mock_retriever,
        ):
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

                    result = (
                        await system.system_status(
                            request=request_mock, db=db_mock, admin=admin_user
                        )
                    ).model_dump()

        assert result["data"]["postgresql"] == "up"
        assert result["data"]["redis"] == "up"
        assert result["data"]["ollama"] == "up"
        assert result["data"]["ollama_models"] == ["llama3", "nomic"]
        assert result["data"]["qdrant"] == "up"
        assert result["data"]["qdrant_collections"] == 2
        assert result["data"]["celery"] == "up"
        assert "worker1" in result["data"]["celery_workers"]

    @pytest.mark.asyncio
    async def test_system_status_ollama_non_200(self, db_mock, admin_user, request_mock):
        """Ollama 返回非 200 → status 'down: HTTP xxx'"""
        ollama_response = MagicMock()
        ollama_response.status_code = 500

        with (
            patch("app.redis_client.get_redis", return_value=MagicMock(ping=AsyncMock())),
            patch("app.rag.retriever.retriever") as mock_retriever,
        ):
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

                    result = (
                        await system.system_status(
                            request=request_mock, db=db_mock, admin=admin_user
                        )
                    ).model_dump()
        assert "down" in result["data"]["ollama"]
        assert "500" in result["data"]["ollama"]


class TestListModels:
    """Task 4: list_models 端点需要认证 (Depends(get_current_user))"""

    @pytest.mark.asyncio
    async def test_list_models_returns_models_for_authenticated_user(
        self, normal_user, request_mock
    ):
        """认证用户 → 返回模型列表"""
        # 模拟 ModelRegistry.list_all 和 ModelRegistry.get
        fake_provider_1 = MagicMock()
        fake_provider_1.provider_name = "ollama-llama3"
        fake_provider_1.model_name = "llama3"
        fake_provider_1.is_healthy = True

        fake_provider_2 = MagicMock()
        fake_provider_2.provider_name = "openai-gpt-4"
        fake_provider_2.model_name = "gpt-4"
        fake_provider_2.is_healthy = False

        with (
            patch(
                "app.models.factory.ModelRegistry.list_all",
                return_value=["ollama-llama3", "openai-gpt-4"],
            ),
            patch(
                "app.models.factory.ModelRegistry.get",
                side_effect=[fake_provider_1, fake_provider_2],
            ),
        ):
            result = (
                await system.list_models(request=request_mock, current_user=normal_user)
            ).model_dump()

        assert "data" in result
        assert "models" in result["data"]
        assert len(result["data"]["models"]) == 2
        assert result["data"]["models"][0]["name"] == "ollama-llama3"
        assert result["data"]["models"][0]["source"] == "local"
        assert result["data"]["models"][0]["status"] == "healthy"
        assert result["data"]["models"][1]["name"] == "openai-gpt-4"
        assert result["data"]["models"][1]["source"] == "cloud"
        assert result["data"]["models"][1]["status"] == "unhealthy"
        assert result["data"]["default_model"] == "ollama"

    @pytest.mark.asyncio
    async def test_list_models_endpoint_signature_requires_current_user(self):
        """list_models 函数签名应包含 current_user: User = Depends(get_current_user) 依赖"""
        import inspect

        from app.api.deps import get_current_user
        from app.db.user import User

        sig = inspect.signature(system.list_models)
        assert "current_user" in sig.parameters
        param = sig.parameters["current_user"]
        # FastAPI Depends 注解: 默认值应是 Depends(...) 实例
        assert param.default is not inspect.Parameter.empty
        assert callable(get_current_user)
        # 类型注解应为 User 或 Union[User, ...]
        annotation = param.annotation
        assert annotation is User or (
            hasattr(annotation, "__args__") and User in annotation.__args__
        )

    @pytest.mark.asyncio
    async def test_list_models_returns_empty_when_no_providers(self, normal_user, request_mock):
        """无可用 Provider → 返回空列表"""
        with patch("app.models.factory.ModelRegistry.list_all", return_value=[]):
            result = (
                await system.list_models(request=request_mock, current_user=normal_user)
            ).model_dump()
        assert result["data"]["models"] == []
        assert result["data"]["default_model"] == "ollama"
