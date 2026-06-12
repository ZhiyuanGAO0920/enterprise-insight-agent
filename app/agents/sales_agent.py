"""销售分析 Agent。

负责：
  - 销售趋势（日/周/月/季/年）
  - 区域销售分布
  - 门店级别排名和贡献度
  - 品类/品牌/SKU 分析

导出：
  - sales_agent: 绑定了销售工具的 LLM（用于独立使用）
  - sales_agent_node: LangGraph 节点函数（用于图谱集成）
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
from prompts.sales_prompt import SALES_SYSTEM_PROMPT

logger = logging.getLogger("eia.agent.sales")


# ---------------------------------------------------------------------------
# LLM 实例
# ---------------------------------------------------------------------------

llm = create_llm()


# ---------------------------------------------------------------------------
# LangGraph 节点
# ---------------------------------------------------------------------------


async def sales_agent_node(state: AnalysisState) -> dict:
    """LangGraph 节点：执行销售 Agent 分析。

    根据 state.store_ids 注入行级门店访问过滤。
    返回包含 sales_result 和可选的 agent_errors 的部分状态字典。
    永不抛出异常 —— 失败会被捕获到 agent_errors 中。
    """
    # Supervisor 路由守卫
    if state.get("activated_agents") and "sales" not in state["activated_agents"]:
        return {"sales_result": None}

    t_start = time.monotonic()
    logger.info("开始执行 - question: %s...", state.get("question", "")[:80])
    writer = get_stream_writer()
    writer({"type": "progress", "node": "sales_agent", "message": "正在查询销售数据..."})

    store_ids = state.get("store_ids")

    # 构建支持行级安全的工具（闭包捕获 store_ids）
    @tool
    async def run_sql(query: str) -> str:
        """Execute a SQL SELECT query and return the results as a formatted table.

        Args:
            query: A SQL SELECT statement to execute. Only SELECT queries are allowed.
        """
        return await run_sql_impl(query, store_ids=store_ids)

    @tool
    async def get_table_schema(table_name: str = "") -> str:
        """Get database table structure. Pass a table name for column details, or omit for all tables.

        Args:
            table_name: Optional table name. If empty, lists all public tables.
        """
        return await get_schema_impl(table_name if table_name else None)

    TOOLS = [run_sql, get_table_schema]
    sales_ = llm.bind_tools(TOOLS)

    # 构建包含门店上下文的系统提示词
    loader = get_prompt_loader()
    system_prompt = loader.get_prompt("sales", "system_prompt", fallback=SALES_SYSTEM_PROMPT)
    # 客户适配：如果 customer_schema.yaml 已配置，自动替换为适配后的 Prompt
    from app.tools.prompt_loader import resolve_agent_prompt
    system_prompt = resolve_agent_prompt("sales", system_prompt)
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
        similar_sqls = await search_similar_sql(state["question"], agent="sales", top_k=3)
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
        sql_row_count = 0  # 跟踪 SQL 返回的行数
        # 工具调用循环：LLM 调用工具，我们执行并反馈结果
        for _ in range(5):  # 最多 5 轮工具调用
            response = await sales_.ainvoke(messages)
            messages.append(response)
            if not response.tool_calls:
                break  # LLM 给出了最终答案
            for tc in response.tool_calls:
                tool_fn = {t.name: t for t in TOOLS}[tc["name"]]
                t0 = time.monotonic()
                result = await tool_fn.ainvoke(tc["args"])
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                if tc["name"] == "run_sql":
                    # 统计 SQL 结果中的数据行数
                    sql_lines = str(result).split("\n")
                    sql_row_count = sum(1 for l in sql_lines if " | " in l and not l.startswith("-"))
                    if sql_row_count > 1:
                        sql_row_count -= 1  # 减去表头行
                    # V3：捕获数据来源以支持可追溯性
                    if settings.feature_data_trace:
                        data_sources.append({
                            "id": len(data_sources) + 1,
                            "agent": "sales",
                            "sql": tc["args"].get("query", ""),
                            "execution_time_ms": elapsed_ms,
                            "row_count": sql_row_count,
                            "raw_data": str(result)[:3000],  # 截断过长的结果
                        })
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
        # 如果工具调用循环耗尽且 LLM 最后仍在请求工具，强制生成最终文本
        if response.tool_calls:
            messages.append(HumanMessage(content="请基于以上所有查询结果，整合并输出你的最终分析结论。"))
            response = await sales_.ainvoke(messages)
        # 后处理：检测截断并强制 LLM 补全
        final = response.content
        if sql_row_count > 10:
            md_rows = sum(1 for l in final.split("\n") if l.strip().startswith("|") and "---" not in l)
            data_rows = max(0, md_rows - 1)  # 减去表头
            if data_rows < sql_row_count * 0.9:  # 缺失超过 10%
                force_msg = (
                    f"你只输出了 {data_rows} 行数据，但 SQL 返回了 {sql_row_count} 行。"
                    f"请立即补充剩余的全部 {sql_row_count - data_rows} 行。不要省略任何一行。"
                    f"用相同的表格格式继续输出，从第 {data_rows + 1} 行开始。"
                )
                messages.append(HumanMessage(content=force_msg))
                retry = await sales_.ainvoke(messages)
                if retry.content:
                    final = final + "\n" + retry.content

        elapsed = time.monotonic() - t_start
        logger.info("执行完成 (%.1fs) - SQL 行数: %s, data_sources: %d", elapsed, sql_row_count, len(data_sources))
        return {"sales_result": final, "data_sources": data_sources}
    except Exception as e:
        elapsed = time.monotonic() - t_start
        logger.error("执行失败 (%.1fs): %s", elapsed, e)
        return {
            "sales_result": None,
            "agent_errors": [{"agent": "sales", "error": str(e)}],
            "data_sources": data_sources,
        }
