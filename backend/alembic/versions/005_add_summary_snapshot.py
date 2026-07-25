"""add_summary_snapshot

Revision ID: 004_summary
Revises: 004_kb_collaborators
Create Date: 2026-07-11 00:00:00.000000

命名历史说明 (Task 1.2):
    本文件名为 005_add_summary_snapshot.py (前缀 005)，但内部 revision id 为
    '004_summary'，与文件名前缀不一致。这是因为该迁移在逻辑上紧随 004_kb_collaborators
    之后，故 revision 沿用 004_ 前缀以体现其在 004 分支上的延续。

    保留 revision='004_summary' 不做修改的原因:
    1. 下游迁移 005_add_audit_logs_and_feedback_uq.py 的 down_revision 指向 '004_summary'，
       修改 revision id 会破坏迁移链。
    2. 已部署环境的 alembic_version 表中记录了 '004_summary'，修改会导致 alembic 无法
       识别当前数据库状态。

    故采用低风险方案: 保留原 revision id，仅添加本注释说明命名历史。
    linter 脚本 (scripts/check_migrations.py) 会对此类文件名前缀与 revision 不一致的情况
    输出警告（非错误）。
"""

import sqlalchemy as sa

from alembic import op

revision = "004_summary"
down_revision = "004_kb_collaborators"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "chat_messages",
        sa.Column("summary_snapshot", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("chat_messages", "summary_snapshot")
