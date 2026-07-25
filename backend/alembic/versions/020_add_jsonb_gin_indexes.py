"""add GIN indexes on JSONB fields

Revision ID: 020_jsonb_gin_indexes
Revises: 019a_chat_prompt_version
Create Date: 2026-07-23

为 evaluation_runs.metrics 和 chat_messages.referenced_chunks 两个 JSONB 字段添加
GIN 索引 (jsonb_path_ops)，支持高效 @> 包含查询。

注:
- CONCURRENTLY 不能在事务中执行，故先 COMMIT 当前事务、建索引后再 BEGIN 新事务
  (参考 010_add_performance_indexes.py 的模式)。
- 仅 PostgreSQL 执行；SQLite 测试环境跳过。
- batch 二 (019_prompt_templates / 019a_chat_prompt_version) 已在并行执行中创建，
  故 down_revision 指向 019a_chat_prompt_version 以保持单一 head 链。
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "020_jsonb_gin_indexes"
down_revision = "019a_chat_prompt_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite 测试环境跳过
        return

    # CONCURRENTLY 不能在事务中执行
    op.execute("COMMIT")

    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_evaluation_runs_metrics_gin "
        "ON evaluation_runs USING GIN (metrics jsonb_path_ops)"
    )
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_chat_messages_referenced_chunks_gin "
        "ON chat_messages USING GIN (referenced_chunks jsonb_path_ops)"
    )

    op.execute("BEGIN")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("COMMIT")

    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_chat_messages_referenced_chunks_gin")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_evaluation_runs_metrics_gin")

    op.execute("BEGIN")
