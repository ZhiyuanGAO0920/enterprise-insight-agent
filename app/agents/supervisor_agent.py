"""主管 / 任务规划 Agent。

根据用户问题决定激活哪些领域 Agent。
使用基于关键词的路由加上结构化 LLM 输出作为主要决策机制，
并带有保守的兜底策略（激活所有 Agent）。

替代 Phase 5 中的 planner_stub。
"""

import json

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


import re

from langchain_core.messages import HumanMessage, SystemMessage
from app.tools.stream_utils import safe_get_stream_writer as get_stream_writer

from app.llm import create_llm
from app.logging_config import bind_context, get_logger
from app.tools.prompt_loader import get_prompt_loader
from app.workflow.state import AnalysisState
from prompts.supervisor_prompt import SUPERVISOR_HUMAN_TEMPLATE, SUPERVISOR_SYSTEM_PROMPT

logger = get_logger("eia.agent.supervisor")

# ---------------------------------------------------------------------------
# 路由决策的结构化输出 schema
# ---------------------------------------------------------------------------

SUPERVISOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "supervisor_decision",
        "description": "Output which agents to activate for this analysis",
        "parameters": {
            "type": "object",
            "properties": {
                "activated_agents": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["sales", "crm", "finance", "inventory", "supply_chain"]},
                    "minItems": 1,
                    "description": "List of agent keys to activate",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Why these agents were selected",
                },
                "analysis_plan": {
                    "type": "string",
                    "description": "Brief plan for the analysis",
                },
            },
            "required": ["activated_agents", "reasoning", "analysis_plan"],
        },
    },
}

# ---------------------------------------------------------------------------
# LLM（temperature=0 以确保路由决策确定性）
# ---------------------------------------------------------------------------

llm = create_llm(temperature=0.0)


# ---------------------------------------------------------------------------
# LangGraph 节点
# ---------------------------------------------------------------------------


async def supervisor_agent_node(state: AnalysisState) -> dict:
    """LangGraph 节点：决定激活哪些 Agent。

    V3：注入 conversation_context 以支持多轮对话连贯性。
    成功时返回 activated_agents 列表和 supervisor_plan JSON。
    失败时兜底激活所有 Agent（保守/安全策略）。
    """
    # V4：绑定 Agent 上下文到日志
    bind_context(
        trace_id=state.get("trace_id", ""),
        session_id=state.get("session_id", ""),
        user_id=state.get("user_id"),
        agent_name="supervisor",
    )
    logger.info("开始执行", question=state.get("question", "")[:80])
    writer = get_stream_writer()
    writer({"type": "progress", "node": "supervisor", "message": "正在规划任务..."})
    try:
        llm_with_schema = llm.bind_tools([SUPERVISOR_SCHEMA])

        # V3：如果有对话上下文则注入
        loader = get_prompt_loader()
        system_prompt = loader.get_prompt("supervisor", "system_prompt", fallback=SUPERVISOR_SYSTEM_PROMPT)
        context = state.get("conversation_context", "")
        if context:
            system_prompt = context + "\n\n---\n\n" + system_prompt

        human_template = loader.get_prompt("supervisor", "human_template", fallback=SUPERVISOR_HUMAN_TEMPLATE)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_template.format(question=state.get("question", ""))),
        ]

        response = await llm_with_schema.ainvoke(messages)

        if response.tool_calls:
            args = response.tool_calls[0]["args"]
        else:
            # 兜底：思考模型可能不调工具，尝试从文本提取 JSON
            _text = (response.content or "")
            # 用括号计数法提取 JSON（支持嵌套 {}，避免 [^}]* 遇到嵌套 } 断裂）
            _parsed_json = _extract_json(_text)
            if _parsed_json:
                try:
                    _parsed = _parsed_json
                    args = {
                        "activated_agents": _parsed.get("activated_agents", ["sales", "crm", "finance", "inventory", "supply_chain"]),
                        "reasoning": _parsed.get("reasoning", "Extracted from text"),
                        "analysis_plan": _parsed.get("analysis_plan", ""),
                    }
                except Exception:
                    args = {"activated_agents": ["sales", "crm", "finance", "inventory", "supply_chain"], "reasoning": "Fallback (JSON parse error)", "analysis_plan": "Activate all agents"}
            else:
                args = {
                    "activated_agents": ["sales", "crm", "finance", "inventory", "supply_chain"],
                    "reasoning": "Fallback (no structured output)",
                    "analysis_plan": "Activate all agents",
                }

        # V4 流式进度：告知前端激活了哪些 Agent
        agent_names = {
            "sales": "销售 Agent（趋势 / 排名 / 品类）",
            "crm": "CRM Agent（会员活跃 / 流失 / 复购）",
            "finance": "财务 Agent（退款 / 客单价 / 利润）",
            "inventory": "库存 Agent（周转 / 缺货 / 滞销）",
            "supply_chain": "供应链 Agent（供应商 / 采购成本）",
        }
        activated_list = args["activated_agents"]
        for agent_key in activated_list:
            desc = agent_names.get(agent_key, agent_key)
            writer({"type": "progress", "node": "supervisor",
                    "message": f"→ 激活 {desc}"})

        return {
            "activated_agents": args["activated_agents"],
            "supervisor_plan": json.dumps(args, ensure_ascii=False),
        }

    except Exception as e:
        # 保守兜底策略：激活所有 Agent
        logger.error("执行失败，激活全部 Agent 兜底", error=str(e))
        return {
            "activated_agents": ["sales", "crm", "finance", "inventory", "supply_chain"],
            "agent_errors": [{"agent": "supervisor", "error": str(e)}],
        }
