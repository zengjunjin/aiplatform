"""add audit log user fk

Revision ID: 013_audit_log_user_fk
Revises: 012_feedback_rating_check
Create Date: 2026-07-23

"""

from alembic import op

revision = "013_audit_log_user_fk"
down_revision = "012_feedback_rating_check"
branch_labels = None
depends_on = None


def upgrade():
    op.create_foreign_key(
        "fk_audit_logs_user_id_users",
        "audit_logs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_audit_logs_user_id_users", "audit_logs", type_="foreignkey")
