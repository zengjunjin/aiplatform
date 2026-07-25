"""evaluation_runs.created_by ondelete SET NULL -> CASCADE

Revision ID: 022_evaluation_created_by_ondelete
Revises: 021_eval_results_contexts_jsonb
Create Date: 2026-07-23

将 evaluation_runs.created_by 外键的 ondelete 策略由 SET NULL 改为
CASCADE: 当用户被删除时, 其创建的评测运行也应级联删除 (与 knowledge_base_id
的 CASCADE 策略一致, 避免出现孤儿评测记录)。

注: 约束名沿用 PostgreSQL 默认命名规则 `<table>_<column>_fkey`
    (与 015_add_evaluation_fk_ondelete 保持一致)。
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "022_eval_created_by_cascade"
down_revision = "021_eval_results_contexts_jsonb"
branch_labels = None
depends_on = None


def upgrade():
    # 删除原 SET NULL 外键约束, 重建为 CASCADE
    op.drop_constraint(
        "evaluation_runs_created_by_fkey",
        "evaluation_runs",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "evaluation_runs_created_by_fkey",
        "evaluation_runs",
        "users",
        ["created_by"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade():
    # 反向操作: 恢复为 SET NULL
    op.drop_constraint(
        "evaluation_runs_created_by_fkey",
        "evaluation_runs",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "evaluation_runs_created_by_fkey",
        "evaluation_runs",
        "users",
        ["created_by"],
        ["id"],
        ondelete="SET NULL",
    )
