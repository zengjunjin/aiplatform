"""Tests for app.api.v1.chat (Chat session API endpoints)"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from app.api.v1 import chat
from app.db.chat_session import ChatSession


@pytest.fixture
def user():
    u = MagicMock()
    u.id = 1
    return u


@pytest.fixture
def db():
    return AsyncMock()


@pytest.fixture
def request_mock():
    """真实的 starlette Request，limiter 装饰器需要"""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/chat/sessions/1/messages",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 8000),
    }
    return Request(scope)


def _make_session(session_id=1, user_id=1, kb_id=None, title="test"):
    s = MagicMock(spec=ChatSession)
    s.id = session_id
    s.user_id = user_id
    s.kb_id = kb_id
    s.title = title
    s.created_at = MagicMock()
    s.created_at.isoformat.return_value = "2026-01-01T00:00:00"
    s.updated_at = MagicMock()
    s.updated_at.isoformat.return_value = "2026-01-01T00:00:00"
    return s


class TestCreateSession:
    @pytest.mark.asyncio
    async def test_create_session_returns_session(self, user, db, request_mock):
        session = _make_session(session_id=99)
        req = MagicMock()
        with patch("app.services.chat_service.create_session", new=AsyncMock(return_value=session)):
            with patch("app.services.audit_service.log_audit", new=AsyncMock()):
                result = (
                    await chat.create_session(req=req, request=request_mock, user=user, db=db)
                ).model_dump()
        assert result["data"]["id"] == 99


class TestListSessions:
    @pytest.mark.asyncio
    async def test_list_sessions_returns_paginated(self, user, db, request_mock):
        sessions = [_make_session(session_id=1), _make_session(session_id=2)]
        with patch(
            "app.services.chat_service.list_sessions", new=AsyncMock(return_value=(sessions, 2))
        ):
            result = (
                await chat.list_sessions(
                    request=request_mock, page=1, page_size=20, user=user, db=db
                )
            ).model_dump()
        assert result["data"]["total"] == 2
        assert len(result["data"]["items"]) == 2


class TestGetSession:
    @pytest.mark.asyncio
    async def test_get_session_returns_session_and_messages(self, user, db, request_mock):
        session = _make_session(session_id=1)
        messages = [MagicMock()]
        with patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)):
            with patch(
                "app.services.chat_service.get_messages", new=AsyncMock(return_value=(messages, 1))
            ):
                # MessageOut.model_validate 需要 spec=ChatMessage
                messages[0].id = 1
                messages[0].session_id = 1
                messages[0].role = "user"
                messages[0].content = "hi"
                messages[0].referenced_chunks = []
                messages[0].token_input = 0
                messages[0].token_output = 0
                messages[0].latency_ms = 0
                messages[0].created_at = MagicMock()
                messages[0].created_at.isoformat.return_value = "2026-01-01T00:00:00"
                result = (
                    await chat.get_session(request=request_mock, session_id=1, user=user, db=db)
                ).model_dump()
        assert "session" in result["data"]
        assert "messages" in result["data"]


class TestUpdateSession:
    @pytest.mark.asyncio
    async def test_update_session_returns_updated(self, user, db, request_mock):
        session = _make_session(session_id=1, title="updated")
        req = MagicMock()
        with patch("app.services.chat_service.update_session", new=AsyncMock(return_value=session)):
            with patch("app.services.audit_service.log_audit", new=AsyncMock()):
                result = (
                    await chat.update_session(
                        session_id=1, req=req, request=request_mock, user=user, db=db
                    )
                ).model_dump()
        assert result["data"]["title"] == "updated"


class TestDeleteSession:
    @pytest.mark.asyncio
    async def test_delete_session_calls_service(self, user, db, request_mock):
        with patch("app.services.chat_service.delete_session", new=AsyncMock()) as mock_del:
            with patch("app.services.audit_service.log_audit", new=AsyncMock()):
                result = (
                    await chat.delete_session(session_id=1, request=request_mock, user=user, db=db)
                ).model_dump()
        mock_del.assert_awaited_once()
        assert "message" in result


class TestGetMessages:
    @pytest.mark.asyncio
    async def test_get_messages_returns_paginated(self, user, db, request_mock):
        msg = MagicMock()
        msg.id = 1
        msg.session_id = 1
        msg.role = "user"
        msg.content = "hi"
        msg.referenced_chunks = []
        msg.token_input = 0
        msg.token_output = 0
        msg.latency_ms = 0
        msg.created_at = MagicMock()
        msg.created_at.isoformat.return_value = "2026-01-01T00:00:00"

        with patch(
            "app.services.chat_service.get_messages", new=AsyncMock(return_value=([msg], 1))
        ):
            result = (
                await chat.get_messages(
                    request=request_mock, session_id=1, page=1, page_size=50, user=user, db=db
                )
            ).model_dump()
        assert result["data"]["total"] == 1
        assert len(result["data"]["items"]) == 1


class TestCancelGeneration:
    @pytest.mark.asyncio
    async def test_cancel_generation_calls_request_cancel(self, user, db, request_mock):
        with patch("app.services.chat_service.get_session", new=AsyncMock()):
            with patch("app.services.chat_service.request_cancel", new=AsyncMock()) as mock_cancel:
                with patch("app.services.audit_service.log_audit", new=AsyncMock()):
                    result = (
                        await chat.cancel_generation(
                            session_id=1, request=request_mock, user=user, db=db
                        )
                    ).model_dump()
        mock_cancel.assert_awaited_once_with(1)
        assert "message" in result


class TestSendMessage:
    """send_message 是 SSE 流式端点，测试 StreamingResponse 行为"""

    @pytest.mark.asyncio
    async def test_send_message_returns_streaming_response(self, user, db, request_mock):
        """send_message 返回 StreamingResponse"""
        from fastapi.responses import StreamingResponse

        session = _make_session(session_id=1, kb_id=None)
        req = MagicMock()
        req.content = "hello"

        with patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)):
            with patch(
                "app.services.chat_service.save_message",
                new=AsyncMock(return_value=MagicMock(id=1)),
            ):
                with patch("app.services.chat_service.append_to_context", new=AsyncMock()):
                    # 即使 session.title 是 "新对话"，db.execute 也会被调用
                    db.execute = AsyncMock(
                        return_value=MagicMock(scalar_one_or_none=lambda: session)
                    )
                    # mock 整个 RAG pipeline
                    with patch(
                        "app.services.chat_service.get_history_context",
                        new=AsyncMock(return_value=[]),
                    ):
                        with patch(
                            "app.services.chat_service.is_cancelled",
                            new=AsyncMock(return_value=True),
                        ):
                            # 预先 cancel → 流直接返回 cancelled 事件
                            response = await chat.send_message(
                                request=request_mock, session_id=1, req=req, user=user, db=db
                            )
        assert isinstance(response, StreamingResponse)

    @pytest.mark.asyncio
    async def test_send_message_stream_yields_cancelled_event_when_pre_cancelled(
        self, user, db, request_mock
    ):
        """预取消（开始前已设置 cancel 标志）→ 流首事件为 cancelled。
        注意：event_stream() 是生成器，body 被消费时才执行，所以 patches 必须在迭代期间仍生效。
        """
        session = _make_session(session_id=1, kb_id=None)
        req = MagicMock()
        req.content = "hello"

        with (
            patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)),
            patch(
                "app.services.chat_service.save_message",
                new=AsyncMock(return_value=MagicMock(id=1)),
            ),
            patch("app.services.chat_service.append_to_context", new=AsyncMock()),
            patch("app.services.chat_service.get_history_context", new=AsyncMock(return_value=[])),
            patch("app.services.chat_service.is_cancelled", new=AsyncMock(return_value=True)),
            patch("app.services.chat_service.clear_cancel", new=AsyncMock()),
        ):
            db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: session))
            response = await chat.send_message(
                request=request_mock, session_id=1, req=req, user=user, db=db
            )
            # 在 with 块内消费 streaming body，确保 patches 仍生效
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()
        body = body_bytes.decode()
        assert "cancelled" in body
        assert "[DONE]" in body

    @pytest.mark.asyncio
    async def test_send_message_stream_with_kb_full_rag_pipeline(
        self, user, db, request_mock, mock_sse_common
    ):
        """有 kb_id → 完整 RAG 流：retrieve → rerank → build → generate → save → done。
        event_stream 内的 patches 必须在迭代期间生效。
        """
        session = _make_session(session_id=1, kb_id=1)
        req = MagicMock()
        req.content = "hello"

        # 模拟 RAG 组件
        fake_chunks = [{"id": 1, "content": "ctx", "filename": "a.md", "file_type": "md"}]
        fake_reranked = [{"id": 1, "content": "ctx", "filename": "a.md", "file_type": "md"}]
        fake_messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]

        # 模拟 LLM chat_stream 异步生成器
        async def fake_chat_stream(msgs, *args, **kwargs):
            for tok in ["Hello", " ", "world"]:
                yield tok

        fake_llm = MagicMock()
        fake_llm.provider_name = "test-provider"
        fake_llm.model_name = "test-model"
        fake_llm.chat_stream = fake_chat_stream

        with (
            patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)),
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(return_value=fake_chunks)),
            patch("app.rag.reranker.reranker.rerank", new=AsyncMock(return_value=fake_reranked)),
            patch(
                "app.rag.context_manager.context_manager.build_messages", return_value=fake_messages
            ),
            patch("app.core.model_router.ModelRouter.select", new=AsyncMock(return_value=fake_llm)),
        ):
            # session.title 为 "test"（非"新对话"），不会触发标题更新
            response = await chat.send_message(
                request=request_mock, session_id=1, req=req, user=user, db=db
            )
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()
        body = body_bytes.decode()
        # 应有 searching、delta、done 事件
        assert "searching" in body
        assert "delta" in body
        assert "Hello" in body
        assert "world" in body
        assert "done" in body
        assert "[DONE]" in body

    @pytest.mark.asyncio
    async def test_send_message_stream_no_kb_skips_retrieval(
        self, user, db, request_mock, mock_sse_common
    ):
        """无 kb_id → 跳过 retrieve，chunks=[]
        注意：session.title 为非"新对话"以避免 db.execute 调用。
        """
        session = _make_session(session_id=1, kb_id=None, title="existing title")
        req = MagicMock()
        req.content = "hello"

        fake_messages = [{"role": "user", "content": "hi"}]

        async def fake_chat_stream(msgs, *args, **kwargs):
            yield "answer"

        fake_llm = MagicMock()
        fake_llm.provider_name = "test-provider"
        fake_llm.model_name = "test-model"
        fake_llm.chat_stream = fake_chat_stream

        with (
            patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)),
            patch(
                "app.rag.context_manager.context_manager.build_messages", return_value=fake_messages
            ),
            patch("app.core.model_router.ModelRouter.select", new=AsyncMock(return_value=fake_llm)),
        ):
            response = await chat.send_message(
                request=request_mock, session_id=1, req=req, user=user, db=db
            )
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()
        body = body_bytes.decode()
        # 无 kb → 不应触发 searching 事件
        assert "searching" not in body
        assert "delta" in body
        assert "answer" in body
        assert "done" in body

    @pytest.mark.asyncio
    async def test_send_message_stream_yields_cancelled_mid_generation(
        self, user, db, request_mock
    ):
        """生成过程中（第 16 个 token 后取消检查）取消 → yields cancelled 事件。
        CANCEL_CHECK_INTERVAL=16，每 16 个 token 检查一次取消。
        is_cancelled: False (pre-check), True (after tok16)。"""
        session = _make_session(session_id=1, kb_id=None, title="t")
        req = MagicMock()
        req.content = "hello"

        fake_messages = [{"role": "user", "content": "hi"}]

        async def fake_chat_stream(msgs, *args, **kwargs):
            for i in range(1, 19):  # 18 tokens
                yield f"tok{i}"

        fake_llm = MagicMock()
        fake_llm.provider_name = "test-provider"
        fake_llm.model_name = "test-model"
        fake_llm.chat_stream = fake_chat_stream

        # is_cancelled: False (pre-check), True (after 16th token → cancel)
        cancel_states = iter([False, True])

        async def fake_is_cancelled(*args, **kwargs):
            return next(cancel_states)

        with (
            patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)),
            patch(
                "app.services.chat_service.save_message",
                new=AsyncMock(return_value=MagicMock(id=99)),
            ),
            patch("app.services.chat_service.append_to_context", new=AsyncMock()),
            patch("app.services.chat_service.get_history_context", new=AsyncMock(return_value=[])),
            patch(
                "app.services.chat_service.is_cancelled",
                new=AsyncMock(side_effect=fake_is_cancelled),
            ),
            patch("app.services.chat_service.clear_cancel", new=AsyncMock()),
            patch(
                "app.rag.context_manager.context_manager.build_messages", return_value=fake_messages
            ),
            patch("app.core.model_router.ModelRouter.select", new=AsyncMock(return_value=fake_llm)),
            patch("app.rag.reference_parser.parse_references", return_value=[]),
            patch("app.utils.token_counter.count_tokens", return_value=5),
        ):
            response = await chat.send_message(
                request=request_mock, session_id=1, req=req, user=user, db=db
            )
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()
        body = body_bytes.decode()
        # tok1-tok16 应在 body 中（取消检查在 tok16 后触发）
        assert "tok1" in body
        assert "tok16" in body
        # tok17, tok18 不应在 body 中（已取消）
        assert "tok17" not in body
        assert "tok18" not in body
        assert "cancelled" in body
        assert "[DONE]" in body

    @pytest.mark.asyncio
    async def test_send_message_stream_handles_internal_exception(self, user, db, request_mock):
        """event_stream 内部抛异常 → yields error 事件 + [DONE]"""
        session = _make_session(session_id=1, kb_id=None, title="t")
        req = MagicMock()
        req.content = "hello"

        with (
            patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)),
            patch(
                "app.services.chat_service.save_message",
                new=AsyncMock(return_value=MagicMock(id=99)),
            ),
            patch("app.services.chat_service.append_to_context", new=AsyncMock()),
            patch(
                "app.services.chat_service.get_history_context",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            patch("app.services.chat_service.clear_cancel", new=AsyncMock()),
        ):
            response = await chat.send_message(
                request=request_mock, session_id=1, req=req, user=user, db=db
            )
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()
        body = body_bytes.decode()
        assert "error" in body
        assert "[DONE]" in body

    @pytest.mark.asyncio
    async def test_send_message_auto_updates_title_for_new_session(self, user, db, request_mock):
        """session.title == '新对话' → 自动更新 title 为 content 前 30 字符"""
        session = _make_session(session_id=1, kb_id=None, title="新对话")
        req = MagicMock()
        req.content = "this is my question"

        # 模拟 async_session() 返回的独立 db 会话（用于标题自动更新）
        sess_mock = MagicMock()
        sess_mock.title = "新对话"
        stream_db_mock = AsyncMock()
        stream_db_mock.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: sess_mock)
        )
        stream_db_mock.commit = AsyncMock()

        # async_session() 返回 async context manager，__aenter__ 返回 stream_db_mock
        mock_async_session = MagicMock()
        mock_async_session.return_value.__aenter__ = AsyncMock(return_value=stream_db_mock)
        mock_async_session.return_value.__aexit__ = AsyncMock(return_value=None)

        fake_messages = [{"role": "user", "content": "hi"}]

        async def fake_chat_stream(msgs, *args, **kwargs):
            yield "answer"

        fake_llm = MagicMock()
        fake_llm.provider_name = "test-provider"
        fake_llm.model_name = "test-model"
        fake_llm.chat_stream = fake_chat_stream

        with (
            patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)),
            patch(
                "app.rag.context_manager.context_manager.build_messages", return_value=fake_messages
            ),
            patch("app.core.model_router.ModelRouter.select", new=AsyncMock(return_value=fake_llm)),
            patch("app.api.v1.chat.async_session", new=mock_async_session),
        ):
            response = await chat.send_message(
                request=request_mock, session_id=1, req=req, user=user, db=db
            )
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()
        # session title 应被更新（前 30 字符）
        assert sess_mock.title == "this is my question"


class TestSSEConcurrentLimit:
    """Task 21: SSE 并发连接限制测试"""

    @pytest.mark.asyncio
    async def test_fourth_connection_returns_429(self, user, db, request_mock):
        """超过 3 个并发连接 → 第 4 个返回 429"""
        from fastapi import HTTPException

        session = _make_session(session_id=1, kb_id=None, title="t")
        req = MagicMock()
        req.content = "hello"

        # Redis mock: eval 返回 4（超过上限），第二次 eval 用于 DECR 回滚
        redis_mock = MagicMock()
        redis_mock.eval = AsyncMock(return_value=4)

        with (
            patch("app.api.v1.chat.get_redis", return_value=redis_mock),
            patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await chat.send_message(
                    request=request_mock, session_id=1, req=req, user=user, db=db
                )
        assert exc_info.value.status_code == 429
        assert "Too many concurrent SSE connections" in exc_info.value.detail
        # 超限时应该 DECR 回滚（通过 eval 调用）
        # eval 调用两次：第一次 INCR（返回 4），第二次 DECR 回滚
        assert redis_mock.eval.await_count == 2

    @pytest.mark.asyncio
    async def test_first_connection_sets_ttl(self, user, db, request_mock):
        """首次连接（INCR 返回 1）应设置 TTL 防止计数器泄漏"""
        session = _make_session(session_id=1, kb_id=None, title="t")
        req = MagicMock()
        req.content = "hello"

        # eval 第一次调用返回 1（INCR+EXPIRE 原子操作），第二次返回 0（DECR 清理）
        redis_mock = MagicMock()
        redis_mock.eval = AsyncMock(side_effect=[1, 0])

        fake_messages = [{"role": "user", "content": "hi"}]

        async def fake_chat_stream(msgs, *args, **kwargs):
            yield "answer"

        fake_llm = MagicMock()
        fake_llm.provider_name = "test-provider"
        fake_llm.model_name = "test-model"
        fake_llm.chat_stream = fake_chat_stream

        with (
            patch("app.api.v1.chat.get_redis", return_value=redis_mock),
            patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)),
            patch(
                "app.services.chat_service.save_message",
                new=AsyncMock(return_value=MagicMock(id=99)),
            ),
            patch("app.services.chat_service.append_to_context", new=AsyncMock()),
            patch("app.services.chat_service.get_history_context", new=AsyncMock(return_value=[])),
            patch("app.services.chat_service.is_cancelled", new=AsyncMock(return_value=False)),
            patch("app.services.chat_service.clear_cancel", new=AsyncMock()),
            patch(
                "app.rag.context_manager.context_manager.build_messages", return_value=fake_messages
            ),
            patch("app.core.model_router.ModelRouter.select", new=AsyncMock(return_value=fake_llm)),
            patch("app.rag.reference_parser.parse_references", return_value=[]),
            patch("app.utils.token_counter.count_tokens", return_value=5),
        ):
            response = await chat.send_message(
                request=request_mock, session_id=1, req=req, user=user, db=db
            )
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()

        # 首次连接应通过 eval 设置 TTL（INCR+EXPIRE 原子脚本）
        # eval 第一次调用参数: (script, numkeys=1, key, ttl_arg)
        incr_call = redis_mock.eval.await_args_list[0]
        assert incr_call.args[2] == "sse_count:1"  # key
        assert incr_call.args[3] == 600  # TTL 应为 600 秒

    @pytest.mark.asyncio
    async def test_counter_decremented_in_finally(self, user, db, request_mock):
        """流式结束后计数器被递减（无论正常结束还是异常）"""
        session = _make_session(session_id=1, kb_id=None, title="t")
        req = MagicMock()
        req.content = "hello"

        # eval 第一次返回 2（INCR，第 2 个连接未超限），第二次返回 1（DECR 清理）
        redis_mock = MagicMock()
        redis_mock.eval = AsyncMock(side_effect=[2, 1])

        fake_messages = [{"role": "user", "content": "hi"}]

        async def fake_chat_stream(msgs, *args, **kwargs):
            yield "answer"

        fake_llm = MagicMock()
        fake_llm.provider_name = "test-provider"
        fake_llm.model_name = "test-model"
        fake_llm.chat_stream = fake_chat_stream

        with (
            patch("app.api.v1.chat.get_redis", return_value=redis_mock),
            patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)),
            patch(
                "app.services.chat_service.save_message",
                new=AsyncMock(return_value=MagicMock(id=99)),
            ),
            patch("app.services.chat_service.append_to_context", new=AsyncMock()),
            patch("app.services.chat_service.get_history_context", new=AsyncMock(return_value=[])),
            patch("app.services.chat_service.is_cancelled", new=AsyncMock(return_value=False)),
            patch("app.services.chat_service.clear_cancel", new=AsyncMock()),
            patch(
                "app.rag.context_manager.context_manager.build_messages", return_value=fake_messages
            ),
            patch("app.core.model_router.ModelRouter.select", new=AsyncMock(return_value=fake_llm)),
            patch("app.rag.reference_parser.parse_references", return_value=[]),
            patch("app.utils.token_counter.count_tokens", return_value=5),
        ):
            response = await chat.send_message(
                request=request_mock, session_id=1, req=req, user=user, db=db
            )
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()

        # 流式结束后应递减计数器（通过 eval DECR 脚本调用）
        # eval 调用两次：第一次 INCR，第二次 DECR
        assert redis_mock.eval.await_count == 2
        decr_call = redis_mock.eval.await_args_list[1]
        assert decr_call.args[2] == "sse_count:1"  # key

    @pytest.mark.asyncio
    async def test_counter_decremented_on_exception(self, user, db, request_mock):
        """event_stream 内部异常时（pre-try 阶段）计数器仍被递减"""
        session = _make_session(session_id=1, kb_id=None, title="t")
        req = MagicMock()
        req.content = "hello"

        # eval 第一次返回 1（INCR），第二次返回 0（DECR 清理）
        redis_mock = MagicMock()
        redis_mock.eval = AsyncMock(side_effect=[1, 0])

        # save_message 抛异常（pre-try 阶段）
        with (
            patch("app.api.v1.chat.get_redis", return_value=redis_mock),
            patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)),
            patch(
                "app.services.chat_service.save_message",
                new=AsyncMock(side_effect=RuntimeError("db down")),
            ),
            patch("app.services.chat_service.clear_cancel", new=AsyncMock()),
        ):
            response = await chat.send_message(
                request=request_mock, session_id=1, req=req, user=user, db=db
            )
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()

        # 即使 pre-try 阶段抛异常，finally 仍应递减计数器（通过 eval DECR 脚本）
        assert redis_mock.eval.await_count == 2
        decr_call = redis_mock.eval.await_args_list[1]
        assert decr_call.args[2] == "sse_count:1"  # key

    @pytest.mark.asyncio
    async def test_redis_unavailable_degrades_open(self, user, db, request_mock):
        """Redis 不可用时降级放行（不抛 429）"""
        session = _make_session(session_id=1, kb_id=None, title="t")
        req = MagicMock()
        req.content = "hello"

        fake_messages = [{"role": "user", "content": "hi"}]

        async def fake_chat_stream(msgs, *args, **kwargs):
            yield "answer"

        fake_llm = MagicMock()
        fake_llm.provider_name = "test-provider"
        fake_llm.model_name = "test-model"
        fake_llm.chat_stream = fake_chat_stream

        # Redis 返回 None（未初始化）
        with (
            patch("app.api.v1.chat.get_redis", return_value=None),
            patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)),
            patch(
                "app.services.chat_service.save_message",
                new=AsyncMock(return_value=MagicMock(id=99)),
            ),
            patch("app.services.chat_service.append_to_context", new=AsyncMock()),
            patch("app.services.chat_service.get_history_context", new=AsyncMock(return_value=[])),
            patch("app.services.chat_service.is_cancelled", new=AsyncMock(return_value=False)),
            patch("app.services.chat_service.clear_cancel", new=AsyncMock()),
            patch(
                "app.rag.context_manager.context_manager.build_messages", return_value=fake_messages
            ),
            patch("app.core.model_router.ModelRouter.select", new=AsyncMock(return_value=fake_llm)),
            patch("app.rag.reference_parser.parse_references", return_value=[]),
            patch("app.utils.token_counter.count_tokens", return_value=5),
        ):
            # 不应抛 429，应正常返回 StreamingResponse
            response = await chat.send_message(
                request=request_mock, session_id=1, req=req, user=user, db=db
            )
        from fastapi.responses import StreamingResponse

        assert isinstance(response, StreamingResponse)

    @pytest.mark.asyncio
    async def test_redis_incr_exception_degrades_open(self, user, db, request_mock):
        """Redis INCR 抛异常时降级放行"""
        session = _make_session(session_id=1, kb_id=None, title="t")
        req = MagicMock()
        req.content = "hello"

        # Redis 抛异常
        redis_mock = MagicMock()
        redis_mock.incr = AsyncMock(side_effect=RuntimeError("redis down"))
        redis_mock.decr = AsyncMock()
        redis_mock.expire = AsyncMock()

        fake_messages = [{"role": "user", "content": "hi"}]

        async def fake_chat_stream(msgs, *args, **kwargs):
            yield "answer"

        fake_llm = MagicMock()
        fake_llm.provider_name = "test-provider"
        fake_llm.model_name = "test-model"
        fake_llm.chat_stream = fake_chat_stream

        with (
            patch("app.api.v1.chat.get_redis", return_value=redis_mock),
            patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)),
            patch(
                "app.services.chat_service.save_message",
                new=AsyncMock(return_value=MagicMock(id=99)),
            ),
            patch("app.services.chat_service.append_to_context", new=AsyncMock()),
            patch("app.services.chat_service.get_history_context", new=AsyncMock(return_value=[])),
            patch("app.services.chat_service.is_cancelled", new=AsyncMock(return_value=False)),
            patch("app.services.chat_service.clear_cancel", new=AsyncMock()),
            patch(
                "app.rag.context_manager.context_manager.build_messages", return_value=fake_messages
            ),
            patch("app.core.model_router.ModelRouter.select", new=AsyncMock(return_value=fake_llm)),
            patch("app.rag.reference_parser.parse_references", return_value=[]),
            patch("app.utils.token_counter.count_tokens", return_value=5),
        ):
            # 不应抛 429，应正常返回 StreamingResponse
            response = await chat.send_message(
                request=request_mock, session_id=1, req=req, user=user, db=db
            )
        from fastapi.responses import StreamingResponse

        assert isinstance(response, StreamingResponse)
        # DECR 不应被调用（因为 sse_acquired=False）
        redis_mock.decr.assert_not_awaited()


class TestLLMFallbackRelease:
    """Task 8: chat.py least_busy 计数泄漏修复

    Primary provider 走了 select() (least_busy 策略下计数 +1), 必须在 finally 释放。
    Fallback provider 直接通过 ModelRegistry.get_available() 获取, 未走 select(),
    故 finally 不应 release fallback (避免错误递减其他并发请求的计数)。
    """

    @pytest.fixture(autouse=True)
    def _setup_session(self, user, db, request_mock):
        self.user = user
        self.db = db
        self.request_mock = request_mock
        self.session = _make_session(session_id=1, kb_id=None, title="t")
        self.req = MagicMock()
        self.req.content = "hello"
        self.fake_messages = [{"role": "user", "content": "hi"}]

    def _make_failing_primary(self):
        """Primary provider 抛 RuntimeError"""

        async def chat_stream(msgs, *args, **kwargs):
            raise RuntimeError("primary down")
            yield  # make it an async generator (unreachable but defines gen)

        primary = MagicMock()
        primary.provider_name = "primary"
        primary.model_name = "primary-model"
        primary.chat_stream = chat_stream
        return primary

    def _make_success_fallback(self):
        """Fallback provider 正常返回"""

        async def chat_stream(msgs, *args, **kwargs):
            yield "fallback"
            yield " answer"

        fb = MagicMock()
        fb.provider_name = "fallback"
        fb.model_name = "fallback-model"
        fb.chat_stream = chat_stream
        return fb

    @pytest.mark.asyncio
    async def test_primary_success_releases_primary_only(self, mock_sse_common):
        """Primary 成功 → release(primary) 被调用一次, 无其他 release"""
        primary = MagicMock()
        primary.provider_name = "primary"
        primary.model_name = "primary-model"

        async def chat_stream(msgs, *args, **kwargs):
            yield "answer"

        primary.chat_stream = chat_stream

        release_calls = []

        with (
            patch(
                "app.services.chat_service.get_session", new=AsyncMock(return_value=self.session)
            ),
            patch(
                "app.rag.context_manager.context_manager.build_messages",
                return_value=self.fake_messages,
            ),
            patch("app.core.model_router.ModelRouter.select", new=AsyncMock(return_value=primary)),
            patch(
                "app.core.model_router.ModelRouter.release",
                side_effect=lambda name: release_calls.append(name),
            ),
        ):
            response = await chat.send_message(
                request=self.request_mock, session_id=1, req=self.req, user=self.user, db=self.db
            )
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()

        # 应只 release primary 一次
        assert release_calls == ["primary"]

    @pytest.mark.asyncio
    async def test_fallback_success_releases_primary_not_fallback(self, mock_sse_common):
        """Primary 失败 + Fallback 成功 → release(primary), 不 release fallback"""
        primary = self._make_failing_primary()
        fallback = self._make_success_fallback()

        release_calls = []

        with (
            patch(
                "app.services.chat_service.get_session", new=AsyncMock(return_value=self.session)
            ),
            patch(
                "app.rag.context_manager.context_manager.build_messages",
                return_value=self.fake_messages,
            ),
            patch("app.core.model_router.ModelRouter.select", new=AsyncMock(return_value=primary)),
            patch(
                "app.core.model_router.ModelRouter.release",
                side_effect=lambda name: release_calls.append(name),
            ),
            patch("app.models.factory.ModelRegistry.get_available", return_value=[fallback]),
        ):
            response = await chat.send_message(
                request=self.request_mock, session_id=1, req=self.req, user=self.user, db=self.db
            )
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()
        body = body_bytes.decode()

        # 应只 release primary (走了 select()), 不 release fallback (未走 select())
        assert release_calls == ["primary"]
        # fallback 事件 + delta 应在 body 中 (两个独立 delta: "fallback" 和 " answer")
        assert '"fallback": true' in body or 'fallback": true' in body
        assert '"content": "fallback"' in body
        assert '"content": " answer"' in body

    @pytest.mark.asyncio
    async def test_all_providers_fail_still_releases_primary(self):
        """Primary + 所有 Fallback 都失败 → 仍 release(primary)"""
        primary = self._make_failing_primary()

        # Fallback 也失败
        async def failing_fallback_stream(msgs, *args, **kwargs):
            raise RuntimeError("fallback also down")
            yield

        failing_fb = MagicMock()
        failing_fb.provider_name = "failing-fallback"
        failing_fb.model_name = "fb-model"
        failing_fb.chat_stream = failing_fallback_stream

        release_calls = []

        with (
            patch(
                "app.services.chat_service.get_session", new=AsyncMock(return_value=self.session)
            ),
            patch(
                "app.services.chat_service.save_message",
                new=AsyncMock(return_value=MagicMock(id=99)),
            ),
            patch("app.services.chat_service.append_to_context", new=AsyncMock()),
            patch("app.services.chat_service.get_history_context", new=AsyncMock(return_value=[])),
            patch("app.services.chat_service.is_cancelled", new=AsyncMock(return_value=False)),
            patch("app.services.chat_service.clear_cancel", new=AsyncMock()),
            patch(
                "app.rag.context_manager.context_manager.build_messages",
                return_value=self.fake_messages,
            ),
            patch("app.core.model_router.ModelRouter.select", new=AsyncMock(return_value=primary)),
            patch(
                "app.core.model_router.ModelRouter.release",
                side_effect=lambda name: release_calls.append(name),
            ),
            patch("app.models.factory.ModelRegistry.get_available", return_value=[failing_fb]),
            patch("app.rag.reference_parser.parse_references", return_value=[]),
            patch("app.utils.token_counter.count_tokens", return_value=5),
        ):
            response = await chat.send_message(
                request=self.request_mock, session_id=1, req=self.req, user=self.user, db=self.db
            )
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk if isinstance(chunk, bytes) else chunk.encode()
        body = body_bytes.decode()

        # 即使所有 provider 失败, primary 仍应被 release (finally 块必执行)
        assert release_calls == ["primary"]
        # 应有 error 事件
        assert "error" in body.lower() or "failed" in body.lower() or "[DONE]" in body

    @pytest.mark.asyncio
    async def test_chat_py_source_uses_primary_provider_variable(self):
        """Task 8: 验证 chat.py 源码使用 primary_provider 变量, 而非 actual_provider"""
        import inspect

        from app.api.v1 import chat as chat_module

        src = inspect.getsource(chat_module)
        # 应有 primary_provider 变量
        assert "primary_provider" in src
        # finally 中应 release(primary_provider), 不是 actual_provider
        # 查找 finally 块附近的 release 调用
        assert "model_router.release(primary_provider)" in src
