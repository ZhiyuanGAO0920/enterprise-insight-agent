"""销售分析 Agent。

负责：
  - 销售趋势（日/周/月/季/年）
  - 区域销售分布
  - 门店级别排名和贡献度
  - 品类/品牌/SKU 分析

使用 BaseAgent 工厂创建，消除与 CRM/财务/库存/供应链 Agent 的代码重复。
"""
from app.agents.base import create_agent_node
from prompts.sales_prompt import SALES_SYSTEM_PROMPT

sales_agent_node = create_agent_node(
    agent_name="sales",
    result_field="sales_result",
    system_prompt=SALES_SYSTEM_PROMPT,
    prompt_key="sales",
    progress_message="正在查询销售数据...",
    detect_truncation=True,
)
