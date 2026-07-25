"""prompt_templates

Revision ID: 019_prompt_templates
Revises: 015_evaluation_fk_ondelete
Create Date: 2026-07-23

Task 10: 新建 prompt_templates 表用于版本化管理 prompt 模板。
- 支持热加载：运维在 DB 中更新 prompt 后，新对话使用新 prompt
- 支持版本追溯：chat_messages 表记录使用的 prompt_version（见 019a 迁移）
"""

import sqlalchemy as sa

from alembic import op

revision = "019_prompt_templates"
down_revision = "015_evaluation_fk_ondelete"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False, index=True),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # 同名 + 版本号唯一约束（允许同名不同版本，但同一 name 只能有一个 active）
    op.create_index(
        "ix_prompt_templates_name_version", "prompt_templates", ["name", "version"], unique=True
    )


def downgrade():
    op.drop_index("ix_prompt_templates_name_version", table_name="prompt_templates")
    op.drop_table("prompt_templates")
