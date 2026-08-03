"""add user_wechat_bindings table for mini program login

Revision ID: 013_add_wechat_bindings
Revises: 011_add_report_share
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "013_add_wechat_bindings"
down_revision: Union[str, None] = "011_add_report_share"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_wechat_bindings (
            id SERIAL PRIMARY KEY,
            openid VARCHAR(128) UNIQUE NOT NULL,
            user_id INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_user_wechat_bindings_openid
        ON user_wechat_bindings (openid)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_user_wechat_bindings_user_id
        ON user_wechat_bindings (user_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_wechat_bindings_user_id")
    op.execute("DROP INDEX IF EXISTS ix_user_wechat_bindings_openid")
    op.execute("DROP TABLE IF EXISTS user_wechat_bindings")
