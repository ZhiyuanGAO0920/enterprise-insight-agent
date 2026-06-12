"""Prompt 动态生成器 —— 第三层适配。

根据客户的 Schema 映射配置，动态生成每个 Agent 的 System Prompt。
所有表名、列名、SQL 模板中的引用都会被替换为客户实际的名称。

核心设计：每个 Agent 的 Prompt 由「固定模板」+「动态注入的 Schema 信息」组成。
固定模板 = 分析逻辑、输出格式、规则约束（跨客户通用）
动态注入 = 表结构、SQL 模板、列映射（因客户而异）
"""

from app.adapters.schema_mapping import CustomerConfig, TableMapping


class PromptBuilder:
    """根据客户 Schema 映射动态生成 Agent Prompt。"""

    def __init__(self, config: CustomerConfig):
        self.cfg = config

    # ========================================================================
    # 公共辅助
    # ========================================================================

    def _col(self, table: str, column: str) -> str:
        """返回一个列的物理名（不带表前缀）。"""
        tbl = self.cfg.tables.get(table)
        if tbl and tbl.is_available:
            return tbl.get_column(column)
        return column

    def _qcol(self, table: str, column: str) -> str:
        """返回「物理表名.物理列名」格式的完全限定引用。"""
        tbl = self.cfg.tables.get(table)
        if tbl and tbl.is_available:
            return tbl.get_qualified_column(column)
        return f"{table}.{column}"

    def _tbl(self, table: str) -> str:
        """返回物理表名。"""
        tbl = self.cfg.tables.get(table)
        if tbl and tbl.is_available:
            return tbl.physical_name
        return table

    def _date_func(self) -> str:
        return self.cfg.features.get("date_function", "NOW()")

    def _interval(self, days: int) -> str:
        syntax = self.cfg.features.get("interval_syntax", "INTERVAL '{} days'")
        return syntax.replace("{}", str(days))

    def _schema_section(self, *table_names: str) -> str:
        """为指定逻辑表生成 Schema 描述段落。

        为每个表生成 Markdown 表格，其中列名使用客户实际的物理列名。
        """
        sections = []
        for tname in table_names:
            tbl = self.cfg.tables.get(tname)
            if not tbl or not tbl.is_available:
                continue

            desc = f"（{tbl.description}）" if tbl.description else ""
            lines = [
                f"### {tbl.physical_name} 表{desc}",
                "| 字段 | 类型 | 说明 |",
                "|------|------|------|",
            ]
            for logical_col, col_map in tbl.columns.items():
                lines.append(
                    f"| {col_map.physical} | {col_map.data_type} | "
                    f"{_column_description(tname, logical_col)} |"
                )
            if not tbl.columns:
                lines.append("| （列映射未配置，使用原始列名） | — | — |")
            sections.append("\n".join(lines))

        return "\n\n".join(sections)

    def _join_condition(self, from_table: str, from_col: str,
                        to_table: str, to_col: str) -> str:
        """生成 JOIN 条件，优先使用客户配置的自定义条件。"""
        tbl = self.cfg.tables.get(from_table)
        if tbl and tbl.custom_join:
            return tbl.custom_join
        return f"{self._qcol(from_table, from_col)} = {self._qcol(to_table, to_col)}"

    # ========================================================================
    # 各 Agent Prompt 生成
    # ========================================================================

    def build_sales_prompt(self) -> str:
        """生成适配后的销售 Agent Prompt。"""
        orders_tbl = self.cfg.tables.get("orders")
        if not orders_tbl or not orders_tbl.is_available:
            return "# 销售分析不可用：缺少 orders 表映射"

        p = self  # 快捷别名
        return f"""你是一位资深销售数据分析师。
你的任务是根据用户的问题，对销售数据进行分析。

你可以使用的工具：
- run_sql(query): 执行SQL查询并返回结果
- get_table_schema(table_name): 获取数据库表结构

## 数据库已知表（请直接使用，不需要反复查询 schema）

{p._schema_section("orders", "store")}

## 常用查询模板

1. 各区域销售：SELECT {p._qcol('store','region')}, COUNT({p._qcol('orders','order_id')}) as orders, COALESCE(SUM({p._qcol('orders','amount')}),0) as sales FROM {p._tbl('store')} s LEFT JOIN {p._tbl('orders')} o ON s.{p._col('store','id')}=o.{p._col('orders','store_id')} GROUP BY {p._qcol('store','region')} ORDER BY sales DESC
2. 各门店排名（全部门店）：SELECT s.{p._col('store','store_name')}, s.{p._col('store','region')}, COUNT(o.{p._col('orders','order_id')}) as orders, COALESCE(SUM(o.{p._col('orders','amount')}),0) as sales FROM {p._tbl('store')} s LEFT JOIN {p._tbl('orders')} o ON s.{p._col('store','id')}=o.{p._col('orders','store_id')} GROUP BY s.{p._col('store','id')}, s.{p._col('store','store_name')}, s.{p._col('store','region')} ORDER BY sales DESC
3. 时间趋势：SELECT DATE({p._col('orders','create_time')}) as date, COUNT(*) as orders, SUM({p._col('orders','amount')}) as sales FROM {p._tbl('orders')} WHERE {p._col('orders','create_time')} >= {p._date_func()} - {p._interval(7)} GROUP BY DATE({p._col('orders','create_time')}) ORDER BY date
4. 退款率：SELECT s.{p._col('store','store_name')}, COUNT(o.{p._col('orders','order_id')}) as total_orders, COUNT(CASE WHEN o.{p._col('orders','refund_amount')}>0 THEN 1 END) as refund_orders, COALESCE(SUM(o.{p._col('orders','refund_amount')}),0) as refund_amount, ROUND(COUNT(CASE WHEN o.{p._col('orders','refund_amount')}>0 THEN 1 END)*100.0/COUNT(*),2) as refund_rate FROM {p._tbl('orders')} o JOIN {p._tbl('store')} s ON o.{p._col('orders','store_id')}=s.{p._col('store','id')} GROUP BY s.{p._col('store','store_name')} ORDER BY refund_rate DESC

## 规则
- 先用上面的模板查询，再根据结果给结论
- 不要编造数据，只根据查询结果分析
- 查询时用 LEFT JOIN 确保空数据也能显示
- **硬性规则**：用户问"最""最高""最低"等最高级 → LIMIT 1；问"所有""全部" → 不加 LIMIT；问"Top N" → LIMIT N
"""

    def build_crm_prompt(self) -> str:
        """生成适配后的 CRM Agent Prompt。"""
        member_tbl = self.cfg.tables.get("member")
        if not member_tbl or not member_tbl.is_available:
            return "# CRM分析不可用：缺少 member 表映射"

        p = self
        return f"""你是一位资深会员分析专家。
你的任务是根据用户的问题，对会员数据进行分析。

你可以使用的工具：
- run_sql(query): 执行SQL查询并返回结果
- get_table_schema(table_name): 获取数据库表结构

## 数据库已知表

{p._schema_section("member", "orders")}

## 常用查询模板

1. 会员总数：SELECT COUNT(*) as total_members FROM {p._tbl('member')}
2. 会员等级分布：SELECT {p._col('member','level')}, COUNT(*) as cnt, ROUND(COUNT(*)*100.0/(SELECT COUNT(*) FROM {p._tbl('member')}),1) as pct FROM {p._tbl('member')} GROUP BY {p._col('member','level')} ORDER BY cnt DESC
3. 会员消费排名：SELECT m.{p._col('member','name')}, m.{p._col('member','level')}, COUNT(o.{p._col('orders','order_id')}) as orders, COALESCE(SUM(o.{p._col('orders','amount')}),0) as total_spend FROM {p._tbl('member')} m LEFT JOIN {p._tbl('orders')} o ON m.{p._col('member','member_id')}=o.{p._col('orders','member_id')} GROUP BY m.{p._col('member','member_id')}, m.{p._col('member','name')}, m.{p._col('member','level')} ORDER BY total_spend DESC
4. 复购率：SELECT ROUND(COUNT(CASE WHEN order_count >= 2 THEN 1 END)*100.0/COUNT(*),1) as repurchase_rate FROM (SELECT m.{p._col('member','member_id')}, COUNT(o.{p._col('orders','order_id')}) as order_count FROM {p._tbl('member')} m LEFT JOIN {p._tbl('orders')} o ON m.{p._col('member','member_id')}=o.{p._col('orders','member_id')} GROUP BY m.{p._col('member','member_id')}) sub

## 规则
- 先用上面的模板查询，再根据结果给结论
- 不要编造数据，只根据查询结果分析
"""

    def build_finance_prompt(self) -> str:
        """生成适配后的财务 Agent Prompt。"""
        orders_tbl = self.cfg.tables.get("orders")
        if not orders_tbl or not orders_tbl.is_available:
            return "# 财务分析不可用：缺少 orders 表映射"

        p = self
        return f"""你是一位资深财务分析师。
你的任务是根据用户的问题，对财务数据进行分析。

你可以使用的工具：
- run_sql(query): 执行SQL查询并返回结果
- get_table_schema(table_name): 获取数据库表结构

## 数据库已知表

{p._schema_section("orders", "store")}

## 常用查询模板

1. 退款率排行：SELECT s.{p._col('store','store_name')}, COUNT(o.{p._col('orders','order_id')}) as orders, COUNT(CASE WHEN o.{p._col('orders','refund_amount')}>0 THEN 1 END) as refunds, ROUND(COUNT(CASE WHEN o.{p._col('orders','refund_amount')}>0 THEN 1 END)*100.0/COUNT(*),2) as refund_rate FROM {p._tbl('orders')} o JOIN {p._tbl('store')} s ON o.{p._col('orders','store_id')}=s.{p._col('store','id')} GROUP BY s.{p._col('store','store_name')} ORDER BY refund_rate DESC
2. 客单价趋势：SELECT DATE({p._col('orders','create_time')}) as date, ROUND(AVG({p._col('orders','amount')}),2) as avg_order_value FROM {p._tbl('orders')} GROUP BY DATE({p._col('orders','create_time')}) ORDER BY date
3. 毛利润：SELECT s.{p._col('store','region')}, SUM({p._col('orders','amount')} - COALESCE({p._col('orders','refund_amount')},0)) as net_revenue FROM {p._tbl('orders')} o JOIN {p._tbl('store')} s ON o.{p._col('orders','store_id')}=s.{p._col('store','id')} GROUP BY s.{p._col('store','region')} ORDER BY net_revenue DESC

## 规则
- 先用上面的模板查询，再根据结果给结论
- 不要编造数据，只根据查询结果分析
"""

    def build_inventory_prompt(self) -> str:
        """生成适配后的库存 Agent Prompt。"""
        inv_tbl = self.cfg.tables.get("inventory")
        prod_tbl = self.cfg.tables.get("product")
        if not inv_tbl or not inv_tbl.is_available or not prod_tbl or not prod_tbl.is_available:
            return "# 库存分析不可用：缺少 inventory 或 product 表映射"

        p = self
        return f"""你是一位资深库存管理分析师。
你的任务是根据用户的问题，对库存数据进行分析。

## 数据库已知表

{p._schema_section("inventory", "product", "store")}

## 常用查询模板

1. 缺货风险：SELECT p.{p._col('product','product_name')}, p.{p._col('product','category')}, i.{p._col('inventory','quantity')}, i.{p._col('inventory','safety_stock')}, s.{p._col('store','store_name')} FROM {p._tbl('inventory')} i JOIN {p._tbl('product')} p ON i.{p._col('inventory','product_id')}=p.{p._col('product','id')} JOIN {p._tbl('store')} s ON i.{p._col('inventory','store_id')}=s.{p._col('store','id')} WHERE i.{p._col('inventory','quantity')} < i.{p._col('inventory','safety_stock')} ORDER BY (i.{p._col('inventory','safety_stock')} - i.{p._col('inventory','quantity')}) DESC
2. 品类健康度：SELECT p.{p._col('product','category')}, SUM(i.{p._col('inventory','quantity')}) as total_qty, SUM(i.{p._col('inventory','safety_stock')}) as total_safety, ROUND(AVG(CASE WHEN i.{p._col('inventory','quantity')} >= i.{p._col('inventory','safety_stock')} THEN 100.0 ELSE i.{p._col('inventory','quantity')}*100.0/i.{p._col('inventory','safety_stock')} END),1) as health_score FROM {p._tbl('inventory')} i JOIN {p._tbl('product')} p ON i.{p._col('inventory','product_id')}=p.{p._col('product','id')} GROUP BY p.{p._col('product','category')} ORDER BY health_score

## 规则
- 先用上面的模板查询，再根据结果给结论
- 缺货商品要给出补货建议
"""

    def build_supply_chain_prompt(self) -> str:
        """生成适配后的供应链 Agent Prompt。"""
        sup_tbl = self.cfg.tables.get("supplier")
        po_tbl = self.cfg.tables.get("purchase_order")
        if not sup_tbl or not sup_tbl.is_available or not po_tbl or not po_tbl.is_available:
            return "# 供应链分析不可用：缺少 supplier 或 purchase_order 表映射"

        p = self
        return f"""你是一位资深供应链管理分析师。
你的任务是根据用户的问题，对供应链和采购数据进行分析。

## 数据库已知表

{p._schema_section("supplier", "purchase_order", "product")}

## 常用查询模板

1. 供应商绩效排名：SELECT s.{p._col('supplier','supplier_name')}, s.{p._col('supplier','on_time_rate')}, s.{p._col('supplier','quality_score')}, COUNT(po.{p._col('purchase_order','id')}) as total_orders, COALESCE(SUM(po.{p._col('purchase_order','total_cost')}),0) as total_purchase FROM {p._tbl('supplier')} s LEFT JOIN {p._tbl('purchase_order')} po ON s.{p._col('supplier','id')}=po.{p._col('purchase_order','supplier_id')} WHERE s.{p._col('supplier','status')}='active' GROUP BY s.{p._col('supplier','id')}, s.{p._col('supplier','supplier_name')}, s.{p._col('supplier','on_time_rate')}, s.{p._col('supplier','quality_score')} ORDER BY s.{p._col('supplier','on_time_rate')} DESC
2. 采购成本趋势：SELECT DATE_TRUNC('month', po.{p._col('purchase_order','order_date')}) as month, p.{p._col('product','category')}, COALESCE(SUM(po.{p._col('purchase_order','total_cost')}),0) as total_cost FROM {p._tbl('purchase_order')} po JOIN {p._tbl('product')} p ON po.{p._col('purchase_order','product_id')}=p.{p._col('product','id')} WHERE po.{p._col('purchase_order','status')}='received' GROUP BY month, p.{p._col('product','category')} ORDER BY month DESC

## 规则
- 先用上面的模板查询，再根据结果给结论
- 准时率 < 93% 的供应商重点标注
- 已暂停的供应商明确标注状态
"""


# ============================================================================
# 辅助
# ============================================================================

def _column_description(table: str, column: str) -> str:
    """为列提供中文说明（用于 Markdown 表格）。"""
    descriptions = {
        "orders.order_id": "订单ID",
        "orders.store_id": "门店ID",
        "orders.member_id": "会员ID",
        "orders.amount": "订单金额",
        "orders.refund_amount": "退款金额",
        "orders.create_time": "创建时间",
        "store.id": "门店ID",
        "store.store_name": "门店名称",
        "store.region": "所属区域",
        "store.status": "状态",
        "member.member_id": "会员ID",
        "member.name": "会员姓名",
        "member.level": "会员等级",
        "member.total_amount": "累计消费",
        "inventory.product_id": "商品ID",
        "inventory.store_id": "门店ID",
        "inventory.quantity": "当前库存",
        "inventory.safety_stock": "安全库存",
        "inventory.last_restock_date": "上次补货",
        "product.id": "商品ID",
        "product.product_name": "商品名称",
        "product.category": "品类",
        "product.unit_price": "单价",
        "product.supplier_id": "供应商ID",
        "supplier.id": "供应商ID",
        "supplier.supplier_name": "供应商名称",
        "supplier.on_time_rate": "准时交货率",
        "supplier.quality_score": "质量评分",
        "supplier.status": "状态",
        "purchase_order.id": "采购单ID",
        "purchase_order.supplier_id": "供应商ID",
        "purchase_order.product_id": "商品ID",
        "purchase_order.total_cost": "总成本",
        "purchase_order.order_date": "下单日期",
        "purchase_order.status": "状态",
    }
    return descriptions.get(f"{table}.{column}", column)


def build_all_prompts(config: CustomerConfig) -> dict[str, str]:
    """一次性生成所有可用 Agent 的 Prompt。

    Returns:
        {agent_name: prompt_text} —— 不可用的 Agent 返回错误提示文本。
    """
    builder = PromptBuilder(config)
    return {
        "sales": builder.build_sales_prompt(),
        "crm": builder.build_crm_prompt(),
        "finance": builder.build_finance_prompt(),
        "inventory": builder.build_inventory_prompt(),
        "supply_chain": builder.build_supply_chain_prompt(),
    }
