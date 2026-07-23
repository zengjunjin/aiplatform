from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.db.base import Base


class MessageFeedback(Base):
    __tablename__ = "message_feedbacks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    message_id = Column(BigInteger, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1 点赞, -1 点踩
    comment = Column(Text, nullable=True)
    feedback_type = Column(String(30), nullable=True)  # not_accurate/incomplete/hallucination/irrelevant/too_verbose/too_brief/other
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("rating IN (-1, 1)", name="ck_message_feedbacks_rating"),
        UniqueConstraint("message_id", "user_id", name="uq_message_user_feedback"),
        Index("ix_message_feedbacks_rating", "rating"),
        Index("ix_message_feedbacks_feedback_type", "feedback_type"),
        Index("ix_message_feedbacks_created_at", "created_at"),
    )
