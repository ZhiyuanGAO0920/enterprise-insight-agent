"""007_fix_constraints — V4 数据完整性补丁

- analysis_history.tenant_id 添加外键约束 → tenants(id)
- analysis_history.tenant_id 回填已有记录的 NULL 值
- audit_log.action 扩展为 VARCHAR(50) 防止截断
- analysis_history.tenant_id 设置为 NOT NULL（回填后）

修订 ID: 007_fix_constraints
父修订: 006_multi_tenant
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007_fix_constraints"
down_revision: Union[str, None] = "006_multi_tenant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 回填 analysis_history 中 NULL 的 tenant_id
    #    通过关联 users 表获知该分析记录的租户
    op.execute("""
        UPDATE analysis_history ah
        SET tenant_id = u.tenant_id
        FROM users u
        WHERE ah.user_id = u.id
          AND ah.tenant_id IS NULL
    """)
    # 没有关联用户的记录回退到默认租户
    op.execute("""
        UPDATE analysis_history
        SET tenant_id = (SELECT id FROM tenants ORDER BY id LIMIT 1)
        WHERE tenant_id IS NULL
    """)

    # 2. 扩展 audit_log.action 列宽
    op.alter_column(
        "audit_log", "action",
        existing_type=sa.VARCHAR(10),
        type_=sa.VARCHAR(50),
        existing_nullable=False,
    )

    # 3. 添加外键约束
    op.create_foreign_key(
        "fk_analysis_history_tenant",
        "analysis_history", "tenants",
        ["tenant_id"], ["id"],
    )

    # 4. 设置 NOT NULL（所有行已回填）
    op.alter_column(
        "analysis_history", "tenant_id",
        existing_type=sa.INTEGER(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column("analysis_history", "tenant_id", nullable=True)
    op.drop_constraint("fk_analysis_history_tenant", "analysis_history", type_="foreignkey")
    op.alter_column(
        "audit_log", "action",
        existing_type=sa.VARCHAR(50),
        type_=sa.VARCHAR(10),
        existing_nullable=False,
    )
