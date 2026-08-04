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
- bar（柱状图）：排名、对比类数据（如"各门店销售额排名"）。排名类数据必须用 bar，禁止用 pie
- line（折线图）：时间趋势类数据（如"近30天销售趋势"）
- pie（饼图）：占比、分布类数据（如"各区域销售额占比"）。pie 只用于占比/分布语义
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
- x_data 最多取 TOP 10 条（数据过多会失去可读性）
- 数据表同时含多个数值列时（如"订单数""销售额"），优先选择业务金额列（销售额/收入/金额/营业额/利润），不要选订单数/数量列
- series 的 data 长度必须与 x_data 一致
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
# LLM 输出后处理：硬性约束（prompt 是软约束，LLM 偶尔不遵守）
# ---------------------------------------------------------------------------

MAX_CHART_ITEMS = 10


def _sanitize_charts(charts: list) -> list:
    """对 LLM 生成的图表配置做强制约束与校验。

    - 排名/对比类（标题含"排名/排行/TOP/前N"）强制 bar，禁止 pie（饼图不适合排名）
      —— 仅凭标题关键词判定，不用数据递减：占比数据天然递减，会误伤合法 pie
    - 数据项最多 10 条（过多失去可读性）
    - 校验 x_data/series 完整性，残缺项直接丢弃
    """
    out = []
    for c in charts:
        if not isinstance(c, dict):
            continue
        x_data = c.get("x_data") or []
        series = c.get("series") or []
        if not isinstance(series, list) or not series:
            continue
        s0 = series[0]
        data = s0.get("data") if isinstance(s0, dict) else None
        if not isinstance(data, list) or len(data) != len(x_data) or not data:
            continue  # 数据残缺，丢弃该图
        title = str(c.get("title") or "")
        is_ranking = ("排名" in title or "排行" in title or "TOP" in title.upper()
                      or ("前" in title and len(data) >= 3))
        ctype = c.get("type", "bar")
        if is_ranking and ctype == "pie":
            ctype = "bar"
        if len(x_data) > MAX_CHART_ITEMS:
            x_data = x_data[:MAX_CHART_ITEMS]
            data = data[:MAX_CHART_ITEMS]
            series = [{"name": s0.get("name", ""), "data": data}]
        out.append({**c, "type": ctype, "x_data": x_data, "series": series})
    return out


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

        # 找数值列：名称列右侧的数值列中，优先选择业务金额列（销售额/收入/金额…），
        # 避免选中"订单数/数量"列（历史案例曾把订单数当销售额画图）
        _NUM_COL_KEYWORDS = [
            ("销售额", 0), ("营业额", 0), ("收入", 0), ("金额", 0), ("利润", 1), ("毛利", 1),
            ("订单", 2), ("销量", 2), ("数量", 2), ("率", 3),
        ]
        num_col_idx = -1
        _best_pri = 99
        for ci in range(name_col_idx + 1, len(headers)):
            try:
                cleaned = rows[0][ci].replace(",", "").replace("¥", "").replace("$", "").replace("元", "").replace("%", "")
                float(cleaned)
            except (ValueError, IndexError):
                continue
            h = headers[ci]
            pri = 9
            for kw, p in _NUM_COL_KEYWORDS:
                if kw in h:
                    pri = min(pri, p)
                    break
            if pri < _best_pri:
                _best_pri, num_col_idx = pri, ci
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
        for row in rows[:10]:
            try:
                val = float(row[num_col_idx].replace(",", "").replace("¥", "").replace("$", "").replace("元", "").replace("%", ""))
                x_data.append(row[name_col_idx] if len(row) > name_col_idx else f"项{len(x_data)+1}")
                series_data.append(val)
            except (ValueError, IndexError):
                continue

        if len(x_data) < 3:
            continue

        # 图型判定：表头信号优先（占比表数据天然递减，不能用递减判断）
        _all_headers = "".join(headers)
        is_share = "占比" in _all_headers or "比例" in _all_headers or "份额" in _all_headers
        is_ranking = "排名" in headers[0] or "排行" in headers[0] or (
            not is_share and len(series_data) >= 3 and series_data[0] > series_data[-1]
        )
        ctype = "bar" if is_ranking else "pie"
        title = (f"{headers[name_col_idx]}{headers[num_col_idx]}排名" if ctype == "bar"
                 else f"{headers[name_col_idx]}{headers[num_col_idx]}占比")
        return {
            "type": ctype,
            "title": title,
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

        # V4.6.1: LLM 输出硬校验（排名强制 bar / TOP 10 / 数据完整性）
        return {"chart_suggestions": _sanitize_charts(charts)}

    except Exception as e:
        elapsed = time.monotonic() - t_start
        logger.warning("执行失败 (%.1fs)，返回空图表列表: %s", elapsed, e)
        # 图表生成失败不影响主流程 —— 尝试规则兜底
        try:
            fallback = parse_tables_from_summary(summary)
            if fallback:
                logger.info("LLM 异常后规则兜底生成图表")
                return {"chart_suggestions": _sanitize_charts([fallback])}
        except Exception:
            logger.warning("规则兜底也失败，返回空图表列表")
        return {"chart_suggestions": []}
