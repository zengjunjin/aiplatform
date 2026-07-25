"""add feedback indexes

Revision ID: 011_feedback_indexes
Revises: 010_perf_indexes
Create Date: 2026-07-23

为 message_feedbacks 表补充查询性能相关索引:
- rating          (按评分维度筛选反馈,如统计点赞/点踩分布)
- feedback_type   (按反馈类型筛选,如统计 hallucination/incomplete 等问题分布)
- created_at      (按时间范围检索反馈,支撑反馈时间线/趋势查询)

注意:
- message_id / user_id 单列索引已在 003_add_message_feedback_table.py 中通过 index=True 创建,此处不重复。
- (message_id, user_id) 唯一约束 uq_message_user_feedback 已由 005_add_audit_logs_and_feedback_uq.py 创建,
  本迁移仅新增用于过滤/排序的单列索引。
- 使用 CONCURRENTLY 以避免长事务阻塞写入(PG),需在事务外执行。
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "011_feedback_indexes"
down_revision = "010_perf_indexes"
branch_labels = None
depends_on = None


def upgrade():
    # CONCURRENTLY 不能在事务中执行
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("COMMIT")

    op.create_index(
        "ix_message_feedbacks_rating",
        "message_feedbacks",
        ["rating"],
        postgresql_concurrently=True,
    )
    op.create_index(
        "ix_message_feedbacks_feedback_type",
        "message_feedbacks",
        ["feedback_type"],
        postgresql_concurrently=True,
    )
    op.create_index(
        "ix_message_feedbacks_created_at",
        "message_feedbacks",
        ["created_at"],
        postgresql_concurrently=True,
    )

    if bind.dialect.name == "postgresql":
        op.execute("BEGIN")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("COMMIT")

    op.drop_index(
        "ix_message_feedbacks_created_at",
        table_name="message_feedbacks",
        postgresql_concurrently=True,
    )
    op.drop_index(
        "ix_message_feedbacks_feedback_type",
        table_name="message_feedbacks",
        postgresql_concurrently=True,
    )
    op.drop_index(
        "ix_message_feedbacks_rating", table_name="message_feedbacks", postgresql_concurrently=True
    )

    if bind.dialect.name == "postgresql":
        op.execute("BEGIN")
