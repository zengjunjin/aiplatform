"""Tests for app.api.v1.chat 拆分后的 orchestrator 函数 (Task 12).

覆盖 _send_sse / _send_sse_error / _save_user_msg / _retrieve_and_rerank /
_stream_llm_with_fallback / _save_assistant_msg。
不依赖真实 PostgreSQL / Redis / LLM。
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1 import chat

# ---------- _send_sse / _send_sse_error ----------


class TestSendSse:
    def test_send_sse_serializes_dict_with_chinese(self):
        """中文应保持原样（ensure_ascii=False）。"""
        evt = chat._send_sse({"event": "warn", "message": "重排序服务暂不可用"})
        assert evt.startswith("data: ")
        assert evt.endswith("\n\n")
        payload = evt[len("data: ") :].strip()
        data = json.loads(payload)
        assert data["event"] == "warn"
        assert data["message"] == "重排序服务暂不可用"

    def test_send_sse_error_returns_error_event(self):
        evt = chat._send_sse_error("boom")
        assert evt.startswith("data: ")
        payload = evt[len("data: ") :].strip()
        data = json.loads(payload)
        assert data["event"] == "error"
        assert data["message"] == "boom"


# ---------- _save_user_msg ----------


class TestSaveUserMsg:
    @pytest.mark.asyncio
    async def test_save_user_msg_persists_and_appends_context(self):
        """普通路径：保存 user message + append_to_context，标题不更新。"""
        with (
            patch("app.api.v1.chat.async_session") as mock_session_cls,
            patch("app.services.chat_service.save_message", new=AsyncMock()) as mock_save,
            patch("app.services.chat_service.append_to_context", new=AsyncMock()) as mock_append,
        ):
            # async_session() 作为 async context manager
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__.return_value = mock_db
            mock_session_cls.return_value.__aexit__.return_value = None

            await chat._save_user_msg(session_id=1, content="hello", session_title="已存在标题")

            mock_save.assert_awaited_once_with(1, "user", "hello", mock_db)
            mock_append.assert_awaited_once_with(1, "user", "hello")

    @pytest.mark.asyncio
    async def test_save_user_msg_updates_title_for_new_session(self):
        """标题为 '新对话' 时应触发更新逻辑（执行 select ChatSession）。"""
        with (
            patch("app.api.v1.chat.async_session") as mock_session_cls,
            patch("app.services.chat_service.save_message", new=AsyncMock()),
            patch("app.services.chat_service.append_to_context", new=AsyncMock()),
        ):
            # 模拟 stream_db.execute 返回一个 session 对象
            mock_db = AsyncMock()
            fake_sess = MagicMock()
            fake_sess.title = "新对话"
            result = MagicMock()
            result.scalar_one_or_none.return_value = fake_sess
            mock_db.execute = AsyncMock(return_value=result)

            # async_session() 被调用 2 次（保存 user msg + 更新 title），都返回 mock_db
            mock_session_cls.return_value.__aenter__.return_value = mock_db
            mock_session_cls.return_value.__aexit__.return_value = None

            await chat._save_user_msg(session_id=1, content="新问题内容", session_title="新对话")

            # 应该执行 select ChatSession 查询
            mock_db.execute.assert_awaited()
            # 应该提交标题更新
            mock_db.commit.assert_awaited()
            # 标题应被截断为前 30 字符
            assert fake_sess.title == "新问题内容"


# ---------- _retrieve_and_rerank ----------


class TestRetrieveAndRerank:
    @pytest.mark.asyncio
    async def test_retrieve_and_rerank_no_kb_returns_empty(self):
        """kb_id 为 None 时直接返回 ([], [])，不发起检索。"""
        chunks, events = await chat._retrieve_and_rerank(query="q", kb_id=None)
        assert chunks == []
        assert events == []

    @pytest.mark.asyncio
    async def test_retrieve_and_rerank_normal_path(self):
        """有 kb_id 时返回 chunks 与 searching 事件。"""
        fake_chunks = [{"id": 1, "content": "c1"}]
        with (
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(return_value=fake_chunks)),
            patch(
                "app.rag.reranker.reranker.rerank", new=AsyncMock(return_value=fake_chunks)
            ) as mock_rerank,
        ):
            chunks, events = await chat._retrieve_and_rerank(query="q", kb_id=1)

        assert chunks == fake_chunks
        # 应有 2 个 searching 事件（chunks_found=0 和 chunks_found=1）
        assert len(events) == 2
        for evt in events:
            data = json.loads(evt[len("data: ") :].strip())
            assert data["event"] == "searching"
        assert json.loads(events[0][len("data: ") :].strip())["chunks_found"] == 0
        assert json.loads(events[1][len("data: ") :].strip())["chunks_found"] == 1
        mock_rerank.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retrieve_and_rerank_reranker_failure_emits_warn(self):
        """reranker 失败时应发出 warn 事件，并保留原 chunks（截断到 top_k）。"""
        fake_chunks = [{"id": i, "content": f"c{i}"} for i in range(8)]
        with (
            patch("app.rag.retriever.retriever.retrieve", new=AsyncMock(return_value=fake_chunks)),
            patch(
                "app.rag.reranker.reranker.rerank",
                new=AsyncMock(side_effect=RuntimeError("model load failed")),
            ),
        ):
            chunks, events = await chat._retrieve_and_rerank(query="q", kb_id=1)

        # 应该有 3 个事件：searching 0, searching 8, warn
        assert len(events) == 3
        warn_data = json.loads(events[2][len("data: ") :].strip())
        assert warn_data["event"] == "warn"
        assert "重排序" in warn_data["message"]
        # chunks 应被截断到 RERANK_TOP_K
        from app.config import settings

        assert len(chunks) == settings.RERANK_TOP_K


# ---------- _stream_llm_with_fallback ----------


class TestStreamLlmWithFallback:
    @pytest.mark.asyncio
    async def test_primary_provider_streams_tokens(self):
        """primary provider 正常时应 yield model + delta 事件，state 累积 full_answer。"""
        primary_llm = MagicMock()
        primary_llm.provider_name = "ollama"
        primary_llm.model_name = "qwen2.5:7b"

        async def fake_stream(messages):
            for tok in ["Hello", " world"]:
                yield tok

        primary_llm.chat_stream = fake_stream

        model_router = MagicMock()
        state = {"full_answer": "", "cancelled": False, "token_count": 0}

        events = []
        async for evt in chat._stream_llm_with_fallback(
            messages=[{"role": "user", "content": "hi"}],
            primary_llm=primary_llm,
            model_router=model_router,
            session_id=1,
            state=state,
        ):
            events.append(evt)

        # 期望：1 个 model 事件 + 2 个 delta 事件
        assert len(events) == 3
        model_data = json.loads(events[0][len("data: ") :].strip())
        assert model_data["event"] == "model"
        assert model_data["model_name"] == "ollama"
        delta1 = json.loads(events[1][len("data: ") :].strip())
        assert delta1 == {"event": "delta", "content": "Hello"}
        # state 应累积完整答案
        assert state["full_answer"] == "Hello world"
        assert state["token_count"] == 2
        assert state["cancelled"] is False
        # 应 release primary provider
        model_router.release.assert_called_once_with("ollama")

    @pytest.mark.asyncio
    async def test_fallback_triggered_on_primary_failure(self):
        """primary provider 抛异常时应触发 fallback，发送 restart 事件。"""
        primary_llm = MagicMock()
        primary_llm.provider_name = "ollama"
        primary_llm.model_name = "qwen2.5:7b"

        async def failing_stream(messages):
            yield "partial"
            raise RuntimeError("ollama down")

        primary_llm.chat_stream = failing_stream

        # Fallback provider
        fallback_llm = MagicMock()
        fallback_llm.provider_name = "openai"
        fallback_llm.model_name = "gpt-4"

        async def fallback_stream(messages):
            for tok in ["full", " answer"]:
                yield tok

        fallback_llm.chat_stream = fallback_stream

        model_router = MagicMock()
        state = {"full_answer": "", "cancelled": False, "token_count": 0}

        with patch("app.models.factory.ModelRegistry.get_available", return_value=[fallback_llm]):
            events = []
            async for evt in chat._stream_llm_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                primary_llm=primary_llm,
                model_router=model_router,
                session_id=1,
                state=state,
            ):
                events.append(evt)

        # 期望事件序列：
        # 1. model (primary)
        # 2. delta (partial)
        # 3. restart (因为 primary 已经 yield 出 token)
        # 4. model (fallback, fallback=True)
        # 5. delta (full)
        # 6. delta (answer)
        event_types = [json.loads(e[len("data: ") :].strip())["event"] for e in events]
        assert event_types == ["model", "delta", "restart", "model", "delta", "delta"]
        # state 应只包含 fallback 的内容（primary 部分已重置）
        assert state["full_answer"] == "full answer"
        assert state["token_count"] == 2
        # 检查 fallback model 事件带 fallback=True
        fallback_model_evt = json.loads(events[3][len("data: ") :].strip())
        assert fallback_model_evt["fallback"] is True
        assert fallback_model_evt["model_name"] == "openai"
        model_router.release.assert_called_once_with("ollama")

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises_exception(self):
        """所有 provider 都失败时应抛异常。"""
        primary_llm = MagicMock()
        primary_llm.provider_name = "ollama"
        primary_llm.model_name = "qwen2.5:7b"

        async def failing_stream(messages):
            raise RuntimeError("ollama down")

        primary_llm.chat_stream = failing_stream

        fallback_llm = MagicMock()
        fallback_llm.provider_name = "openai"
        fallback_llm.model_name = "gpt-4"

        async def failing_fallback(messages):
            raise RuntimeError("openai also down")

        fallback_llm.chat_stream = failing_fallback

        model_router = MagicMock()
        state = {"full_answer": "", "cancelled": False, "token_count": 0}

        with patch("app.models.factory.ModelRegistry.get_available", return_value=[fallback_llm]):
            with pytest.raises(Exception, match="All LLM providers failed"):
                async for _ in chat._stream_llm_with_fallback(
                    messages=[{"role": "user", "content": "hi"}],
                    primary_llm=primary_llm,
                    model_router=model_router,
                    session_id=1,
                    state=state,
                ):
                    pass

        # finally 仍应释放 primary provider
        model_router.release.assert_called_once_with("ollama")

    @pytest.mark.asyncio
    async def test_cancel_flag_breaks_stream(self):
        """每 CANCEL_CHECK_INTERVAL 个 token 检查一次取消标志，命中后停止。"""
        primary_llm = MagicMock()
        primary_llm.provider_name = "ollama"
        primary_llm.model_name = "qwen2.5:7b"

        # 让 CANCEL_CHECK_INTERVAL=16 触发：生成 17 个 token 后第 16 个检查时取消
        async def fake_stream(messages):
            for i in range(20):
                yield f"t{i}_"

        primary_llm.chat_stream = fake_stream

        model_router = MagicMock()
        state = {"full_answer": "", "cancelled": False, "token_count": 0}

        # is_cancelled 第 1 次调用返回 True（在第 16 个 token 时检查）
        with patch("app.services.chat_service.is_cancelled", new=AsyncMock(return_value=True)):
            events = []
            async for evt in chat._stream_llm_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                primary_llm=primary_llm,
                model_router=model_router,
                session_id=1,
                state=state,
            ):
                events.append(evt)

        # 应在第 16 个 token 后取消
        delta_count = sum(
            1 for e in events if json.loads(e[len("data: ") :].strip())["event"] == "delta"
        )
        assert delta_count == 16
        assert state["cancelled"] is True
        assert state["token_count"] == 16
        model_router.release.assert_called_once_with("ollama")


# ---------- _save_assistant_msg ----------


class TestSaveAssistantMsg:
    @pytest.mark.asyncio
    async def test_save_assistant_msg_normal_path(self):
        """正常保存路径应返回 saved_msg.id。"""
        fake_msg = MagicMock()
        fake_msg.id = 42
        with (
            patch("app.api.v1.chat.async_session") as mock_session_cls,
            patch(
                "app.services.chat_service.save_message", new=AsyncMock(return_value=fake_msg)
            ) as mock_save,
        ):
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__.return_value = mock_db
            mock_session_cls.return_value.__aexit__.return_value = None

            msg_id = await chat._save_assistant_msg(
                session_id=1,
                content="answer",
                references=[1, 2],
                latency_ms=200,
                summary_text=None,
                token_input=10,
                token_output=20,
            )

        assert msg_id == 42
        mock_save.assert_awaited_once()
        # save_message 前 4 个参数是位置参数：session_id, role, content, db
        args, kwargs = mock_save.call_args
        assert args[0] == 1
        assert args[1] == "assistant"
        assert args[2] == "answer"
        assert args[3] is mock_db
        # 后续参数是关键字参数
        assert kwargs["references"] == [1, 2]
        assert kwargs["latency_ms"] == 200
        assert kwargs["token_input"] == 10
        assert kwargs["token_output"] == 20

    @pytest.mark.asyncio
    async def test_save_assistant_msg_fallback_on_failure(self):
        """首次保存失败时应尝试保存错误 fallback 消息。"""
        fallback_msg = MagicMock()
        fallback_msg.id = 99
        with (
            patch("app.api.v1.chat.async_session") as mock_session_cls,
            patch(
                "app.services.chat_service.save_message",
                new=AsyncMock(side_effect=[RuntimeError("db error"), fallback_msg]),
            ) as mock_save,
        ):
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__.return_value = mock_db
            mock_session_cls.return_value.__aexit__.return_value = None

            msg_id = await chat._save_assistant_msg(
                session_id=1,
                content="answer",
                references=[],
                latency_ms=200,
                summary_text=None,
                token_input=10,
                token_output=20,
            )

        assert msg_id == 99
        assert mock_save.await_count == 2
        # 第二次调用：前 4 个位置参数中 args[2] 是 content（错误 fallback 消息）
        second_call_args, _ = mock_save.call_args_list[1]
        assert "[系统错误]" in second_call_args[2]
        assert "answer" in second_call_args[2]

    @pytest.mark.asyncio
    async def test_save_assistant_msg_returns_none_on_total_failure(self):
        """两次保存都失败时应返回 None。"""
        with (
            patch("app.api.v1.chat.async_session") as mock_session_cls,
            patch(
                "app.services.chat_service.save_message",
                new=AsyncMock(side_effect=[RuntimeError("1st"), RuntimeError("2nd")]),
            ),
        ):
            mock_db = AsyncMock()
            mock_session_cls.return_value.__aenter__.return_value = mock_db
            mock_session_cls.return_value.__aexit__.return_value = None

            msg_id = await chat._save_assistant_msg(
                session_id=1,
                content="answer",
                references=[],
                latency_ms=200,
                summary_text=None,
                token_input=10,
                token_output=20,
            )

        assert msg_id is None


# ---------- event_stream 主函数编排 ----------


class TestEventStreamOrchestration:
    """验证 event_stream 主函数仅做编排（通过 mock 子函数测试端到端流程）。"""

    @pytest.mark.asyncio
    async def test_event_stream_yields_done_on_success(self):
        """正常路径：生成 done 事件 + [DONE]。

        注意：event_stream 是 async generator，必须在与 patch 同一上下文内迭代
        body_iterator，否则 patch 退出后 mock 失效。
        """
        from starlette.requests import Request

        # 构造 send_message 调用所需的上下文
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/chat/sessions/1/messages",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 8000),
        }
        request = Request(scope)
        user = MagicMock()
        user.id = 1
        db = AsyncMock()

        # mock session
        session = MagicMock()
        session.id = 1
        session.kb_id = None  # 跳过 RAG
        session.title = "已存在"
        session.user_id = 1

        req = MagicMock()
        req.content = "hello"
        req.model = "ollama"

        # mock 所有依赖：SSE 计数（直接降级）+ 子函数
        with (
            patch("app.services.chat_service.get_session", new=AsyncMock(return_value=session)),
            patch("app.api.v1.chat.get_redis", return_value=None),
            patch("app.api.v1.chat._save_user_msg", new=AsyncMock()) as mock_save_user,
            patch("app.services.chat_service.get_history_context", new=AsyncMock(return_value=[])),
            patch("app.services.chat_service.is_cancelled", new=AsyncMock(return_value=False)),
            patch("app.api.v1.chat._retrieve_and_rerank", new=AsyncMock(return_value=([], []))),
            patch(
                "app.rag.context_manager.context_manager.build_messages",
                return_value=[{"role": "user", "content": "hi"}],
            ),
            patch("app.core.model_router.ModelRouter") as mock_router_cls,
            patch("app.api.v1.chat._stream_llm_with_fallback") as mock_stream_gen,
            patch(
                "app.api.v1.chat._save_assistant_msg", new=AsyncMock(return_value=42)
            ) as mock_save_asst,
            patch("app.services.chat_service.append_to_context", new=AsyncMock()),
            patch("app.services.chat_service.clear_cancel", new=AsyncMock()),
        ):
            # _stream_llm_with_fallback 是 async generator
            async def fake_stream(messages, llm, router, sid, state):
                state["full_answer"] = "answer"
                state["cancelled"] = False
                state["token_count"] = 1
                yield chat._send_sse({"event": "delta", "content": "answer"})

            mock_stream_gen.side_effect = fake_stream
            mock_router_cls.return_value.select = AsyncMock(
                return_value=MagicMock(provider_name="ollama", model_name="qwen")
            )
            mock_router_cls.return_value.release = MagicMock()

            # 调用 send_message（会内部构造 event_stream 并返回 StreamingResponse）
            response = await chat.send_message(
                request=request,
                session_id=1,
                req=req,
                user=user,
                db=db,
            )

            # 必须在 patch 上下文内迭代 body_iterator，才会真正执行 event_stream
            events = []
            async for chunk in response.body_iterator:
                events.append(chunk)

        # 期望：delta (from mock) + done + [DONE]
        joined = "".join(events)
        assert "delta" in joined
        assert "done" in joined
        assert joined.endswith("data: [DONE]\n\n")
        # 子函数被调用
        mock_save_user.assert_awaited_once()
        mock_save_asst.assert_awaited_once()
