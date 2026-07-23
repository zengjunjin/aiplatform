from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db.base import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    # Task 24: GIN 索引支持高效 referenced_chunks @> 查询 (jsonb_path_ops)
    __table_args__ = (
        Index(
            "ix_chat_messages_referenced_chunks_gin",
            "referenced_chunks",
            postgresql_using="gin",
            postgresql_ops={"referenced_chunks": "jsonb_path_ops"},
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(BigInteger, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    referenced_chunks = Column(JSONB, nullable=True)
    token_input = Column(Integer, nullable=True)
    token_output = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    summary_snapshot = Column(Text, nullable=True)
    # Task 10: 记录该消息使用的 prompt 模板版本号，便于审计与回溯
    prompt_version = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    session = relationship("ChatSession", back_populates="messages")
