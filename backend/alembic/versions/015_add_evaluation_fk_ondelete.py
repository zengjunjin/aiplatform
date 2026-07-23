"""add evaluation fk ondelete

Revision ID: 015_evaluation_fk_ondelete
Revises: 014_json_to_jsonb
Create Date: 2026-07-23

为 evaluation_runs 表的外键补充 ondelete 策略:
- knowledge_base_id -> knowledge_bases.id  ondelete CASCADE  (KB 删除时级联清理评测)
- created_by         -> users.id           ondelete SET NULL (用户删除时保留评测记录)

注: 实际列名为 knowledge_base_id / created_by (非 kb_id / user_id)。
"""
from alembic import op


revision = '015_evaluation_fk_ondelete'
down_revision = '014_json_to_jsonb'
branch_labels = None
depends_on = None


def upgrade():
    # Drop existing FK constraints and recreate with ondelete
    op.drop_constraint('evaluation_runs_knowledge_base_id_fkey', 'evaluation_runs', type_='foreignkey')
    op.create_foreign_key(
        'evaluation_runs_knowledge_base_id_fkey',
        'evaluation_runs',
        'knowledge_bases',
        ['knowledge_base_id'],
        ['id'],
        ondelete='CASCADE'
    )

    op.drop_constraint('evaluation_runs_created_by_fkey', 'evaluation_runs', type_='foreignkey')
    op.create_foreign_key(
        'evaluation_runs_created_by_fkey',
        'evaluation_runs',
        'users',
        ['created_by'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade():
    op.drop_constraint('evaluation_runs_created_by_fkey', 'evaluation_runs', type_='foreignkey')
    op.create_foreign_key('evaluation_runs_created_by_fkey', 'evaluation_runs', 'users', ['created_by'], ['id'])

    op.drop_constraint('evaluation_runs_knowledge_base_id_fkey', 'evaluation_runs', type_='foreignkey')
    op.create_foreign_key('evaluation_runs_knowledge_base_id_fkey', 'evaluation_runs', 'knowledge_bases', ['knowledge_base_id'], ['id'])
