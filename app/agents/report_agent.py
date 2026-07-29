"""报告生成 Agent — V3 增强版。

整合来自销售、CRM 和财务 Agent 的聚合分析结果，合成为结构化的业务报告。

V3 新增：
  - 嵌入来自 chart_suggestions 的 [CHART:type|...] 标记
  - 生成 followup_questions 以支持多轮对话
"""

import json
from app.logging_config import get_logger
import time
import urllib.parse

from langchain_core.messages import HumanMessage, SystemMessage
from app.tools.stream_utils import safe_get_stream_writer as get_stream_writer

from app.config import get_settings
from app.llm import create_llm
from app.tools.prompt_loader import get_prompt_loader
from app.workflow.state import AnalysisState
from prompts.report_prompt import REPORT_HUMAN_TEMPLATE, REPORT_SYSTEM_PROMPT

logger = get_logger("eia.agent.report")

llm = create_llm()


def build_chart_markers(charts: list[dict]) -> str:
    """将图表建议转换为 [CHART:type|url_encoded_json] 标记（LLM 可直接复制的最终格式）。"""
    if not charts:
        return ""
    markers = []
    for c in charts:
        safe = {k: c[k] for k in ("type", "title", "x_data", "series", "height", "note") if k in c}
        encoded = urllib.parse.quote(json.dumps(safe, ensure_ascii=False), safe="")
        markers.append(f"[CHART:{safe.get('type','bar')}|{encoded}]")
    return "\n".join(markers)


def _find_chart_end(text: str, pos: int) -> int:
    """从 [CHART: 的 [ 位置开始，括号计数找到匹配的 ]（支持嵌套 []）。"""
    depth = 0
    for i in range(pos, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return i
    return -1


def encode_chart_markers(report: str) -> str:
    """后处理报告：将 [CHART:...] 标记转换为 URL 编码的 JSON 格式。

    build_chart_markers 现在直接输出 URL 编码的 JSON（LLM 直接复制，保持原样）。
    此函数保持向后兼容：检测到已经是 URL 编码的标记则透传，
    遇到旧的管道分隔格式（或 LLM 修改过的标记）则转换。
    使用括号计数法（而非找第一个 ]）来正确处理 JSON 中的嵌套 []。
    """
    result = []
    i = 0
    while i < len(report):
        pos = report.find("[CHART:", i)
        if pos == -1:
            result.append(report[i:])
            break
        result.append(report[i:pos])
        # 用括号计数找到匹配的 ]（支持嵌套 JSON 中的 []）
        end = _find_chart_end(report, pos)
        if end == -1 or end > pos + 5000:
            result.append(report[pos:])
            break
        # 定位 | 分隔符（[CHART:type|...]）
        bar = report.find("|", pos + 7)
        if bar == -1 or bar > pos + 100:
            # 没有 |，不是合法标记，保留原样
            result.append(report[pos:end + 1])
            i = end + 1
            continue
        chart_type = report[pos + 7:bar]
        params_raw = report[bar + 1:end]
        # 检测是否已经是 URL 编码的 JSON（以 %7B 或 { 开头）→ 直接透传
        if params_raw.startswith("%7B") or params_raw.startswith("{"):
            try:
                json.loads(urllib.parse.unquote(params_raw))
                result.append(report[pos:end + 1])
                i = end + 1
                continue
            except Exception:
                pass  # 不是合法 JSON，按旧格式解析
        # 旧格式管道分隔解析（兼容 LLM 手工修改的情况）
        config = {"type": chart_type}
        for pair in params_raw.split("|"):
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

    # V4.2: chart_advisor 未生成图表时，report_agent 自己扫描摘要表格兜底
    if settings.feature_chart and not charts and summary:
        from app.agents.chart_advisor_agent import parse_tables_from_summary
        fallback_chart = parse_tables_from_summary(summary)
        if fallback_chart:
            logger.info("report_agent 规则兜底: %s", fallback_chart.get("title", ""))
            charts = [fallback_chart]

    # 构建图表指令（功能禁用或无图表时为空字符串）
    chart_instructions = ""
    if settings.feature_chart and charts:
        chart_instructions = build_chart_instructions(charts)

    # 构建追问指令（仅用于非重试运行）
    followup_instruction = ""
    if settings.feature_multi_turn:
        logger.info("添加追问指令（feature_multi_turn=%s, reflection_feedback=%s）", settings.feature_multi_turn, state.get("reflection_feedback"))
        followup_instruction = "【强制指令】你必须在报告末尾输出 3 个 JSON 格式的建议追问问题。\n格式（直接输出，不要代码块）：\n[FOLLOWUP:[\"具体追问1\", \"具体追问2\", \"具体追问3\"]]\n追问必须基于当前分析内容，用实际指标/门店等数据。不输出=报告不完整。"
    else:
        logger.info("跳过追问指令（feature_multi_turn=%s, reflection_feedback=%s）", settings.feature_multi_turn, state.get("reflection_feedback"))

    try:
        # 追问指令已作为独立 SystemMessage，不在 HumanMessage 中重复
        content = REPORT_HUMAN_TEMPLATE.format(
            question=state["question"],
            aggregator_summary=summary,
            chart_instructions=chart_instructions,
            followup_instruction="",
        )

        # 如果是重试（反思阶段标记了问题），则包含反馈
        if state.get("reflection_feedback") and not state.get("reflection_passed"):
            content += f"\n\n⚠️ 上次报告审核未通过，请根据以下反馈修改：\n{state['reflection_feedback']}"

        loader = get_prompt_loader()
        messages = [
            SystemMessage(content=loader.get_prompt("report", "system_prompt", fallback=REPORT_SYSTEM_PROMPT)),
        ]
        # 追问指令作为独立 SystemMessage，比混在 Human 末尾更醒目
        if followup_instruction:
            messages.append(SystemMessage(content=followup_instruction))
        messages.append(HumanMessage(content=content))
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

        # V4.2: 最终报告解析兜底 —— 如果报告中含 Markdown 表格但无 [CHART:] 标记，
        # 直接从报告文本中提取表格数据生成图表标记
        if "[CHART:" not in report:
            try:
                from app.agents.chart_advisor_agent import parse_tables_from_summary
                final_chart = parse_tables_from_summary(report)
                if final_chart:
                    import urllib.parse
                    safe = json.dumps({k: final_chart[k] for k in ("type","title","x_data","series","height","note") if k in final_chart}, ensure_ascii=False)
                    encoded = urllib.parse.quote(safe, safe="")
                    chart_marker = "\n\n[CHART:%s|%s]\n" % (final_chart["type"], encoded)
                    report += chart_marker
                    logger.info("报告解析兜底注入图表: %s", final_chart.get("title", ""))
            except Exception as chart_err:
                logger.warning("报告解析兜底图表失败: %s", chart_err)

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
                    # [FOLLOWUP:...]] 标记保留在报告中，save_memory_node 会从中提取追问存库
                    # 前端 views.js 的渐进展示回调中会用正则清理显示

        # V4.4: 追问兜底 —— 如果 LLM 未生成追问，用规则生成
        if not followup_questions and settings.feature_multi_turn:
            _q = []
            _rl = report.lower()
            if "门店" in report or "store" in _rl:
                _q.append("哪家门店销售额最高？")
                _q.append("各区域的门店业绩对比如何？")
            if "区域" in report or "region" in _rl:
                _q.append("各区域的销售占比情况？")
            if "趋势" in report or "trend" in _rl or "增长" in report:
                _q.append("近期的销售增长趋势如何？")
            if "退款" in report or "退货" in report:
                _q.append("退款率变化趋势如何？")
            if "会员" in report or "member" in _rl:
                _q.append("会员活跃度与留存率如何？")
            if "商品" in report or "品类" in report or "product" in _rl:
                _q.append("哪些品类销售最好？")
            # 通用兜底（如果关键词都没命中）
            _common = ["各门店销售额排名如何？", "近30天销售趋势是怎样的？", "退款率最高的门店有哪些？"]
            _seen = set()
            for _item in _q + _common:
                if _item not in _seen:
                    _seen.add(_item)
                    followup_questions.append(_item)
                if len(followup_questions) >= 3:
                    break
            logger.info("追问规则兜底: %d 个", len(followup_questions))

        elapsed = time.monotonic() - t_start
        # 最终保险：无论 LLM 是否生成，保证追问非空（用于存库和监控统计）
        if not followup_questions:
            followup_questions = ["各门店销售额排名如何？", "近30天销售趋势是怎样的？", "退款率最高的门店有哪些？"]
        logger.info("执行完成 (%.1fs) - 报告长度: %d, 追问: %s", elapsed, len(report), json.dumps(followup_questions, ensure_ascii=False))
        # 将追问嵌入报告尾部（save_memory_node 会从中提取持久化到数据库）
        try:
            _fq_json = json.dumps(followup_questions, ensure_ascii=False)
            if _fq_json and "[FOLLOWUP_SAVE:" not in report:
                report = report + "\n\n" + "[FOLLOWUP_SAVE:" + _fq_json + "]"
        except Exception:
            pass
        return {
            "report": report,
            "followup_questions": followup_questions or [],
        }
    except Exception as e:
        elapsed = time.monotonic() - t_start
        logger.error("执行失败 (%.1fs): %s", elapsed, e)
        return {
            "report": None,
            "agent_errors": [{"agent": "report", "error": str(e)}],
        }
