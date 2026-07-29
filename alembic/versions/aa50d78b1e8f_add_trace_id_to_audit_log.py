"""add_trace_id_to_audit_log

Revision ID: aa50d78b1e8f
Revises: 010_add_reflection_issues
Create Date: 2026-07-28 12:06:17.915300
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aa50d78b1e8f'
down_revision: Union[str, None] = '010_add_reflection_issues'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 仅添加 trace_id 列，不动其他已被 ORM 漏报的表
    op.add_column('audit_log', sa.Column('trace_id', sa.String(length=12), nullable=True,
                  comment='全链路追踪 ID，关联分析请求'))
    op.create_index(op.f('ix_audit_log_trace_id'), 'audit_log', ['trace_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_audit_log_trace_id'), table_name='audit_log')
    op.drop_column('audit_log', 'trace_id')
