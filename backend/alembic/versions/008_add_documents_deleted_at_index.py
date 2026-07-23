"""add partial index on documents.deleted_at

Revision ID: 008_deleted_at_index
Revises: 007_document_deleted_at
Create Date: 2026-07-20

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "008_deleted_at_index"
down_revision = "007_document_deleted_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_documents_deleted_at",
        "documents",
        ["deleted_at"],
        postgresql_where=op.f("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_documents_deleted_at", table_name="documents")
