"""图表顾问 Agent — V3 功能 (P0-1)。

根据聚合器摘要中的数据特征推荐图表类型。
插入 [CHART:...] 标记，前端将其渲染为 ECharts 可视化图表。

受 FEATURE_CHART 环境变量控制。禁用时透传不变。
"""

import json
from app.logging_config import get_logger
import re
import time

from langchain_core.messages import HumanMessage, SystemMessage
from app.tools.stream_utils import safe_get_stream_writer as get_stream_writer

from app.config import get_settings
from app.llm import create_llm
from app.tools.prompt_loader import get_prompt_loader
from app.workflow.state import AnalysisState

logger = get_logger("eia.agent.chart_advisor")

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
# 规则兜底：从聚合摘要中解析 Markdown 表格生成图表
# ---------------------------------------------------------------------------


def parse_tables_from_summary(summary: str) -> dict | None:
    """从聚合摘要文本中解析 Markdown 表格并生成图表配置。

    当 LLM 未推荐图表时，作为规则兜底自动检测排名/对比类表格。
    """
    lines = summary.split("\n")
    tables = []
    i = 0
    while i < len(lines):
        if lines[i].count("|") >= 2 and "---" not in lines[i]:
            header_line = lines[i].strip()
            if i + 1 < len(lines) and "---" in lines[i + 1]:
                headers = [h.strip() for h in header_line.strip("|").split("|")]
                rows = []
                j = i + 2
                while j < len(lines) and lines[j].count("|") >= 2 and "---" not in lines[j]:
                    cells = [c.strip() for c in lines[j].strip("|").split("|")]
                    if cells:
                        rows.append(cells)
                    j += 1
                if len(rows) >= 4 and len(headers) >= 2:
                    tables.append({"headers": headers, "rows": rows})
                i = j
                continue
        i += 1

    if not tables:
        return None

    for tbl in tables:
        headers = tbl["headers"]
        rows = tbl["rows"]

        # 找名称列：从左向右找第一个非数值列（跳过排名/序号列）
        name_col_idx = -1
        for ci in range(len(headers)):
            try:
                cleaned = rows[0][ci].replace(",", "").replace("¥", "").replace("$", "").replace("元", "").replace("%", "")
                float(cleaned)
            except (ValueError, IndexError):
                name_col_idx = ci
                break
        if name_col_idx < 0:
            name_col_idx = 0

        # 找数值列：名称列右侧第一个数值列（主要指标，如销售额、准时率）
        num_col_idx = -1
        for ci in range(name_col_idx + 1, len(headers)):
            try:
                cleaned = rows[0][ci].replace(",", "").replace("¥", "").replace("$", "").replace("元", "").replace("%", "")
                float(cleaned)
                num_col_idx = ci
                break
            except (ValueError, IndexError):
                continue
        if num_col_idx < 0:
            # 兜底：名称列右侧无数值列，尝试左侧
            for ci in range(name_col_idx - 1, -1, -1):
                try:
                    cleaned = rows[0][ci].replace(",", "").replace("¥", "").replace("$", "").replace("元", "").replace("%", "")
                    float(cleaned)
                    num_col_idx = ci
                    break
                except (ValueError, IndexError):
                    continue
        if num_col_idx < 0:
            continue

        x_data = []
        series_data = []
        for row in rows[:20]:
            try:
                val = float(row[num_col_idx].replace(",", "").replace("¥", "").replace("$", "").replace("元", "").replace("%", ""))
                x_data.append(row[name_col_idx] if len(row) > name_col_idx else f"项{len(x_data)+1}")
                series_data.append(val)
            except (ValueError, IndexError):
                continue

        if len(x_data) < 3:
            continue

        is_ranking = len(series_data) >= 3 and series_data[0] > series_data[-1]
        return {
            "type": "bar" if is_ranking else "pie",
            "title": f"{headers[name_col_idx]}{headers[num_col_idx]}排名",
            "x_data": x_data,
            "series": [{"name": headers[num_col_idx], "data": series_data}],
            "height": max(300, min(600, len(x_data) * 25)),
            "note": "数据来源：分析结果自动提取",
        }

    return None


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

    # V4.1: 图表推荐不需要全量数据，仅保留开头关键部分即可判断图表类型
    # 截断阈值设置为 8000 字符作为兜底（aggregator 端已做源头截断）
    CHART_MAX_CHARS = 8000
    if len(summary) > CHART_MAX_CHARS:
        logger.info("图表推荐输入过长，截断: %d → %d 字符", len(summary), CHART_MAX_CHARS)
        summary = summary[:CHART_MAX_CHARS] + f"\n\n>（数据分析太长，已截断至前 {CHART_MAX_CHARS} 字符）"

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
        if isinstance(result, dict):
            charts = result.get("charts", [])
        elif isinstance(result, list):
            # LLM 直接返回了数组（如 [{type:"bar",...},...]），直接使用
            charts = result
        else:
            charts = []
        elapsed = time.monotonic() - t_start
        logger.info("执行完成 (%.1fs) - LLM 推荐图表: %d 个", elapsed, len(charts))

        # V4.2: 规则兜底解析 Markdown 表格补充图表（仅 LLM 未生成时执行）
        if not charts:
            fallback = parse_tables_from_summary(summary)
            if fallback:
                logger.info("规则兜底生成图表: %s", fallback.get("title", ""))
                charts = [fallback]
            else:
                logger.warning("规则兜底未生成图表, summary_len=%d", len(summary))

        return {"chart_suggestions": charts}

    except Exception as e:
        elapsed = time.monotonic() - t_start
        logger.warning("执行失败 (%.1fs)，返回空图表列表: %s", elapsed, e)
        # 图表生成失败不影响主流程 —— 尝试规则兜底
        try:
            fallback = parse_tables_from_summary(summary)
            if fallback:
                logger.info("LLM 异常后规则兜底生成图表")
                return {"chart_suggestions": [fallback]}
        except Exception:
            logger.warning("规则兜底也失败，返回空图表列表")
        return {"chart_suggestions": []}
