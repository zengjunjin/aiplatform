"""Tests for app.redis_client and app.database"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import database as database_module
from app import redis_client as redis_module

# ========== redis_client ==========


class TestRedisClient:
    def test_get_redis_returns_none_when_not_initialized(self):
        """init_redis 未调用 → get_redis 返回 None"""
        # 重置模块状态
        original = redis_module.redis_client
        try:
            redis_module.redis_client = None
            assert redis_module.get_redis() is None
        finally:
            redis_module.redis_client = original

    def test_get_redis_returns_client_when_initialized(self):
        """init_redis 调用后 → get_redis 返回 Redis 实例"""
        original = redis_module.redis_client
        try:
            fake_redis = MagicMock()
            redis_module.redis_client = fake_redis
            assert redis_module.get_redis() is fake_redis
        finally:
            redis_module.redis_client = original

    def test_init_redis_creates_client_from_url(self):
        """init_redis 调用 redis.from_url 并返回 client"""
        original = redis_module.redis_client
        fake_redis = MagicMock()
        with patch("app.redis_client.redis.from_url", return_value=fake_redis) as mock_from_url:
            try:
                result = redis_module.init_redis()
                assert result is fake_redis
                assert redis_module.redis_client is fake_redis
                # 验证 from_url 调用参数
                args, kwargs = mock_from_url.call_args
                assert kwargs.get("encoding") == "utf-8"
                assert kwargs.get("decode_responses") is True
            finally:
                redis_module.redis_client = original


# ========== database ==========


class TestDatabase:
    def test_engine_created_with_settings(self):
        """engine 已在模块加载时创建，验证它是 AsyncEngine"""
        from sqlalchemy.ext.asyncio import AsyncEngine

        assert isinstance(database_module.engine, AsyncEngine)

    def test_async_session_is_sessionmaker(self):
        """async_session 是 async_sessionmaker"""
        from sqlalchemy.ext.asyncio import async_sessionmaker

        assert isinstance(database_module.async_session, async_sessionmaker)

    @pytest.mark.asyncio
    async def test_get_db_yields_session(self):
        """get_db 是 async generator，yield 一个 session"""
        from sqlalchemy.ext.asyncio import AsyncSession

        gen = database_module.get_db()
        session = await gen.__anext__()
        assert isinstance(session, AsyncSession)
        # 关闭 generator（触发 finally）
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
        await session.close()

    @pytest.mark.asyncio
    async def test_init_db_creates_tables(self):
        """init_db 调用 Base.metadata.create_all"""
        # 用 mock engine 避免真实连接
        fake_engine = MagicMock()
        fake_conn = AsyncMock()
        fake_engine.begin = MagicMock(return_value=fake_conn)
        # context manager
        fake_engine.begin.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
        fake_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.object(database_module, "engine", fake_engine):
            await database_module.init_db()

        # 验证 run_sync 被调用
        fake_conn.run_sync.assert_called_once()
