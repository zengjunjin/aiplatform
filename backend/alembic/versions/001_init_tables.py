"""init_tables

Revision ID: 001_init
Revises:
Create Date: 2026-07-05 00:00:00.000000

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### users table ###
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("idx_users_username", "users", ["username"], unique=False)
    op.create_index("idx_users_email", "users", ["email"], unique=False)

    # ### knowledge_bases table ###
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("doc_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_kb_owner", "knowledge_bases", ["owner_id"], unique=False)

    # ### documents table ###
    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kb_id", sa.BigInteger(), nullable=False),
        sa.Column("uploader_id", sa.BigInteger(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("file_type", sa.String(length=20), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["uploader_id"],
            ["users.id"],
        ),
        sa.UniqueConstraint("kb_id", "file_hash", name="uq_doc_kb_hash"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_doc_kb", "documents", ["kb_id"], unique=False)
    op.create_index("idx_doc_status", "documents", ["status"], unique=False)

    # ### document_chunks table ###
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("doc_id", sa.BigInteger(), nullable=False),
        sa.Column("kb_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("vector_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["doc_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("doc_id", "chunk_index", name="uq_doc_chunk_index"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_chunk_doc", "document_chunks", ["doc_id"], unique=False)
    op.create_index("idx_chunk_kb", "document_chunks", ["kb_id"], unique=False)

    # ### chat_sessions table ###
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kb_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False, server_default="新对话"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_session_user", "chat_sessions", ["user_id"], unique=False)

    # ### chat_messages table ###
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("referenced_chunks", postgresql.JSONB(), nullable=True),
        sa.Column("token_input", sa.Integer(), nullable=True),
        sa.Column("token_output", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_msg_session", "chat_messages", ["session_id"], unique=False)
    op.create_index("idx_msg_created", "chat_messages", ["created_at"], unique=False)


def downgrade():
    op.drop_index("idx_msg_created", table_name="chat_messages")
    op.drop_index("idx_msg_session", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("idx_session_user", table_name="chat_sessions")
    op.drop_table("chat_sessions")

    op.drop_index("idx_chunk_kb", table_name="document_chunks")
    op.drop_index("idx_chunk_doc", table_name="document_chunks")
    op.drop_table("document_chunks")

    op.drop_index("idx_doc_status", table_name="documents")
    op.drop_index("idx_doc_kb", table_name="documents")
    op.drop_table("documents")

    op.drop_index("idx_kb_owner", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")

    op.drop_index("idx_users_email", table_name="users")
    op.drop_index("idx_users_username", table_name="users")
    op.drop_table("users")
