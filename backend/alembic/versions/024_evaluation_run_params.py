"""evaluation_runs / evaluation_results params columns

Revision ID: 024_evaluation_run_params
Revises: 023_evaluation_result_created_at
Create Date: 2026-07-24

为 evaluation_runs 新增参数快照列（prompt_version、retriever_alpha、
retriever_top_k、rerank_top_k、trigger_source），用于横向对比不同检索/
生成参数下的评估效果；trigger_source 默认 'manual'。

为 evaluation_results 新增题目元数据与执行开销列（question_type、
difficulty、latency_ms、token_count），便于按维度聚合分析。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "024_evaluation_run_params"
down_revision = "023_evaluation_result_created_at"
branch_labels = None
depends_on = None


def upgrade():
    # evaluation_runs: 参数快照
    op.add_column(
        "evaluation_runs",
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "evaluation_runs",
        sa.Column("retriever_alpha", sa.Float(), nullable=True),
    )
    op.add_column(
        "evaluation_runs",
        sa.Column("retriever_top_k", sa.Integer(), nullable=True),
    )
    op.add_column(
        "evaluation_runs",
        sa.Column("rerank_top_k", sa.Integer(), nullable=True),
    )
    op.add_column(
        "evaluation_runs",
        sa.Column(
            "trigger_source",
            sa.String(length=20),
            nullable=False,
            server_default="manual",
        ),
    )

    # evaluation_results: 题目元数据与执行开销
    op.add_column(
        "evaluation_results",
        sa.Column("question_type", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "evaluation_results",
        sa.Column("difficulty", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "evaluation_results",
        sa.Column("latency_ms", sa.Integer(), nullable=True),
    )
    op.add_column(
        "evaluation_results",
        sa.Column("token_count", sa.Integer(), nullable=True),
    )


def downgrade():
    # evaluation_results
    op.drop_column("evaluation_results", "token_count")
    op.drop_column("evaluation_results", "latency_ms")
    op.drop_column("evaluation_results", "difficulty")
    op.drop_column("evaluation_results", "question_type")

    # evaluation_runs
    op.drop_column("evaluation_runs", "trigger_source")
    op.drop_column("evaluation_runs", "rerank_top_k")
    op.drop_column("evaluation_runs", "retriever_top_k")
    op.drop_column("evaluation_runs", "retriever_alpha")
    op.drop_column("evaluation_runs", "prompt_version")
