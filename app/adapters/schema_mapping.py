"""Schema 语义映射 —— 第二层适配。

加载客户配置的 YAML 映射文件，建立「逻辑概念 → 物理表/列」的映射关系。
提供验证功能，确保所有 Agent 引用的逻辑表都有对应的物理映射。

逻辑概念（系统内部固定）：
  orders, store, member, employee_performance,
  product, supplier, inventory, purchase_order

物理表/列（客户实际数据库）：
  由 customer_schema.yaml 定义，因客户而异。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


# ============================================================================
# 数据模型
# ============================================================================


@dataclass
class ColumnMapping:
    """单个列的映射：逻辑名 → 物理名。"""
    logical: str          # 系统内部名称（如 "order_id"）
    physical: str         # 客户实际列名（如 "sale_id"）
    data_type: str = ""   # 客户数据类型（如 "INT"）
    note: str = ""        # 特殊说明（如值转换规则）


@dataclass
class TableMapping:
    """单张表的映射：逻辑概念 → 物理表 + 列映射。"""
    logical: str                           # 系统内部概念名（如 "orders"）
    physical_name: Optional[str] = None    # 客户实际表名（如 "t_sales"），None = 客户无此表
    description: str = ""
    columns: dict[str, ColumnMapping] = field(default_factory=dict)
    custom_join: Optional[str] = None      # 自定义 JOIN 条件（覆盖默认的外键关系）

    @property
    def is_available(self) -> bool:
        return self.physical_name is not None

    def get_column(self, logical_name: str) -> str:
        """将逻辑列名映射为物理列名。如果未配置映射，返回原始名称。"""
        if logical_name in self.columns:
            return self.columns[logical_name].physical
        return logical_name

    def get_qualified_column(self, logical_name: str) -> str:
        """返回「表名.列名」格式的完全限定列引用。"""
        return f"{self.physical_name}.{self.get_column(logical_name)}"


@dataclass
class CustomerConfig:
    """完整的客户配置。"""
    name: str = ""
    database_type: str = "postgresql"
    database_url: str = ""
    tables: dict[str, TableMapping] = field(default_factory=dict)
    features: dict[str, Any] = field(default_factory=dict)

    def available_agents(self) -> list[str]:
        """返回该客户可用的 Agent 列表。

        根据哪些逻辑表有物理映射来判断：
        - orders → sales agent
        - member → crm agent
        - orders + refund_amount → finance agent
        - inventory + product → inventory agent
        - supplier + purchase_order → supply_chain agent
        """
        agents = []
        if self.tables.get("orders") and self.tables["orders"].is_available:
            agents.append("sales")
        if self.tables.get("member") and self.tables["member"].is_available:
            agents.append("crm")
        if self.tables.get("orders") and self.tables["orders"].is_available:
            agents.append("finance")  # 只要有 orders 表就能做财务分析
        if (self.tables.get("inventory") and self.tables["inventory"].is_available and
                self.tables.get("product") and self.tables["product"].is_available):
            agents.append("inventory")
        if (self.tables.get("supplier") and self.tables["supplier"].is_available and
                self.tables.get("purchase_order") and self.tables["purchase_order"].is_available):
            agents.append("supply_chain")
        return agents

    def validate(self) -> list[str]:
        """验证映射配置的完整性。

        Returns:
            缺失配置的列表（空列表 = 全部通过）。
        """
        issues = []
        required_tables = ["orders", "store", "member"]
        for t in required_tables:
            if t not in self.tables or not self.tables[t].is_available:
                issues.append(f"缺少核心表映射：{t}（对应 Agent 将被禁用）")

        # 检查列映射完整性
        for table_name, table_mapping in self.tables.items():
            if not table_mapping.is_available:
                continue
            if not table_mapping.columns:
                issues.append(
                    f"表 '{table_name}' 已映射物理表 '{table_mapping.physical_name}' "
                    f"但没有列映射——Agent 将使用原始列名（可能不匹配）"
                )

        return issues


# ============================================================================
# 加载器
# ============================================================================


def load_schema_mapping(yaml_path: str | Path) -> CustomerConfig:
    """从 YAML 文件加载客户 Schema 映射配置。

    Args:
        yaml_path: customer_schema.yaml 文件路径。

    Returns:
        解析后的 CustomerConfig 对象。

    Raises:
        FileNotFoundError: YAML 文件不存在。
        yaml.YAMLError: YAML 格式错误。
    """
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"客户配置文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    customer_raw = raw.get("customer", {})
    features_raw = raw.get("database_features", {})

    # 解析表映射
    tables: dict[str, TableMapping] = {}
    for logical_name, table_raw in raw.get("tables", {}).items():
        columns: dict[str, ColumnMapping] = {}
        for col_logical, col_raw in (table_raw.get("columns") or {}).items():
            columns[col_logical] = ColumnMapping(
                logical=col_logical,
                physical=col_raw.get("physical", col_logical),
                data_type=col_raw.get("type", ""),
                note=col_raw.get("note", ""),
            )
        tables[logical_name] = TableMapping(
            logical=logical_name,
            physical_name=table_raw.get("physical_name"),
            description=table_raw.get("description", ""),
            columns=columns,
            custom_join=table_raw.get("custom_join"),
        )

    return CustomerConfig(
        name=customer_raw.get("name", "未命名客户"),
        database_type=customer_raw.get("database_type", "postgresql"),
        database_url=customer_raw.get("database_url", ""),
        tables=tables,
        features={
            "supports_window_functions": features_raw.get("supports_window_functions", True),
            "date_function": features_raw.get("date_function", "NOW()"),
            "interval_syntax": features_raw.get("interval_syntax", "INTERVAL '30 days'"),
            "quote_char": features_raw.get("quote_char", '"'),
        },
    )


# ============================================================================
# 全局配置（启动时加载）
# ============================================================================

_customer_config: Optional[CustomerConfig] = None


def set_customer_config(config: CustomerConfig) -> None:
    """设置当前客户配置（应用启动时调用）。"""
    global _customer_config
    _customer_config = config


def get_customer_config() -> CustomerConfig:
    """获取当前客户配置。

    如果客户配置尚未加载，返回默认配置（使用系统内置表名）。
    """
    global _customer_config
    if _customer_config is not None:
        return _customer_config
    return _default_config()


def _default_config() -> CustomerConfig:
    """返回默认配置——直接使用系统内置表名和列名（零映射）。"""
    tables = {}
    for logical_name in ["orders", "store", "member", "employee_performance",
                          "product", "supplier", "inventory", "purchase_order"]:
        tables[logical_name] = TableMapping(
            logical=logical_name,
            physical_name=logical_name,
            description=f"（默认配置）{logical_name} 表",
        )
    return CustomerConfig(
        name="默认（开发环境）",
        database_type="postgresql",
        tables=tables,
    )
