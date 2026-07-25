"""Tests for app.services.feedback_service

使用 mock AsyncSession 测试业务逻辑，不依赖真实 PostgreSQL。
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ForbiddenError, NotFoundError
from app.db.chat_message import ChatMessage
from app.db.chat_session import ChatSession
from app.db.feedback import MessageFeedback
from app.schemas.feedback import FeedbackCreate, FeedbackDetail, FeedbackStats
from app.services import feedback_service

# ---------- 辅助函数 ----------


def _make_message(msg_id=10, session_id=1, content="assistant reply"):
    msg = MagicMock(spec=ChatMessage)
    msg.id = msg_id
    msg.session_id = session_id
    msg.content = content
    msg.role = "assistant"
    return msg


def _make_session(session_id=1, user_id=1, kb_id=1):
    sess = MagicMock(spec=ChatSession)
    sess.id = session_id
    sess.user_id = user_id
    sess.kb_id = kb_id
    sess.title = "session"
    return sess


def _make_feedback(
    fb_id=100,
    message_id=10,
    user_id=1,
    rating=-1,
    feedback_type="faithfulness_issue",
    comment="bad",
):
    fb = MagicMock(spec=MessageFeedback)
    fb.id = fb_id
    fb.message_id = message_id
    fb.user_id = user_id
    fb.rating = rating
    fb.feedback_type = feedback_type
    fb.comment = comment
    fb.created_at = datetime(2026, 7, 1, tzinfo=UTC)
    return fb


# ---------- create_feedback ----------


class TestCreateFeedback:
    @pytest.mark.asyncio
    async def test_message_not_found_raises(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        req = MagicMock(spec=FeedbackCreate)
        req.rating = 1
        req.comment = None
        req.feedback_type = None

        with pytest.raises(NotFoundError):
            await feedback_service.create_feedback(message_id=999, req=req, user_id=1, db=db)

    @pytest.mark.asyncio
    async def test_session_not_found_raises(self):
        msg = _make_message()
        msg.session = None  # selectinload 未加载到 session
        db = AsyncMock()
        # 合并查询后只 1 次 execute（message + session 一起），session 为 None
        msg_result = MagicMock()
        msg_result.scalar_one_or_none.return_value = msg
        db.execute = AsyncMock(side_effect=[msg_result])

        req = MagicMock(spec=FeedbackCreate)
        req.rating = 1
        req.comment = None
        req.feedback_type = None

        with pytest.raises(NotFoundError):
            await feedback_service.create_feedback(message_id=10, req=req, user_id=1, db=db)

    @pytest.mark.asyncio
    async def test_session_not_owner_raises_forbidden(self):
        msg = _make_message()
        sess = _make_session(user_id=999)  # 别人的 session
        msg.session = sess  # 通过 selectinload 加载的关联 session
        db = AsyncMock()
        msg_result = MagicMock()
        msg_result.scalar_one_or_none.return_value = msg
        db.execute = AsyncMock(side_effect=[msg_result])

        req = MagicMock(spec=FeedbackCreate)
        req.rating = 1
        req.comment = None
        req.feedback_type = None

        with pytest.raises(ForbiddenError):
            await feedback_service.create_feedback(message_id=10, req=req, user_id=1, db=db)

    @pytest.mark.asyncio
    async def test_creates_new_feedback(self):
        msg = _make_message()
        sess = _make_session(user_id=1)
        msg.session = sess  # 通过 selectinload 加载的关联 session
        db = AsyncMock()
        msg_result = MagicMock()
        msg_result.scalar_one_or_none.return_value = msg
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None  # 没有已存在的反馈
        db.execute = AsyncMock(side_effect=[msg_result, existing_result])

        async def fake_refresh(obj, *args, **kwargs):
            obj.id = 100

        db.refresh = AsyncMock(side_effect=fake_refresh)

        req = MagicMock(spec=FeedbackCreate)
        req.rating = 1
        req.comment = "good"
        req.feedback_type = None

        result = await feedback_service.create_feedback(message_id=10, req=req, user_id=1, db=db)

        assert result.id == 100
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_existing_feedback(self):
        msg = _make_message()
        sess = _make_session(user_id=1)
        msg.session = sess  # 通过 selectinload 加载的关联 session
        existing_fb = _make_feedback(rating=-1, feedback_type="faithfulness_issue")

        db = AsyncMock()
        msg_result = MagicMock()
        msg_result.scalar_one_or_none.return_value = msg
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing_fb
        db.execute = AsyncMock(side_effect=[msg_result, existing_result])

        req = MagicMock(spec=FeedbackCreate)
        req.rating = 1
        req.comment = "actually good"
        req.feedback_type = None

        result = await feedback_service.create_feedback(message_id=10, req=req, user_id=1, db=db)

        # 更新已有反馈，不调用 add
        assert result.rating == 1
        assert result.comment == "actually good"
        db.add.assert_not_called()
        db.commit.assert_awaited_once()


# ---------- get_feedback ----------


class TestGetFeedback:
    @pytest.mark.asyncio
    async def test_returns_feedback_when_exists(self):
        fb = _make_feedback()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: fb))

        result = await feedback_service.get_feedback(message_id=10, user_id=1, db=db)
        assert result.id == 100

    @pytest.mark.asyncio
    async def test_returns_none_when_not_exists(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        result = await feedback_service.get_feedback(message_id=10, user_id=1, db=db)
        assert result is None


# ---------- get_feedback_stats ----------


class TestGetFeedbackStats:
    @pytest.mark.asyncio
    async def test_no_feedback_returns_zeros(self):
        db = AsyncMock()
        # Task 33: 合并后单 SQL 返回 total=0（函数短路返回零值）
        stats_row = MagicMock(
            total=0,
            positive=0,
            negative=0,
            type_faithfulness_issue=0,
            type_context_insufficient=0,
            type_incompleteness=0,
            type_irrelevance=0,
            type_verbosity=0,
        )
        stats_result = MagicMock()
        stats_result.one.return_value = stats_row
        db.execute = AsyncMock(return_value=stats_result)

        result = await feedback_service.get_feedback_stats(kb_id=None, db=db)
        assert result.total_feedback == 0
        assert result.positive_rate == 0.0
        assert result.negative_rate == 0.0
        assert result.by_type == {}

    @pytest.mark.asyncio
    async def test_with_feedback_returns_stats(self):
        db = AsyncMock()
        # Task 33: 合并后单 SQL 返回 total/positive/negative + 各 feedback_type 计数
        stats_row = MagicMock(
            total=10,
            positive=7,
            negative=3,
            type_faithfulness_issue=2,
            type_context_insufficient=0,
            type_incompleteness=1,
            type_irrelevance=0,
            type_verbosity=0,
        )
        stats_result = MagicMock()
        stats_result.one.return_value = stats_row
        db.execute = AsyncMock(return_value=stats_result)

        result = await feedback_service.get_feedback_stats(kb_id=None, db=db)
        assert result.total_feedback == 10
        assert result.positive_rate == 0.7
        assert result.negative_rate == 0.3
        assert result.by_type == {"faithfulness_issue": 2, "incompleteness": 1}


# ---------- get_low_rated_feedbacks ----------


class TestGetLowRatedFeedbacks:
    @pytest.mark.asyncio
    async def test_empty_feedbacks_returns_empty_list(self):
        db = AsyncMock()
        # count_result.scalar_one() = 0
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        # data_result.scalars().all() = []
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(side_effect=[count_result, data_result])

        details, total = await feedback_service.get_low_rated_feedbacks(db=db)
        assert details == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_returns_feedback_details_with_question(self):
        # 构造 feedback / message / session / prev_user_message
        msg = _make_message(msg_id=10, session_id=1, content="assistant reply")
        sess = _make_session(session_id=1, user_id=1, kb_id=5)
        fb = _make_feedback(fb_id=100, message_id=10, rating=-1, feedback_type="faithfulness_issue")

        # 用户之前的消息（id 小于 assistant msg.id=10）
        prev_user_msg = MagicMock(spec=ChatMessage)
        prev_user_msg.id = 9
        prev_user_msg.session_id = 1
        prev_user_msg.role = "user"
        prev_user_msg.content = "user question"

        db = AsyncMock()
        # 1. count_query → scalar_one() = 1
        # 2. data query → scalars().all() = [fb]
        # 3. batch fetch messages → scalars().all() = [msg]
        # 4. batch fetch sessions → scalars().all() = [sess]
        # 5. batch fetch prev user msgs → scalars().all() = [prev_user_msg]
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [fb]

        msg_result = MagicMock()
        msg_result.scalars.return_value.all.return_value = [msg]

        sess_result = MagicMock()
        sess_result.scalars.return_value.all.return_value = [sess]

        prev_result = MagicMock()
        prev_result.scalars.return_value.all.return_value = [prev_user_msg]

        db.execute = AsyncMock(
            side_effect=[count_result, data_result, msg_result, sess_result, prev_result]
        )

        details, total = await feedback_service.get_low_rated_feedbacks(kb_id=5, db=db)

        assert total == 1
        assert len(details) == 1
        detail = details[0]
        assert detail.id == 100
        assert detail.message_id == 10
        assert detail.rating == -1
        assert detail.question == "user question"
        assert detail.answer == "assistant reply"
        assert detail.session_id == 1
        assert detail.kb_id == 5

    @pytest.mark.asyncio
    async def test_skips_feedback_when_message_missing(self):
        fb = _make_feedback(fb_id=100, message_id=999)  # message_id 在 map 中找不到
        db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = [fb]
        msg_result = MagicMock()
        msg_result.scalars.return_value.all.return_value = []  # 空 → messages_map 为空
        # session_ids 为空，但 service 仍执行 session 和 prev_msg 查询
        sess_result = MagicMock()
        sess_result.scalars.return_value.all.return_value = []
        prev_result = MagicMock()
        prev_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(
            side_effect=[count_result, data_result, msg_result, sess_result, prev_result]
        )

        details, total = await feedback_service.get_low_rated_feedbacks(db=db)
        assert details == []
        assert total == 1


# ---------- analyze_feedback ----------


class TestAnalyzeFeedback:
    @pytest.mark.asyncio
    async def test_returns_analysis_with_suggestions(self):
        # Mock get_feedback_stats 和 get_low_rated_feedbacks
        stats = FeedbackStats(
            total_feedback=10,
            positive_rate=0.7,
            negative_rate=0.3,
            by_type={"faithfulness_issue": 2, "incompleteness": 1},
        )
        low_rated = [
            FeedbackDetail(
                id=1,
                message_id=10,
                rating=-1,
                comment="bad",
                feedback_type="faithfulness_issue",
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
                question="Q1",
                answer="A1",
                session_id=1,
                kb_id=1,
            ),
            FeedbackDetail(
                id=2,
                message_id=11,
                rating=-1,
                comment=None,
                feedback_type="incompleteness",
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
                question="Q2",
                answer="A2",
                session_id=1,
                kb_id=1,
            ),
        ]
        with (
            patch.object(feedback_service, "get_feedback_stats", new=AsyncMock(return_value=stats)),
            patch.object(
                feedback_service,
                "get_low_rated_feedbacks",
                new=AsyncMock(return_value=(low_rated, 2)),
            ),
        ):
            result = await feedback_service.analyze_feedback(kb_id=1, db=AsyncMock())

        assert result["low_rated_count"] == 2
        assert result["failure_patterns"]["faithfulness_issue"] == 1
        assert result["failure_patterns"]["incompleteness"] == 1
        # 幻觉 + 完整性 → 至少 2 条建议
        assert len(result["suggestions"]) >= 2
        assert any("幻觉" in s for s in result["suggestions"])
        assert any("完整性" in s for s in result["suggestions"])

    @pytest.mark.asyncio
    async def test_no_low_rated_returns_empty_patterns(self):
        stats = FeedbackStats(
            total_feedback=0,
            positive_rate=0.0,
            negative_rate=0.0,
            by_type={},
        )
        with (
            patch.object(feedback_service, "get_feedback_stats", new=AsyncMock(return_value=stats)),
            patch.object(
                feedback_service, "get_low_rated_feedbacks", new=AsyncMock(return_value=([], 0))
            ),
        ):
            result = await feedback_service.analyze_feedback(kb_id=None, db=AsyncMock())

        assert result["low_rated_count"] == 0
        assert all(v == 0 for v in result["failure_patterns"].values())
        assert result["suggestions"] == []
