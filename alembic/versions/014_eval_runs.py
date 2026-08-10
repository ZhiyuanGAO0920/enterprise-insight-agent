"""add eval_runs table for canary drift detection

Revision ID: 014_eval_runs
Revises: 013_add_wechat_bindings
Create Date: 2026-08-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "014_eval_runs"
down_revision: Union[str, None] = "013_add_wechat_bindings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 eval_runs：每次离线评估落库（带 model_version），支撑金丝雀漂移闭环。"""
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("canary", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("pass_rate", sa.Float(), nullable=False),
        sa.Column("dimension_coverage", sa.Float(), nullable=True),
        sa.Column("cross_check_rate", sa.Float(), nullable=True),
        sa.Column("sql_accuracy", sa.Float(), nullable=True),
        sa.Column("reflection_strict_pass_rate", sa.Float(), nullable=True),
        sa.Column("reflection_effective_pass_rate", sa.Float(), nullable=True),
        sa.Column("avg_latency_ms", sa.Integer(), nullable=True),
        sa.Column("drift", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("drift_summary", sa.Text(), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("results_file", sa.String(255), nullable=True),
    )
    op.create_index("ix_eval_runs_run_at", "eval_runs", ["run_at"])
    op.create_index("ix_eval_runs_canary", "eval_runs", ["canary"])


def downgrade() -> None:
    op.drop_index("ix_eval_runs_canary", table_name="eval_runs")
    op.drop_index("ix_eval_runs_run_at", table_name="eval_runs")
    op.drop_table("eval_runs")
