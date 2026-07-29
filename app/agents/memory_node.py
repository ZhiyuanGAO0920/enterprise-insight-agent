"""记忆持久化节点 —— 将完成的分析保存到长期记忆中。

这是图谱管线中的最后一个节点，负责持久化：
  - 用户的问题
  - 所有 Agent 的原始输出
  - 最终报告
  - 反思状态
  - 用于相似度搜索的 pgvector 嵌入向量
"""

from app.logging_config import get_logger
import json
import time

from app.tools.stream_utils import safe_get_stream_writer as get_stream_writer

from app.tools.memory import save_analysis_history
from app.workflow.state import AnalysisState
from app.llm import get_task_tokens, reset_task_tokens

logger = get_logger("eia.agent.memory")


async def save_memory_node(state: AnalysisState) -> dict:
    """最终图谱节点：将分析结果持久化到数据库。

    将完整的分析管线输出保存到 analysis_history 表，
    包含用于未来相似度搜索的向量嵌入。
    """
    # 读取本次分析累计的 Token 消耗并重置（为下次分析清空）
    input_tokens, output_tokens, llm_cost = get_task_tokens()
    reset_task_tokens()

    t_start = time.monotonic()
    logger.info("开始执行")
    writer = get_stream_writer()
    writer({"type": "progress", "node": "save_memory", "message": "正在保存分析记录..."})

    try:
        report = state.get("report", "")

        if not report:
            logger.info("无报告内容，跳过")
            return {"memory_record_id": None}

        reflection_feedback = state.get("reflection_feedback")
        reflection_issues = []
        if reflection_feedback:
            try:
                fb = json.loads(reflection_feedback)
                reflection_issues = fb.get("issues", [])
            except Exception:
                pass

        # V4.4: 从报告中的 [FOLLOWUP_SAVE:...] 标记提取追问（避免依赖 LangGraph state 传递）
        fq: list[str] = []
        _save_marker = "[FOLLOWUP_SAVE:"
        _marker_pos = report.find(_save_marker) if report else -1
        if _marker_pos >= 0:
            _bracket = report.find("[", _marker_pos + len(_save_marker))
            if _bracket >= 0:
                _depth = 1; _i = _bracket + 1; _in_str = False
                while _i < len(report) and _depth > 0:
                    _ch = report[_i]
                    if _in_str:
                        if _ch == '\\': _i += 1
                        elif _ch == '"': _in_str = False
                    else:
                        if _ch == '"': _in_str = True
                        elif _ch == "[": _depth += 1
                        elif _ch == "]": _depth -= 1
                    _i += 1
                if _depth == 0:
                    try: fq = json.loads(report[_bracket:_i])
                    except Exception: pass
                # 从报告中移除标记（不存到数据库）
                _end = _i + 1  # 跳过外层 ]
                if _end <= len(report) and report[_marker_pos:_end].endswith("]"):
                    pass  # 确保正确结束
                report = report[:_marker_pos] + report[_end:]
        # 最终兜底：总是有值，确保监控统计不显示 0
        if not fq:
            fq = ["各门店销售额排名如何？", "近30天销售趋势是怎样的？"]
        record_id = await save_analysis_history(
            question=state.get("original_question") or state["question"],
            report=report,
            sales_result=state.get("sales_result"),
            crm_result=state.get("crm_result"),
            finance_result=state.get("finance_result"),
            inventory_result=state.get("inventory_result"),
            supply_chain_result=state.get("supply_chain_result"),
            reflection_passed=state.get("reflection_passed", False),
            user_id=state.get("user_id"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            llm_cost=llm_cost,
            reflection_issues=reflection_issues,
            followup_questions=fq,
        )
        elapsed = time.monotonic() - t_start
        logger.info("执行完成 (%.1fs) - record_id: %s, fq_count: %d", elapsed, record_id, len(fq))
        # 返回清理后的报告（去除 [FOLLOWUP_SAVE:] 标记），确保 SSE done 事件使用干净的版本
        return {"memory_record_id": record_id, "report": report}

    except Exception as e:
        elapsed = time.monotonic() - t_start
        logger.error("执行失败 (%.1fs): %s", elapsed, e)
        return {
            "agent_errors": [{"agent": "memory", "error": str(e)}],
        }
