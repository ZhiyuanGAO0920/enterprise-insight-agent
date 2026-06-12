"""图表顾问 Agent — V3 功能 (P0-1)。

根据聚合器摘要中的数据特征推荐图表类型。
插入 [CHART:...] 标记，前端将其渲染为 ECharts 可视化图表。

受 FEATURE_CHART 环境变量控制。禁用时透传不变。
"""

import json
import logging
import re
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_stream_writer

from app.config import get_settings
from app.llm import create_llm
from app.tools.prompt_loader import get_prompt_loader
from app.workflow.state import AnalysisState

logger = logging.getLogger("eia.agent.chart_advisor")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

CHART_ADVISOR_SYSTEM_PROMPT = """你是一位数据可视化顾问。
你的任务是根据分析数据，推荐合适的图表类型并输出图表配置。

## 图表类型选择规则
- bar（柱状图）：排名、对比类数据（如"各门店销售额排名"）
- line（折线图）：时间趋势类数据（如"近30天销售趋势"）
- pie（饼图）：占比、分布类数据（如"各区域销售额占比"）
- scatter（散点图）：两个数值维度的相关性（如"客单价 vs 退款率"）
- radar（雷达图）：多维度对比（如"华东 vs 华北 4维度对比"）

## 不需要图表的情况
- 纯文字分析，无数据表
- 数据行数 ≤ 3
- 用户明确只要文字结论

## 输出格式
请以 JSON 格式输出，每个图表一个对象：
{
  "charts": [
    {
      "type": "bar",
      "title": "各门店销售额排名（TOP 10）",
      "x_data": ["门店A", "门店B", ...],
      "series": [{"name": "销售额（万元）", "data": [120, 115, 108, ...]}],
      "height": 400,
      "note": "数据来源：销售分析 Agent"
    }
  ]
}

如果不需要图表，输出：{"charts": []}

注意：
- x_data 最多取 TOP 20 条（避免柱状图过密）
- 数值取整数或保留1位小数
- 不要输出 null 值"""

CHART_ADVISOR_HUMAN_TEMPLATE = """分析数据：
{aggregator_summary}

请判断是否需要生成图表，并输出图表配置 JSON。"""

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

llm = create_llm(temperature=0.0)


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------


async def chart_advisor_node(state: AnalysisState) -> dict:
    """分析数据并推荐图表可视化方案。

    当 FEATURE_CHART 被禁用时，返回空的建议列表（透传模式）。
    """
    t_start = time.monotonic()
    logger.info("开始执行")
    writer = get_stream_writer()
    writer({"type": "progress", "node": "chart_advisor", "message": "正在推荐图表..."})

    settings = get_settings()
    if not settings.feature_chart:
        logger.info("功能未启用，跳过")
        return {"chart_suggestions": []}

    summary = state.get("aggregator_summary")
    if not summary:
        logger.info("无聚合摘要数据，跳过")
        return {"chart_suggestions": []}

    try:
        loader = get_prompt_loader()
        messages = [
            SystemMessage(content=loader.get_prompt("chart_advisor", "system_prompt", fallback=CHART_ADVISOR_SYSTEM_PROMPT)),
            HumanMessage(content=loader.get_prompt("chart_advisor", "human_template", fallback=CHART_ADVISOR_HUMAN_TEMPLATE).format(aggregator_summary=summary)),
        ]
        response = await llm.ainvoke(messages)
        content = response.content.strip()

        # 从 LLM 响应中鲁棒提取 JSON（可能被 ```json 代码块包裹，可能有 trailing text）
        # 使用正则而非 split/endswith，避免代码块后额外文本导致的 JSONDecodeError
        code_match = re.search(r'```(?:json)?\s*\n?(.*?)```', content, re.DOTALL)
        if code_match:
            content = code_match.group(1).strip()
        # 如果未包裹在代码块中，尝试直接查找 JSON 对象
        elif not content.startswith("{"):
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                content = json_match.group(0)

        result = json.loads(content)
        charts = result.get("charts", [])
        elapsed = time.monotonic() - t_start
        logger.info("执行完成 (%.1fs) - 推荐图表: %d 个", elapsed, len(charts))
        return {"chart_suggestions": charts}

    except Exception as e:
        elapsed = time.monotonic() - t_start
        logger.warning("执行失败 (%.1fs)，返回空图表列表: %s", elapsed, e)
        # 图表生成失败不影响主流程 —— 返回空列表
        return {"chart_suggestions": []}
