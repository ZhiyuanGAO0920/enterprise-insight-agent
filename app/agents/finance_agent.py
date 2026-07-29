"""财务分析 Agent。

负责：
  - 退款率趋势和异常
  - 客单价分布和变化
  - 利润分析
  - 成本结构

使用 BaseAgent 工厂创建。
"""
from app.agents.base import create_agent_node
from prompts.finance_prompt import FINANCE_SYSTEM_PROMPT

finance_agent_node = create_agent_node(
    agent_name="finance",
    result_field="finance_result",
    system_prompt=FINANCE_SYSTEM_PROMPT,
    prompt_key="finance",
    progress_message="正在查询财务数据...",
)
