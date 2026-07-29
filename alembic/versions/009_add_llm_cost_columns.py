"""add llm_cost columns to analysis_history

Revision ID: 009
Revises: 008_add_performance_indexes
Create Date: 2026-07-16
"""

from alembic import op

revision = "009_add_llm_cost_columns"
down_revision = "008_add_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE analysis_history
        ADD COLUMN IF NOT EXISTS input_tokens INTEGER DEFAULT 0
    """)
    op.execute("""
        ALTER TABLE analysis_history
        ADD COLUMN IF NOT EXISTS output_tokens INTEGER DEFAULT 0
    """)
    op.execute("""
        ALTER TABLE analysis_history
        ADD COLUMN IF NOT EXISTS llm_cost REAL DEFAULT 0.0
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE analysis_history DROP COLUMN IF EXISTS input_tokens")
    op.execute("ALTER TABLE analysis_history DROP COLUMN IF EXISTS output_tokens")
    op.execute("ALTER TABLE analysis_history DROP COLUMN IF EXISTS llm_cost")
