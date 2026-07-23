"""chat_messages prompt_version

Revision ID: 019a_chat_prompt_version
Revises: 019_prompt_templates
Create Date: 2026-07-23

Task 10: 在 chat_messages 表新增 prompt_version 字段，记录该消息使用的 prompt 模板版本号。
- 历史消息保留旧版本号，新消息使用新版本
- 允许审计与回溯
"""
import sqlalchemy as sa
from alembic import op


revision = '019a_chat_prompt_version'
down_revision = '019_prompt_templates'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'chat_messages',
        sa.Column('prompt_version', sa.String(50), nullable=True),
    )


def downgrade():
    op.drop_column('chat_messages', 'prompt_version')
