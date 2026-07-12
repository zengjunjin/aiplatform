import json
import time
from fastapi import APIRouter, Depends, Request
from app.config import settings
from app.core.middleware import limiter
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db, async_session
from app.api.deps import get_current_user, get_admin_user
from app.services import chat_service
from app.services.audit_service import log_audit
from app.schemas.chat import SessionCreate, SessionUpdate, SessionOut, MessageCreate, MessageOut
from app.schemas.feedback import FeedbackCreate, FeedbackOut
from app.schemas.common import ok, paginated_ok
from app.db.user import User
from loguru import logger

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions")
async def create_session(
    req: SessionCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await chat_service.create_session(req, user.id, db)
    await log_audit(db, action="chat.session.create", user_id=user.id, request=request,
                   details={"session_id": session.id})
    return ok(data=SessionOut.model_validate(session).model_dump())


@router.get("/sessions")
async def list_sessions(
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sessions, total = await chat_service.list_sessions(user.id, db, page, page_size)
    items = [SessionOut.model_validate(s).model_dump() for s in sessions]
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await chat_service.get_session(session_id, user.id, db)
    messages, _ = await chat_service.get_messages(session_id, user.id, db, page=1, page_size=100)
    return ok(data={
        "session": SessionOut.model_validate(session).model_dump(),
        "messages": [MessageOut.model_validate(m).model_dump() for m in messages],
    })


@router.put("/sessions/{session_id}")
async def update_session(
    session_id: int,
    req: SessionUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await chat_service.update_session(session_id, req, user.id, db)
    await log_audit(db, action="chat.session.update", user_id=user.id, request=request,
                   details={"session_id": session_id})
    return ok(data=SessionOut.model_validate(session).model_dump())


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await chat_service.delete_session(session_id, user.id, db)
    await log_audit(db, action="chat.session.delete", user_id=user.id, request=request,
                   details={"session_id": session_id})
    return ok(message="Deleted")


@router.get("/sessions/{session_id}/messages")
async def get_messages(
    session_id: int,
    page: int = 1,
    page_size: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    messages, total = await chat_service.get_messages(session_id, user.id, db, page, page_size)
    items = [MessageOut.model_validate(m).model_dump() for m in messages]
    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.post("/sessions/{session_id}/messages")
@limiter.limit("20/minute")
async def send_message(
    request: Request,
    session_id: int,
    req: MessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 使用注入的 db 验证 session 归属 (短持有, 路由返回后即释放)
    session = await chat_service.get_session(session_id, user.id, db)
    # 缓存必要字段, 避免在 event_stream 中访问 detached 对象
    session_kb_id = session.kb_id
    session_title = session.title

    async def event_stream():
        start_time = time.time()

        # 使用独立 db 会话进行 db 操作, 避免 Depends(get_db) 的会话在整个 SSE 流期间被长持有
        # 1. Save user message
        async with async_session() as stream_db:
            await chat_service.save_message(session_id, "user", req.content, stream_db)
        await chat_service.append_to_context(session_id, "user", req.content)

        # Auto-update session title from first message
        if session_title == "新对话" or not session_title:
            async with async_session() as stream_db:
                from app.db.chat_session import ChatSession
                from sqlalchemy import select as sa_select
                result = await stream_db.execute(sa_select(ChatSession).where(ChatSession.id == session_id))
                sess = result.scalar_one_or_none()
                if sess:
                    sess.title = req.content[:30] + ("..." if len(req.content) > 30 else "")
                    await stream_db.commit()

        try:
            # Get history context (Redis, 不需要 db)
            history = await chat_service.get_history_context(session_id, limit=20)

            # RAG pipeline
            from app.rag.retriever import retriever
            from app.rag.reranker import reranker
            from app.rag.context_manager import context_manager
            from app.rag.reference_parser import parse_references
            from app.models.factory import ModelRegistry
            from app.utils.token_counter import count_tokens

            # Pre-cancel check: 若在开始生成前已被取消（双击发送取消）
            if await chat_service.is_cancelled(session_id):
                yield f"data: {json.dumps({'event': 'cancelled', 'message': '生成已取消'}, ensure_ascii=False)}\n\n"
                return

            # 立即发送开始事件, 让用户知道请求已开始处理
            if session_kb_id:
                yield f"data: {json.dumps({'event': 'searching', 'chunks_found': 0}, ensure_ascii=False)}\n\n"
                # 1. Retrieve
                chunks = await retriever.retrieve(req.content, session_kb_id, top_k=settings.RETRIEVAL_TOP_K)
                # 发送检索结果数量
                yield f"data: {json.dumps({'event': 'searching', 'chunks_found': len(chunks)}, ensure_ascii=False)}\n\n"

                # 2. Rerank (skip on failure so chat still works)
                if chunks:
                    try:
                        chunks = await reranker.rerank(req.content, chunks, top_k=settings.RERANK_TOP_K)
                    except Exception:
                        logger.warning("Reranker failed, proceeding without reranking")
                        yield f"data: {json.dumps({'event': 'warn', 'message': '重排序服务暂不可用，检索质量可能下降'}, ensure_ascii=False)}\n\n"
                        # keep original chunks order, truncated to top_k
                        chunks = chunks[:settings.RERANK_TOP_K]
            else:
                chunks = []

            # 3. Build messages with summary compression (多轮对话摘要优化)
            summary_text = None
            if len(history) > 8:
                from app.redis_client import get_summary_cache, set_summary_cache
                cached_summary = await get_summary_cache(session_id)
                messages, summary_text = await context_manager.get_context_with_summary(
                    history, req.content, chunks, existing_summary=cached_summary
                )
                if summary_text and summary_text != cached_summary:
                    await set_summary_cache(session_id, summary_text)
            else:
                messages = context_manager.build_messages(history, req.content, chunks)

            # 4. Generate (streaming) - 使用 ModelRouter 选择 Provider 并支持 Fallback
            #    LLM streaming 期间不持有 db 连接
            from app.core.model_router import ModelRouter

            model_router = ModelRouter()
            preferred_model = req.model  # 用户指定的模型名称

            # 选择 Provider
            try:
                llm = await model_router.select(preferred_model)
            except ValueError as e:
                yield f"data: {json.dumps({'event': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
                return

            # 在第一个事件中告知用户使用的模型名称
            yield f"data: {json.dumps({'event': 'model', 'model_name': llm.provider_name, 'display_name': llm.model_name}, ensure_ascii=False)}\n\n"

            full_answer = ""
            cancelled = False
            token_count = 0
            CANCEL_CHECK_INTERVAL = 16  # check cancellation every 16 tokens
            llm_failed = False
            actual_provider = llm.provider_name  # 记录实际使用的 provider 用于 release
            try:
                async for token in llm.chat_stream(messages):
                    full_answer += token
                    token_count += 1
                    yield f"data: {json.dumps({'event': 'delta', 'content': token}, ensure_ascii=False)}\n\n"
                    if token_count % CANCEL_CHECK_INTERVAL == 0:
                        if await chat_service.is_cancelled(session_id):
                            cancelled = True
                            break
            except Exception as e:
                logger.warning(f"Primary provider '{llm.provider_name}' failed: {e}, attempting fallback...")
                llm_failed = True
                # Fallback: 尝试其他 Provider
                fallback_success = False
                available = ModelRegistry.get_available()
                for fallback_llm in available:
                    if fallback_llm.provider_name == llm.provider_name:
                        continue
                    try:
                        logger.info(f"Fallback to provider: {fallback_llm.provider_name}")
                        actual_provider = fallback_llm.provider_name
                        yield f"data: {json.dumps({'event': 'model', 'model_name': fallback_llm.provider_name, 'display_name': fallback_llm.model_name, 'fallback': True}, ensure_ascii=False)}\n\n"
                        async for token in fallback_llm.chat_stream(messages):
                            full_answer += token
                            token_count += 1
                            yield f"data: {json.dumps({'event': 'delta', 'content': token}, ensure_ascii=False)}\n\n"
                            if token_count % CANCEL_CHECK_INTERVAL == 0:
                                if await chat_service.is_cancelled(session_id):
                                    cancelled = True
                                    break
                        fallback_success = True
                        break
                    except Exception as fe:
                        logger.warning(f"Fallback provider '{fallback_llm.provider_name}' also failed: {fe}")
                if not fallback_success:
                    raise Exception(f"All LLM providers failed after fallback attempts")
            finally:
                # 释放 least_busy 策略的请求计数
                model_router.release(actual_provider)

            # 5. Parse references (仅在有 chunks 且未取消时解析引用)
            references = parse_references(full_answer, chunks) if chunks and not cancelled else []

            # 6. Save assistant message (即使取消也保存已生成的部分)
            latency_ms = int((time.time() - start_time) * 1000)
            try:
                async with async_session() as stream_db:
                    saved_msg = await chat_service.save_message(
                        session_id, "assistant", full_answer, stream_db,
                        references=references,
                        token_input=count_tokens(req.content),
                        token_output=count_tokens(full_answer),
                        latency_ms=latency_ms,
                        summary_snapshot=summary_text,
                    )
            except Exception as save_err:
                logger.error(f"Failed to save assistant message for session {session_id}: {save_err}")
                # 保存一个 fallback 错误消息, 避免 user 消息孤悬
                try:
                    async with async_session() as stream_db:
                        saved_msg = await chat_service.save_message(
                            session_id, "assistant",
                            f"[系统错误] 消息保存失败，请重试。已生成内容：\n{full_answer[:500]}",
                            stream_db,
                            references=references,
                            latency_ms=latency_ms,
                        )
                except Exception:
                    saved_msg = None
            await chat_service.append_to_context(session_id, "assistant", full_answer)

            msg_id = saved_msg.id if saved_msg else None
            if cancelled:
                yield f"data: {json.dumps({'event': 'cancelled', 'message_id': msg_id, 'message': '生成已取消'}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'event': 'done', 'message_id': msg_id, 'references': references}, ensure_ascii=False)}\n\n"

        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Chat SSE error: {e}")
            yield f"data: {json.dumps({'event': 'error', 'message': '服务内部错误,请稍后重试'}, ensure_ascii=False)}\n\n"
            return  # error occurred, do not send [DONE]
        finally:
            # 清理取消标志（避免残留影响下次生成）
            await chat_service.clear_cancel(session_id)
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/sessions/{session_id}/cancel")
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
    await log_audit(db, action="chat.cancel", user_id=user.id, request=request,
                   details={"session_id": session_id})
    return ok(message="Cancellation requested")


# ---------- 反馈 API ----------

@router.post("/messages/{message_id}/feedback")
async def submit_feedback(
    message_id: int,
    request: Request,
    req: "FeedbackCreate",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交消息反馈（点赞/点踩）"""
    from app.services import feedback_service

    feedback = await feedback_service.create_feedback(message_id, req, user.id, db)
    await log_audit(db, action="chat.feedback.create", user_id=user.id, request=request,
                   details={"message_id": message_id, "rating": req.rating})
    return ok(data=FeedbackOut.model_validate(feedback).model_dump())


@router.get("/messages/{message_id}/feedback")
async def get_message_feedback(
    message_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取某条消息当前用户的反馈"""
    from app.services import feedback_service

    feedback = await feedback_service.get_feedback(message_id, user.id, db)
    return ok(data=FeedbackOut.model_validate(feedback).model_dump() if feedback else None)


@router.get("/feedback/stats")
async def get_feedback_stats(
    kb_id: int | None = None,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取反馈统计（admin 权限）"""
    from app.services import feedback_service

    stats = await feedback_service.get_feedback_stats(kb_id=kb_id, db=db)
    return ok(data=stats.model_dump())


@router.get("/feedback/analysis")
async def get_feedback_analysis(
    kb_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取反馈分析报告（admin 权限）"""
    from app.services import feedback_service
    from datetime import datetime

    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None

    analysis = await feedback_service.analyze_feedback(
        kb_id=kb_id,
        start_date=start,
        end_date=end,
        db=db,
    )
    return ok(data=analysis)


@router.get("/feedback/low-rated")
async def get_low_rated_feedbacks(
    kb_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    feedback_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取低分反馈列表（admin 权限）"""
    from app.services import feedback_service
    from datetime import datetime

    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None

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