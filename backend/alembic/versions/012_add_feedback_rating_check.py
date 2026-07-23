"""add feedback rating check constraint

Revision ID: 012_feedback_rating_check
Revises: 011_feedback_indexes
Create Date: 2026-07-23

"""
from alembic import op


revision = '012_feedback_rating_check'
down_revision = '011_feedback_indexes'
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        'ck_message_feedbacks_rating',
        'message_feedbacks',
        'rating IN (-1, 1)'
    )


def downgrade():
    op.drop_constraint('ck_message_feedbacks_rating', 'message_feedbacks', type_='check')
