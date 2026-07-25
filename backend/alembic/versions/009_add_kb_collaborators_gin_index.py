"""add GIN index on knowledge_bases.collaborators

Revision ID: 009_kb_collaborators_gin
Revises: 008_deleted_at_index
Create Date: 2026-07-21

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "009_kb_collaborators_gin"
down_revision = "008_deleted_at_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_kb_collaborators_gin ON knowledge_bases "
        "USING GIN (collaborators jsonb_path_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_kb_collaborators_gin")
