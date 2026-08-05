"""LangGraph 执行图谱 —— 编排中枢。

V3 图谱拓扑：
  supervisor → [sales_agent ‖ crm_agent ‖ finance_agent] → aggregator
    → chart_advisor → report_agent → reflection_agent ⇄ report_agent（最多1次重试）
    → save_memory → END
"""

from langgraph.graph import END, StateGraph
from langgraph.config import get_stream_writer
from langgraph.types import Send

from app.agents.chart_advisor_agent import chart_advisor_node
from app.agents.crm_agent import crm_agent_node
from app.agents.finance_agent import finance_agent_node
from app.agents.inventory_agent import inventory_agent_node
from app.agents.memory_node import save_memory_node
from app.agents.reflection_agent import reflection_agent_node
from app.agents.report_agent import report_agent_node
from app.agents.sales_agent import sales_agent_node
from app.agents.supervisor_agent import supervisor_agent_node
from app.agents.supply_chain_agent import supply_chain_agent_node
from app.apm.tracer import trace_node
from app.workflow.state import AnalysisState
from app.logging_config import get_logger

logger = get_logger("eia.workflow.graph")


# ============================================================================
# 节点
# ============================================================================


async def aggregate_node(state: AnalysisState) -> dict:
    """将所有已执行 Agent 的结果聚合为单个摘要。

    仅包含实际产生了输出的 Agent（非 None）。
    V4.1：限制总长度防止下游 LLM 调用超时。
    使用头尾保留策略而非简单截断，避免丢失末尾关键结论。
    """
    writer = get_stream_writer()
    writer({"type": "progress", "node": "aggregator", "message": "正在聚合分析结果..."})
    sections: list[str] = []

    if state.get("sales_result"):
        sections.append(f"【销售分析】\n{state['sales_result']}")
    if state.get("crm_result"):
        sections.append(f"【CRM分析】\n{state['crm_result']}")
    if state.get("finance_result"):
        sections.append(f"【财务分析】\n{state['finance_result']}")
    if state.get("inventory_result"):
        sections.append(f"【库存分析】\n{state['inventory_result']}")
    if state.get("supply_chain_result"):
        sections.append(f"【供应链分析】\n{state['supply_chain_result']}")

    if not sections:
        return {"aggregator_summary": None}

    summary = "\n\n---\n\n".join(sections)

    # V4.1: 限制聚合摘要总长度，防止大量原始数据导致下游 LLM 超时
    # 使用头尾保留策略：前 70% + 后 30%，中间截断。
    # 这样开头（分析框架）和末尾（关键发现/总结）都不会缺失。
    MAX_SUMMARY_CHARS = 15000
    if len(summary) > MAX_SUMMARY_CHARS:
        tail_ratio = 0.3
        head_len = int(MAX_SUMMARY_CHARS * (1 - tail_ratio))
        tail_len = int(MAX_SUMMARY_CHARS * tail_ratio)
        head_part = summary[:head_len]
        tail_part = summary[-tail_len:]
        logger.info("聚合摘要过长，头尾保留截断: %d → %d 字符", len(summary), MAX_SUMMARY_CHARS)
        summary = head_part + f"\n\n>（中间数据已截断，完整数据见报告数据来源）\n\n" + tail_part

    return {"aggregator_summary": summary}


# ============================================================================
# 路由函数
# ============================================================================


def route_to_agents(state: AnalysisState) -> list[Send]:
    """根据 Supervisor 的 activated_agents 分发到并行 Agent。

    使用 LangGraph Send 创建独立的执行分支。
    每个分支接收自己的状态副本并在聚合器处汇合。
    """
    activated = state.get("activated_agents", ["sales", "crm", "finance", "inventory", "supply_chain"])
    sends: list[Send] = []

    if "sales" in activated:
        sends.append(Send("sales_agent", state))
    if "crm" in activated:
        sends.append(Send("crm_agent", state))
    if "finance" in activated:
        sends.append(Send("finance_agent", state))
    if "inventory" in activated:
        sends.append(Send("inventory_agent", state))
    if "supply_chain" in activated:
        sends.append(Send("supply_chain_agent", state))

    if not sends:
        sends.append(Send("aggregator", state))

    return sends


def after_aggregation(state: AnalysisState) -> str:
    """从聚合器路由：如果有数据，前往 chart_advisor；否则结束。

    V4 修复：当所有 Agent 失败导致 aggregator_summary 为空时，
    仍路由到 report_agent 以生成错误说明报告（而非静默跳到 END）。
    V4.5: simple 查询型问题跳过 chart_advisor（省一次 LLM 调用）。
    """
    if state.get("aggregator_summary"):
        if state.get("query_type") == "simple":
            return "report_agent"  # 简单查询不需要图表
        return "chart_advisor"
    # V4: 优雅降级 —— 有错误时让 report_agent 生成 fallback 报告
    if state.get("agent_errors"):
        return "chart_advisor"  # chart_advisor 会直接通过 → report_agent 生成错误报告
    return END


def after_reflection(state: AnalysisState) -> str:
    """从反思路由：通过 → 保存记忆 → END，失败且尚有重试次数 → 重试报告，否则 → END。"""
    if state.get("reflection_passed"):
        return "save_memory"

    retries = state.get("reflection_retries", 0)
    if retries < 2:
        return "report_agent"  # 重试一次（首次失败时 retries=1，因此 <2 允许重试）

    # 重试次数耗尽 —— 保存现有结果并结束
    return "save_memory"


def after_report(state: AnalysisState) -> str:
    """从报告路由：如果有输出，前往反思；否则跳到记忆。
    V4.5: simple 查询型问题跳过 reflection（省一次 LLM 调用）。
    V4.6.3: skip_reflection（对照实验）同样直接保存，不进入质检与重试。
    """
    if state.get("report"):
        if state.get("skip_reflection") or state.get("query_type") == "simple":
            return "save_memory"
        return "reflection_agent"
    return "save_memory"


# ============================================================================
# 图谱构建
# ============================================================================


def build_graph() -> StateGraph:
    """构建完整的 LangGraph StateGraph。

    Returns:
        编译后的 LangGraph 图谱，可用于 .ainvoke() 或 .astream()。
    """
    builder = StateGraph(AnalysisState)

    # ---- 注册所有节点（以 trace_node 包裹，自动记录 APM 追踪） ----
    builder.add_node("supervisor", trace_node("supervisor")(supervisor_agent_node))
    builder.add_node("sales_agent", trace_node("sales_agent")(sales_agent_node))
    builder.add_node("crm_agent", trace_node("crm_agent")(crm_agent_node))
    builder.add_node("finance_agent", trace_node("finance_agent")(finance_agent_node))
    builder.add_node("inventory_agent", trace_node("inventory_agent")(inventory_agent_node))       # V3 P3: 库存分析
    builder.add_node("supply_chain_agent", trace_node("supply_chain_agent")(supply_chain_agent_node)) # V3 P3: 供应链分析
    builder.add_node("aggregator", trace_node("aggregator")(aggregate_node))
    builder.add_node("chart_advisor", trace_node("chart_advisor")(chart_advisor_node))        # V3：图表推荐
    builder.add_node("report_agent", trace_node("report_agent")(report_agent_node))
    builder.add_node("reflection_agent", trace_node("reflection_agent")(reflection_agent_node))
    builder.add_node("save_memory", trace_node("save_memory")(save_memory_node))

    # ---- 入口点 ----
    builder.set_entry_point("supervisor")

    # ---- Supervisor → 并行 Agent（扇出） ----
    builder.add_conditional_edges(
        "supervisor",
        route_to_agents,
        ["sales_agent", "crm_agent", "finance_agent", "inventory_agent", "supply_chain_agent", "aggregator"],
    )

    # ---- 各 Agent → 聚合器（扇入） ----
    builder.add_edge("sales_agent", "aggregator")
    builder.add_edge("crm_agent", "aggregator")
    builder.add_edge("finance_agent", "aggregator")
    builder.add_edge("inventory_agent", "aggregator")
    builder.add_edge("supply_chain_agent", "aggregator")

    # ---- 聚合器 → 图表顾问 → 报告 Agent（V3 管线） ----
    builder.add_conditional_edges("aggregator", after_aggregation, {"chart_advisor": "chart_advisor", "report_agent": "report_agent", END: END})
    builder.add_edge("chart_advisor", "report_agent")

    # ---- 报告 Agent → 反思 Agent（simple 查询直接保存） ----
    builder.add_conditional_edges(
        "report_agent",
        after_report,
        {"reflection_agent": "reflection_agent", "save_memory": "save_memory"},
    )

    # ---- 反思 Agent → 重试（报告）或保存 ----
    builder.add_conditional_edges(
        "reflection_agent",
        after_reflection,
        {"report_agent": "report_agent", "save_memory": "save_memory"},
    )

    # ---- 保存记忆 → END ----
    builder.add_edge("save_memory", END)

    return builder


# 编译后的图谱 —— 从 API 路由和测试中导入此实例
graph = build_graph().compile()
