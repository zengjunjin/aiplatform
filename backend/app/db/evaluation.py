import enum

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db.base import Base


class EvaluationStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    # Task 24: GIN 索引支持高效 metrics @> 查询 (jsonb_path_ops)
    __table_args__ = (
        Index(
            "ix_evaluation_runs_metrics_gin",
            "metrics",
            postgresql_using="gin",
            postgresql_ops={"metrics": "jsonb_path_ops"},
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_base_id = Column(
        BigInteger, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    metrics = Column(JSONB, nullable=True)
    total_questions = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    error_message = Column(Text, nullable=True)
    # 评估时使用的检索/生成参数快照（便于横向对比不同参数下的效果）
    prompt_version = Column(String(50), nullable=True)
    retriever_alpha = Column(Float, nullable=True)
    retriever_top_k = Column(Integer, nullable=True)
    rerank_top_k = Column(Integer, nullable=True)
    trigger_source = Column(String(20), nullable=False, default="manual", server_default="manual")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    knowledge_base = relationship("KnowledgeBase", backref="evaluation_runs")
    creator = relationship("User", backref="evaluation_runs")


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(
        BigInteger, ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    question = Column(Text, nullable=False)
    ground_truth = Column(Text, nullable=False)
    generated_answer = Column(Text, nullable=False)
    contexts = Column(JSONB, nullable=False)
    faithfulness = Column(Float, nullable=True)
    answer_relevancy = Column(Float, nullable=True)
    context_precision = Column(Float, nullable=True)
    context_recall = Column(Float, nullable=True)
    # 题目元数据与执行开销（便于按维度聚合分析）
    question_type = Column(String(20), nullable=True)
    difficulty = Column(String(20), nullable=True)
    latency_ms = Column(Integer, nullable=True)
    token_count = Column(Integer, nullable=True)
    # 记录评测结果写入时间, 便于排序与审计 (与 evaluation_runs.created_at 一致)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    run = relationship("EvaluationRun", backref="results")
