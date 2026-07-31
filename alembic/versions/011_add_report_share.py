"""add share_token to analysis_history for report sharing

Revision ID: 011_add_report_share
Revises: aa50d78b1e8f
Create Date: 2026-07-31
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011_add_report_share"
down_revision: Union[str, None] = "aa50d78b1e8f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE analysis_history
        ADD COLUMN IF NOT EXISTS share_token VARCHAR(64)
    """)
    op.execute("""
        ALTER TABLE analysis_history
        ADD COLUMN IF NOT EXISTS share_expires_at TIMESTAMP
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_analysis_history_share_token
        ON analysis_history (share_token)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_analysis_history_share_token")
    op.execute("ALTER TABLE analysis_history DROP COLUMN IF EXISTS share_expires_at")
    op.execute("ALTER TABLE analysis_history DROP COLUMN IF EXISTS share_token")
