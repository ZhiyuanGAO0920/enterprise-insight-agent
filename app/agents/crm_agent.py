"""CRM / 会员分析 Agent。

负责：
  - 会员增长率和渠道
  - 会员流失率和原因
  - 复购率（总体、按品类、按等级）
  - 活跃会员分层（RFM 模型）
  - 会员等级分布和迁移

使用 BaseAgent 工厂创建。
"""
from app.agents.base import create_agent_node
from prompts.crm_prompt import CRM_SYSTEM_PROMPT

crm_agent_node = create_agent_node(
    agent_name="crm",
    result_field="crm_result",
    system_prompt=CRM_SYSTEM_PROMPT,
    prompt_key="crm",
    progress_message="正在查询会员数据...",
)
