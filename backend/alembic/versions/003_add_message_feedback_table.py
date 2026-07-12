"""add_message_feedback_table

Revision ID: 003_feedback
Revises: placeholder_002
Create Date: 2026-07-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '003_feedback'
down_revision = '002_eval'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'message_feedbacks',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('message_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('feedback_type', sa.String(length=30), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['chat_messages.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_feedback_message', 'message_feedbacks', ['message_id'], unique=False)
    op.create_index('idx_feedback_user', 'message_feedbacks', ['user_id'], unique=False)


def downgrade():
    op.drop_index('idx_feedback_user', table_name='message_feedbacks')
    op.drop_index('idx_feedback_message', table_name='message_feedbacks')
    op.drop_table('message_feedbacks')