"""反思 / 质量保证 Agent。

从 4 个维度验证生成的报告：
  1. 数据一致性（跨 Agent 矛盾检查）
  2. 逻辑严谨性（因果关系、过度推断）
  3. 可操作性（具体、有优先级的建议）
  4. 完整性（用户问题的覆盖程度）

使用 bind_tools 生成结构化输出，
供图谱进行条件路由判断。思考模型不支持强制 tool_choice，
有兜底：未返回工具调用时视为通过。
"""

import json
from app.logging_config import get_logger
import time

from langchain_core.messages import HumanMessage, SystemMessage
from app.tools.stream_utils import safe_get_stream_writer as get_stream_writer

from app.llm import create_llm
from app.tools.prompt_loader import get_prompt_loader
from app.workflow.state import AnalysisState
from prompts.reflection_prompt import REFLECTION_HUMAN_TEMPLATE, REFLECTION_SYSTEM_PROMPT

logger = get_logger("eia.agent.reflection")

# ---------------------------------------------------------------------------
# JSON 提取工具（括号计数法，支持嵌套 {}）
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> dict | None:
    """用括号计数从文本中提取最外层 JSON 对象，不受嵌套层级影响。"""
    stack = []
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if not stack:
                start = i
            stack.append(ch)
        elif ch == "}":
            if stack:
                stack.pop()
                if not stack and start >= 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        return None
    return None


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

    通过 bind_tools 引导结构化输出（思考模型不支持 tool_choice，
    有兜底：未返回工具调用时视为通过）。
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
        llm_with_schema = llm.bind_tools([REFLECTION_SCHEMA])

        loader = get_prompt_loader()
        # 截断报告和聚合摘要，防止过大导致 LLM 调用超时
        # V4.2: 提高限值适配更长报告（含图表标签和详细洞察）
        MAX_REPORT_CHARS = 18000
        MAX_SUMMARY_CHARS = 8000
        if len(report) > MAX_REPORT_CHARS:
            tail_len = int(MAX_REPORT_CHARS * 0.25)
            truncated_report = report[:MAX_REPORT_CHARS - tail_len] + f"\n\n>（报告中间部分已截断）\n\n" + report[-tail_len:]
        else:
            truncated_report = report
        truncated_summary = (state.get("aggregator_summary") or "(no raw data)")[:MAX_SUMMARY_CHARS]
        messages = [
            SystemMessage(content=loader.get_prompt("reflection", "system_prompt", fallback=REFLECTION_SYSTEM_PROMPT)),
            HumanMessage(
                content=loader.get_prompt("reflection", "human_template", fallback=REFLECTION_HUMAN_TEMPLATE).format(
                    question=state["question"],
                    aggregator_summary=truncated_summary,
                    report=truncated_report,
                )
            ),
        ]

        response = await llm_with_schema.ainvoke(messages)

        # 解析工具调用中的结构化输出
        if response.tool_calls:
            args = response.tool_calls[0]["args"]
        else:
            # 兜底：思考模型可能不调工具，从文本中提取 JSON
            _text = response.content or ""
            # 用括号计数法提取 JSON（支持嵌套 {}，[^}]* 正则遇到嵌套 } 会断裂）
            _parsed_json = _extract_json(_text)
            if _parsed_json is not None:
                try:
                    _parsed = _parsed_json
                    args = {
                        "passed": _parsed.get("passed", False),
                        "issues": _parsed.get("issues", []),
                        "summary": _parsed.get("summary", "") or "Extracted from text",
                    }
                except Exception:
                    args = {"passed": False, "issues": [{"severity":"high","category":"completeness","description":"Reflection response could not be parsed"}], "summary":"Parse error"}
            else:
                # 完全无结构化输出时，不放过（而非硬编码 passed=True）
                args = {"passed": False, "issues": [{"severity":"high","category":"completeness","description":"Reflection did not return structured result"}], "summary":"No structured output"}

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
