"""报告生成 Agent — V3 增强版。

整合来自销售、CRM 和财务 Agent 的聚合分析结果，合成为结构化的业务报告。

V3 新增：
  - 嵌入来自 chart_suggestions 的 [CHART:type|...] 标记
  - 生成 followup_questions 以支持多轮对话
"""

import json
import logging
import time
import urllib.parse

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.config import get_stream_writer

from app.config import get_settings
from app.llm import create_llm
from app.tools.prompt_loader import get_prompt_loader
from app.workflow.state import AnalysisState
from prompts.report_prompt import REPORT_HUMAN_TEMPLATE, REPORT_SYSTEM_PROMPT

logger = logging.getLogger("eia.agent.report")

llm = create_llm()


def build_chart_markers(charts: list[dict]) -> str:
    """将图表建议转换为 [CHART:...] 标记（LLM 可读格式）。"""
    if not charts:
        return ""
    markers = []
    for c in charts:
        # 将 | 替换为 ‖ 防止破坏管道分隔的参数格式
        title = c.get('title', '').replace('|', '‖')
        params = f"title={title}|x_data={json.dumps(c.get('x_data',[]),ensure_ascii=False)}|series={json.dumps(c.get('series',[]),ensure_ascii=False)}|height={c.get('height',400)}"
        markers.append(f"[CHART:{c.get('type','bar')}|{params}]")
    return "\n".join(markers)


def encode_chart_markers(report: str) -> str:
    """后处理报告：将 [CHART:...] 标记转换为 URL 编码的 JSON 格式。

    LLM 在其指令中收到的是可读的管道分隔标记，
    但前端需要 URL 编码的 JSON 以避免 ]/| 字符破坏正则匹配。
    此函数在 LLM 生成后进行转换。
    使用 |height= 作为标记末尾的可靠锚点。
    """
    result = []
    i = 0
    while i < len(report):
        pos = report.find("[CHART:", i)
        if pos == -1:
            result.append(report[i:])
            break
        result.append(report[i:pos])
        # 通过 |height=NNN] 模式定位标记末尾
        height_pos = report.find("|height=", pos + 7)
        if height_pos == -1 or height_pos > pos + 2000:
            # 兜底：|height= 未找到，尝试直接找 ] 作为标记结束
            end = report.find("]", pos + 7)
            if end == -1 or end > pos + 3000:
                result.append(report[pos:])
                break
        else:
            end = report.find("]", height_pos)
            if end == -1:
                result.append(report[pos:])
                break
        raw_marker = report[pos:end + 1]
        # 解析 [CHART:type|params]（鲁棒处理 LLM 畸形输出）
        bar = raw_marker.find("|")
        if bar == -1:
            # LLM 输出格式异常，跳过这个标记
            result.append(report[i:end + 1])
            i = end + 1
            continue
        chart_type = raw_marker[7:bar]  # 7 = len("[CHART:")
        params_str = raw_marker[bar + 1:-1]  # -1 = 去掉末尾的 ]
        # 解析管道分隔的参数
        config = {"type": chart_type}
        for pair in params_str.split("|"):
            eq = pair.index("=") if "=" in pair else -1
            if eq == -1:
                continue
            key = pair[:eq]
            val = pair[eq + 1:]
            if key == "title":
                config["title"] = val
            elif key == "height":
                try:
                    config["height"] = int(val)
                except (ValueError, TypeError):
                    config["height"] = 400
            else:
                try:
                    config[key] = json.loads(val)
                except (json.JSONDecodeError, ValueError, TypeError):
                    config[key] = val
        safe = {k: config[k] for k in ("type", "title", "x_data", "series", "height", "note") if k in config}
        encoded = urllib.parse.quote(json.dumps(safe, ensure_ascii=False), safe="")
        result.append(f"[CHART:{chart_type}|{encoded}]")
        i = end + 1
    return "".join(result)


def build_chart_instructions(charts: list[dict]) -> str:
    """构建 LLM 的图表标记放置指令。"""
    if not charts:
        return ""
    markers = build_chart_markers(charts)
    return f"""## 📊 图表嵌入指令
以下图表已自动生成，请在报告合适位置插入这些标记（每个标记独占一行，放在对应数据段落之后）：

{markers}

**规则**：
- 柱状图标记放在排名表格之后
- 折线图标记放在趋势分析之后
- 饼图标记放在占比分析之后
- 不要修改标记格式"""


def _build_error_report(question: str, errors: list[dict]) -> str:
    """当所有 Agent 失败时，生成 Python 级别的错误说明报告（不依赖 LLM）。

    包含每条错误的 Agent 名称、用户友好消息和建议操作。
    """
    lines = [
        f"# 分析未能完成",
        f"",
        f"**您的问题**：{question}",
        f"",
        f"## 错误详情",
        f"",
    ]
    # 去重：同一 Agent 只显示一次
    seen_agents = set()
    for err in errors:
        agent = err.get("agent", "unknown")
        error_msg = err.get("error", "")
        user_msg = err.get("user_message", "")
        icon = err.get("icon", "⚠️")
        action = err.get("action", "")

        # 优先展示用户友好消息
        display_msg = user_msg or error_msg
        if agent not in seen_agents:
            seen_agents.add(agent)
            lines.append(f"- **{icon} {agent} Agent**：{display_msg}")
            if action:
                lines.append(f"  - 建议：{action}")

    lines.append("")
    lines.append("## 可能的原因")
    lines.append("")
    # 根据错误类型给出诊断
    error_text = " ".join(str(e.get("error", "")) for e in errors).lower()
    if "401" in error_text or "unauthorized" in error_text or "auth" in error_text:
        lines.append("1. **API 密钥无效**：请检查 `.env` 中的 `DEEPSEEK_API_KEY` 是否正确")
        lines.append("2. 请检查 API 服务商控制台以获取有效密钥")
    elif "timeout" in error_text or "connect" in error_text:
        lines.append("1. **网络连接异常**：请检查是否能访问 LLM API 服务地址")
        lines.append("2. 确认代理设置是否正确（`NO_PROXY` 已自动配置）")
    else:
        lines.append("1. 请检查服务日志获取详细错误信息")
        lines.append("2. 确认所有依赖服务（PostgreSQL、Redis）正常运行")

    lines.append("")
    lines.append("---")
    lines.append("*此报告由系统自动生成，请修复上述问题后重新提问。*")

    return "\n".join(lines)


async def report_agent_node(state: AnalysisState) -> dict:
    """LangGraph 节点：根据聚合分析结果生成结构化业务报告。

    V3：嵌入图表标记并生成追问问题。
    """
    t_start = time.monotonic()
    logger.info("开始执行 - question: %s...", state.get("question", "")[:80])
    writer = get_stream_writer()
    writer({"type": "progress", "node": "report_agent", "message": "正在生成分析报告..."})

    summary = state.get("aggregator_summary")
    if not summary:
        # V4: 当所有 Agent 失败时，生成 Python 级别的错误报告（不依赖 LLM）
        errors = state.get("agent_errors", [])
        if errors:
            report = _build_error_report(state.get("question", "未知问题"), errors)
            logger.warning("生成错误降级报告 - %d 条错误", len(errors))
            return {"report": report}
        logger.warning("缺少聚合摘要数据且无错误信息")
        return {
            "report": None,
            "agent_errors": [{"agent": "report", "error": "No analysis data available"}],
        }

    settings = get_settings()
    charts = state.get("chart_suggestions") or []

    # 构建图表指令（功能禁用或无图表时为空字符串）
    chart_instructions = ""
    if settings.feature_chart and charts:
        chart_instructions = build_chart_instructions(charts)

    # 构建追问指令（仅用于非重试运行）
    followup_instruction = ""
    if settings.feature_multi_turn and not state.get("reflection_feedback"):
        followup_instruction = "\n\n## 追问建议\n在报告末尾，请额外输出 3 个 JSON 格式的建议追问问题（以 JSON 数组格式输出，方便前端解析渲染按钮）：\n[FOLLOWUP:[\"问题1\", \"问题2\", \"问题3\"]]"

    try:
        content = REPORT_HUMAN_TEMPLATE.format(
            question=state["question"],
            aggregator_summary=summary,
            chart_instructions=chart_instructions,
            followup_instruction=followup_instruction,
        )

        # 如果是重试（反思阶段标记了问题），则包含反馈
        if state.get("reflection_feedback") and not state.get("reflection_passed"):
            content += f"\n\n⚠️ 上次报告审核未通过，请根据以下反馈修改：\n{state['reflection_feedback']}"

        loader = get_prompt_loader()
        messages = [
            SystemMessage(content=loader.get_prompt("report", "system_prompt", fallback=REPORT_SYSTEM_PROMPT)),
            HumanMessage(content=content),
        ]
        # P0-1: 使用流式调用 + StreamWriter 同时支持 /analyze 和 /analyze-stream
        # 当通过 graph.astream(stream_mode="custom") 调用时，writer 将 token
        # 推送到前端 SSE；当通过 graph.ainvoke() 调用时，writer 为 no-op。
        writer = get_stream_writer()
        full_text = ""
        async for chunk in llm.astream(messages):
            token = chunk.content if hasattr(chunk, 'content') and chunk.content else ""
            if token:
                full_text += token
                writer({"type": "token", "text": token})
        report = full_text

        # 后处理：将 [CHART:...] 标记编码为前端可用的 URL 编码 JSON
        report = encode_chart_markers(report)

        # 从 [FOLLOWUP:...] 标记中提取追问问题
        # 使用括号计数法（而非脆弱的正则），确保正确匹配嵌套的 ]]
        followup_questions: list[str] = []
        marker_start = report.find("[FOLLOWUP:")
        if marker_start >= 0:
            # 定位 JSON 数组的起始 [（在 "FOLLOWUP:" 之后）
            bracket_start = report.find("[", marker_start + 10)
            if bracket_start >= 0:
                # 括号计数（字符串感知）：跳过 JSON 字符串内的 [] 字符
                depth = 1
                i = bracket_start + 1
                in_string = False
                while i < len(report) and depth > 0:
                    ch = report[i]
                    if in_string:
                        if ch == '\\':
                            i += 1  # 跳过转义字符
                        elif ch == '"':
                            in_string = False
                    else:
                        if ch == '"':
                            in_string = True
                        elif ch == "[":
                            depth += 1
                        elif ch == "]":
                            depth -= 1
                    i += 1
                array_end = i - 1  # JSON 数组的结束 ]
                if depth == 0 and array_end + 1 < len(report) and report[array_end + 1] == "]":
                    # 提取 JSON 数组内容并解析
                    json_str = report[bracket_start:array_end + 1]
                    try:
                        followup_questions = json.loads(json_str)
                    except json.JSONDecodeError:
                        pass
                    # 移除完整的 [FOLLOWUP:...]] 标记
                    report = report[:marker_start] + report[array_end + 2:]

        elapsed = time.monotonic() - t_start
        logger.info("执行完成 (%.1fs) - 报告长度: %d, 追问: %d", elapsed, len(report), len(followup_questions))
        return {
            "report": report,
            "followup_questions": followup_questions,
        }
    except Exception as e:
        elapsed = time.monotonic() - t_start
        logger.error("执行失败 (%.1fs): %s", elapsed, e)
        return {
            "report": None,
            "agent_errors": [{"agent": "report", "error": str(e)}],
        }
