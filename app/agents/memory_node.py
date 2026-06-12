"""记忆持久化节点 —— 将完成的分析保存到长期记忆中。

这是图谱管线中的最后一个节点，负责持久化：
  - 用户的问题
  - 所有 Agent 的原始输出
  - 最终报告
  - 反思状态
  - 用于相似度搜索的 pgvector 嵌入向量
"""

import logging
import time

from langgraph.config import get_stream_writer

from app.tools.memory import save_analysis_history
from app.workflow.state import AnalysisState

logger = logging.getLogger("eia.agent.memory")


async def save_memory_node(state: AnalysisState) -> dict:
    """最终图谱节点：将分析结果持久化到数据库。

    将完整的分析管线输出保存到 analysis_history 表，
    包含用于未来相似度搜索的向量嵌入。
    """
    t_start = time.monotonic()
    logger.info("开始执行")
    writer = get_stream_writer()
    writer({"type": "progress", "node": "save_memory", "message": "正在保存分析记录..."})

    try:
        report = state.get("report", "")

        if not report:
            logger.info("无报告内容，跳过")
            return {"memory_record_id": None}

        record_id = await save_analysis_history(
            question=state["question"],
            report=report,
            sales_result=state.get("sales_result"),
            crm_result=state.get("crm_result"),
            finance_result=state.get("finance_result"),
            inventory_result=state.get("inventory_result"),
            supply_chain_result=state.get("supply_chain_result"),
            reflection_passed=state.get("reflection_passed", False),
            user_id=state.get("user_id"),
        )
        elapsed = time.monotonic() - t_start
        logger.info("执行完成 (%.1fs) - record_id: %s", elapsed, record_id)
        return {"memory_record_id": record_id}

    except Exception as e:
        elapsed = time.monotonic() - t_start
        logger.error("执行失败 (%.1fs): %s", elapsed, e)
        return {
            "agent_errors": [{"agent": "memory", "error": str(e)}],
        }
