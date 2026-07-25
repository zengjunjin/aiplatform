"""evaluation_results.contexts JSON -> JSONB

Revision ID: 021_eval_results_contexts_jsonb
Revises: 020_jsonb_gin_indexes
Create Date: 2026-07-23

将 evaluation_results.contexts 列从 JSON 转换为 JSONB，以获得 GIN 索引、
去重、高效键查询等优势（与 evaluation_runs.metrics 保持一致）。

仅 PostgreSQL 执行类型变更；SQLite 测试环境跳过。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "021_eval_results_contexts_jsonb"
down_revision = "020_jsonb_gin_indexes"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite 测试环境跳过
        return

    op.alter_column(
        "evaluation_results",
        "contexts",
        type_=sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
        postgresql_using="contexts::jsonb",
    )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.alter_column(
        "evaluation_results",
        "contexts",
        type_=sa.JSON(),
        postgresql_using="contexts::json",
    )
