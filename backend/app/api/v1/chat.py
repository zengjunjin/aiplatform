import json
import time
from fastapi import APIRouter, Depends, Request
from app.core.middleware import limiter
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db, async_session
from app.api.deps import get_current_user
from app.services import chat_service
from app.services.audit_service import log_audit
from app.schemas.chat import SessionCreate, SessionUpdate, SessionOut, MessageCreate, MessageOut
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
            history = await chat_service.get_history_context(session_id, limit=8)

            # RAG pipeline
            from app.rag.retriever import retriever
            from app.rag.reranker import reranker
            from app.rag.context_manager import context_manager
            from app.rag.reference_parser import parse_references
            from app.models.factory import ModelFactory
            from app.utils.token_counter import count_tokens

            # Pre-cancel check: 若在开始生成前已被取消（双击发送取消）
            if await chat_service.is_cancelled(session_id):
                yield f"data: {json.dumps({'event': 'cancelled', 'message': '生成已取消'}, ensure_ascii=False)}\n\n"
                return

            # 立即发送开始事件, 让用户知道请求已开始处理
            if session_kb_id:
                yield f"data: {json.dumps({'event': 'searching', 'chunks_found': 0}, ensure_ascii=False)}\n\n"
                # 1. Retrieve
                chunks = await retriever.retrieve(req.content, session_kb_id, top_k=10)
                # 发送检索结果数量
                yield f"data: {json.dumps({'event': 'searching', 'chunks_found': len(chunks)}, ensure_ascii=False)}\n\n"

                # 2. Rerank (skip on failure so chat still works)
                if chunks:
                    try:
                        chunks = await reranker.rerank(req.content, chunks, top_k=5)
                    except Exception:
                        logger.warning("Reranker failed, proceeding without reranking")
                        # keep original chunks order, truncated to top_k
                        chunks = chunks[:5]
            else:
                chunks = []

            # 3. Build messages
            messages = context_manager.build_messages(history, req.content, chunks)

            # 4. Generate (streaming) - check cancel flag every N tokens to reduce Redis overhead
            #    LLM streaming 期间不持有 db 连接
            llm = ModelFactory.create_llm()
            full_answer = ""
            cancelled = False
            token_count = 0
            CANCEL_CHECK_INTERVAL = 16  # check cancellation every 16 tokens
            async for token in llm.chat_stream(messages):
                full_answer += token
                token_count += 1
                yield f"data: {json.dumps({'event': 'delta', 'content': token}, ensure_ascii=False)}\n\n"
                if token_count % CANCEL_CHECK_INTERVAL == 0:
                    if await chat_service.is_cancelled(session_id):
                        cancelled = True
                        break

            # 5. Parse references (仅在有 chunks 且未取消时解析引用)
            references = parse_references(full_answer, chunks) if chunks and not cancelled else []

            # 6. Save assistant message (即使取消也保存已生成的部分)
            latency_ms = int((time.time() - start_time) * 1000)
            async with async_session() as stream_db:
                saved_msg = await chat_service.save_message(
                    session_id, "assistant", full_answer, stream_db,
                    references=references,
                    token_input=count_tokens(req.content),
                    token_output=count_tokens(full_answer),
                    latency_ms=latency_ms,
                )
            await chat_service.append_to_context(session_id, "assistant", full_answer)

            if cancelled:
                yield f"data: {json.dumps({'event': 'cancelled', 'message_id': saved_msg.id, 'message': '生成已取消'}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'event': 'done', 'message_id': saved_msg.id, 'references': references}, ensure_ascii=False)}\n\n"

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