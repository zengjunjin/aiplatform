"""alter_collaborators_to_jsonb

Revision ID: 006_collaborators_jsonb
Revises: 005_audit_logs
Create Date: 2026-07-11 20:18:00.000000

"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "006_collaborators_jsonb"
down_revision = "005_audit_feedback"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "knowledge_bases",
        "collaborators",
        existing_type=sa.JSON(),
        type_=JSONB(),
        postgresql_using="collaborators::jsonb",
        existing_nullable=False,
        existing_server_default=sa.text("'[]'"),
    )


def downgrade():
    op.alter_column(
        "knowledge_bases",
        "collaborators",
        existing_type=JSONB(),
        type_=sa.JSON(),
        postgresql_using="collaborators::json",
        existing_nullable=False,
        existing_server_default=sa.text("'[]'"),
    )
