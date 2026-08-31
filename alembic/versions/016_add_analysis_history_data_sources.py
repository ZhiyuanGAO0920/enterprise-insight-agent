"""V5 T-10a: analysis_history 加 data_sources 列（证据链持久化）

历史分析可回查"结论当时依据什么数据"——
- 每条 data_sources 元素 = 一次 SQL 执行的完整证据 {id, agent, sql, execution_time_ms, row_count, raw_data}
- Phase 2 Grounding 校验器消费此字段做数字 ↔ raw_data 比对，Evidence Coverage 指标据此出数

Revision ID: 016_add_analysis_history_data_sources
Revises: 015_tenant_isolation_rls
Create Date: 2026-08-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "016_ah_data_sources"
down_revision: Union[str, None] = "015_tenant_isolation_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """加 data_sources JSON 列（nullable，历史记录默认 None，不回填——新增数据自动写入）。"""
    op.add_column(
        "analysis_history",
        sa.Column("data_sources", sa.JSON(), nullable=True,
                  comment="V5 T-10a: 证据链持久化 {id,agent,sql,row_count,raw_data}"),
    )


def downgrade() -> None:
    op.drop_column("analysis_history", "data_sources")
