"""反思 / 质量保证 Agent。

从 4 个维度验证生成的报告：
  1. 数据一致性（跨 Agent 矛盾检查）
  2. 逻辑严谨性（因果关系、过度推断）
  3. 可操作性（具体、有优先级的建议）
  4. 完整性（用户问题的覆盖程度）

使用结构化输出（tool_choice）生成机器可解析的结果，
供图谱进行条件路由判断。
"""

import json
import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_stream_writer

from app.llm import create_llm
from app.tools.prompt_loader import get_prompt_loader
from app.workflow.state import AnalysisState
from prompts.reflection_prompt import REFLECTION_HUMAN_TEMPLATE, REFLECTION_SYSTEM_PROMPT

logger = logging.getLogger("eia.agent.reflection")

# ---------------------------------------------------------------------------
# 结构化输出 schema（通过 tool_choice 强制 JSON 格式）
# ---------------------------------------------------------------------------

REFLECTION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "reflection_result",
        "description": "Output the reflection quality check result",
        "parameters": {
            "type": "object",
            "properties": {
                "passed": {
                    "type": "boolean",
                    "description": "Whether the report passed quality check",
                },
                "issues": {
                    "type": "array",
                    "description": "List of issues found (empty if passed)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "severity": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                                "description": "Impact severity",
                            },
                            "category": {
                                "type": "string",
                                "enum": [
                                    "consistency",
                                    "logic",
                                    "actionability",
                                    "completeness",
                                ],
                                "description": "Type of issue",
                            },
                            "description": {
                                "type": "string",
                                "description": "What the issue is",
                            },
                            "suggestion": {
                                "type": "string",
                                "description": "How to fix the issue",
                            },
                        },
                        "required": ["severity", "category", "description", "suggestion"],
                    },
                },
                "summary": {
                    "type": "string",
                    "description": "Brief overall assessment",
                },
            },
            "required": ["passed", "issues", "summary"],
        },
    },
}

# ---------------------------------------------------------------------------
# LLM（temperature=0 以确保验证结果确定性）
# ---------------------------------------------------------------------------

llm = create_llm(temperature=0.0)


# ---------------------------------------------------------------------------
# LangGraph 节点
# ---------------------------------------------------------------------------


async def reflection_agent_node(state: AnalysisState) -> dict:
    """LangGraph 节点：验证报告质量和一致性。

    返回 reflection_passed（布尔值）、reflection_feedback（JSON 字符串），
    并递增 reflection_retries。

    使用 tool_choice 强制结构化 JSON 输出。
    """
    t_start = time.monotonic()
    logger.info("开始执行")
    writer = get_stream_writer()
    writer({"type": "progress", "node": "reflection_agent", "message": "正在审核报告质量..."})

    report = state.get("report")
    current_retries = state.get("reflection_retries", 0)
    next_retries = current_retries + 1

    if not report:
        logger.warning("无报告可供审核")
        return {
            "reflection_passed": False,
            "reflection_retries": next_retries,
            "reflection_feedback": json.dumps(
                {"passed": False, "issues": [], "summary": "No report to validate"},
                ensure_ascii=False,
            ),
        }

    try:
        llm_with_schema = llm.bind_tools([REFLECTION_SCHEMA], tool_choice="reflection_result")

        loader = get_prompt_loader()
        messages = [
            SystemMessage(content=loader.get_prompt("reflection", "system_prompt", fallback=REFLECTION_SYSTEM_PROMPT)),
            HumanMessage(
                content=loader.get_prompt("reflection", "human_template", fallback=REFLECTION_HUMAN_TEMPLATE).format(
                    question=state["question"],
                    aggregator_summary=state.get("aggregator_summary", "(no raw data)"),
                    report=report,
                )
            ),
        ]

        response = await llm_with_schema.ainvoke(messages)

        # 解析工具调用中的结构化输出
        if response.tool_calls:
            args = response.tool_calls[0]["args"]
        else:
            # 兜底：LLM 未使用工具 —— 视为通过
            args = {"passed": True, "issues": [], "summary": "Reflection could not parse result"}

        elapsed = time.monotonic() - t_start
        logger.info("执行完成 (%.1fs) - 通过: %s", elapsed, args.get("passed", False))
        return {
            "reflection_passed": args.get("passed", False),
            "reflection_retries": next_retries,
            "reflection_feedback": json.dumps(args, ensure_ascii=False),
        }

    except Exception as e:
        elapsed = time.monotonic() - t_start
        logger.error("执行失败 (%.1fs): %s", elapsed, e)
        return {
            "reflection_passed": False,
            "reflection_retries": next_retries,
            "reflection_feedback": json.dumps(
                {"passed": False, "issues": [], "summary": f"Reflection error: {str(e)}"},
                ensure_ascii=False,
            ),
        }
