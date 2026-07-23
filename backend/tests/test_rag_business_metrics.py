"""Tests for 5 RAG business metrics instrumentation (Task 1).

验证以下 5 个指标在对应代码路径中被正确 observe/set：
- RAG_RETRIEVAL_LATENCY{stage=vector|bm25|rrf|rerank|total}
- RAG_LLM_TTFT{model=...}
- RAG_LLM_TOKENS_PER_SECOND{model=...}
- RAG_E2E_LATENCY{kb_id=...}
- RAG_DOCUMENT_COUNT{kb_id=...}
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1 import chat as chat_module
from app.tasks import metrics_collector


# ---------------------------------------------------------------------------
# Task 1.1: RAG_RETRIEVAL_LATENCY — retriever.retrieve() 各阶段埋点
# ---------------------------------------------------------------------------


class TestRetrievalLatencyMetrics:
    @pytest.mark.asyncio
    async def test_retrieve_observes_all_latency_stages(self):
        """retrieve() 完成后应 observe vector/bm25/rrf/total 四个 stage"""
        from app.rag.retriever import HybridRetriever

        r = HybridRetriever()
        # mock 依赖方法，避免真实 IO
        r._get_chunks_for_bm25 = AsyncMock(return_value=[])
        r._vector_search = AsyncMock(return_value=[
            {"chunk_id": 1, "content": "a", "score": 0.9}
        ])

        with patch("app.rag.retriever.bm25_store") as mock_bm25, \
             patch("app.rag.retriever.RAG_RETRIEVAL_LATENCY") as mock_latency, \
             patch("app.rag.retriever.RAG_RETRIEVAL_TOTAL"):
            mock_bm25.search = AsyncMock(return_value=[
                {"chunk_id": 1, "content": "a", "score": 5.0}
            ])
            result = await r.retrieve("query", kb_id=1, top_k=5)

        assert len(result) == 1
        # 验证 4 个 stage 都被 observe
        # labels(stage=...).observe(...) 调用形式：labels(stage=...) 返回 histogram
        # 注意 labels 是 kwargs 调用（stage=...），所以用 call.kwargs.get("stage")
        stage_values = []
        for call in mock_latency.labels.call_args_list:
            stage = call.kwargs.get("stage")
            if stage:
                stage_values.append(stage)
        assert "vector" in stage_values
        assert "bm25" in stage_values
        assert "rrf" in stage_values
        assert "total" in stage_values
        # 每个 labels() 返回的对象应被 observe 调用
        assert mock_latency.labels.return_value.observe.call_count >= 4


# ---------------------------------------------------------------------------
# Task 1.2: RAG_LLM_TTFT / RAG_LLM_TOKENS_PER_SECOND — _stream_llm_with_fallback
# ---------------------------------------------------------------------------


class TestLLMMetrics:
    @pytest.mark.asyncio
    async def test_stream_llm_records_ttft_and_tokens_per_second(self):
        """_stream_llm_with_fallback 应在首 token 时记录 TTFT，结束时记录 tokens/s"""
        # 构造 mock primary_llm：chat_stream yield 3 个 token
        async def fake_chat_stream(messages):
            for t in ["hello", " world", "!"]:
                yield t

        primary_llm = MagicMock()
        primary_llm.provider_name = "ollama"
        primary_llm.model_name = "qwen2.5:7b"
        primary_llm.chat_stream = fake_chat_stream

        model_router = MagicMock()
        state = {"full_answer": "", "cancelled": False, "token_count": 0}

        with patch("app.api.v1.chat.RAG_LLM_TTFT") as mock_ttft, \
             patch("app.api.v1.chat.RAG_LLM_TOKENS_PER_SECOND") as mock_tps:
            events = []
            async for evt in chat_module._stream_llm_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                primary_llm=primary_llm,
                model_router=model_router,
                session_id=1,
                state=state,
            ):
                events.append(evt)

        # TTFT 在首 token 到达时记录一次
        mock_ttft.labels.assert_called_with(model="ollama")
        mock_ttft.labels.return_value.observe.assert_called_once()
        # tokens/s 在 finally 中记录
        mock_tps.labels.assert_called_with(model="ollama")
        mock_tps.labels.return_value.set.assert_called_once()
        # state 被正确更新
        assert state["token_count"] == 3
        assert state["full_answer"] == "hello world!"

    @pytest.mark.asyncio
    async def test_stream_llm_no_tokens_no_metrics(self):
        """LLM 未产出任何 token 时不记录 tokens/s（避免除零或无意义数据）"""
        async def empty_stream(messages):
            return
            yield  # 使其成为 async generator

        primary_llm = MagicMock()
        primary_llm.provider_name = "ollama"
        primary_llm.model_name = "qwen2.5:7b"
        primary_llm.chat_stream = empty_stream

        model_router = MagicMock()
        state = {"full_answer": "", "cancelled": False, "token_count": 0}

        with patch("app.api.v1.chat.RAG_LLM_TTFT"), \
             patch("app.api.v1.chat.RAG_LLM_TOKENS_PER_SECOND") as mock_tps:
            async for _ in chat_module._stream_llm_with_fallback(
                messages=[{"role": "user", "content": "hi"}],
                primary_llm=primary_llm,
                model_router=model_router,
                session_id=1,
                state=state,
            ):
                pass

        # 无 token 产出时不应记录 tokens/s
        mock_tps.labels.return_value.set.assert_not_called()


# ---------------------------------------------------------------------------
# Task 1.3: RAG_E2E_LATENCY — _run_sse_stream 入口/出口
# ---------------------------------------------------------------------------


class TestE2ELatencyMetric:
    @pytest.mark.asyncio
    async def test_e2e_latency_observed_on_normal_completion(self):
        """_run_sse_stream 正常完成时 RAG_E2E_LATENCY 被 observe"""
        # mock 所有依赖，使 _run_sse_stream 走 happy path
        counter_cm = MagicMock()
        counter_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("app.api.v1.chat._save_user_msg", new=AsyncMock()), \
             patch("app.api.v1.chat.chat_service") as mock_chat_svc, \
             patch("app.api.v1.chat._retrieve_and_rerank", new=AsyncMock(return_value=([], []))), \
             patch("app.api.v1.chat._stream_llm_with_fallback") as mock_stream, \
             patch("app.api.v1.chat._save_assistant_msg", new=AsyncMock(return_value=100)), \
             patch("app.api.v1.chat.RAG_E2E_LATENCY") as mock_e2e, \
             patch("app.api.v1.chat.settings"):
            mock_chat_svc.get_history_context = AsyncMock(return_value=[])
            mock_chat_svc.is_cancelled = AsyncMock(return_value=False)
            mock_chat_svc.clear_cancel = AsyncMock()
            mock_chat_svc.append_to_context = AsyncMock()

            async def fake_stream(*args, **kwargs):
                if False:
                    yield ""  # 使其成为 async generator

            mock_stream.return_value = fake_stream()

            # 消费 generator
            async for _ in chat_module._run_sse_stream(
                session_id=1, content="hi", kb_id=5,
                session_title="test", model=None, counter_cm=counter_cm,
            ):
                pass

        # RAG_E2E_LATENCY.labels(kb_id="5").observe(...) 被调用
        mock_e2e.labels.assert_called_with(kb_id="5")
        mock_e2e.labels.return_value.observe.assert_called_once()

    @pytest.mark.asyncio
    async def test_e2e_latency_observed_on_exception(self):
        """_run_sse_stream 异常时 RAG_E2E_LATENCY 仍在 finally 中被 observe"""
        counter_cm = MagicMock()
        counter_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("app.api.v1.chat._save_user_msg", new=AsyncMock(side_effect=RuntimeError("boom"))), \
             patch("app.api.v1.chat.chat_service") as mock_chat_svc, \
             patch("app.api.v1.chat.RAG_E2E_LATENCY") as mock_e2e, \
             patch("app.api.v1.chat.settings"):
            mock_chat_svc.clear_cancel = AsyncMock()

            async for _ in chat_module._run_sse_stream(
                session_id=1, content="hi", kb_id=None,
                session_title="test", model=None, counter_cm=counter_cm,
            ):
                pass

        # kb_id=None 时标签为 "none"
        mock_e2e.labels.assert_called_with(kb_id="none")
        mock_e2e.labels.return_value.observe.assert_called_once()


# ---------------------------------------------------------------------------
# Task 1.4: RAG_DOCUMENT_COUNT — metrics_collector.update_business_metrics
# ---------------------------------------------------------------------------


class TestDocumentCountMetric:
    @pytest.mark.asyncio
    async def test_document_count_set_per_kb(self):
        """update_business_metrics 按 KB 分组设置 RAG_DOCUMENT_COUNT"""
        fake_db = AsyncMock()
        fake_db.scalar = AsyncMock(side_effect=[5, 10, 3])
        fake_result = MagicMock()
        fake_result.all.return_value = [(1, 4), (2, 6), (3, 0)]
        fake_db.execute = AsyncMock(return_value=fake_result)

        with patch("app.tasks.metrics_collector.async_session") as mock_session_cls, \
             patch("app.tasks.metrics_collector.RAG_DOCUMENT_COUNT") as mock_dc:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=fake_db)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_cls.return_value = mock_session

            with patch("app.tasks.metrics_collector.TOTAL_USERS"), \
                 patch("app.tasks.metrics_collector.TOTAL_DOCUMENTS"), \
                 patch("app.tasks.metrics_collector.ACTIVE_SESSIONS"):
                await metrics_collector.update_business_metrics()

        # 3 个 KB 都被设置
        assert mock_dc.labels.call_count == 3
        mock_dc.labels.assert_any_call(kb_id="1")
        mock_dc.labels.assert_any_call(kb_id="2")
        mock_dc.labels.assert_any_call(kb_id="3")
        # count=0 时仍 set(0)（不跳过）
        mock_dc.labels.return_value.set.assert_any_call(4)
        mock_dc.labels.return_value.set.assert_any_call(6)
        mock_dc.labels.return_value.set.assert_any_call(0)
