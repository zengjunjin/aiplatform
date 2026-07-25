"""evaluation_results.created_at column

Revision ID: 023_evaluation_result_created_at
Revises: 022_evaluation_created_by_ondelete
Create Date: 2026-07-23

为 evaluation_results 表新增 created_at 列 (TIMESTAMPTZ, NOT NULL,
server_default=now()), 便于按时间排序与审计。

使用 server_default 让现有行自动填充当前时间, 满足 NOT NULL 约束。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "023_evaluation_result_created_at"
down_revision = "022_eval_created_by_cascade"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "evaluation_results",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade():
    op.drop_column("evaluation_results", "created_at")
