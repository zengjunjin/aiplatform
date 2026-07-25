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


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    doc_id = Column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kb_id = Column(
        BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    char_count = Column(Integer, nullable=False)
    vector_id = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("doc_id", "chunk_index", name="uq_doc_chunk_index"),)

    document = relationship("Document", backref="chunks")
