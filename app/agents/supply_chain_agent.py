"""供应链分析 Agent — V3 P3 扩展。

负责：
  - 供应商准时交货率
  - 采购成本趋势
  - 供应商绩效评估
  - 供应链风险预警

使用 BaseAgent 工厂创建。
"""
from app.agents.base import create_agent_node
from prompts.supply_chain_prompt import SUPPLY_CHAIN_SYSTEM_PROMPT

supply_chain_agent_node = create_agent_node(
    agent_name="supply_chain",
    result_field="supply_chain_result",
    system_prompt=SUPPLY_CHAIN_SYSTEM_PROMPT,
    prompt_key="supply_chain",
    progress_message="正在查询供应链数据...",
)
