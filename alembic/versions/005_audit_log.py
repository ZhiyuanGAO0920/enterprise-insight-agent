"""005_audit_log — V4 审计日志表

记录所有 API 请求的操作审计追踪：
  - 谁在什么时候访问了什么资源
  - IP 地址、User-Agent
  - 响应状态码、处理耗时

修订 ID: 005_audit_log
父修订: 004_rbac_enhancement
创建时间: 2026-06-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005_audit_log"
down_revision: Union[str, None] = "004_rbac_enhancement"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            tenant_id INTEGER,
            action VARCHAR(10) NOT NULL,
            resource VARCHAR(200) NOT NULL,
            detail TEXT,
            ip_address VARCHAR(45),
            session_id VARCHAR(100),
            user_agent VARCHAR(500),
            status_code INTEGER,
            elapsed_ms INTEGER,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    # 为常用查询创建索引
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_resource ON audit_log(resource)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")
