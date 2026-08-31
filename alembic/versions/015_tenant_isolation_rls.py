"""015_tenant_isolation_rls — V5 T-01 路径 B 真 PG RLS

Member 表加 tenant_id 列 + 数据回填 + FK + 非空约束 + PG RLS 策略。
users.tenant_id 回填 + 非空约束（T-02 共享，006 迁移声称回填但实际未生效）。

RLS 策略：member 表 SELECT 用 current_setting('app.tenant_id') 过滤，
应用层（connection.py after_begin 事件）从 contextvar 注入 SET LOCAL app.tenant_id。

Revision ID: 015_tenant_isolation_rls
Revises: 014_eval_runs
Create Date: 2026-08-31
"""
from typing import Sequence, Union

from alembic import op

revision: str = "015_tenant_isolation_rls"
down_revision: Union[str, None] = "014_eval_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """T-01 路径 B：Member 表加列 + 回填 + FK + 非空 + RLS；T-02 共享 users 回填 + 非空。"""

    # ---- 1. Member 表加 tenant_id 列（006 迁移漏加，PG 层本无此列）----
    op.execute("""
        ALTER TABLE member
        ADD COLUMN IF NOT EXISTS tenant_id INTEGER
    """)

    # ---- 2. Member 数据回填（全部指向默认租户 id=1）----
    op.execute("""
        UPDATE member
        SET tenant_id = (SELECT id FROM tenants WHERE slug = 'default')
        WHERE tenant_id IS NULL
    """)

    # ---- 3. users.tenant_id 回填（T-02 共享；006 迁移声称回填但实测全员 NULL）----
    op.execute("""
        UPDATE users
        SET tenant_id = (SELECT id FROM tenants WHERE slug = 'default')
        WHERE tenant_id IS NULL
    """)

    # ---- 4. Member 加 FK + 非空约束 ----
    op.execute("""
        ALTER TABLE member
        DROP CONSTRAINT IF EXISTS fk_member_tenant
    """)
    op.execute("""
        ALTER TABLE member
        ADD CONSTRAINT fk_member_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenants(id)
    """)
    op.execute("ALTER TABLE member ALTER COLUMN tenant_id SET NOT NULL")

    # ---- 5. users.tenant_id 非空约束（T-02 共享）----
    op.execute("ALTER TABLE users ALTER COLUMN tenant_id SET NOT NULL")

    # ---- 6. 索引 ----
    op.execute("CREATE INDEX IF NOT EXISTS idx_member_tenant_id ON member(tenant_id)")

    # ---- 7. PG RLS 策略（路径 B 核心）----
    # current_setting('app.tenant_id', true)：未设置返回 NULL（不报错）
    # NULLIF(..., '')：空字符串转 NULL（防 ::INTEGER 报错）
    # tenant_id = NULL → FALSE（SQL NULL 语义）→ 查询返回 0 行（安全失败：拒绝而非放行）
    # FOR ALL：覆盖 SELECT/INSERT/UPDATE/DELETE
    #   USING     → SELECT/UPDATE/DELETE 过滤可见行
    #   WITH CHECK→ INSERT/UPDATE 检查新行 tenant_id 匹配当前会话 tenant_id
    op.execute("ALTER TABLE member ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY member_tenant_isolation ON member
        FOR ALL
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::INTEGER)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::INTEGER)
    """)
    # FORCE：让 owner 也受 RLS 约束（否则 admin DB 用户绕过 RLS，策略形同虚设）
    # 应用层用 eia_app（NOSUPERUSER+NOBYPASSRLS），RLS 生效；alembic 用 admin（BYPASSRLS）
    op.execute("ALTER TABLE member FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """回滚 RLS + 约束 + 列。注意：downgrade 不回滚数据回填（数据保留）。"""
    op.execute("DROP POLICY IF EXISTS member_tenant_isolation ON member")
    op.execute("ALTER TABLE member NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE member DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS idx_member_tenant_id")
    op.execute("ALTER TABLE users ALTER COLUMN tenant_id DROP NOT NULL")
    op.execute("ALTER TABLE member ALTER COLUMN tenant_id DROP NOT NULL")
    op.execute("ALTER TABLE member DROP CONSTRAINT IF EXISTS fk_member_tenant")
    op.execute("ALTER TABLE member DROP COLUMN IF EXISTS tenant_id")
