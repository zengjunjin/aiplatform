"""add_summary_snapshot

Revision ID: 004_summary
Revises: 003_feedback
Create Date: 2026-07-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '004_summary'
down_revision = '004_kb_collaborators'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'chat_messages',
        sa.Column('summary_snapshot', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column('chat_messages', 'summary_snapshot')