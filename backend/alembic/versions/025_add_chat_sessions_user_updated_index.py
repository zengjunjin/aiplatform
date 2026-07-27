"""chat_sessions (user_id, updated_at) composite index

Revision ID: 025_chat_sessions_user_updated_idx
Revises: 024_evaluation_run_params
Create Date: 2026-07-27

为 chat_sessions 添加 (user_id, updated_at) 复合索引，优化用户会话列表
按更新时间倒序查询的性能（列表页 `WHERE user_id=? ORDER BY updated_at DESC`）。

当前数据量小（~52 行）无需此索引，但为未来数据增长预留。
使用 CONCURRENTLY 避免锁表（PostgreSQL）。
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "025_chat_sess_user_updated"
down_revision = "024_evaluation_run_params"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 注：CONCURRENTLY 不能在 alembic 事务中执行，数据量小（~52 行）直接 CREATE INDEX
    op.create_index(
        "ix_chat_sessions_user_id_updated_at",
        "chat_sessions",
        ["user_id", "updated_at"],
        postgresql_using="btree",
        postgresql_concurrently=False,
    )
    # 添加 DESC 排序的独立索引（PostgreSQL 复合索引方向敏感）
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chat_sessions_user_id_updated_at_desc "
        "ON chat_sessions (user_id, updated_at DESC)"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_chat_sessions_user_id_updated_at_desc"
    )
    op.drop_index("ix_chat_sessions_user_id_updated_at", table_name="chat_sessions")
