"""V5 Phase 3：Reflection 契约化 Agent。

从 V4 的「4 项主观自评」改为「4 项质量契约合规审查」。
核心变更：
  1. Numerical Consistency（30%）   → 系统确定性（SQL 结果集数值 vs 报告数值，grounding.py）
  2. Evidence Grounding （35%）   → 系统确定性（关键结论 ↔ data_sources 命中，grounding.py）
  3. Reasoning Validity （15%）   → LLM（因果判断有数据支撑？）
  4. Recommendation Alignment（20%） → LLM（建议有 Finding 锚点？）

  通过规则：加权综合 ≥ 70 分  AND  Numerical/Grounding 两项均无 high-sev 违约（score ≥ 50）

  向后兼容：reflection_feedback JSON 同时有老 schema（passed/issues/summary + 4 category 枚举）
            和新 schema（scores/contract），graph.py 老消费者 + eval_runner 新消费者都不挂。
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict

from langchain_core.messages import HumanMessage, SystemMessage

from app.logging_config import get_logger
from app.tools.grounding import (
    GroundingResult,
    NumericalResult,
    check_numerical_consistency,
    check_report_grounding,
)
from app.tools.prompt_loader import get_prompt_loader
from app.tools.stream_utils import safe_get_stream_writer as get_stream_writer
from app.llm import create_llm
from app.workflow.state import AnalysisState
from prompts.reflection_prompt import REFLECTION_HUMAN_TEMPLATE, REFLECTION_SYSTEM_PROMPT

logger = get_logger("eia.agent.reflection")

# Phase 3 Step 0 拍板权重 + 阈值（详见 scripts/phase3_step0_correlation_analysis.py）
WEIGHTS: dict[str, float] = {
    "numerical":  0.30,
    "grounding":  0.35,
    "reasoning":  0.15,
    "alignment":  0.20,
}
THRESHOLD_WEIGHTED = 70.0
THRESHOLD_HIGH_SEV = 50  # Numerical / Grounding < 50 → high severity 违约 → 一票否决

# Old category 映射（保持老 reflection_feedback issues.category 枚举兼容）
DIM_TO_OLD_CAT = {
    "numerical":  "consistency",
    "grounding":  "consistency",   # 证据支撑属于一致性大类（"编造"口径）
    "reasoning":  "logic",
    "alignment":  "actionability",
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "契约权重之和必须等于 1"

# 独立 LLM：temperature=0，输出 JSON 稳定
_llm_for_contract = None
def _get_llm():
    global _llm_for_contract
    if _llm_for_contract is None:
        _llm_for_contract = create_llm(temperature=0.0)
    return _llm_for_contract


def _extract_json(text: str) -> dict | None:
    """括号计数法提取 JSON（与 V4.6.2 加固逻辑一致）。"""
    in_str = False
    escape = False
    stack = []
    start = -1
    for i, ch in enumerate(text or ""):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if not stack:
                start = i
            stack.append(ch)
        elif ch == "}":
            if stack:
                stack.pop()
                if not stack and start >= 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        start = -1
    return None


# ---------------------------------------------------------------------------
# 4 契约维度 → 统一 issues 格式
# ---------------------------------------------------------------------------

def _build_numerical_issues(nr: NumericalResult) -> tuple[list[dict], bool]:
    """把 NumericalResult.unmatched 转为 issues 列表。

    high_sev 判定：score < THRESHOLD_HIGH_SEV
    """
    issues: list[dict] = []
    if nr.score >= 100 or not nr.unmatched:
        return issues, False

    # 前 10 条 unmatched 单独报，其余合并（避免 issues 爆炸）
    top = nr.unmatched[:10]
    rest_cnt = len(nr.unmatched) - len(top)
    for u in top:
        sev = "high" if nr.score < THRESHOLD_HIGH_SEV else "medium"
        pct = "%" if u.get("is_percent") else ""
        issues.append({
            "severity": sev,
            "category": DIM_TO_OLD_CAT["numerical"],
            "description": f"[Numerical] 报告中的数字「{u['original']}{pct}」在 SQL 结果集里找不到对应（归一化值={u['value']}），可能为编造或四舍五入超阈值。",
            "suggestion": "核对该数字对应的 SQL 执行结果；若为百分比/单位换算需保留换算过程，不要省略。",
        })
    if rest_cnt > 0:
        issues.append({
            "severity": "medium" if nr.score >= THRESHOLD_HIGH_SEV else "high",
            "category": DIM_TO_OLD_CAT["numerical"],
            "description": f"[Numerical] 另有 {rest_cnt} 个报告数字同样未在 SQL 结果中找到对应。",
            "suggestion": "按报告行文顺序对照 raw_data 逐条修正。",
        })
    return issues, (nr.score < THRESHOLD_HIGH_SEV)


def _build_grounding_issues(gr: GroundingResult) -> tuple[list[dict], bool]:
    """把 grounding result.details 中未 grounded 的 claims 转为 issues。"""
    issues: list[dict] = []
    if gr.total_claims == 0 or gr.grounded_claims == gr.total_claims:
        return issues, False

    # 取前 5 条未 grounded claim 展示，其余给汇总
    ungrounded = [d for d in gr.details if not d.get("grounded")]
    for c in ungrounded[:5]:
        claim_text = (c.get("claim") or "")[:160]
        sev = "high" if (gr.score if hasattr(gr, "score") else gr.evidence_coverage * 100) < THRESHOLD_HIGH_SEV else "medium"
        issues.append({
            "severity": sev,
            "category": DIM_TO_OLD_CAT["grounding"],
            "description": f"[Grounding] 关键结论未被 data_sources 支撑：{claim_text}",
            "suggestion": "补充支撑该结论的 SQL 查询（或调整结论措辞，使其不超出已查到的范围）。",
        })
    if len(ungrounded) > 5:
        issues.append({
            "severity": "medium",
            "category": DIM_TO_OLD_CAT["grounding"],
            "description": f"[Grounding] 另有 {len(ungrounded) - 5} 条关键结论未找到数据支撑。",
            "suggestion": "逐句对照 claims ↔ data_sources 修复。",
        })

    # 补充 score 字段（GroundingResult 目前未直接带 score，这里补一下方便后续引用）
    gr_score = int(round(gr.evidence_coverage * 100))  # type: ignore[attr-defined]
    gr.score = gr_score  # type: ignore[attr-defined]
    return issues, (gr_score < THRESHOLD_HIGH_SEV)


def _normalize_llm_issues(raw_list: list, dim: str) -> list[dict]:
    """把 LLM 返回的 reasoning/alignment issues 规整成老 schema。"""
    normalized: list[dict] = []
    if not isinstance(raw_list, list):
        return normalized
    for it in raw_list:
        if not isinstance(it, dict):
            continue
        sev = it.get("severity", "medium")
        if sev not in {"high", "medium", "low"}:
            sev = "medium"
        desc = it.get("description") or it.get("reason") or "(无描述)"
        sug = it.get("suggestion") or ""
        normalized.append({
            "severity": sev,
            "category": DIM_TO_OLD_CAT[dim],
            "description": f"[{dim.capitalize()}] {desc}",
            "suggestion": sug,
        })
    return normalized


def _llm_judge_reasoning_alignment(
    question: str,
    report: str,
    aggregator_summary: str,
    numerical_score: int,
    grounding_score: int,
    numerical_issue_count: int,
    grounded_claims: int,
    total_claims: int,
) -> tuple[dict, dict]:
    """调 LLM 判定 Reasoning / Alignment 两项。

    Returns:
      reasoning: {"score": int, "issues": [...]}
      alignment: {"score": int, "issues": [...]}
    """
    llm = _get_llm()
    loader = get_prompt_loader()

    MAX_REPORT_CHARS = 18000
    MAX_SUMMARY_CHARS = 8000
    if len(report) > MAX_REPORT_CHARS:
        tail = int(MAX_REPORT_CHARS * 0.25)
        truncated_report = report[: MAX_REPORT_CHARS - tail] + "\n\n>（报告中间部分已截断）\n\n" + report[-tail:]
    else:
        truncated_report = report
    truncated_summary = (aggregator_summary or "(no raw data)")[:MAX_SUMMARY_CHARS]

    # query_type_label 推断：综合/查询——给 LLM 作为参考（不影响最终打分，仅给上下文）
    qtype_label = "综合分析型" if any(k in question for k in ["分析", "原因", "诊断", "为什么", "经营状况", "下降", "问题"]) else "数据查询型"

    # --- 尝试 YAML 版 human_template（注入 5 个字段），KeyError 则 fallback 到 Python 硬编码 ---
    system_prompt = loader.get_prompt("reflection", "system_prompt", fallback=REFLECTION_SYSTEM_PROMPT)
    try:
        human_msg = loader.get_prompt("reflection", "human_template", fallback=REFLECTION_HUMAN_TEMPLATE).format(
            question=question,
            query_type_label=qtype_label,
            aggregator_summary=truncated_summary,
            report=truncated_report,
            numerical_score=numerical_score,
            grounding_score=grounding_score,
            numerical_issue_count=numerical_issue_count,
            grounded_claims=grounded_claims,
            total_claims=total_claims,
        )
    except (KeyError, IndexError):
        # 兜底硬编码：不注入新字段（Python REFLECTION_HUMAN_TEMPLATE 也只需要 3 个字段）
        human_msg = REFLECTION_HUMAN_TEMPLATE.format(
            question=question,
            aggregator_summary=truncated_summary,
            report=truncated_report,
        )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_msg),
    ]

    def _parse(raw_response) -> dict | None:
        txt = getattr(raw_response, "content", None) or ""
        data = _extract_json(txt)
        if data is None:
            return None
        return data

    try:
        resp = llm.invoke(messages)
    except Exception as e:
        logger.warning("Reflection LLM 调用失败，按 Reasoning=80/Alignment=80 兜底：%s", e)
        return (
            {"score": 80, "issues": [{"severity": "low", "description": "LLM 调用失败，Reasoning 按 80 分保守估计", "suggestion": "—"}]},
            {"score": 80, "issues": [{"severity": "low", "description": "LLM 调用失败，Alignment 按 80 分保守估计", "suggestion": "—"}]},
        )

    data = _parse(resp)
    if data is None:
        # 重问一次：强制只输出 JSON（与 V4.6.2 解析加固一致）
        try:
            retry_msg = messages + [HumanMessage(
                content="请只输出一个 JSON 对象，schema 为 {reasoning:{score:int,issues:[]}, alignment:{score:int,issues:[]}}。不要 Markdown 代码块，不要解释文字。"
            )]
            resp2 = llm.invoke(retry_msg)
            data = _parse(resp2)
        except Exception as e:
            logger.warning("Reflection 解析重试调用失败: %s", e)
            data = None

    if data is None:
        # 重问仍失败 → 兜底通过分数（避免误杀好报告）
        logger.error("Reflection Reasoning/Alignment 两次均无法解析 JSON，按 85/85 处理（PARSE_FALLBACK）")
        return (
            {"score": 85, "issues": [{"severity": "low",
                                      "description": "LLM 输出 JSON 解析失败，Reasoning 按 85 分保守处理（PARSING_FALLBACK）",
                                      "suggestion": "—"}]},
            {"score": 85, "issues": [{"severity": "low",
                                      "description": "LLM 输出 JSON 解析失败，Alignment 按 85 分保守处理（PARSING_FALLBACK）",
                                      "suggestion": "—"}]},
        )

    # 取 reasoning / alignment 子结构
    def _dim_block(key: str, fallback_score: int) -> dict:
        blk = data.get(key)
        if not isinstance(blk, dict):
            return {"score": fallback_score, "issues": []}
        score = blk.get("score")
        if not isinstance(score, int) or score < 0 or score > 100:
            if isinstance(score, (int, float)) and 0 <= score <= 100:
                score = int(round(float(score)))
            else:
                score = fallback_score
        iss = blk.get("issues", [])
        return {"score": int(score), "issues": iss if isinstance(iss, list) else []}

    reasoning = _dim_block("reasoning", 80)
    alignment = _dim_block("alignment", 80)
    return reasoning, alignment


# ---------------------------------------------------------------------------
# 综合加权 + 契约判定
# ---------------------------------------------------------------------------

def _contract_verdict(
    num_score: int,
    grd_score: int,
    reasoning_score: int,
    alignment_score: int,
) -> tuple[bool, float, dict]:
    """按权重和阈值给出契约通过判定。

    Returns: (passed_bool, weighted_score, thresholds_info_dict)
    """
    weighted = (
        num_score       * WEIGHTS["numerical"]
        + grd_score       * WEIGHTS["grounding"]
        + reasoning_score * WEIGHTS["reasoning"]
        + alignment_score * WEIGHTS["alignment"]
    )
    weighted = round(weighted, 2)
    num_high_sev = num_score < THRESHOLD_HIGH_SEV
    grd_high_sev = grd_score < THRESHOLD_HIGH_SEV
    hard_fail = num_high_sev or grd_high_sev
    passed = (weighted >= THRESHOLD_WEIGHTED) and (not hard_fail)
    thresholds = {
        "weighted_passed_min": THRESHOLD_WEIGHTED,
        "high_sev_threshold": THRESHOLD_HIGH_SEV,
        "numerical_high_sev_breach": num_high_sev,
        "grounding_high_sev_breach": grd_high_sev,
    }
    return passed, weighted, thresholds


# ---------------------------------------------------------------------------
# LangGraph 节点
# ---------------------------------------------------------------------------

async def reflection_agent_node(state: AnalysisState) -> dict:
    """V5 契约化 Reflection 节点。"""
    t_start = time.monotonic()
    logger.info("开始执行（契约化 V5）")
    writer = get_stream_writer()
    writer({"type": "progress", "node": "reflection_agent", "message": "正在进行 4 项质量契约审核..."})

    report = state.get("report")
    data_sources = state.get("data_sources") or []
    aggregator_summary = state.get("aggregator_summary") or ""
    question = state.get("question") or ""
    current_retries = state.get("reflection_retries", 0)
    next_retries = current_retries + 1

    # 无报告 → 直接判未过
    if not report:
        logger.warning("无报告可供审核")
        return {
            "reflection_passed": False,
            "reflection_retries": next_retries,
            "reflection_feedback": json.dumps(
                {"version": "v5_contract", "passed": False, "summary": "No report to validate",
                 "issues": [], "scores": {k: 0 for k in WEIGHTS} | {"weighted": 0}},
                ensure_ascii=False,
            ),
            "reflection_scores": {k: 0 for k in list(WEIGHTS)} | {"weighted": 0},
            "reflection_contract": {
                "version": "v5", "weights": WEIGHTS,
                "scores": {k: 0 for k in WEIGHTS}, "weighted": 0,
                "thresholds": {},
                "dimensions": {k: {"score": 0, "issues": [], "high_sev_breach": False}
                               for k in WEIGHTS},
                "passed": False,
            },
        }

    # 步骤 1：确定性 Numerical
    nr = check_numerical_consistency(report, data_sources)
    num_score = nr.score
    num_issues, num_high_sev = _build_numerical_issues(nr)

    # 步骤 2：确定性 Grounding
    gr = check_report_grounding(report, data_sources)
    grd_score = int(round(gr.evidence_coverage * 100))
    grd_issues, grd_high_sev_prev = _build_grounding_issues(gr)
    # _build_grounding_issues 里可能已经把 score 写入 gr，重新取一次避免重复判定
    grd_high_sev = grd_score < THRESHOLD_HIGH_SEV

    # 步骤 3：LLM Reasoning + Alignment
    reasoning_blk, alignment_blk = _llm_judge_reasoning_alignment(
        question=question,
        report=report,
        aggregator_summary=aggregator_summary,
        numerical_score=num_score,
        grounding_score=grd_score,
        numerical_issue_count=len(num_issues),
        grounded_claims=gr.grounded_claims,
        total_claims=gr.total_claims,
    )
    reasoning_score = int(reasoning_blk["score"])
    reasoning_issues = _normalize_llm_issues(reasoning_blk.get("issues", []), "reasoning")
    alignment_score = int(alignment_blk["score"])
    alignment_issues = _normalize_llm_issues(alignment_blk.get("issues", []), "alignment")

    # 步骤 4：综合判定
    passed, weighted, thresholds = _contract_verdict(
        num_score, grd_score, reasoning_score, alignment_score
    )

    # 步骤 5：组装 reflection_contract（新 schema，结构化）
    scores = {
        "numerical": num_score,
        "grounding": grd_score,
        "reasoning": reasoning_score,
        "alignment": alignment_score,
    }
    all_issues = num_issues + grd_issues + reasoning_issues + alignment_issues
    contract = {
        "version": "v5",
        "weights": dict(WEIGHTS),
        "scores": scores,
        "weighted": weighted,
        "thresholds": thresholds,
        "grounding_detail": {  # eval_runner 用到
            "evidence_coverage": gr.evidence_coverage,
            "total_claims": gr.total_claims,
            "grounded_claims": gr.grounded_claims,
        },
        "numerical_detail": {
            "coverage": nr.coverage,
            "total_report_numbers": nr.total_report_numbers,
            "matched_numbers": nr.matched_numbers,
        },
        "dimensions": {
            "numerical":  {"score": num_score,       "issues": num_issues,        "high_sev_breach": num_high_sev},
            "grounding":  {"score": grd_score,       "issues": grd_issues,        "high_sev_breach": grd_high_sev},
            "reasoning":  {"score": reasoning_score, "issues": reasoning_issues,  "high_sev_breach": reasoning_score < THRESHOLD_HIGH_SEV},
            "alignment":  {"score": alignment_score, "issues": alignment_issues,  "high_sev_breach": alignment_score < THRESHOLD_HIGH_SEV},
        },
        "passed": passed,
    }

    scores_with_weighted = dict(scores); scores_with_weighted["weighted"] = weighted

    summary = (
        f"{'✅ 契约通过' if passed else '❌ 契约未通过'}"
        f" | 加权综合 {weighted:.1f} / 阈值 ≥ {THRESHOLD_WEIGHTED}"
        f" | 数值 {num_score} / 证据 {grd_score} / 推理 {reasoning_score} / 对齐 {alignment_score}"
        + (f" | ⚠️ HIGH-SEV: Numerical{'<50' if num_high_sev else ''}"
           f"{' Grounding<50' if grd_high_sev else ''}" if (num_high_sev or grd_high_sev) else "")
    )

    # 兼容老 schema（有 passed/issues/summary 三个字段，保留原 category 枚举）
    legacy_feedback = {
        "version": "v5_contract",
        "passed": passed,
        "summary": summary,
        "issues": all_issues,
        "scores": scores_with_weighted,
        "contract": contract,
    }

    elapsed = time.monotonic() - t_start
    logger.info("执行完成 (%.1fs)  passed=%s weighted=%.1f num=%d grd=%d rea=%d ali=%d",
                elapsed, passed, weighted,
                num_score, grd_score, reasoning_score, alignment_score)

    return {
        "reflection_passed": passed,
        "reflection_retries": next_retries,
        "reflection_feedback": json.dumps(legacy_feedback, ensure_ascii=False),
        "reflection_scores": scores_with_weighted,
        "reflection_contract": contract,
    }
