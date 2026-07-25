"""add_document_deleted_at

Revision ID: 007_document_deleted_at
Revises: 006_collaborators_jsonb
Create Date: 2026-07-11 20:30:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "007_document_deleted_at"
down_revision = "006_collaborators_jsonb"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "documents",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column("documents", "deleted_at")
