from datetime import datetime
from sqlalchemy import Column, BigInteger, String, Float, Integer, DateTime, ForeignKey, Text, JSON, func
from sqlalchemy.orm import relationship
from app.db.base import Base
import enum


class EvaluationStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_base_id = Column(BigInteger, ForeignKey("knowledge_bases.id"), nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    metrics = Column(JSON, nullable=True)
    total_questions = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    knowledge_base = relationship("KnowledgeBase", backref="evaluation_runs")
    creator = relationship("User", backref="evaluation_runs")


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(BigInteger, ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False)
    question = Column(Text, nullable=False)
    ground_truth = Column(Text, nullable=False)
    generated_answer = Column(Text, nullable=False)
    contexts = Column(JSON, nullable=False)
    faithfulness = Column(Float, nullable=True)
    answer_relevancy = Column(Float, nullable=True)
    context_precision = Column(Float, nullable=True)
    context_recall = Column(Float, nullable=True)

    run = relationship("EvaluationRun", backref="results")