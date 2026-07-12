"""add_evaluation_tables

Revision ID: 002_eval
Revises: 22fb00c5239c
Create Date: 2026-07-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002_eval'
down_revision = 'placeholder_002'
branch_labels = None
depends_on = None


def upgrade():
    # ### evaluation_runs table ###
    op.create_table(
        'evaluation_runs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('knowledge_base_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('metrics', postgresql.JSON(), nullable=True),
        sa.Column('total_questions', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_bases.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_eval_run_kb', 'evaluation_runs', ['knowledge_base_id'], unique=False)
    op.create_index('idx_eval_run_status', 'evaluation_runs', ['status'], unique=False)

    # ### evaluation_results table ###
    op.create_table(
        'evaluation_results',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.BigInteger(), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('ground_truth', sa.Text(), nullable=False),
        sa.Column('generated_answer', sa.Text(), nullable=False),
        sa.Column('contexts', postgresql.JSON(), nullable=False),
        sa.Column('faithfulness', sa.Float(), nullable=True),
        sa.Column('answer_relevancy', sa.Float(), nullable=True),
        sa.Column('context_precision', sa.Float(), nullable=True),
        sa.Column('context_recall', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['evaluation_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_eval_result_run', 'evaluation_results', ['run_id'], unique=False)


def downgrade():
    op.drop_index('idx_eval_result_run', table_name='evaluation_results')
    op.drop_table('evaluation_results')
    op.drop_index('idx_eval_run_status', table_name='evaluation_runs')
    op.drop_index('idx_eval_run_kb', table_name='evaluation_runs')
    op.drop_table('evaluation_runs')