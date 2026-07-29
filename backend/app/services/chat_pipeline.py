"""Chat Pipeline 业务核心：拆自 api/v1/chat.py（Blade 2 Step 3）。

职责：
- ChatPipeline.run() 编排 SSE 全流（保存用户消息 → 检索重排 → 构建消息 → 选 provider → 流式 fallback → 回填助手消息 → 最终 SSE），
  对外暴露 AsyncIterator[str]（SSE 事件）供路由层 yield。
- `_retrieve_and_rerank`、`_stream_llm_with_fallback`、`_sse_counter`、`_run_sse_stream`
  均由 chat.py 迁移至此，chat.py 仅保留 FastAPI 路由装配层（APIRouter / Depends / 限流）。

依赖方向：api/v1/chat → chat_pipeline → services/chat_service / rag/* / models/factory，
chat_pipeline 不再反向 import api，chat.py 不再 import main，彻底消除循环依赖。
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.config import settings
from app.core import sse_registry
from app.core.exceptions import AllProvidersFailedError
from app.core.metrics import (
    CHAT_RESPONSE_DURATION,
    LLM_INFERENCE_DURATION,
    RAG_E2E_LATENCY,
    RAG_LLM_TOKENS_PER_SECOND,
    RAG_LLM_TTFT,
    RAG_RETRIEVAL_LATENCY,
)
from app.core.redis_scripts import _DECR_CLEANUP_LUA, _INCR_EXPIRE_LUA
from app.database import async_session
from app.rag.reference_parser import parse_references
from app.redis_client import get_redis
from app.services import chat_service
from app.utils.token_counter import count_tokens

# SSE 计数 key 前缀（路由装配层也会引用此常量，放 chat_pipeline 作为源）
SSE_COUNT_KEY_PREFIX = "sse_count"


# ---------- SSE 序列化 ----------


def _send_sse(event: dict) -> str:
    """格式化 SSE data 事件字符串（确保中文不转义）。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _send_sse_error(message: str) -> str:
    """构造 SSE error 事件字符串。"""
    return _send_sse({"event": "error", "message": message})


# ---------- DB/Redis 辅助 ----------


async def _save_user_msg(session_id: int, content: str, session_title: str | None) -> None:
    """保存用户消息到 DB + 追加到 Redis 上下文，必要时自动更新会话标题。"""
    async with async_session() as stream_db:
        await chat_service.save_message(session_id, "user", content, stream_db)
    await chat_service.append_to_context(session_id, "user", content)

    if session_title == "新对话" or not session_title:
        async with async_session() as stream_db:
            from sqlalchemy import select as sa_select

            from app.db.chat_session import ChatSession

            result = await stream_db.execute(
                sa_select(ChatSession).where(ChatSession.id == session_id)
            )
            sess = result.scalar_one_or_none()
            if sess:
                sess.title = content[:30] + ("..." if len(content) > 30 else "")
                await stream_db.commit()


async def _get_history_context(session_id: int) -> list:
    """获取会话历史上下文（Redis 不可用时回退 DB 查询历史）。"""
    async with async_session() as history_db:
        return await chat_service.get_history_context(
            session_id, limit=settings.CHAT_HISTORY_LIMIT, db=history_db
        )


async def _save_assistant_msg(
    session_id: int,
    content: str,
    references: list,
    latency_ms: int,
    summary_text: str | None,
    token_input: int,
    token_output: int,
    message_id: int | None = None,
) -> int | None:
    """保存或回填助手消息到 DB；失败时写入 fallback 错误消息，避免 user 消息孤悬。

    H6: 若 message_id 不为 None，视为预创建的占位消息，先 UPDATE，
    未找到 / 抛错时降级 INSERT。
    """
    if message_id is not None:
        try:
            async with async_session() as stream_db:
                updated = await chat_service.update_assistant_message(
                    message_id,
                    stream_db,
                    content,
                    references=references,
                    token_input=token_input,
                    token_output=token_output,
                    latency_ms=latency_ms,
                    summary_snapshot=summary_text,
                )
            if updated:
                return message_id
            logger.warning(
                f"Placeholder message_id={message_id} not found, falling back to INSERT"
            )
        except Exception as update_err:
            logger.error(
                f"Failed to update placeholder message_id={message_id} for session {session_id}: {update_err}"
            )
    try:
        async with async_session() as stream_db:
            saved_msg = await chat_service.save_message(
                session_id,
                "assistant",
                content,
                stream_db,
                references=references,
                token_input=token_input,
                token_output=token_output,
                latency_ms=latency_ms,
                summary_snapshot=summary_text,
            )
        return saved_msg.id
    except Exception as save_err:
        logger.error(f"Failed to save assistant message for session {session_id}: {save_err}")
        try:
            async with async_session() as stream_db:
                saved_msg = await chat_service.save_message(
                    session_id,
                    "assistant",
                    f"[系统错误] 消息保存失败，请重试。已生成内容：\n{content[:500]}",
                    stream_db,
                    references=references,
                    latency_ms=latency_ms,
                )
            return saved_msg.id
        except Exception as fe:
            logger.error(f"Fallback save also failed for session {session_id}: {fe}")
            return None


# ---------- 检索 + 重排 ----------


async def _retrieve_and_rerank(query: str, kb_id: int | None) -> tuple[list, list[str]]:
    """执行 RAG 检索 + 重排序，返回 (chunks, sse_events)。

    sse_events 含 searching/warn 事件字符串，由调用方直接 yield。
    kb_id 为 None 时返回 ([], [])。
    """
    events: list[str] = []
    if not kb_id:
        return [], events

    from app.rag.reranker import reranker
    from app.rag.retriever import retriever

    events.append(_send_sse({"event": "searching", "chunks_found": 0}))
    if settings.QUERY_EXPANSION_ENABLED:
        from app.rag.query_rewriter import retrieve_with_expansion

        chunks = await retrieve_with_expansion(query, kb_id, top_k=settings.RETRIEVAL_TOP_K)
    else:
        chunks = await retriever.retrieve(query, kb_id, top_k=settings.RETRIEVAL_TOP_K)
    events.append(_send_sse({"event": "searching", "chunks_found": len(chunks)}))

    if chunks:
        rerank_t0 = time.perf_counter()
        try:
            chunks = await reranker.rerank(query, chunks, top_k=settings.RERANK_TOP_K)
        except Exception as e:
            logger.warning(f"Reranker failed, proceeding without reranking: {e}")
            events.append(
                _send_sse({"event": "warn", "message": "重排序服务暂不可用，检索质量可能下降"})
            )
            chunks = [
                c
                for c in chunks
                if c.get("score") is None or c.get("score", 0) >= settings.RETRIEVAL_SCORE_THRESHOLD
            ][: settings.RERANK_TOP_K]
        finally:
            RAG_RETRIEVAL_LATENCY.labels(stage="rerank").observe(time.perf_counter() - rerank_t0)

    return chunks, events


# ---------- LLM：构建消息 + 选 provider + 流式 fallback ----------


async def _build_llm_messages(
    history: list,
    content: str,
    chunks: list,
    session_id: int,
) -> tuple[list[dict], str | None]:
    """构建 LLM 消息列表，长历史时进行摘要压缩。

    返回 (messages, summary_text)。
    """
    from app.rag.context_manager import context_manager
    from app.redis_client import get_summary_cache, set_summary_cache

    summary_text = None
    if context_manager.needs_summary(history):
        cached_summary = await get_summary_cache(session_id)
        messages, summary_text = await context_manager.get_context_with_summary(
            history, content, chunks, existing_summary=cached_summary
        )
        if summary_text and summary_text != cached_summary:
            await set_summary_cache(session_id, summary_text)
    else:
        messages = context_manager.build_messages(history, content, chunks)
    return messages, summary_text


async def _select_llm_provider(model: str | None) -> tuple:
    """选择 LLM provider，返回 (llm, model_router)；失败时抛 ValueError。"""
    from app.core.model_router import ModelRouter

    model_router = ModelRouter()
    llm = await model_router.select(model)
    return llm, model_router


async def _stream_llm_with_fallback(
    messages: list[dict],
    primary_llm,
    model_router,
    session_id: int,
    state: dict[str, Any],
    message_id: int | None = None,
) -> AsyncIterator[str]:
    """流式生成 LLM 回答，支持 fallback + 取消。

    state 用于可变返回：
      state["full_answer"] / state["cancelled"] / state["token_count"]
    """
    primary_provider = primary_llm.provider_name
    stream_t0 = time.perf_counter()
    ttft_recorded = False

    def _record_ttft(model_name: str) -> None:
        nonlocal ttft_recorded
        if not ttft_recorded:
            RAG_LLM_TTFT.labels(model=model_name).observe(time.perf_counter() - stream_t0)
            ttft_recorded = True

    try:
        yield _send_sse(
            {
                "event": "model",
                "model_name": primary_llm.provider_name,
                "display_name": primary_llm.model_name,
            }
        )
        first_delta = True
        async for token in primary_llm.chat_stream(messages):
            _record_ttft(primary_llm.provider_name)
            state["full_answer"] += token
            state["token_count"] += 1
            evt: dict = {"event": "delta", "content": token}
            if first_delta and message_id is not None:
                evt["message_id"] = message_id
                first_delta = False
            yield _send_sse(evt)
            if (
                state["token_count"] % settings.CANCEL_CHECK_INTERVAL == 0
                and await chat_service.is_cancelled(session_id)
            ):
                state["cancelled"] = True
                break
    except Exception as e:
        logger.warning(
            f"Primary provider '{primary_llm.provider_name}' failed: {e}, attempting fallback..."
        )
        if state["full_answer"]:
            yield _send_sse({"event": "restart", "data": "{}"})
        state["full_answer"] = ""
        state["token_count"] = 0
        from app.models.factory import ModelRegistry

        fallback_success = False
        fallbacks_tried = 0
        available = ModelRegistry.get_available()
        for fallback_llm in available:
            if fallback_llm.provider_name == primary_llm.provider_name:
                continue
            fallbacks_tried += 1
            try:
                logger.info(f"Fallback to provider: {fallback_llm.provider_name}")
                yield _send_sse(
                    {
                        "event": "model",
                        "model_name": fallback_llm.provider_name,
                        "display_name": fallback_llm.model_name,
                        "fallback": True,
                    }
                )
                first_delta = True
                async for token in fallback_llm.chat_stream(messages):
                    _record_ttft(fallback_llm.provider_name)
                    state["full_answer"] += token
                    state["token_count"] += 1
                    evt = {"event": "delta", "content": token}
                    if first_delta and message_id is not None:
                        evt["message_id"] = message_id
                        first_delta = False
                    yield _send_sse(evt)
                    if (
                        state["token_count"] % settings.CANCEL_CHECK_INTERVAL == 0
                        and await chat_service.is_cancelled(session_id)
                    ):
                        state["cancelled"] = True
                        break
                fallback_success = True
                break
            except Exception as fe:
                logger.warning(
                    f"Fallback provider '{fallback_llm.provider_name}' also failed: {fe}"
                )
        if not fallback_success:
            raise AllProvidersFailedError(
                primary=primary_provider, fallbacks_tried=fallbacks_tried
            ) from e
    finally:
        elapsed = time.perf_counter() - stream_t0
        if elapsed > 0 and state.get("token_count", 0) > 0:
            RAG_LLM_TOKENS_PER_SECOND.labels(model=primary_llm.provider_name).set(
                state["token_count"] / elapsed
            )
        LLM_INFERENCE_DURATION.labels(model=primary_llm.provider_name).observe(elapsed)
        model_router.release(primary_provider)


# ---------- SSE 并发计数器 ----------


@asynccontextmanager
async def _sse_counter(user_id: int) -> AsyncIterator[None]:
    """SSE 并发连接计数器 context manager。

    进入时 INCR + 设置 TTL，超过上限 raise 429；
    退出时 DECR（仅成功获取配额时）。Redis 不可用时降级放行。
    """
    redis = get_redis()
    sse_key = f"{SSE_COUNT_KEY_PREFIX}:{user_id}"
    sse_acquired = False
    if redis:
        try:
            count = await redis.eval(_INCR_EXPIRE_LUA, 1, sse_key, settings.SSE_COUNT_TTL)
            if count > settings.SSE_MAX_CONCURRENT:
                await redis.eval(_DECR_CLEANUP_LUA, 1, sse_key)
                logger.warning(f"SSE concurrent limit exceeded: user={user_id} count={count}")
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many concurrent SSE connections (max {settings.SSE_MAX_CONCURRENT})",
                )
            sse_acquired = True
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"SSE counter INCR failed (degrade open): {e}")
            sse_acquired = False
    else:
        logger.warning("Redis unavailable, SSE concurrent limit degraded open")

    try:
        yield
    finally:
        if sse_acquired:
            try:
                redis_client = get_redis()
                if redis_client:
                    await redis_client.eval(_DECR_CLEANUP_LUA, 1, sse_key)
            except Exception as decr_err:
                logger.warning(
                    f"SSE counter DECR failed (may leak quota): user={user_id} err={decr_err}"
                )


# ---------- SSE 主编排 ----------


async def _run_sse_stream(
    session_id: int,
    content: str,
    kb_id: int | None,
    session_title: str | None,
    model: str | None,
    counter_cm: AsyncIterator[None],
) -> AsyncIterator[str]:
    """SSE 流式生成主流程（模块级，避免闭包捕获）。

    counter_cm: 已通过 __aenter__ 的 _sse_counter context manager，
    在 finally 中 __aexit__ 以触发 DECR。
    """
    current_task = asyncio.current_task()
    if current_task is not None:
        sse_registry.register(current_task)
    try:
        start_time = time.time()
        e2e_t0 = time.perf_counter()
        await _save_user_msg(session_id, content, session_title)
        history = await _get_history_context(session_id)

        if await chat_service.is_cancelled(session_id):
            yield _send_sse({"event": "cancelled", "message": "生成已取消"})
            yield "data: [DONE]\n\n"
            return

        from app.rag.query_rewriter import rewrite_query

        try:
            retrieve_query = await rewrite_query(content, history)
        except Exception as e:
            logger.warning(f"Query rewrite failed, using original: {e}")
            retrieve_query = content

        chunks, retrieve_events = await _retrieve_and_rerank(retrieve_query, kb_id)
        for evt in retrieve_events:
            yield evt

        messages, summary_text = await _build_llm_messages(history, content, chunks, session_id)

        try:
            llm, model_router = await _select_llm_provider(model)
        except ValueError as e:
            yield _send_sse_error(str(e))
            return

        msg_id: int | None = None
        try:
            async with async_session() as placeholder_db:
                placeholder_msg = await chat_service.create_assistant_placeholder(
                    session_id, placeholder_db
                )
            msg_id = placeholder_msg.id
        except Exception as placeholder_err:
            logger.warning(
                f"Failed to create assistant placeholder for session {session_id}: {placeholder_err}"
            )
            msg_id = None

        state: dict[str, Any] = {"full_answer": "", "cancelled": False, "token_count": 0}
        async for sse_evt in _stream_llm_with_fallback(
            messages, llm, model_router, session_id, state, message_id=msg_id
        ):
            yield sse_evt

        full_answer = state["full_answer"]
        cancelled = state["cancelled"]
        references = parse_references(full_answer, chunks) if chunks and not cancelled else []
        latency_ms = int((time.time() - start_time) * 1000)
        saved_msg_id = await _save_assistant_msg(
            session_id,
            full_answer,
            references,
            latency_ms,
            summary_text,
            count_tokens(content),
            count_tokens(full_answer),
            message_id=msg_id,
        )
        if saved_msg_id is not None:
            msg_id = saved_msg_id
        await chat_service.append_to_context(session_id, "assistant", full_answer)

        if cancelled:
            yield _send_sse({"event": "cancelled", "message_id": msg_id, "message": "生成已取消"})
        else:
            yield _send_sse({"event": "done", "message_id": msg_id, "references": references})
        yield "data: [DONE]\n\n"

    except Exception as e:
        logger.exception(f"Chat SSE error: {e}")
        yield _send_sse_error("服务内部错误,请稍后重试")
        yield "data: [DONE]\n\n"
    finally:
        if current_task is not None:
            sse_registry.discard(current_task)
        # E2E 延迟：ChatPipeline 内唯一打点（路由层不再重复，避免重复计数
        try:
            e2e_latency = time.perf_counter() - e2e_t0
            RAG_E2E_LATENCY.labels(kb_id=str(kb_id) if kb_id is not None else "none").observe(
                e2e_latency
            )
            CHAT_RESPONSE_DURATION.observe(e2e_latency)
        except NameError:
            pass
        await chat_service.clear_cancel(session_id)
        await counter_cm.__aexit__(None, None, None)


# ---------- 对外入口：ChatPipeline（chat.py 仅调用此对象）----------


class ChatPipeline:
    """ChatPipeline 为 SSE 生成的唯一编排入口，chat.py 的 `/sessions/{id}/messages` 仅负责：

    1. APIRouter 路由注册、Depends 注入、限流、session 归属校验
    2. 调用 ChatPipeline 提供的 stream() 获取 AsyncIterator[str]，
       以 StreamingResponse 形式返回。
    """

    # 允许子类/单测注入 mock 的 _run_sse_stream
    _run_stream_impl = staticmethod(_run_sse_stream)
    _sse_counter_impl = staticmethod(_sse_counter)

    @staticmethod
    def make_sse_counter(user_id: int) -> AsyncIterator[None]:
        """路由层装配 _sse_counter 的便捷方法。"""
        return ChatPipeline._sse_counter_impl(user_id)

    @staticmethod
    async def stream(
        session_id: int,
        content: str,
        kb_id: int | None,
        session_title: str | None,
        model: str | None,
        counter_cm: AsyncIterator[None],
    ) -> AsyncIterator[str]:
        """对外暴露的 SSE 流式入口。"""
        async for evt in ChatPipeline._run_stream_impl(
            session_id, content, kb_id, session_title, model, counter_cm
        ):
            yield evt
