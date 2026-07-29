"""库存分析 Agent — V3 P3 扩展。

负责：
  - 库存周转率
  - 缺货预警
  - 滞销商品识别
  - 安全库存水平

使用 BaseAgent 工厂创建。
"""
from app.agents.base import create_agent_node
from prompts.inventory_prompt import INVENTORY_SYSTEM_PROMPT

inventory_agent_node = create_agent_node(
    agent_name="inventory",
    result_field="inventory_result",
    system_prompt=INVENTORY_SYSTEM_PROMPT,
    prompt_key="inventory",
    progress_message="正在查询库存数据...",
)
