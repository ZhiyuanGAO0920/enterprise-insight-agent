"""add performance indexes

Revision ID: 008
Revises: 007
Create Date: 2026-06-13
"""

from alembic import op

# revision identifiers
revision = "008_add_performance_indexes"
down_revision = "007_fix_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # orders 表：高频查询字段加索引
    op.execute("CREATE INDEX IF NOT EXISTS idx_orders_create_time ON orders (create_time)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_orders_store_id ON orders (store_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_orders_store_time ON orders (store_id, create_time)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_orders_member_id ON orders (member_id)")

    # member 表：外键索引
    op.execute("CREATE INDEX IF NOT EXISTS idx_member_register_date ON member (register_date)")

    # inventory 表：库存查询常用字段
    op.execute("CREATE INDEX IF NOT EXISTS idx_inventory_product_store ON inventory (product_id, store_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_inventory_store_id ON inventory (store_id)")

    # analysis_history 表：按用户和时间查询
    op.execute("CREATE INDEX IF NOT EXISTS idx_analysis_history_user_time ON analysis_history (user_id, create_time DESC)")

    # employee_performance 表
    op.execute("CREATE INDEX IF NOT EXISTS idx_emp_perf_store_month ON employee_performance (store_id, month)")


def downgrade() -> None:
    for idx in [
        "idx_orders_create_time", "idx_orders_store_id", "idx_orders_store_time",
        "idx_orders_member_id", "idx_member_register_date",
        "idx_inventory_product_store", "idx_inventory_store_id",
        "idx_analysis_history_user_time", "idx_emp_perf_store_month",
    ]:
        op.execute(f"DROP INDEX IF EXISTS {idx}")
