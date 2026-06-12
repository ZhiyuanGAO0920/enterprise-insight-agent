"""库存分析 Agent — V3 P3 扩展。

负责：
  - 库存周转率分析（按品类/门店/商品）
  - 滞销商品预警（库存过高 + 长期未补货）
  - 缺货风险预警（库存低于安全库存）
  - 补货建议（结合日均销量和供货周期）
  - 品类库存健康度评分

导出：
  - inventory_agent_node: LangGraph 节点函数（用于图谱集成）
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
from prompts.inventory_prompt import INVENTORY_SYSTEM_PROMPT

logger = logging.getLogger("eia.agent.inventory")

# ---------------------------------------------------------------------------
# LLM 实例
# ---------------------------------------------------------------------------

llm = create_llm()


# ---------------------------------------------------------------------------
# LangGraph 节点
# ---------------------------------------------------------------------------


async def inventory_agent_node(state: AnalysisState) -> dict:
    """LangGraph 节点：执行库存 Agent 分析。

    根据 state.store_ids 注入行级门店访问过滤。
    返回包含 inventory_result 和可选的 agent_errors 的部分状态字典。
    永不抛出异常 —— 失败会被捕获到 agent_errors 中。
    """
    if state.get("activated_agents") and "inventory" not in state["activated_agents"]:
        return {"inventory_result": None}

    t_start = time.monotonic()
    logger.info("开始执行 - question: %s...", state.get("question", "")[:80])
    writer = get_stream_writer()
    writer({"type": "progress", "node": "inventory_agent", "message": "正在查询库存数据..."})

    store_ids = state.get("store_ids")

    @tool
    async def run_sql(query: str) -> str:
        """Execute a SQL SELECT query and return the results as a formatted table."""
        return await run_sql_impl(query, store_ids=store_ids)

    @tool
    async def get_table_schema(table_name: str = "") -> str:
        """Get database table structure. Pass a table name for column details, or omit for all tables."""
        return await get_schema_impl(table_name if table_name else None)

    TOOLS = [run_sql, get_table_schema]
    inv_agent = llm.bind_tools(TOOLS)

    loader = get_prompt_loader()
    system_prompt = loader.get_prompt("inventory", "system_prompt", fallback=INVENTORY_SYSTEM_PROMPT)
    from app.tools.prompt_loader import resolve_agent_prompt
    system_prompt = resolve_agent_prompt("inventory", system_prompt)
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
        similar_sqls = await search_similar_sql(state["question"], agent="inventory", top_k=3)
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
            response = await inv_agent.ainvoke(messages)
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
                        "agent": "inventory",
                        "sql": tc["args"].get("query", ""),
                        "execution_time_ms": elapsed_ms,
                        "row_count": row_count,
                        "raw_data": str(result)[:3000],
                    })
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        # 如果工具调用循环耗尽且 LLM 最后仍在请求工具，强制生成最终文本
        if response.tool_calls:
            messages.append(HumanMessage(content="请基于以上所有查询结果，整合并输出你的最终分析结论。"))
            response = await inv_agent.ainvoke(messages)
        elapsed = time.monotonic() - t_start
        logger.info("执行完成 (%.1fs) - data_sources: %d", elapsed, len(data_sources))
        return {"inventory_result": response.content, "data_sources": data_sources}
    except Exception as e:
        elapsed = time.monotonic() - t_start
        logger.error("执行失败 (%.1fs): %s", elapsed, e)
        return {
            "inventory_result": None,
            "agent_errors": [{"agent": "inventory", "error": str(e)}],
            "data_sources": data_sources,
        }
