"""006_multi_tenant — V4 多租户

添加租户表(tenants)和用户/分析历史的 tenant_id 关联。
支持 shared-database + tenant_id 隔离模式（默认）。

修订 ID: 006_multi_tenant
父修订: 005_audit_log
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006_multi_tenant"
down_revision: Union[str, None] = "005_audit_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 创建租户表
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id SERIAL PRIMARY KEY,
            name VARCHAR(200) NOT NULL UNIQUE,
            slug VARCHAR(50) NOT NULL UNIQUE,
            db_schema VARCHAR(50),
            db_url VARCHAR(500),
            is_active BOOLEAN DEFAULT TRUE,
            max_users INTEGER DEFAULT 50,
            plan VARCHAR(50) DEFAULT 'free',
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    # 2. 添加 tenant_id 到 users 表
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id)
    """)

    # 3. 添加 tenant_id 到 analysis_history 表
    op.execute("""
        ALTER TABLE analysis_history
        ADD COLUMN IF NOT EXISTS tenant_id INTEGER
    """)

    # 4. 创建默认租户
    op.execute("""
        INSERT INTO tenants (name, slug, plan)
        VALUES ('默认租户', 'default', 'enterprise')
        ON CONFLICT (slug) DO NOTHING
    """)

    # 5. 将现有用户关联到默认租户
    op.execute("""
        UPDATE users SET tenant_id = (SELECT id FROM tenants WHERE slug = 'default')
        WHERE tenant_id IS NULL
    """)

    # 6. 索引
    op.execute("CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON users(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_analysis_history_tenant_id ON analysis_history(tenant_id)")


def downgrade() -> None:
    op.execute("ALTER TABLE analysis_history DROP COLUMN IF EXISTS tenant_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS tenant_id")
    op.execute("DROP TABLE IF EXISTS tenants CASCADE")
