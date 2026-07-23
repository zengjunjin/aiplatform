"""add performance indexes

Revision ID: 010_perf_indexes
Revises: 009_kb_collaborators_gin
Create Date: 2026-07-21

补充查询性能相关索引:
- documents.uploader_id            (用户上传文档列表查询)
- document_chunks.vector_id        (向量库反向定位 chunk)
- chat_sessions.kb_id              (按知识库维度查看会话)
- chat_messages(session_id, created_at) 复合索引 (会话消息时间线查询,覆盖现有 idx_msg_session 单列索引)
- knowledge_bases(owner_id, name)  复合索引 (按 owner 维度检索/去重校验)

注意:
- documents.status 已由 001_init_tables.py 中的 idx_doc_status 创建,此处不重复创建。
- chat_messages.session_id 单列索引 idx_msg_session 与 created_at 单列索引 idx_msg_created 已存在,
  本复合索引服务于"按 session_id 过滤并按 created_at 排序"的高频查询路径。
- knowledge_bases.owner_id 单列索引 idx_kb_owner 已存在,本复合索引服务于
  "按 owner_id 过滤并按 name 检索/排序"的查询路径。
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "010_perf_indexes"
down_revision = "009_kb_collaborators_gin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY 不能在事务中执行
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute('COMMIT')

    # documents.uploader_id 索引
    op.create_index(
        "ix_documents_uploader_id",
        "documents",
        ["uploader_id"],
        postgresql_concurrently=True,
    )

    # document_chunks.vector_id 索引
    op.create_index(
        "ix_document_chunks_vector_id",
        "document_chunks",
        ["vector_id"],
        postgresql_concurrently=True,
    )

    # chat_sessions.kb_id 索引
    op.create_index(
        "ix_chat_sessions_kb_id",
        "chat_sessions",
        ["kb_id"],
        postgresql_concurrently=True,
    )

    # chat_messages(session_id, created_at) 复合索引
    # 高选择性字段 session_id 在前,created_at 用于同会话内排序
    op.create_index(
        "ix_chat_messages_session_created",
        "chat_messages",
        ["session_id", "created_at"],
        postgresql_concurrently=True,
    )

    # knowledge_bases(owner_id, name) 复合索引
    op.create_index(
        "ix_knowledge_bases_owner_name",
        "knowledge_bases",
        ["owner_id", "name"],
        postgresql_concurrently=True,
    )

    if bind.dialect.name == 'postgresql':
        op.execute('BEGIN')


def downgrade() -> None:
    # CONCURRENTLY 不能在事务中执行
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute('COMMIT')

    op.drop_index("ix_knowledge_bases_owner_name", table_name="knowledge_bases", postgresql_concurrently=True)
    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages", postgresql_concurrently=True)
    op.drop_index("ix_chat_sessions_kb_id", table_name="chat_sessions", postgresql_concurrently=True)
    op.drop_index("ix_document_chunks_vector_id", table_name="document_chunks", postgresql_concurrently=True)
    op.drop_index("ix_documents_uploader_id", table_name="documents", postgresql_concurrently=True)

    if bind.dialect.name == 'postgresql':
        op.execute('BEGIN')
