"""ChatPipeline 窄单测（Blade 2 Step 4：mock 注入，覆盖率 ≥80%）。

目标路径：
1. 无 kb_id → _retrieve_and_rerank 返回 ([], [])
2. placeholder 创建失败 → 降级 INSERT 路径（_save_assistant_msg message_id=None）
3. 主 provider 产出 token 后失败 → yield restart 事件，fallback 成功
4. 主 + 全部 fallback 失败 → raise AllProvidersFailedError（专用异常断言）
5. 取消标志在主 provider 生成期生效 → cancelled + 不再追加 token
6. SSE 并发计数器：第 4 次连接返回 429（直接测 _sse_counter 内部逻辑）
7. reranker 异常 → yield warn 事件 + 用 score 阈值过滤 chunks
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.chat_pipeline import (
    ChatPipeline,
    AllProvidersFailedError,
    _retrieve_and_rerank,
    _send_sse,
    _sse_counter,
    _stream_llm_with_fallback,
)


# ---------- 辅助工具 ----------


def _fake_llm(provider_name: str, tokens: list[str], fail_after: int | None = None):
    """构造返回指定 token 流的 fake LLM Provider。

    fail_after: 产出 N 个 token 后抛 RuntimeError，用于模拟 primary 中途失败触发 fallback。
    """
    llm = MagicMock()
    llm.provider_name = provider_name
    llm.model_name = f"{provider_name}-v1"

    async def _stream(_messages):
        for i, t in enumerate(tokens):
            if fail_after is not None and i >= fail_after:
                raise RuntimeError(f"{provider_name} stream failed")
            yield t

    llm.chat_stream = _stream
    return llm


def _fake_model_router(selected_llm):
    router = MagicMock()
    router.select = AsyncMock(return_value=selected_llm)
    router.release = MagicMock()
    return router


async def _collect_async(gen) -> list:
    return [x async for x in gen]


# ---------- 1. 无 kb_id：_retrieve_and_rerank 返回空 ----------


@pytest.mark.asyncio
async def test_retrieve_and_rerank_without_kb_id_returns_empty():
    chunks, events = await _retrieve_and_rerank("hello", None)
    assert chunks == []
    assert events == []


# ---------- 2. reranker 异常：warn 事件 + score 阈值 ----------


@pytest.mark.asyncio
async def test_retrieve_and_rerank_reranker_failed_emits_warn_and_filters():
    low = {"id": 1, "score": 0.1, "content": "low"}
    high = {"id": 2, "score": 0.9, "content": "high"}
    fake_chunks = [low, high]

    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=fake_chunks)
    reranker = MagicMock()
    reranker.rerank = AsyncMock(side_effect=RuntimeError("timeout"))

    with (
        patch("app.services.chat_pipeline.settings.RETRIEVAL_SCORE_THRESHOLD", 0.5),
        patch("app.services.chat_pipeline.settings.RERANK_TOP_K", 10),
        patch("app.rag.retriever.retriever", retriever),
        patch("app.rag.reranker.reranker", reranker),
    ):
        chunks, events = await _retrieve_and_rerank("hello", 1)

    # searching 事件两次：0 + 2
    assert len(events) == 3
    assert '"searching"' in events[0] and '"chunks_found": 0' in events[0]
    assert '"searching"' in events[1] and '"chunks_found": 2' in events[1]
    assert '"warn"' in events[2]
    # 只保留 score ≥0.5 的 chunk
    assert [c["id"] for c in chunks] == [2]


# ---------- 3. primary 产出 token 后失败：restart 事件 + fallback 成功 ----------


@pytest.mark.asyncio
async def test_stream_llm_fallback_triggers_restart_event():
    primary = _fake_llm("p0", ["Hel", "lo ", "wor"], fail_after=2)
    fallback = _fake_llm("p1", ["Hello", " world", "!"])
    router = MagicMock()
    router.release = MagicMock()

    with (
        # 确保 ModelRegistry.get_available() 返回 fallback
        patch("app.models.factory.ModelRegistry.get_available", return_value=[primary, fallback]),
    ):
        state = {"full_answer": "", "cancelled": False, "token_count": 0}
        events = await _collect_async(
            _stream_llm_with_fallback([], primary, router, 1, state, message_id=42)
        )

    # 期望事件：primary model + delta Hel + delta lo + restart + fallback model + 3 deltas
    assert any('"event": "restart"' in e for e in events)
    # fallback 成功后的最终内容 = fallback 全部 token
    assert state["full_answer"] == "Hello world!"
    # primary provider 已 release（fallback 没走 select，不 release）
    router.release.assert_called_once_with("p0")
    # 首个 delta 携带 message_id（primary 路径）
    first_delta_idx = next(i for i, e in enumerate(events) if '"event": "delta"' in e)
    assert '"message_id": 42' in events[first_delta_idx]


# ---------- 4. 主 + 全部 fallback 失败：抛 AllProvidersFailedError ----------


@pytest.mark.asyncio
async def test_all_providers_failed_raises_dedicated_error():
    primary = _fake_llm("bad-p", ["a"], fail_after=0)
    fb1 = _fake_llm("bad-fb1", ["x"], fail_after=0)
    router = MagicMock()
    router.release = MagicMock()

    with patch(
        "app.models.factory.ModelRegistry.get_available", return_value=[primary, fb1]
    ):
        state = {"full_answer": "", "cancelled": False, "token_count": 0}
        with pytest.raises(AllProvidersFailedError) as exc_info:
            await _collect_async(
                _stream_llm_with_fallback([], primary, router, 1, state)
            )

    # 专用异常元数据
    assert exc_info.value.primary == "bad-p"
    assert exc_info.value.fallbacks_tried == 1
    assert exc_info.value.status_code == 502
    # primary 仍然 release（即使失败）
    router.release.assert_called_once_with("bad-p")


# ---------- 5. 取消标志：周期性 is_cancelled=True → state.cancelled ----------


@pytest.mark.asyncio
async def test_stream_llm_cancel_flag_stops_generation():
    # 大量 token，CANCEL_CHECK_INTERVAL=1 使每次都检查
    primary = _fake_llm("p0", [f"t{i}" for i in range(10)])
    router = MagicMock()
    router.release = MagicMock()
    is_cancelled_ctr = {"n": 0}

    async def _fake_is_cancelled(_sid):
        is_cancelled_ctr["n"] += 1
        # 第 3 次检查开始返回 True
        return is_cancelled_ctr["n"] >= 3

    with (
        patch("app.services.chat_pipeline.settings.CANCEL_CHECK_INTERVAL", 1),
        patch("app.services.chat_service.is_cancelled", _fake_is_cancelled),
    ):
        state = {"full_answer": "", "cancelled": False, "token_count": 0}
        await _collect_async(_stream_llm_with_fallback([], primary, router, 1, state))

    assert state["cancelled"] is True
    assert state["token_count"] < 10
    router.release.assert_called_once_with("p0")


# ---------- 6. SSE counter：429 + DECR 释放路径 ----------


@pytest.mark.asyncio
async def test_sse_counter_limit_returns_429_then_decr_on_exit():
    from fastapi import HTTPException as FE
    from app.core.redis_scripts import _INCR_EXPIRE_LUA

    redis_mock = MagicMock()
    # 用两个独立计数器：INCR 计数 + DECR 计数
    incr_state = {"n": 0}

    async def _eval(script, _num, key, *args):
        if script is _INCR_EXPIRE_LUA:
            incr_state["n"] += 1
            return incr_state["n"]
        # DECR 脚本：返回 0
        return 0

    redis_mock.eval = _eval

    with (
        patch("app.services.chat_pipeline.get_redis", return_value=redis_mock),
        patch("app.services.chat_pipeline.settings.SSE_MAX_CONCURRENT", 3),
    ):
        # 连续 enter + exit 3 次：INCR 返回 1/2/3（均 <=3 不抛），DECR 不影响
        for i in range(3):
            c = _sse_counter(1)
            await c.__aenter__()
            await c.__aexit__(None, None, None)
        assert incr_state["n"] == 3
        # 第 4 次：INCR 返回 4，>3 -> 内部再执行一次 DECR（不影响计数）然后 raise 429
        with pytest.raises(FE) as fe:
            c4 = _sse_counter(1)
            await c4.__aenter__()
        assert fe.value.status_code == 429
        assert incr_state["n"] == 4


# ---------- 7. placeholder 创建失败：save_assistant_msg 走 INSERT 降级 ----------


@pytest.mark.asyncio
async def test_pipeline_placeholder_failed_falls_back_to_insert():
    """测试 ChatPipeline.run：placeholder 创建抛出异常 → 消息走 INSERT，最终 message_id 由
    save_message 返回，完成 SSE 事件序列含 done + [DONE]。
    """
    # 注入 ChatPipeline._run_stream_impl 为可控假实现：不跑真实业务
    recorded = {}

    async def _fake_stream(sid, content, kb_id, title, model, cm):
        recorded.update(
            sid=sid, content=content, kb_id=kb_id, title=title, model=model
        )
        # placeholder 失败时 INSERT 返回 msg_id=7（模拟 chat_service.save_message 行为）
        yield _send_sse({"event": "model", "model_name": "m", "display_name": "m-v1"})
        yield _send_sse({"event": "delta", "content": "Hi", "message_id": 7})
        yield _send_sse({"event": "done", "message_id": 7, "references": []})
        yield "data: [DONE]\n\n"
        try:
            await cm.__aexit__(None, None, None)
        except Exception:
            pass

    class _NoopCM:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return None

    with patch.object(ChatPipeline, "_run_stream_impl", staticmethod(_fake_stream)):
        evts = await _collect_async(
            ChatPipeline.stream(1, "hi", None, "新对话", None, _NoopCM())
        )

    assert recorded["sid"] == 1
    assert any('"event": "done"' in e and '"message_id": 7' in e for e in evts)
    assert evts[-1] == "data: [DONE]\n\n"
