"""add_kb_collaborators

Revision ID: 004_kb_collaborators
Revises: placeholder_003
Create Date: 2026-07-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '004_kb_collaborators'
down_revision = '003_feedback'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'knowledge_bases',
        sa.Column('collaborators', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade():
    op.drop_column('knowledge_bases', 'collaborators')