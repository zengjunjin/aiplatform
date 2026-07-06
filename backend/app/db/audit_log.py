from datetime import datetime
from sqlalchemy import Column, BigInteger, String, DateTime, JSON, func
from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=True, index=True)
    action = Column(String(50), nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    details = Column(JSON, nullable=True)
    result = Column(String(10), nullable=False, default="success")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
