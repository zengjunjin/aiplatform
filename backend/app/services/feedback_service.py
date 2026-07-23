from collections import Counter
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ForbiddenError, NotFoundError
from app.db.chat_message import ChatMessage
from app.db.chat_session import ChatSession
from app.db.feedback import MessageFeedback
from app.schemas.feedback import FeedbackCreate, FeedbackDetail, FeedbackStats
from app.services.audit_service import log_audit

# 与 schemas/feedback.py 中 Literal 定义保持一致的反馈类型集合
FEEDBACK_TYPES = (
    "faithfulness_issue",
    "context_insufficient",
    "incompleteness",
    "irrelevance",
    "verbosity",
)


async def create_feedback(
    message_id: int,
    req: FeedbackCreate,
    user_id: int,
    db: AsyncSession,
) -> MessageFeedback:
    """创建或更新消息反馈（同一用户对同一消息只能有一条反馈）"""
    # 验证消息存在，并通过 selectinload 一次性加载关联 session（合并 message+session 查询，避免 N+1）
    result = await db.execute(
        select(ChatMessage)
        .options(selectinload(ChatMessage.session))
        .where(ChatMessage.id == message_id)
    )
    message = result.scalar_one_or_none()
    if not message:
        raise NotFoundError("Message not found")

    # 验证 session 存在且属于当前用户
    session = message.session
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
    is_create = feedback is None  # 标记新增或更新，用于审计日志

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

    try:
        await db.commit()
    except IntegrityError:
        # TOCTOU: SELECT 与 COMMIT 之间另一请求插入了同一 (message_id, user_id)，
        # 触发唯一约束冲突。回滚后重试为更新（select existing → update → commit），
        # 保持最终业务语义与正常更新路径一致。
        await db.rollback()
        existing = await db.execute(
            select(MessageFeedback).where(
                and_(
                    MessageFeedback.message_id == message_id,
                    MessageFeedback.user_id == user_id,
                )
            )
        )
        feedback = existing.scalar_one_or_none()
        if feedback is None:
            # 极端竞态：冲突行又被并发删除。重新抛出以保持异常流程不变。
            raise
        feedback.rating = req.rating
        feedback.comment = req.comment
        feedback.feedback_type = req.feedback_type
        is_create = False  # 重试为更新，审计日志记 update
        await db.commit()
    await db.refresh(feedback)
    logger.info(f"Feedback created/updated: message_id={message_id} user={user_id} rating={req.rating}")

    # 记录审计日志：区分新增与更新
    audit_action = "chat.feedback.create" if is_create else "chat.feedback.update"
    await log_audit(
        action=audit_action,
        user_id=user_id,
        details={
            "resource_type": "feedback",
            "resource_id": feedback.id,
            "message_id": message_id,
            "rating": req.rating,
            "feedback_type": req.feedback_type,
        },
    )

    return feedback


async def get_feedback(
    message_id: int,
    user_id: int,
    db: AsyncSession,
) -> MessageFeedback | None:
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
    db: AsyncSession,
    kb_id: int | None = None,
) -> FeedbackStats:
    """获取反馈统计（使用 SQL 聚合，避免全表加载到内存）。"""
    # Task 33: 合并 stats_q 和 type_q 两次串行查询为单 SQL，
    # 使用 FILTER (WHERE ...) 聚合 positive/negative 及各 feedback_type 计数。
    stats_q = select(
        func.count(MessageFeedback.id).label("total"),
        func.count(MessageFeedback.id).filter(
            MessageFeedback.rating == 1
        ).label("positive"),
        func.count(MessageFeedback.id).filter(
            MessageFeedback.rating == -1
        ).label("negative"),
        *[
            func.count(MessageFeedback.id)
            .filter(MessageFeedback.feedback_type == ft)
            .label(f"type_{ft}")
            for ft in FEEDBACK_TYPES
        ],
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

    # 从单 SQL 结果中提取 by_type（跳过计数为 0 的类型，与原 GROUP BY 行为一致）
    by_type = {
        ft: count
        for ft in FEEDBACK_TYPES
        if (count := getattr(stats_row, f"type_{ft}") or 0)
    }

    return FeedbackStats(
        total_feedback=total,
        positive_rate=round(positive / total, 4),
        negative_rate=round(negative / total, 4),
        by_type=by_type,
    )


async def _batch_load_message_contexts(
    message_ids: list[int], db: AsyncSession
) -> tuple[dict[int, ChatMessage], dict[int, ChatSession], dict[int, list[ChatMessage]]]:
    """批量加载消息上下文（messages, sessions, 每会话用户消息列表），避免 N+1 查询。

    返回 (messages_map, sessions_map, user_msgs_by_session)。
    """
    if not message_ids:
        return {}, {}, {}

    # Batch fetch messages
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

    return messages_map, sessions_map, user_msgs_by_session


def _build_feedback_detail(
    fb: MessageFeedback,
    msg: ChatMessage,
    session: ChatSession | None,
    user_msgs: list[ChatMessage],
) -> FeedbackDetail:
    """构建单条反馈详情。"""
    # Find the latest user message before this assistant message
    question_content = ""
    for um in user_msgs:  # already sorted desc by id
        if um.id < msg.id:
            question_content = um.content
            break

    return FeedbackDetail(
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
    )


async def get_low_rated_feedbacks(
    db: AsyncSession,
    kb_id: int | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    feedback_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
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
    total = (await db.execute(count_query)).scalar_one()

    # 分页
    query = query.offset((page - 1) * page_size).limit(page_size)
    feedbacks = (await db.execute(query)).scalars().all()

    if not feedbacks:
        return [], total

    # Batch load contexts + build details
    message_ids = [fb.message_id for fb in feedbacks]
    messages_map, sessions_map, user_msgs_by_session = await _batch_load_message_contexts(message_ids, db)

    details = [
        _build_feedback_detail(
            fb, messages_map[fb.message_id],
            sessions_map.get(messages_map[fb.message_id].session_id),
            user_msgs_by_session.get(messages_map[fb.message_id].session_id, []),
        )
        for fb in feedbacks
        if fb.message_id in messages_map
    ]

    return details, total


async def analyze_feedback(
    db: AsyncSession,
    kb_id: int | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> dict:
    """分析反馈数据，识别失败模式"""
    if end_date is None:
        end_date = datetime.now(UTC)
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

    # Task 37: 用 Counter 替代 if/elif 计数，更简洁且与 FEEDBACK_TYPES 保持一致。
    # retrieval_bias 无对应 feedback_type，保持初始值 0。
    type_counts = Counter(fb.feedback_type for fb in low_rated)
    for ft in FEEDBACK_TYPES:
        patterns[ft] = type_counts.get(ft, 0)

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
