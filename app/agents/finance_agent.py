"""财务分析 Agent。

负责：
  - 平均单价及趋势
  - 退款率（总体、按品类、按原因）
  - 利润率（毛利/净利、按品类/门店）
  - 成本分析（采购、运营、人工）
  - 现金流分析
  - 应收账款分析

导出：
  - finance_agent: 绑定了工具的 LLM（用于独立使用）
  - finance_agent_node: LangGraph 节点函数（用于图谱集成）
"""

import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.config import get_settings
from app.llm import create_llm
from app.tools.prompt_loader import get_prompt_loader
from app.tools.schema_provider import get_table_schema as get_schema_impl
from app.tools.sql_runner import run_sql as run_sql_impl
from app.workflow.state import AnalysisState
from prompts.finance_prompt import FINANCE_SYSTEM_PROMPT

logger = logging.getLogger("eia.agent.finance")


# ---------------------------------------------------------------------------
# LLM 实例
# ---------------------------------------------------------------------------

llm = create_llm()


# ---------------------------------------------------------------------------
# LangGraph 节点
# ---------------------------------------------------------------------------


async def finance_agent_node(state: AnalysisState) -> dict:
    """LangGraph 节点：执行财务 Agent 分析。

    根据 state.store_ids 注入行级门店访问过滤。
    返回包含 finance_result 和可选的 agent_errors 的部分状态字典。
    永不抛出异常 —— 失败会被捕获到 agent_errors 中。
    """
    if state.get("activated_agents") and "finance" not in state["activated_agents"]:
        return {"finance_result": None}

    t_start = time.monotonic()
    logger.info("开始执行 - question: %s...", state.get("question", "")[:80])
    writer = get_stream_writer()
    writer({"type": "progress", "node": "finance_agent", "message": "正在查询财务数据..."})

    store_ids = state.get("store_ids")

    # 构建支持行级安全的工具（闭包捕获 store_ids）
    @tool
    async def run_sql(query: str) -> str:
        """Execute a SQL SELECT query and return the results as a formatted table."""
        return await run_sql_impl(query, store_ids=store_ids)

    @tool
    async def get_table_schema(table_name: str = "") -> str:
        """Get database table structure. Pass a table name for column details, or omit for all tables."""
        return await get_schema_impl(table_name if table_name else None)

    TOOLS = [run_sql, get_table_schema]
    finance_agent = llm.bind_tools(TOOLS)

    # 构建包含门店上下文的系统提示词
    loader = get_prompt_loader()
    system_prompt = loader.get_prompt("finance", "system_prompt", fallback=FINANCE_SYSTEM_PROMPT)
    from app.tools.prompt_loader import resolve_agent_prompt
    system_prompt = resolve_agent_prompt("finance", system_prompt)
    if store_ids is not None:
        if store_ids:
            store_list = ", ".join(store_ids)
            system_prompt += f"\n\n## 数据权限限制\n你只能查询以下门店的数据，所有 SQL 查询必须包含门店过滤条件：store_id IN ({store_list})\n门店 ID 列表：{store_list}"
        else:
            system_prompt += "\n\n## 数据权限限制\n你的账号没有可访问的门店数据，所有查询都将返回空结果。"

    # V3：为追问问题注入多轮对话上下文
    context = state.get("conversation_context", "")
    is_followup = state.get("is_followup", False)
    if context and is_followup:
        system_prompt = context + "\n\n---\n\n" + system_prompt

    # V3 RAG 增强：检索历史上相似问题的已验证 SQL 作为 Few-shot 参考
    try:
        from app.tools.memory import search_similar_sql
        similar_sqls = await search_similar_sql(state["question"], agent="finance", top_k=3)
        if similar_sqls:
            rag_context = "\n\n## 参考：历史上类似问题的 SQL（已验证准确，可直接复用或参考）\n"
            for i, item in enumerate(similar_sqls, 1):
                rag_context += f"\n示例 {i}：\n  - 历史问题：{item['question'][:120]}\n  - 参考SQL：{item['sql']}\n"
            system_prompt = rag_context + system_prompt
    except Exception:
        pass  # RAG 检索失败不影响主流程

    settings = get_settings()
    data_sources: list[dict] = []

    try:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=state["question"]),
        ]
        for _ in range(5):
            response = await finance_agent.ainvoke(messages)
            messages.append(response)
            if not response.tool_calls:
                break
            for tc in response.tool_calls:
                tool_fn = {t.name: t for t in TOOLS}[tc["name"]]
                t0 = time.monotonic()
                result = await tool_fn.ainvoke(tc["args"])
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                if tc["name"] == "run_sql" and settings.feature_data_trace:
                    sql_lines = str(result).split("\n")
                    row_count = sum(1 for l in sql_lines if " | " in l and not l.startswith("-"))
                    if row_count > 1:
                        row_count -= 1
                    data_sources.append({
                        "id": len(data_sources) + 1,
                        "agent": "finance",
                        "sql": tc["args"].get("query", ""),
                        "execution_time_ms": elapsed_ms,
                        "row_count": row_count,
                        "raw_data": str(result)[:3000],
                    })
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        # 如果工具调用循环耗尽且 LLM 最后仍在请求工具，强制生成最终文本
        if response.tool_calls:
            messages.append(HumanMessage(content="请基于以上所有查询结果，整合并输出你的最终分析结论。"))
            response = await finance_agent.ainvoke(messages)
        elapsed = time.monotonic() - t_start
        logger.info("执行完成 (%.1fs) - data_sources: %d", elapsed, len(data_sources))
        return {"finance_result": response.content, "data_sources": data_sources}
    except Exception as e:
        elapsed = time.monotonic() - t_start
        logger.error("执行失败 (%.1fs): %s", elapsed, e)
        return {
            "finance_result": None,
            "agent_errors": [{"agent": "finance", "error": str(e)}],
            "data_sources": data_sources,
        }
