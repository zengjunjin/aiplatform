"""add_audit_logs_and_feedback_uq

Revision ID: 005_audit_feedback
Revises: 004_summary
Create Date: 2026-07-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '005_audit_feedback'
down_revision = '004_summary'
branch_labels = None
depends_on = None


def upgrade():
    # ### audit_logs table (use IF NOT EXISTS since init_db may have created it) ###
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id BIGSERIAL NOT NULL,
            user_id BIGINT,
            action VARCHAR(50) NOT NULL,
            ip_address VARCHAR(45),
            user_agent VARCHAR(500),
            details JSON,
            result VARCHAR(10) NOT NULL DEFAULT 'success',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at)")

    # ### message_feedbacks unique constraint (IF NOT EXISTS) ###
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_message_user_feedback'
            ) THEN
                ALTER TABLE message_feedbacks
                ADD CONSTRAINT uq_message_user_feedback UNIQUE (message_id, user_id);
            END IF;
        END $$;
    """)


def downgrade():
    op.drop_constraint('uq_message_user_feedback', 'message_feedbacks', type_='unique')
    op.drop_index('idx_audit_created', table_name='audit_logs')
    op.drop_index('idx_audit_action', table_name='audit_logs')
    op.drop_index('idx_audit_user', table_name='audit_logs')
    op.drop_table('audit_logs')
