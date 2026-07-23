"""Tests for app.services.chat_service (session CRUD + history context)"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from app.services import chat_service
from app.core.exceptions import NotFoundError, ForbiddenError
from app.db.chat_session import ChatSession


def _make_session(session_id=1, user_id=1, kb_id=None, title="test"):
    s = MagicMock(spec=ChatSession)
    s.id = session_id
    s.user_id = user_id
    s.kb_id = kb_id
    s.title = title
    return s


def _mock_db_with_session(session):
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: session))
    return db


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_create_session_success(self):
        req = MagicMock()
        req.kb_id = 1
        req.title = "my session"
        db = AsyncMock()

        async def fake_refresh(obj, *args, **kwargs):
            obj.id = 99
        db.refresh = AsyncMock(side_effect=fake_refresh)

        result = await chat_service.create_session(req, user_id=1, db=db)
        assert result.id == 99
        db.add.assert_called_once()
        db.commit.assert_awaited_once()


class TestGetSession:
    @pytest.mark.asyncio
    async def test_get_session_success(self):
        session = _make_session(session_id=5, user_id=1)
        db = _mock_db_with_session(session)
        result = await chat_service.get_session(session_id=5, user_id=1, db=db)
        assert result.id == 5

    @pytest.mark.asyncio
    async def test_get_session_not_found(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        with pytest.raises(NotFoundError):
            await chat_service.get_session(session_id=999, user_id=1, db=db)

    @pytest.mark.asyncio
    async def test_get_session_wrong_user_raises_forbidden(self):
        session = _make_session(user_id=2)  # 别人的
        db = _mock_db_with_session(session)
        with pytest.raises(ForbiddenError):
            await chat_service.get_session(session_id=1, user_id=1, db=db)


class TestUpdateSession:
    @pytest.mark.asyncio
    async def test_update_session_title(self):
        session = _make_session(title="old")
        db = _mock_db_with_session(session)
        req = MagicMock()
        req.title = "new title"
        req.kb_id = None
        result = await chat_service.update_session(session_id=1, req=req, user_id=1, db=db)
        assert result.title == "new title"

    @pytest.mark.asyncio
    async def test_update_session_kb_id(self):
        session = _make_session()
        db = _mock_db_with_session(session)
        req = MagicMock()
        req.title = None
        req.kb_id = 5
        result = await chat_service.update_session(session_id=1, req=req, user_id=1, db=db)
        assert result.kb_id == 5


class TestDeleteSession:
    @pytest.mark.asyncio
    async def test_delete_session_clears_redis_context(self):
        """删除 session → 清理 Redis 中的 context 缓存"""
        session = _make_session(session_id=10, user_id=1)
        db = _mock_db_with_session(session)
        redis_mock = MagicMock()
        redis_mock.delete = AsyncMock()

        with patch("app.services.chat_service.get_redis", return_value=redis_mock):
            await chat_service.delete_session(session_id=10, user_id=1, db=db)
        redis_mock.delete.assert_awaited_once_with("chat:session:10:context")
        db.delete.assert_awaited_once_with(session)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_session_no_redis_still_deletes_db(self):
        session = _make_session(session_id=10, user_id=1)
        db = _mock_db_with_session(session)
        with patch("app.services.chat_service.get_redis", return_value=None):
            await chat_service.delete_session(session_id=10, user_id=1, db=db)
        db.delete.assert_awaited_once()


class TestListSessions:
    @pytest.mark.asyncio
    async def test_list_sessions_returns_items_and_total(self):
        sessions = [_make_session(session_id=1), _make_session(session_id=2)]
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = sessions
        db.execute = AsyncMock(side_effect=[count_result, list_result])

        items, total = await chat_service.list_sessions(user_id=1, db=db, page=1, page_size=20)
        assert total == 2
        assert len(items) == 2


class TestGetMessages:
    @pytest.mark.asyncio
    async def test_get_messages_returns_paginated(self):
        messages = [MagicMock(), MagicMock()]
        db = AsyncMock()
        # get_session 内部 execute
        # count execute
        # list execute
        session = _make_session(session_id=1, user_id=1)
        session_result = MagicMock()
        session_result.scalar_one_or_none.return_value = session
        count_result = MagicMock()
        count_result.scalar_one.return_value = 5
        list_result = MagicMock()
        list_result.scalars.return_value.all.return_value = messages
        db.execute = AsyncMock(side_effect=[session_result, count_result, list_result])

        items, total = await chat_service.get_messages(
            session_id=1, user_id=1, db=db, page=1, page_size=10
        )
        assert total == 5
        assert len(items) == 2


class TestGetHistoryContext:
    @pytest.mark.asyncio
    async def test_get_history_no_redis_returns_empty(self):
        with patch("app.services.chat_service.get_redis", return_value=None):
            result = await chat_service.get_history_context(session_id=1, limit=8)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_history_returns_messages_in_reverse(self):
        """Redis lrange 返回最新在前，get_history_context 反转为时间顺序"""
        redis_mock = MagicMock()
        # Redis lpush 后 lrange(0, limit-1) 返回 [最新, ..., 最旧]
        redis_mock.lrange = AsyncMock(return_value=[
            json.dumps({"role": "assistant", "content": "reply"}),
            json.dumps({"role": "user", "content": "question"}),
        ])
        with patch("app.services.chat_service.get_redis", return_value=redis_mock):
            result = await chat_service.get_history_context(session_id=1, limit=8)
        # 反转后：question 在前，reply 在后（时间顺序）
        assert len(result) == 2
        assert result[0]["content"] == "question"
        assert result[1]["content"] == "reply"

    @pytest.mark.asyncio
    async def test_get_history_skips_invalid_json(self):
        """Redis 中有非法 JSON → 跳过"""
        redis_mock = MagicMock()
        redis_mock.lrange = AsyncMock(return_value=[
            "invalid json",
            json.dumps({"role": "user", "content": "ok"}),
        ])
        with patch("app.services.chat_service.get_redis", return_value=redis_mock):
            result = await chat_service.get_history_context(session_id=1, limit=8)
        assert len(result) == 1
        assert result[0]["content"] == "ok"

    @pytest.mark.asyncio
    async def test_get_history_empty_redis(self):
        redis_mock = MagicMock()
        redis_mock.lrange = AsyncMock(return_value=[])
        with patch("app.services.chat_service.get_redis", return_value=redis_mock):
            result = await chat_service.get_history_context(session_id=1, limit=8)
        assert result == []


class TestAppendToContext:
    @pytest.mark.asyncio
    async def test_append_to_context_no_redis_noop(self):
        with patch("app.services.chat_service.get_redis", return_value=None):
            # 不应抛异常
            await chat_service.append_to_context(session_id=1, role="user", content="hi")

    @pytest.mark.asyncio
    async def test_append_to_context_uses_pipeline_single_rtt(self):
        """pipeline 将 lpush+expire+ltrim 合并为 1 次 RTT"""
        redis_mock = MagicMock()
        pipe_mock = MagicMock()
        pipe_mock.lpush = MagicMock()
        pipe_mock.expire = MagicMock()
        pipe_mock.ltrim = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[1, True, True])
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        with patch("app.services.chat_service.get_redis", return_value=redis_mock):
            await chat_service.append_to_context(session_id=1, role="user", content="hi")

        # pipeline 只调用一次（transaction=True）
        redis_mock.pipeline.assert_called_once_with(transaction=True)
        # 三个命令都应被调用（在 pipeline 上，非 await）
        pipe_mock.lpush.assert_called_once()
        args = pipe_mock.lpush.call_args
        assert args[0][0] == "chat:session:1:context"
        msg = json.loads(args[0][1])
        assert msg["role"] == "user"
        assert msg["content"] == "hi"

        pipe_mock.expire.assert_called_once_with("chat:session:1:context", 86400)
        pipe_mock.ltrim.assert_called_once_with("chat:session:1:context", 0, 19)
        # execute 只 await 一次（1 次 RTT）
        pipe_mock.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_append_to_context_does_not_call_redis_directly(self):
        """确认不再直接调用 redis.lpush/expire/ltrim，全部走 pipeline"""
        redis_mock = MagicMock()
        redis_mock.lpush = AsyncMock()
        redis_mock.expire = AsyncMock()
        redis_mock.ltrim = AsyncMock()
        pipe_mock = MagicMock()
        pipe_mock.lpush = MagicMock()
        pipe_mock.expire = MagicMock()
        pipe_mock.ltrim = MagicMock()
        pipe_mock.execute = AsyncMock(return_value=[1, True, True])
        redis_mock.pipeline = MagicMock(return_value=pipe_mock)

        with patch("app.services.chat_service.get_redis", return_value=redis_mock):
            await chat_service.append_to_context(session_id=1, role="user", content="hi")

        # 直接调用应该不存在
        redis_mock.lpush.assert_not_awaited()
        redis_mock.expire.assert_not_awaited()
        redis_mock.ltrim.assert_not_awaited()


class TestSaveMessage:
    @pytest.mark.asyncio
    async def test_save_message_creates_record_with_all_fields(self):
        async def fake_refresh(obj, *args, **kwargs):
            obj.id = 99
        db = AsyncMock()
        db.refresh = AsyncMock(side_effect=fake_refresh)

        result = await chat_service.save_message(
            session_id=1, role="assistant", content="hello",
            db=db, references=[{"chunk_id": 1}],
            token_input=10, token_output=20, latency_ms=500,
        )
        assert result.id == 99
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_save_message_minimal_fields(self):
        db = AsyncMock()
        db.refresh = AsyncMock()
        await chat_service.save_message(
            session_id=1, role="user", content="hi", db=db,
        )
        db.add.assert_called_once()
