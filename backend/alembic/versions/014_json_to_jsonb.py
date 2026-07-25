"""json to jsonb

Revision ID: 014_json_to_jsonb
Revises: 013_audit_log_user_fk
Create Date: 2026-07-23

将 JSON 列改为 JSONB 以获得 GIN 索引、去重、高效键查询等优势。
仅 PostgreSQL 执行类型变更; 其他方言 (如 SQLite 测试) 跳过。

涉及的列:
- audit_logs.details       (JSON -> JSONB)
- evaluation_runs.metrics  (JSON -> JSONB)

注: evaluation_runs 表无 dataset 列; evaluation_results.contexts 暂不在本迁移范围。
"""

import sqlalchemy as sa

from alembic import op

revision = "014_json_to_jsonb"
down_revision = "013_audit_log_user_fk"
branch_labels = None
depends_on = None


def upgrade():
    # PostgreSQL specific: alter column types to JSONB
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "audit_logs",
            "details",
            type_=sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            postgresql_using="details::jsonb",
        )
        op.alter_column(
            "evaluation_runs",
            "metrics",
            type_=sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            postgresql_using="metrics::jsonb",
        )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "evaluation_runs", "metrics", type_=sa.JSON(), postgresql_using="metrics::json"
        )
        op.alter_column("audit_logs", "details", type_=sa.JSON(), postgresql_using="details::json")
