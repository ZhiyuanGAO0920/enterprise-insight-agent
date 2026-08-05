"""核心 AnalysisState TypedDict —— 整个 LangGraph 的数据契约。

每个 Agent 都从此状态读取并写入。`agent_errors` 上的 `add` 归约器
确保并行分支合并其错误列表而非互相覆盖。
"""

from operator import add
from typing import Annotated, Optional

from typing_extensions import TypedDict


class AnalysisState(TypedDict):
    """流经所有 LangGraph 节点的共享状态。"""

    # ==== 输入 ====
    question: str
    original_question: Optional[str]       # V4.2: 原始用户问题（不含 ranking hint 注入），用于展示
    user_id: Optional[int]
    store_ids: Optional[list[str]]  # None=无限制, []=无门店, [...] = 允许的门店
    trace_id: Optional[str]         # V4: 全链路追踪 ID

    # ==== 各 Agent 结果 ====
    sales_result: Optional[str]
    crm_result: Optional[str]
    finance_result: Optional[str]
    inventory_result: Optional[str]       # V3 P3: 库存分析
    supply_chain_result: Optional[str]    # V3 P3: 供应链分析

    # ==== 错误追踪 ====
    # `add` 归约器将并行分支的错误合并
    agent_errors: Annotated[list[dict], add]

    # ==== 聚合 ====
    aggregator_summary: Optional[str]

    # ==== 报告 ====
    report: Optional[str]

    # ==== 反思 ====
    reflection_passed: Optional[bool]
    reflection_feedback: Optional[str]
    reflection_retries: int  # 硬上限以防止无限循环
    skip_reflection: Optional[bool]  # V4.6.3: 对照实验用——跳过质检与重试（生产勿开启）

    # ==== Supervisor 路由 ====
    supervisor_plan: Optional[str]
    activated_agents: Optional[list[str]]
    query_type: Optional[str]  # V4.5: simple=数据查询型，comprehensive=综合分析型

    # ==== 最终输出 ====
    # V4: final_report 已移除 —— 无任何节点写入，report 字段已覆盖所有使用场景

    # ==== 记忆 ====
    memory_record_id: Optional[int]

    # =========================================================================
    # V3: 数据可追溯性 (P0-3)
    # =========================================================================
    # 每条记录：{id, claim, agent, sql, execution_time_ms, row_count, raw_data}
    # `add` 归约器合并来自并行 Agent 的数据来源
    data_sources: Annotated[list[dict], add]

    # =========================================================================
    # V3: 图表建议 (P0-1) —— Chart Advisor 输出
    # =========================================================================
    chart_suggestions: Optional[list[dict]]

    # =========================================================================
    # V3: 多轮对话 (P0-2)
    # =========================================================================
    session_id: Optional[str]
    conversation_context: Optional[str]
    followup_questions: Optional[list[str]]
    is_followup: bool
    resolved_question: Optional[str]
