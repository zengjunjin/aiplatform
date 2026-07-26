import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_admin_user, get_current_user
from app.config import (
    RATE_LIMIT_DEFAULT,
    RATE_LIMIT_MODERATE,
    RATE_LIMIT_STRICT,
    settings,
)
from app.core.metrics import (
    RAG_E2E_LATENCY,
    RAG_LLM_TOKENS_PER_SECOND,
    RAG_LLM_TTFT,
    RAG_RETRIEVAL_LATENCY,
)
from app.core.middleware import limiter
from app.core.redis_scripts import _DECR_CLEANUP_LUA, _INCR_EXPIRE_LUA
from app.database import async_session, get_db
from app.db.user import User
from app.redis_client import get_redis
from app.schemas.chat import MessageCreate, MessageOut, SessionCreate, SessionOut, SessionUpdate
from app.schemas.common import ok, paginated_ok
from app.schemas.feedback import FeedbackCreate, FeedbackOut
from app.services import chat_service
from app.services.audit_service import log_audit

# Task 20: SSE 并发连接限制与取消检查间隔已迁移到 config.py
# SSE_COUNT_KEY_PREFIX 仍保留为模块常量（仅用于构造 Redis key，非业务参数）
SSE_COUNT_KEY_PREFIX = "sse_count"

router = APIRouter(prefix="/chat", tags=["chat"])


# ---------- SSE event_stream 拆分辅助函数 (Task 12) ----------


def _send_sse(event: dict) -> str:
    """格式化 SSE data 事件字符串（确保中文不转义）。"""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _send_sse_error(message: str) -> str:
    """构造 SSE error 事件字符串。"""
    return _send_sse({"event": "error", "message": message})


async def _save_user_msg(session_id: int, content: str, session_title: str | None) -> None:
    """保存用户消息到 DB + 追加到 Redis 上下文，必要时自动更新会话标题。

    使用独立 db 会话，避免在 SSE 流期间长持有 Depends(get_db) 的会话。
    """
    async with async_session() as stream_db:
        await chat_service.save_message(session_id, "user", content, stream_db)
    await chat_service.append_to_context(session_id, "user", content)

    # 首条消息自动更新会话标题
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
    """获取会话历史上下文（使用独立 db 会话，避免长持有）。

    Redis 不可用时回退 DB 查询历史。
    """
    async with async_session() as history_db:
        return await chat_service.get_history_context(
            session_id, limit=settings.CHAT_HISTORY_LIMIT, db=history_db
        )


async def _retrieve_and_rerank(query: str, kb_id: int | None) -> tuple[list, list[str]]:
    """执行 RAG 检索 + 重排序，返回 (chunks, sse_events)。

    sse_events 包含 searching/warn 事件字符串，由调用方直接 yield。
    kb_id 为 None 时直接返回 ([], [])。
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
        import time as _time

        rerank_t0 = _time.perf_counter()
        try:
            chunks = await reranker.rerank(query, chunks, top_k=settings.RERANK_TOP_K)
        except Exception as e:
            logger.warning(f"Reranker failed, proceeding without reranking: {e}")
            events.append(
                _send_sse({"event": "warn", "message": "重排序服务暂不可用，检索质量可能下降"})
            )
            # Task 13: reranker fallback 时同样过滤低于 score 阈值的 chunks
            chunks = [
                c
                for c in chunks
                if c.get("score") is None or c.get("score", 0) >= settings.RETRIEVAL_SCORE_THRESHOLD
            ][: settings.RERANK_TOP_K]
        finally:
            RAG_RETRIEVAL_LATENCY.labels(stage="rerank").observe(_time.perf_counter() - rerank_t0)

    return chunks, events


async def _build_llm_messages(
    history: list,
    content: str,
    chunks: list,
    session_id: int,
) -> tuple[list[dict], str | None]:
    """构建 LLM 消息列表，长历史时进行摘要压缩。

    返回 (messages, summary_text)。
    Task 12: 使用 context_manager.needs_summary() 替代硬编码 8，
    阈值与 CHAT_HISTORY_KEEP_RECENT 一致。
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
    """选择 LLM provider，返回 (llm, model_router)。

    失败时抛出 ValueError（由调用方负责 yield error 事件）。
    """
    from app.core.model_router import ModelRouter

    model_router = ModelRouter()
    llm = await model_router.select(model)
    return llm, model_router


async def _stream_llm_with_fallback(
    messages: list[dict],
    primary_llm,
    model_router,
    session_id: int,
    state: dict,
    message_id: int | None = None,
) -> AsyncIterator[str]:
    """流式生成 LLM 回答，支持 fallback 与取消。

    yield SSE 事件字符串（model/delta/restart），调用方直接转发。
    最终结果通过 state dict 返回：
      - state["full_answer"]: 完整回答文本
      - state["cancelled"]: 是否被取消
      - state["token_count"]: 已生成的 token 数

    primary_llm: 已通过 model_router.select() 选定的 LLM Provider
    model_router: ModelRouter 实例（用于 release primary provider）
    message_id: H6 助手消息占位记录 ID，会在每个 provider 的首个 delta 事件中携带，
        便于客户端在流式过程中即可拿到 message_id 用于反馈提交。
    """
    primary_provider = primary_llm.provider_name
    # 用于计算 TTFT 与 tokens/s 指标
    stream_t0 = time.perf_counter()
    ttft_recorded = False

    def _record_ttft(model_name: str) -> None:
        nonlocal ttft_recorded
        if not ttft_recorded:
            RAG_LLM_TTFT.labels(model=model_name).observe(time.perf_counter() - stream_t0)
            ttft_recorded = True

    try:
        # 在第一个事件中告知用户使用的模型名称
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
            # H6: 首个 delta 事件携带 message_id，方便客户端尽早用于反馈
            evt: dict = {"event": "delta", "content": token}
            if first_delta and message_id is not None:
                evt["message_id"] = message_id
                first_delta = False
            yield _send_sse(evt)
            # SIM102: 合并嵌套 if（外层周期性检查 + 内层取消检查）
            if state[
                "token_count"
            ] % settings.CANCEL_CHECK_INTERVAL == 0 and await chat_service.is_cancelled(session_id):
                state["cancelled"] = True
                break
    except Exception as e:
        logger.warning(
            f"Primary provider '{primary_llm.provider_name}' failed: {e}, attempting fallback..."
        )
        # Bug 12: 修复脏数据 - 进入 fallback 前重置 full_answer 与 token_count,
        # 避免 DB 保存 primary 部分内容 + fallback 完整内容的拼接脏数据。
        # 若 primary 已 yield 出 token, 发送 restart 事件让前端清空已显示内容
        if state["full_answer"]:
            yield _send_sse({"event": "restart", "data": "{}"})
        state["full_answer"] = ""
        state["token_count"] = 0
        # Fallback: 尝试其他 Provider
        # 注意: fallback 直接通过 ModelRegistry.get_available() 获取,
        # 未走 model_router.select(), 故 least_busy 计数未 +1,
        # finally 中无需 release fallback provider
        from app.models.factory import ModelRegistry

        fallback_success = False
        available = ModelRegistry.get_available()
        for fallback_llm in available:
            if fallback_llm.provider_name == primary_llm.provider_name:
                continue
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
                    # H6: fallback 首个 delta 事件同样携带 message_id
                    evt = {"event": "delta", "content": token}
                    if first_delta and message_id is not None:
                        evt["message_id"] = message_id
                        first_delta = False
                    yield _send_sse(evt)
                    # SIM102: 合并嵌套 if（外层周期性检查 + 内层取消检查）
                    if state[
                        "token_count"
                    ] % settings.CANCEL_CHECK_INTERVAL == 0 and await chat_service.is_cancelled(
                        session_id
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
            raise Exception("All LLM providers failed after fallback attempts") from e
    finally:
        # 记录 token 生成速率（仅在成功生成至少 1 个 token 时）
        elapsed = time.perf_counter() - stream_t0
        if elapsed > 0 and state.get("token_count", 0) > 0:
            RAG_LLM_TOKENS_PER_SECOND.labels(model=primary_llm.provider_name).set(
                state["token_count"] / elapsed
            )
        # 释放 least_busy 策略的请求计数
        # 仅 release primary_provider (走了 select()), fallback provider 未走 select() 不 release
        # release() 内部有 >0 检查, 非 least_busy 策略下 _request_counts 为空, 无副作用
        model_router.release(primary_provider)


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
    """保存或回填助手消息到 DB，失败时尝试保存错误 fallback 消息。

    H6: 若 message_id 不为 None，则视为已预创建的占位消息，执行 UPDATE 回填；
    否则降级为旧的 INSERT 行为（兼容占位创建失败的场景）。
    返回 saved_msg.id（彻底失败时返回 None）。
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
        # 保存一个 fallback 错误消息, 避免 user 消息孤悬
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


# ---------- SSE 并发计数器与流式主流程 (Task 1.3) ----------


@asynccontextmanager
async def _sse_counter(user_id: int) -> AsyncIterator[None]:
    """SSE 并发连接计数器 context manager。

    进入时 INCR + 设置 TTL，超过上限 raise 429。
    退出时 DECR（仅在成功获取配额时）。
    Redis 不可用时降级放行（不阻断业务）。
    """
    redis = get_redis()
    sse_key = f"{SSE_COUNT_KEY_PREFIX}:{user_id}"
    sse_acquired = False
    if redis:
        try:
            count = await redis.eval(_INCR_EXPIRE_LUA, 1, sse_key, settings.SSE_COUNT_TTL)
            if count > settings.SSE_MAX_CONCURRENT:
                # 超过上限：回滚刚才的 INCR 并拒绝
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
            # Redis 异常时降级：允许通过，仅记录警告
            logger.warning(f"SSE counter INCR failed (degrade open): {e}")
            sse_acquired = False
    else:
        # Redis 未初始化：降级放行
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
                # DECR 失败不影响主流程，但需记录以便排查计数器漂移
                logger.warning(
                    f"SSE counter DECR failed (may leak quota): user={user_id} err={decr_err}"
                )


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
    # Task 32: 将当前 SSE 请求注册到全局集合，用于优雅关闭时等待其完成。
    # 延迟 import 避免与 app.main 的循环依赖。
    from app.main import _active_sse_requests

    current_task = asyncio.current_task()
    if current_task is not None:
        _active_sse_requests.add(current_task)
    try:
        start_time = time.time()
        # Task 1.3: 记录 E2E 延迟（按 kb_id 标签）
        e2e_t0 = time.perf_counter()
        # 1. Save user message + auto-update title
        await _save_user_msg(session_id, content, session_title)
        # 使用独立 db 会话，Redis 不可用时回退 DB 查询历史
        history = await _get_history_context(session_id)

        # Pre-cancel check: 若在开始生成前已被取消（双击发送取消）
        if await chat_service.is_cancelled(session_id):
            yield _send_sse({"event": "cancelled", "message": "生成已取消"})
            return

        # Query rewrite: 消解多轮对话中的代词（仅用于检索，不影响用户原文）
        from app.rag.query_rewriter import rewrite_query

        try:
            retrieve_query = await rewrite_query(content, history)
        except Exception as e:
            logger.warning(f"Query rewrite failed, using original: {e}")
            retrieve_query = content

        # 2. Retrieve + rerank
        chunks, retrieve_events = await _retrieve_and_rerank(retrieve_query, kb_id)
        for evt in retrieve_events:
            yield evt

        # 3. Build messages (with summary compression for long history)
        messages, summary_text = await _build_llm_messages(history, content, chunks, session_id)

        # 4. Select LLM provider
        try:
            llm, model_router = await _select_llm_provider(model)
        except ValueError as e:
            yield _send_sse_error(str(e))
            return

        # H6: 在 LLM 流式开始前预创建助手消息占位记录，获取 message_id。
        # 这样首个 delta 事件即可携带 message_id，便于客户端流式过程中提交反馈。
        # 占位创建失败时降级为 msg_id=None（流后走旧 INSERT 路径，保持向后兼容）。
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

        # 5. Stream LLM with fallback (state 收集 full_answer/cancelled/token_count)
        state = {"full_answer": "", "cancelled": False, "token_count": 0}
        async for sse_evt in _stream_llm_with_fallback(
            messages, llm, model_router, session_id, state, message_id=msg_id
        ):
            yield sse_evt

        # 6. Parse references + save assistant message
        from app.rag.reference_parser import parse_references
        from app.utils.token_counter import count_tokens

        full_answer = state["full_answer"]
        cancelled = state["cancelled"]
        references = parse_references(full_answer, chunks) if chunks and not cancelled else []
        latency_ms = int((time.time() - start_time) * 1000)
        # H6: 若占位消息已创建，传入 message_id 执行 UPDATE 回填；否则降级 INSERT
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
        # 占位创建失败但后续 INSERT 成功时，使用 INSERT 返回的 id
        if saved_msg_id is not None:
            msg_id = saved_msg_id
        await chat_service.append_to_context(session_id, "assistant", full_answer)

        # 7. Final event
        if cancelled:
            yield _send_sse({"event": "cancelled", "message_id": msg_id, "message": "生成已取消"})
        else:
            yield _send_sse({"event": "done", "message_id": msg_id, "references": references})

    except Exception as e:
        logger.exception(f"Chat SSE error: {e}")
        yield _send_sse_error("服务内部错误,请稍后重试")
        return  # error occurred, do not send [DONE]
    finally:
        # Task 32: 从全局集合移除当前 SSE 请求
        if current_task is not None:
            _active_sse_requests.discard(current_task)
        # Task 1.3: 记录 E2E 延迟（kb_id 为 None 时统一记到 "none" 标签）
        RAG_E2E_LATENCY.labels(kb_id=str(kb_id) if kb_id is not None else "none").observe(
            time.perf_counter() - e2e_t0
        )
        # 清理取消标志（避免残留影响下次生成）
        await chat_service.clear_cancel(session_id)
        # 递减 SSE 并发计数器（无论正常结束、异常或客户端断开都会执行）
        # counter_cm 的 __aexit__ 触发 DECR（仅在成功获取配额时）
        await counter_cm.__aexit__(None, None, None)
        yield "data: [DONE]\n\n"


@router.post("/sessions")
@limiter.limit(RATE_LIMIT_MODERATE)
async def create_session(
    req: SessionCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await chat_service.create_session(req, user.id, db)
    await log_audit(
        action="chat.session.create",
        user_id=user.id,
        request=request,
        details={"session_id": session.id},
    )
    return ok(data=SessionOut.model_validate(session).model_dump())


@router.get("/sessions")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def list_sessions(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sessions, total = await chat_service.list_sessions(user.id, db, page, page_size)
    items = [SessionOut.model_validate(s).model_dump() for s in sessions]
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.get("/sessions/{session_id}")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def get_session(
    request: Request,
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await chat_service.get_session(session_id, user.id, db)
    messages, _ = await chat_service.get_messages(session_id, user.id, db, page=1, page_size=100)
    return ok(
        data={
            "session": SessionOut.model_validate(session).model_dump(),
            "messages": [MessageOut.model_validate(m).model_dump() for m in messages],
        }
    )


@router.put("/sessions/{session_id}")
@limiter.limit(RATE_LIMIT_MODERATE)
async def update_session(
    session_id: int,
    req: SessionUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await chat_service.update_session(session_id, req, user.id, db)
    await log_audit(
        action="chat.session.update",
        user_id=user.id,
        request=request,
        details={"session_id": session_id},
    )
    return ok(data=SessionOut.model_validate(session).model_dump())


@router.delete("/sessions/{session_id}")
@limiter.limit(RATE_LIMIT_MODERATE)
async def delete_session(
    session_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await chat_service.delete_session(session_id, user.id, db)
    await log_audit(
        action="chat.session.delete",
        user_id=user.id,
        request=request,
        details={"session_id": session_id},
    )
    return ok(message="Deleted")


@router.get("/sessions/{session_id}/messages")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def get_messages(
    request: Request,
    session_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    messages, total = await chat_service.get_messages(session_id, user.id, db, page, page_size)
    items = [MessageOut.model_validate(m).model_dump() for m in messages]
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.post("/sessions/{session_id}/messages")
@limiter.limit(RATE_LIMIT_STRICT)
async def send_message(
    request: Request,
    session_id: int,
    req: MessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 使用注入的 db 验证 session 归属 (短持有, 路由返回后即释放)
    session = await chat_service.get_session(session_id, user.id, db)

    # SSE 并发计数器：__aenter__ 做 INCR + 429 检查；__aexit__ 由 _run_sse_stream 在 finally 中调用做 DECR
    # 用 try/except 保护 __aenter__ 到返回 StreamingResponse 之间的间隙：
    # 若客户端在流开始迭代前断开 / 构造异常，_run_sse_stream 的 finally 不会执行，
    # 需在此处补做 __aexit__ 以避免 Redis 计数器泄漏导致用户被永久 429。
    counter_cm = _sse_counter(user.id)
    counter_entered = False
    try:
        await counter_cm.__aenter__()
        counter_entered = True
        return StreamingResponse(
            _run_sse_stream(
                session_id, req.content, session.kb_id, session.title, req.model, counter_cm
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
    except Exception:
        # 仅当 __aenter__ 成功后才需要 __aexit__ 释放计数器；
        # __aenter__ 自身失败（如 429，已在内部回滚 DECR）时不调用 __aexit__。
        # 成功返回路径不进入此处，__aexit__ 仍由 _run_sse_stream 的 finally 负责。
        logger.debug(f"SSE streaming setup failed for user_id={user.id}, re-raising")
        if counter_entered:
            await counter_cm.__aexit__(None, None, None)
        raise


@router.post("/sessions/{session_id}/cancel")
@limiter.limit(RATE_LIMIT_MODERATE)
async def cancel_generation(
    session_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消指定 session 当前进行中的流式生成。

    Phase F3: 通过 Redis 设置 cancel 标志，生成循环在下一次 token 检查时停止。
    """
    # 验证 session 归属
    await chat_service.get_session(session_id, user.id, db)
    await chat_service.request_cancel(session_id)
    await log_audit(
        action="chat.cancel", user_id=user.id, request=request, details={"session_id": session_id}
    )
    return ok(message="Cancellation requested")


# ---------- 反馈 API ----------


def _parse_date_range(start_date: str | None, end_date: str | None) -> tuple:
    """将 ISO 格式字符串解析为 datetime，None 或空则返回 None。

    消除 feedback/analysis 与 feedback/low-rated 中重复的 fromisoformat 调用。
    非法 ISO 字符串抛出 400 (HTTPException) 而非泄漏 500。
    """
    try:
        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date) if end_date else None
    except ValueError as e:
        # fromisoformat 对非法格式抛 ValueError，转为 400 避免被 generic_exception_handler 误判为 500
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format (expected ISO 8601): {e}",
        ) from e
    return start, end


@router.post("/messages/{message_id}/feedback")
@limiter.limit(RATE_LIMIT_MODERATE)  # Task 24: 反馈提交用更严格的限流
async def submit_feedback(
    message_id: int,
    request: Request,
    req: FeedbackCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交消息反馈（点赞/点踩）"""
    from app.services import feedback_service

    # Task 27: 审计日志在 service 层统一记录（区分新增/更新），避免此处重复记录
    feedback = await feedback_service.create_feedback(message_id, req, user.id, db)
    return ok(data=FeedbackOut.model_validate(feedback).model_dump())


@router.get("/messages/{message_id}/feedback")
@limiter.limit(RATE_LIMIT_DEFAULT)  # Task 24: 反馈查询限流
async def get_message_feedback(
    message_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取某条消息当前用户的反馈"""
    from app.services import feedback_service

    feedback = await feedback_service.get_feedback(message_id, user.id, db)
    return ok(data=FeedbackOut.model_validate(feedback).model_dump() if feedback else None)


@router.get("/feedback/stats")
@limiter.limit(RATE_LIMIT_DEFAULT)  # Task 24: 反馈统计限流
async def get_feedback_stats(
    request: Request,
    kb_id: int | None = None,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取反馈统计（admin 权限）"""
    from app.services import feedback_service

    stats = await feedback_service.get_feedback_stats(kb_id=kb_id, db=db)
    return ok(data=stats.model_dump())


@router.get("/feedback/analysis")
@limiter.limit(RATE_LIMIT_DEFAULT)  # Task 24: 反馈分析限流
async def get_feedback_analysis(
    request: Request,
    kb_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取反馈分析报告（admin 权限）"""
    from app.services import feedback_service

    start, end = _parse_date_range(start_date, end_date)

    analysis = await feedback_service.analyze_feedback(
        kb_id=kb_id,
        start_date=start,
        end_date=end,
        db=db,
    )
    return ok(data=analysis)


@router.get("/feedback/low-rated")
@limiter.limit(RATE_LIMIT_DEFAULT)  # Task 24: 低分反馈列表限流
async def get_low_rated_feedbacks(
    request: Request,
    kb_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    feedback_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取低分反馈列表（admin 权限）"""
    from app.services import feedback_service

    start, end = _parse_date_range(start_date, end_date)

    details, total = await feedback_service.get_low_rated_feedbacks(
        kb_id=kb_id,
        start_date=start,
        end_date=end,
        feedback_type=feedback_type,
        page=page,
        page_size=page_size,
        db=db,
    )
    items = [
        {
            "id": d.id,
            "message_id": d.message_id,
            "rating": d.rating,
            "comment": d.comment,
            "feedback_type": d.feedback_type,
            "created_at": d.created_at.isoformat(),
            "question": d.question,
            "answer": d.answer,
            "session_id": d.session_id,
            "kb_id": d.kb_id,
        }
        for d in details
    ]
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)
