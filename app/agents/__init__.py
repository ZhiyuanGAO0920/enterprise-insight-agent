"""Agents 包。

每个模块导出：
  - 一个绑定了工具的 LLM 实例（用于独立使用）
  - 一个 LangGraph 节点函数（异步，接收 AnalysisState → 返回部分字典）
"""

from app.agents.chart_advisor_agent import chart_advisor_node
from app.agents.crm_agent import crm_agent_node
from app.agents.finance_agent import finance_agent_node
from app.agents.memory_node import save_memory_node
from app.agents.reflection_agent import reflection_agent_node
from app.agents.report_agent import report_agent_node
from app.agents.sales_agent import sales_agent_node
from app.agents.supervisor_agent import supervisor_agent_node

__all__ = [
    "chart_advisor_node",
    "sales_agent_node",
    "crm_agent_node",
    "finance_agent_node",
    "report_agent_node",
    "reflection_agent_node",
    "supervisor_agent_node",
    "save_memory_node",
]
