from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


# Task 2.3: 文档状态到进度百分比的映射（统一魔法数字，消除 documents.py 内联 status_map）
STATUS_PROGRESS: dict[str, int] = {
    "pending": 0,
    "parsing": 10,
    "chunking": 30,
    "embedding": 60,
    "done": 100,
    "failed": 100,
}


class Document(Base):
    __tablename__ = "documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    kb_id = Column(BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    uploader_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(20), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    file_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    chunk_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    deleted_at = Column(DateTime, nullable=True, default=None)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("kb_id", "file_hash", name="uq_doc_kb_hash"),
    )

    kb = relationship("KnowledgeBase", backref="documents")
    uploader = relationship("User", backref="uploaded_docs")
