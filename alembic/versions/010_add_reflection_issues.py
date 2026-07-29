"""add reflection_issues column to analysis_history

Revision ID: 010
Revises: 009_add_llm_cost_columns
Create Date: 2026-07-16
"""

from alembic import op

revision = "010_add_reflection_issues"
down_revision = "009_add_llm_cost_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE analysis_history
        ADD COLUMN IF NOT EXISTS reflection_issues JSON
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE analysis_history DROP COLUMN IF EXISTS reflection_issues")
