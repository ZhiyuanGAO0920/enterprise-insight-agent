"""初始 Schema —— 企业智能经营分析平台 V2。

修订 ID: 001_initial
创建日期: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 启用 pgvector 扩展（AnalysisHistory.embedding 所需）
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 用户与 RBAC
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(100), unique=True, nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
    )
    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(100), unique=True, nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), primary_key=True),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), primary_key=True),
        sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id"), primary_key=True),
    )
    op.create_table(
        "user_store_access",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("store_id", sa.String(50), primary_key=True),
        sa.Column("region", sa.String(100), nullable=True),
    )

    # 分析历史（基于 pgvector 的长期记忆）
    op.create_table(
        "analysis_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("report", sa.Text(), nullable=False),
        sa.Column("sales_result", sa.Text(), nullable=True),
        sa.Column("crm_result", sa.Text(), nullable=True),
        sa.Column("finance_result", sa.Text(), nullable=True),
        sa.Column("reflection_passed", sa.Boolean(), default=False),
        sa.Column("create_time", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        # pgvector Vector(1024) —— 使用服务端 CREATE 列来避免
        # 迁移时对 pgvector Python 包的依赖。
        # 该列通过下面的原始 SQL 添加。
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
    )
    # 将 LargeBinary 占位符替换为真正的 pgvector 类型
    # 全新安装时列可能已经是 vector 类型（由 pgvector 自动处理），因此使用 DO 块容错
    op.execute("""
        DO $$
        BEGIN
            ALTER TABLE analysis_history
            ALTER COLUMN embedding TYPE vector(1024) USING embedding::vector(1024);
        EXCEPTION WHEN others THEN
            RAISE NOTICE 'embedding column already vector type, skipping conversion';
        END $$;
    """)

    # 预警
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("metric", sa.String(100), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("enabled", sa.Boolean(), default=True),
        sa.Column("notify_channels", sa.JSON(), default=list),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("alert_rules.id"), nullable=False),
        sa.Column("metric", sa.String(100), nullable=False),
        sa.Column("actual_value", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("acknowledged", sa.Boolean(), default=False),
        sa.Column("acknowledged_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
    )

    # 周报
    op.create_table(
        "weekly_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("week_start", sa.DateTime(), nullable=False),
        sa.Column("week_end", sa.DateTime(), nullable=False),
        sa.Column("report_content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )

    # 种子数据：默认权限和角色
    op.execute("""
        INSERT INTO permissions (code, description) VALUES
            ('analysis:create', 'Create analysis requests'),
            ('analysis:view', 'View analysis results'),
            ('history:view', 'View analysis history'),
            ('report:view', 'View weekly reports'),
            ('report:create', 'Create weekly reports'),
            ('alert:view', 'View alert rules'),
            ('alert:configure', 'Configure alert rules'),
            ('user:manage', 'Manage users'),
            ('role:manage', 'Manage roles');
    """)
    op.execute("""
        INSERT INTO roles (name, description) VALUES
            ('admin', 'System admin -- full access'),
            ('manager', 'HQ management -- view all data'),
            ('regional_manager', 'Regional manager -- regional data'),
            ('store_manager', 'Store manager -- store data only');
    """)


def downgrade() -> None:
    op.drop_table("weekly_reports")
    op.drop_table("alerts")
    op.drop_table("alert_rules")
    op.drop_table("analysis_history")
    op.drop_table("user_store_access")
    op.drop_table("role_permissions")
    op.drop_table("user_roles")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_table("users")
