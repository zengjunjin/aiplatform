from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, case
from app.db.feedback import MessageFeedback
from app.db.chat_message import ChatMessage
from app.db.chat_session import ChatSession
from app.core.exceptions import NotFoundError, ForbiddenError
from app.schemas.feedback import FeedbackCreate, FeedbackStats, FeedbackDetail
from loguru import logger


async def create_feedback(
    message_id: int,
    req: FeedbackCreate,
    user_id: int,
    db: AsyncSession,
) -> MessageFeedback:
    """创建或更新消息反馈（同一用户对同一消息只能有一条反馈）"""
    # 验证消息存在
    result = await db.execute(select(ChatMessage).where(ChatMessage.id == message_id))
    message = result.scalar_one_or_none()
    if not message:
        raise NotFoundError("Message not found")

    # 验证 session 存在且属于当前用户
    session_result = await db.execute(
        select(ChatSession).where(ChatSession.id == message.session_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise NotFoundError("Session not found")
    if session.user_id != user_id:
        raise ForbiddenError("Access denied: cannot feedback on other user's session")

    # 检查是否已有反馈，有则更新
    existing = await db.execute(
        select(MessageFeedback).where(
            and_(
                MessageFeedback.message_id == message_id,
                MessageFeedback.user_id == user_id,
            )
        )
    )
    feedback = existing.scalar_one_or_none()

    if feedback:
        feedback.rating = req.rating
        feedback.comment = req.comment
        feedback.feedback_type = req.feedback_type
    else:
        feedback = MessageFeedback(
            message_id=message_id,
            user_id=user_id,
            rating=req.rating,
            comment=req.comment,
            feedback_type=req.feedback_type,
        )
        db.add(feedback)

    await db.commit()
    await db.refresh(feedback)
    logger.info(f"Feedback created/updated: message_id={message_id} user={user_id} rating={req.rating}")
    return feedback


async def get_feedback(
    message_id: int,
    user_id: int,
    db: AsyncSession,
) -> Optional[MessageFeedback]:
    """获取某条消息当前用户的反馈"""
    result = await db.execute(
        select(MessageFeedback).where(
            and_(
                MessageFeedback.message_id == message_id,
                MessageFeedback.user_id == user_id,
            )
        )
    )
    return result.scalar_one_or_none()


async def get_feedback_stats(
    kb_id: Optional[int] = None,
    db: AsyncSession = None,
) -> FeedbackStats:
    """获取反馈统计（使用 SQL 聚合，避免全表加载到内存）。"""
    # 总数 + 正/负计数（单次 SQL 聚合）
    stats_q = select(
        func.count(MessageFeedback.id).label("total"),
        func.sum(case((MessageFeedback.rating == 1, 1), else_=0)).label("positive"),
        func.sum(case((MessageFeedback.rating == -1, 1), else_=0)).label("negative"),
    )
    if kb_id is not None:
        stats_q = (
            stats_q
            .join(ChatMessage, MessageFeedback.message_id == ChatMessage.id)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(ChatSession.kb_id == kb_id)
        )

    stats_row = (await db.execute(stats_q)).one()
    total = stats_row.total or 0
    if total == 0:
        return FeedbackStats(
            total_feedback=0,
            positive_rate=0.0,
            negative_rate=0.0,
            by_type={},
        )

    positive = stats_row.positive or 0
    negative = stats_row.negative or 0

    # by_type（单次 GROUP BY 聚合）
    type_q = (
        select(MessageFeedback.feedback_type, func.count(MessageFeedback.id))
        .where(MessageFeedback.feedback_type.isnot(None))
        .group_by(MessageFeedback.feedback_type)
    )
    if kb_id is not None:
        type_q = (
            type_q
            .join(ChatMessage, MessageFeedback.message_id == ChatMessage.id)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(ChatSession.kb_id == kb_id)
        )

    by_type_rows = (await db.execute(type_q)).all()
    by_type = {row[0]: row[1] for row in by_type_rows}

    return FeedbackStats(
        total_feedback=total,
        positive_rate=round(positive / total, 4),
        negative_rate=round(negative / total, 4),
        by_type=by_type,
    )


async def get_low_rated_feedbacks(
    kb_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    feedback_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = None,
) -> tuple[list[FeedbackDetail], int]:
    """获取低分反馈列表（用于分析）"""
    # 查询负反馈
    query = (
        select(MessageFeedback)
        .where(MessageFeedback.rating == -1)
    )

    if start_date:
        query = query.where(MessageFeedback.created_at >= start_date)
    if end_date:
        query = query.where(MessageFeedback.created_at <= end_date)
    if feedback_type:
        query = query.where(MessageFeedback.feedback_type == feedback_type)

    # 按知识库过滤
    if kb_id is not None:
        query = (
            query
            .join(ChatMessage, MessageFeedback.message_id == ChatMessage.id)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(ChatSession.kb_id == kb_id)
        )

    query = query.order_by(MessageFeedback.created_at.desc())

    # 计数
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    # 分页
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    feedbacks = result.scalars().all()

    if not feedbacks:
        return [], total

    # Batch fetch messages for all feedbacks (avoid N+1)
    message_ids = [fb.message_id for fb in feedbacks]
    msg_result = await db.execute(
        select(ChatMessage).where(ChatMessage.id.in_(message_ids))
    )
    messages_map = {m.id: m for m in msg_result.scalars().all()}

    # Batch fetch sessions
    session_ids = list({m.session_id for m in messages_map.values()})
    session_result = await db.execute(
        select(ChatSession).where(ChatSession.id.in_(session_ids))
    )
    sessions_map = {s.id: s for s in session_result.scalars().all()}

    # Batch fetch previous user message for each assistant message
    prev_msg_result = await db.execute(
        select(ChatMessage)
        .where(
            and_(
                ChatMessage.session_id.in_(session_ids),
                ChatMessage.role == "user",
            )
        )
        .order_by(ChatMessage.session_id, ChatMessage.id.desc())
    )
    all_user_msgs = prev_msg_result.scalars().all()

    # Build map: session_id -> list of user messages (desc by id)
    user_msgs_by_session: dict[int, list[ChatMessage]] = {}
    for um in all_user_msgs:
        user_msgs_by_session.setdefault(um.session_id, []).append(um)

    # 构建详情
    details = []
    for fb in feedbacks:
        msg = messages_map.get(fb.message_id)
        if not msg:
            continue

        session = sessions_map.get(msg.session_id)

        # Find the latest user message before this assistant message
        question_content = ""
        session_user_msgs = user_msgs_by_session.get(msg.session_id, [])
        for um in session_user_msgs:  # already sorted desc by id
            if um.id < msg.id:
                question_content = um.content
                break

        details.append(FeedbackDetail(
            id=fb.id,
            message_id=fb.message_id,
            rating=fb.rating,
            comment=fb.comment,
            feedback_type=fb.feedback_type,
            created_at=fb.created_at,
            question=question_content,
            answer=msg.content,
            session_id=msg.session_id,
            kb_id=session.kb_id if session else None,
        ))

    return details, total


async def analyze_feedback(
    kb_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = None,
) -> dict:
    """分析反馈数据，识别失败模式"""
    if end_date is None:
        end_date = datetime.now(timezone.utc)
    if start_date is None:
        start_date = end_date - timedelta(days=7)

    stats = await get_feedback_stats(kb_id=kb_id, db=db)
    low_rated, _ = await get_low_rated_feedbacks(
        kb_id=kb_id,
        start_date=start_date,
        end_date=end_date,
        page=1,
        page_size=100,
        db=db,
    )

    # 识别失败模式
    patterns = {
        "context_insufficient": 0,  # 上下文覆盖不足
        "retrieval_bias": 0,        # 检索偏差
        "faithfulness_issue": 0,    # 忠实度问题（幻觉）
        "incompleteness": 0,        # 完整性不足
        "irrelevance": 0,           # 不相关
        "verbosity": 0,             # 冗长/简短
    }

    for fb in low_rated:
        ft = fb.feedback_type
        if ft == "hallucination":
            patterns["faithfulness_issue"] += 1
        elif ft == "incomplete":
            patterns["incompleteness"] += 1
        elif ft == "not_accurate":
            patterns["context_insufficient"] += 1
        elif ft == "irrelevant":
            patterns["irrelevance"] += 1
        elif ft in ("too_verbose", "too_brief"):
            patterns["verbosity"] += 1

    # 生成优化建议
    suggestions = []
    if patterns["faithfulness_issue"] > 0:
        suggestions.append(
            "幻觉问题: 建议在 Prompt 中强调「仅基于提供的上下文回答，不要编造信息」"
        )
    if patterns["context_insufficient"] > 0:
        suggestions.append(
            "准确性问题: 建议增加检索结果数量或调整 chunk 大小，确保相关上下文被充分检索"
        )
    if patterns["incompleteness"] > 0:
        suggestions.append(
            "完整性问题: 建议在 Prompt 中要求「请全面覆盖上下文中的所有关键信息」"
        )
    if patterns["irrelevance"] > 0:
        suggestions.append(
            "相关性问题: 建议优化 reranker 阈值或调整检索策略"
        )
    if patterns["verbosity"] > 0:
        suggestions.append(
            "回答长度问题: 建议在 Prompt 中明确指定的回答长度要求"
        )

    return {
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        },
        "stats": stats.model_dump(),
        "low_rated_count": len(low_rated),
        "failure_patterns": patterns,
        "suggestions": suggestions,
        "low_rated_samples": [
            {
                "question": fb.question[:200],
                "answer": fb.answer[:200],
                "feedback_type": fb.feedback_type,
                "comment": fb.comment,
            }
            for fb in low_rated[:5]
        ],
    }