"""离线评估脚本 — 在修改 Prompt 后运行以量化验证分析质量。

用法：
    python tests/run_eval.py                       # 跑全部 102 条
    python tests/run_eval.py --type lookup         # 只跑查询型
    python tests/run_eval.py --type analysis       # 只跑分析型
    python tests/run_eval.py --id Q01              # 只跑单条
    python tests/run_eval.py --parallel 5          # 并发 5 条（默认串行）
    python tests/run_eval.py --judge               # 分析型追加 LLM-as-Judge 深度评分
    python tests/run_eval.py --judge-all           # 全部类型追加 LLM-as-Judge 评分
    python tests/run_eval.py --skip-reflection     # 对照实验：跳过质检与重试（量化质检价值）
    python tests/run_eval.py --output result.json  # 输出结果到 JSON
    python tests/run_eval.py --compare baseline.json  # 与基线对比
    python tests/run_eval.py --canary             # 只跑金丝雀子集（eval_set.json 中 canary=true 的固定抽样）
    python tests/run_eval.py --save-db            # 结果落库 eval_runs（带 model_version），自动对比上一次基线计算漂移

指标说明（V4.6.2 升级）：
    1. dimension_coverage   —— 规则：期望维度关键词覆盖
    2. rows_in_range        —— 规则：报告表格行数区间
    3. cross_check_rate     —— 数值交叉校验：报告数字必须能在 SQL 执行结果中找到出处
                              （取代单一关键词的"无幻觉"信号；无数据可校验时标记 skipped）
    4. sql_accuracy         —— SQL 执行成功率（[SQL_ERROR] 计数）+ 表名白名单告警
    5. reflection_status    —— 质检三态：passed / failed / parsing_fallback（解析兜底视为过）/ skipped
    6. judge_*              —— LLM-as-Judge 深度评分（--judge 时启用，4 维 1-5 分）
    7. latency_ms           —— 端到端延迟
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 绕过代理（同启动脚本）
os.environ["NO_PROXY"] = "api.deepseek.com,localhost,127.0.0.1"
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)


# ---------------------------------------------------------------------------
# 评估函数 —— 指标逻辑已抽至 app/services/eval_metrics.py（金丝雀闭环共用同一口径）
# ---------------------------------------------------------------------------

from app.services.eval_metrics import (  # noqa: E402
    check_dimension_coverage,
    check_no_hallucination,
    check_result_rows,
    classify_reflection,
    compute_evidence_coverage,   # V5 T-10a: Claim-level grounding
    compute_metrics,
    compute_sql_accuracy,
    cross_check_report,
)


# V4.6.2 数值交叉校验 / SQL 准确率 / Reflection 分类 / 指标汇总 —— 已迁至 app/services/eval_metrics.py


# ---------------------------------------------------------------------------
# LLM-as-Judge（--judge 时启用）：对报告做 4 维深度评分
# ---------------------------------------------------------------------------

JUDGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "judge_result",
        "description": "Output the quality judge scores for the analysis report",
        "parameters": {
            "type": "object",
            "properties": {
                "scores": {
                    "type": "object",
                    "properties": {
                        "accuracy": {"type": "number", "description": "数据准确性（数字/结论是否与报告内数据一致，1-5）"},
                        "logic": {"type": "number", "description": "逻辑严谨性（归因是否有依据、有无过度推断，1-5）"},
                        "actionability": {"type": "number", "description": "可操作性（建议是否具体可执行，1-5）"},
                        "completeness": {"type": "number", "description": "完整性（是否完整回答用户问题，1-5）"},
                    },
                    "required": ["accuracy", "logic", "actionability", "completeness"],
                },
                "pass": {"type": "boolean", "description": "该报告是否达到合格线（综合 >= 3 分）"},
                "rationale": {"type": "string", "description": "一句话评分依据"},
            },
            "required": ["scores", "pass", "rationale"],
        },
    },
}

JUDGE_SYSTEM_PROMPT = (
    "你是连锁零售经营分析领域的资深质检专家。你会收到一条用户问题和系统生成的经营分析报告。\n"
    "请从 4 个维度对报告质量打分（1-5 分，5 最好），并判定是否合格（pass）。\n"
    "1. accuracy 数据准确性：报告中的数字与结论是否自洽、有无明显编造或自相矛盾。\n"
    "2. logic 逻辑严谨性：归因和结论是否有数据依据、是否过度推断。\n"
    "3. actionability 可操作性：建议是否具体、可执行、有优先级。\n"
    "4. completeness 完整性：是否完整回答了用户问题，有无遗漏关键维度。\n"
    "只依据报告内容本身评分，不要假设报告之外的数据。"
)


async def judge_report(question: str, report: str, llm) -> dict | None:
    """调用 LLM 对报告做 4 维评分。tool_calls 优先，文本 JSON 兜底；失败返回 None。"""
    from app.agents.reflection_agent import _extract_json
    from langchain_core.messages import HumanMessage, SystemMessage

    messages = [
        SystemMessage(content=JUDGE_SYSTEM_PROMPT),
        HumanMessage(content=f"## 用户问题\n{question}\n\n## 分析报告\n{report[:18000]}"),
    ]
    try:
        resp = await llm.bind_tools([JUDGE_SCHEMA]).ainvoke(messages)
        if resp.tool_calls:
            return resp.tool_calls[0]["args"]
        parsed = _extract_json(resp.content or "")
        if parsed:
            return parsed
    except Exception as e:
        print(f"    [judge 失败: {str(e)[:80]}]")
    return None


# ---------------------------------------------------------------------------
# 异步并发执行
# ---------------------------------------------------------------------------


async def run_single_eval(
    question: dict, token: str, port: int,
    sem: asyncio.Semaphore | None = None,
    judge: bool = False,
    judge_llm=None,
    skip_reflection: bool = False,
) -> dict:
    """对单条问题运行评估。

    Args:
        question: eval_set 中的问题条目。
        token: 登录令牌。
        port: V4 服务端口。
        sem: 并发信号量。
        judge: 是否追加 LLM-as-Judge 深度评分（失败不影响主指标）。
        judge_llm: 复用的 Judge LLM 实例（judge=True 时由调用方创建）。
        skip_reflection: 对照实验 —— 请求服务跳过质检与重试（reflection_status 记为 ablation）。
    """
    import urllib.request

    async def _run():
        # bypass_cache=true：评估必须每次真实执行——命中 Redis 缓存会测不出漂移，
        # 且评估结果也不应污染生产缓存（V4.7 起评估请求绕过缓存读写）
        analyze_data = json.dumps({
            "question": question["question"],
            "skip_reflection": skip_reflection,
            "bypass_cache": True,
        }).encode()
        req = urllib.request.Request(
            f"http://localhost:{port}/api/v1/analysis/analyze",
            data=analyze_data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )

        t_start = time.monotonic()
        try:
            resp = urllib.request.urlopen(req, timeout=120)
            data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {
                "id": question["id"],
                "type": question.get("type"),
                "question": question["question"][:60],
                "error": str(e),
                "latency_ms": int((time.monotonic() - t_start) * 1000),
            }

        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        report = data.get("report") or ""
        errors = data.get("agent_errors", [])
        sources = data.get("data_sources", [])

        sqls = [s.get("sql", "") for s in sources if s.get("sql")]

        result: dict = {
            "id": question["id"],
            "type": question["type"],
            "question": question["question"][:80],
            "report_length": len(report),
            "dimension_coverage": check_dimension_coverage(report, question.get("expected_dimensions", [])),
            "rows_in_range": check_result_rows(report, question.get("min_result_rows", 0), question.get("max_result_rows", 999)),
            "no_hallucination": check_no_hallucination(report),
            "cross_check": cross_check_report(report, sources, question.get("question", "")),
            "sql_accuracy": compute_sql_accuracy(sources),
            # V5 T-10a: Claim-level Grounding（零 LLM，纯确定性）
            "grounding": (gr := compute_evidence_coverage(report, sources)),
            "evidence_coverage": gr["evidence_coverage"],
            "reflection_status": (
                "ablation" if skip_reflection else classify_reflection(
                    data.get("reflection_feedback"), data.get("reflection_passed", False)
                )
            ),
            # V5 Phase 3：Reflection 契约 4 维度分 & contract 明细（随 eval 结果持久化，下次 eval 自动有 4 维分做相关性分析）
            "reflection_scores": data.get("reflection_scores"),
            "reflection_contract": data.get("reflection_contract"),
            "sql_count": len(sqls),
            "sqls": sqls[:3],
            "errors": len(errors),
            "error_details": [f"{e['agent']}: {e.get('user_message', e.get('error', ''))[:80]}" for e in errors[:3]],
            "reflection_passed": data.get("reflection_passed"),
            "data_source_count": len(sources),
            "latency_ms": elapsed_ms,
        }

        if judge and report and judge_llm is not None:
            judge_result = await judge_report(question.get("question", ""), report, judge_llm)
            if judge_result:
                result["judge"] = judge_result

        return result

    if sem:
        async with sem:
            return await _run()
    else:
        return await _run()


# ---------------------------------------------------------------------------
# 结果落库（V4.7 金丝雀闭环）：eval_runs 表 + 漂移对比
# ---------------------------------------------------------------------------


async def save_run_to_db(metrics: dict, model_version: str, canary: bool, results_file: str | None = None) -> dict:
    """将本次评估结果落库 eval_runs，并对比上一次同模型、同类型的运行计算漂移信号。

    - 漂移判定阈值与 print_report 的 --compare 一致：通过率 -5%、维度覆盖率 -10%、延迟 +5s，
      另加 Reflection 严格通过率 -8%（金丝雀重点盯质检质量）。
    - 模型版本变更时不比较（基线切换本身需要人关注，另行提示）。
    """
    from sqlalchemy import select

    from app.database.connection import get_session
    from app.database.models import EvalRun

    session = get_session()
    try:
        res = await session.execute(
            select(EvalRun)
            .where(EvalRun.canary == canary)
            .order_by(EvalRun.run_at.desc())
            .limit(1)
        )
        prev = res.scalar_one_or_none()

        drift = False
        summary = ""
        if prev is not None:
            if prev.model_version == model_version:
                parts = []
                pass_diff = metrics["pass_rate"] - prev.pass_rate
                if pass_diff < -5:
                    drift = True
                    parts.append(f"通过率 {prev.pass_rate:.1f}% -> {metrics['pass_rate']:.1f}% ({pass_diff:+.1f}%)")
                dim_diff = (metrics["avg_dimension_coverage"] - prev.dimension_coverage) * 100
                if dim_diff < -10:
                    drift = True
                    parts.append(f"维度覆盖率下降 {dim_diff:+.1f}%")
                lat_diff = metrics["avg_latency_ms"] - prev.avg_latency_ms
                if lat_diff > 5000:
                    drift = True
                    parts.append(f"平均延迟 +{lat_diff / 1000:.0f}s")
                cur_sr = metrics.get("reflection_strict_pass_rate")
                if prev.reflection_strict_pass_rate is not None and cur_sr is not None:
                    r_diff = cur_sr - prev.reflection_strict_pass_rate
                    if r_diff < -8:
                        drift = True
                        parts.append(f"Reflection 严格通过率 {r_diff:+.1f}%")
                summary = "；".join(parts) if parts else "无显著退化"
            else:
                summary = f"模型变更 {prev.model_version} -> {model_version}，基线切换，本次不比较"
        else:
            summary = "首次运行，基线建立"

        run = EvalRun(
            run_at=datetime.now(timezone.utc).replace(tzinfo=None),  # 与 models._utcnow 一致（naive UTC）
            model_version=model_version,
            canary=canary,
            total=metrics["total"],
            passed=metrics["passed"],
            failed=metrics["failed"],
            pass_rate=metrics["pass_rate"],
            dimension_coverage=metrics.get("avg_dimension_coverage"),
            cross_check_rate=metrics.get("cross_check_rate"),
            sql_accuracy=metrics.get("sql_accuracy"),
            reflection_strict_pass_rate=metrics.get("reflection_strict_pass_rate"),
            reflection_effective_pass_rate=metrics.get("reflection_effective_pass_rate"),
            avg_latency_ms=metrics.get("avg_latency_ms"),
            drift=drift,
            drift_summary=summary,
            metrics_json=metrics,
            results_file=results_file,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return {"run_id": run.id, "drift": drift, "summary": summary}
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------


def print_report(results: list[dict], baseline: dict | None = None):
    """打印格式化的评估报告，可选与基线对比。"""
    metrics = compute_metrics(results)

    print()
    print("=" * 70)
    print("  V4 Agent 离线评估报告")
    print("=" * 70)

    print(f"  完成: {metrics['passed']}/{metrics['total']}  "
          f"失败: {metrics['failed']}/{metrics['total']}  "
          f"通过率: {metrics['pass_rate']}%")
    print(f"  维度覆盖率:      {metrics['avg_dimension_coverage']*100:.1f}%  "
          f"行数合理: {metrics['rows_in_range_rate']:.0f}%")
    print(f"  数值交叉校验:    {metrics['cross_check_rate']*100:.1f}%"
          f"（{metrics['cross_check_failures']} 条存疑，{metrics['cross_check_skipped']} 条跳过）")
    print(f"  SQL 执行成功率:  {metrics['sql_accuracy']*100:.1f}%"
          f"（失败 {metrics['sql_failed_count']}/{metrics['sql_total_count']}）")
    rs = metrics["reflection_status_counts"]
    sr = metrics["reflection_strict_pass_rate"]
    er = metrics["reflection_effective_pass_rate"]
    sr_txt = f"{sr:.0f}%" if sr is not None else "-"
    er_txt = f"{er:.0f}%" if er is not None else "-"
    print(f"  Reflection:      严格通过 {sr_txt} / "
          f"含兜底 {er_txt}"
          f"（过 {rs['passed']} / 未过 {rs['failed']} / 解析兜底 {rs['parsing_fallback']} / "
          f"跳过 {rs['skipped']}"
          + (f" / 对照跳过 {rs['ablation']}" if rs.get("ablation") else "")
          + "）")
    if metrics.get("judge_avg_scores"):
        ja = metrics["judge_avg_scores"]
        print(f"  Judge 深度评分:  准确 {ja.get('accuracy', 0):.1f} / 逻辑 {ja.get('logic', 0):.1f} / "
              f"可操作 {ja.get('actionability', 0):.1f} / 完整 {ja.get('completeness', 0):.1f}  "
              f"合格率 {metrics['judge_pass_rate']:.0f}%")
    print(f"  平均延迟: {metrics['avg_latency_ms']/1000:.1f}s")
    print("-" * 70)

    if baseline:
        b = baseline
        print("  [与基线对比]")
        changes = []
        pass_diff = metrics['pass_rate'] - b.get('pass_rate', 0)
        changes.append(f"通过率: {b.get('pass_rate', 0):.1f}% -> {metrics['pass_rate']:.1f}% ({'+' if pass_diff>=0 else ''}{pass_diff:.1f}%)")
        dim_diff = (metrics['avg_dimension_coverage'] - b.get('avg_dimension_coverage', 0)) * 100
        changes.append(f"维度覆盖率: {b.get('avg_dimension_coverage', 0)*100:.1f}% -> {metrics['avg_dimension_coverage']*100:.1f}% ({'+' if dim_diff>=0 else ''}{dim_diff:.1f}%)")
        lat_diff = metrics['avg_latency_ms'] - b.get('avg_latency_ms', 0)
        changes.append(f"平均延迟: {b.get('avg_latency_ms', 0)/1000:.1f}s -> {metrics['avg_latency_ms']/1000:.1f}s ({'+' if lat_diff>=0 else ''}{lat_diff}ms)")
        for c in changes:
            print(f"    {c}")

        regressions = []
        if pass_diff < -5:
            regressions.append("通过率下降超过 5%")
        if dim_diff < -10:
            regressions.append("维度覆盖率下降超过 10%")
        if lat_diff > 5000:
            regressions.append("平均延迟增加超过 5 秒")
        if regressions:
            print()
            for r in regressions:
                print(f"  {r}")
        else:
            print("  无显著退化")
        print("-" * 70)

    for qtype in ["lookup", "analysis", "edge"]:
        type_results = [r for r in results if r.get("type") == qtype]
        if not type_results:
            continue
        type_dim = sum(r.get("dimension_coverage", 0) for r in type_results) / len(type_results)
        type_latency = sum(r.get("latency_ms", 0) for r in type_results) / len(type_results)
        type_fail = sum(1 for r in type_results if r.get("error"))
        print(f"  [{qtype:8s}] {len(type_results)} 条 | 失败 {type_fail} | "
              f"覆盖率 {type_dim*100:.0f}% | 平均 {type_latency/1000:.1f}s")

    print("-" * 70)

    for r in results:
        dim_pct = r.get("dimension_coverage", 0) * 100
        cross = r.get("cross_check") or {}
        cross_mark = ""
        if cross.get("rate") is not None:
            if cross["rate"] < 0.6:
                cross_mark = f" | CROSS_CHECK {cross['rate']*100:.0f}%（缺失: {cross.get('missing', [])[:3]}）"
            elif cross["rate"] < 0.9:
                cross_mark = f" | cross={cross['rate']*100:.0f}%（缺失待复核: {cross.get('missing', [])[:3]}）"
        status = "OK" if not r.get("error") and r.get("rows_in_range") and r.get("no_hallucination") else "!!"
        error_info = f" | ERROR: {r['error']}" if r.get("error") else ""
        row_mark = "" if r.get("rows_in_range") else " | ROWS_OOB"
        hall_mark = "" if r.get("no_hallucination") else " | HALL?"
        sql_fail = ""
        sa = r.get("sql_accuracy") or {}
        if sa.get("failed"):
            sql_fail = f" | SQL_FAIL {sa['failed']}/{sa['total']}"
        ut = sa.get("unknown_tables") or []
        ut_mark = f" | UNKNOWN_TBL {ut}" if ut else ""
        print(
            f"  {status} {r['id']} [{r.get('type','?'):8s}] "
            f"dim={dim_pct:.0f}% lat={r.get('latency_ms',0)/1000:.1f}s"
            f"{row_mark}{hall_mark}{sql_fail}{ut_mark}{cross_mark}{error_info}"
        )

    print("=" * 70)

    rows_ok = sum(1 for r in results if r.get("rows_in_range"))
    no_hall = sum(1 for r in results if r.get("no_hallucination"))
    dim_scores = [r["dimension_coverage"] for r in results if "dimension_coverage" in r]
    cross_rates = [
        r["cross_check"]["rate"] for r in results
        if r.get("cross_check") and r["cross_check"].get("rate") is not None
    ]
    sql_rates = [
        r["sql_accuracy"]["rate"] for r in results
        if r.get("sql_accuracy") and r["sql_accuracy"].get("rate") is not None
    ]
    unknown_tables = sorted({
        t for r in results for t in (r.get("sql_accuracy") or {}).get("unknown_tables", [])
    })
    cross_by_type = {}
    for r in results:
        cc = r.get("cross_check")
        if not cc or cc.get("rate") is None:
            continue
        t = r.get("type", "unknown")
        cross_by_type.setdefault(t, []).append(cc["rate"])

    issues = []
    if rows_ok / max(len(results), 1) < 0.8:
        issues.append("行数检查通过率低于 80%，需要检查 Agent 是否在截断输出")
    if sum(dim_scores) / max(len(dim_scores), 1) < 0.7:
        issues.append("维度覆盖率低于 70%，需要检查 Prompt 是否遗漏了关键分析维度")
    if metrics["reflection_effective_pass_rate"] is not None and metrics["reflection_effective_pass_rate"] < 85:
        issues.append("Reflection 有效通过率低于 85%（含解析兜底），需检查质检 Agent 是否过严或报告质量下滑")
    if no_hall / max(len(results), 1) < 0.95:
        issues.append("幻觉信号检出率偏低，需检查报告是否有编造数据的情况")
    for t, rates in cross_by_type.items():
        avg = sum(rates) / len(rates)
        if avg < 0.6:
            issues.append(f"{t} 型数值交叉校验通过率 {avg*100:.0f}%（阈值 60%），报告数字存在无法溯源的情况（最可能是编造）")
    if sql_rates and sum(sql_rates) / len(sql_rates) < 0.8:
        issues.append("SQL 执行成功率低于 80%，Agent 生成的 SQL 存在语法/权限问题")
    if unknown_tables:
        issues.append(f"SQL 引用了白名单外的表名: {unknown_tables}，需检查 Schema 映射或补充白名单")

    if issues:
        print("\n  改进建议:")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
    else:
        print("\n  所有指标正常")
    print()


def main():
    parser = argparse.ArgumentParser(description="V4 Agent 离线评估")
    parser.add_argument("--type", choices=["lookup", "analysis", "edge"], help="只跑指定类型")
    parser.add_argument("--id", help="只跑指定 ID 的问题")
    parser.add_argument("--port", type=int, default=8002, help="V4 服务端口（默认 8002）")
    parser.add_argument("--output", help="输出评估结果到 JSON 文件")
    parser.add_argument("--parallel", type=int, default=0,
                        help="并发数（默认 0=串行; 建议 3-5 加速大规模评估）")
    parser.add_argument("--compare", help="与基线 JSON 文件对比（先前 --output 的结果）")
    parser.add_argument("--canary", action="store_true",
                        help="只跑金丝雀子集（eval_set.json 中 canary=true 的固定抽样，每周漂移检测用）")
    parser.add_argument("--save-db", action="store_true",
                        help="结果落库 eval_runs（带 model_version），自动对比上一次同模型运行计算漂移信号")
    parser.add_argument("--judge", action="store_true",
                        help="对 analysis 型问题追加 LLM-as-Judge 深度评分（约 +38 次 LLM 调用）")
    parser.add_argument("--judge-all", action="store_true",
                        help="对所有类型追加 LLM-as-Judge 深度评分")
    parser.add_argument("--skip-reflection", action="store_true",
                        help="对照实验：请求服务跳过 Reflection 质检与重试（需服务已部署 skip_reflection 参数），"
                             "与正常跑结果对比可量化质检价值")
    args = parser.parse_args()

    eval_path = Path(__file__).parent / "eval_set.json"
    with open(eval_path, "r", encoding="utf-8") as f:
        eval_set = json.load(f)

    questions = eval_set["questions"]
    if args.type:
        questions = [q for q in questions if q["type"] == args.type]
    if args.id:
        questions = [q for q in questions if q["id"] == args.id]
    if args.canary:
        canary_questions = [q for q in questions if q.get("canary")]
        print(f"  [金丝雀模式] 全量 {len(questions)} 条 -> 子集 {len(canary_questions)} 条（每周漂移检测）")
        questions = canary_questions

    print(f"\n  加载 {len(questions)} 条评估问题（来自 {eval_path}）")
    print(f"  目标服务: http://localhost:{args.port}")

    baseline = None
    if args.compare:
        compare_path = Path(args.compare)
        if compare_path.exists():
            with open(compare_path, "r", encoding="utf-8") as f:
                baseline_data = json.load(f)
            if isinstance(baseline_data, list):
                baseline = compute_metrics(baseline_data)
                print(f"  基线: {args.compare} ({baseline['total']} 条)")
            elif isinstance(baseline_data, dict) and "pass_rate" in baseline_data:
                baseline = baseline_data
                print(f"  基线: {args.compare} ({baseline['total']} 条)")
            else:
                print(f"  基线文件格式无法识别，跳过对比")
        else:
            print(f"  基线文件不存在: {args.compare}，跳过对比")

    async def run_all():
        import urllib.request

        login_data = json.dumps({"username": "admin", "password": "admin123"}).encode()
        try:
            req = urllib.request.Request(
                f"http://localhost:{args.port}/api/v1/auth/login",
                data=login_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=10)
            token = json.loads(resp.read().decode("utf-8"))["access_token"]
            print(f"  登录成功")
        except Exception as e:
            print(f"  登录失败: {e}")
            print(f"  请确保 V4 服务在端口 {args.port} 运行")
            return

        sem = asyncio.Semaphore(args.parallel) if args.parallel > 0 else None
        if sem:
            print(f"  并发模式: {args.parallel} 条并行")

        judge_enabled = args.judge or args.judge_all
        judge_llm = None
        if judge_enabled:
            from app.llm import create_llm
            judge_llm = create_llm(temperature=0.0)
            scope = "全部类型" if args.judge_all else "analysis 型"
            print(f"  Judge 深度评分: 启用（{scope}）")
        if args.skip_reflection:
            print("  对照实验: 跳过 Reflection（结果与正常跑对比可量化质检价值）")

        results = []
        total = len(questions)
        t_start = time.monotonic()
        for i, q in enumerate(questions, 1):
            print(f"  [{i:3d}/{total}] {q['id']:4s}: {q['question'][:50]:50s}...", end=" ", flush=True)
            need_judge = judge_enabled and (args.judge_all or q.get("type") == "analysis")
            result = await run_single_eval(q, token, args.port, sem, judge=need_judge, judge_llm=judge_llm, skip_reflection=args.skip_reflection)
            results.append(result)
            if result.get("error"):
                print("ERR")
            else:
                dim = result.get("dimension_coverage", 0) * 100
                print(f"OK dim={dim:.0f}% lat={result.get('latency_ms',0)/1000:.1f}s")

        elapsed = time.monotonic() - t_start
        print(f"\n  总耗时: {elapsed:.0f}s 平均: {elapsed/max(total,1):.1f}s/条")

        print_report(results, baseline)

        if args.output:
            output_path = Path(args.output)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"  结果已保存到 {output_path}")

            metrics = compute_metrics(results)
            metrics_path = output_path.with_suffix(".metrics.json")
            with open(metrics_path, "w", encoding="utf-8") as f:
                json.dump(metrics, f, ensure_ascii=False, indent=2)
            print(f"  Metrics 摘要已保存到 {metrics_path}")

        if args.save_db:
            metrics = compute_metrics(results)
            from app.config import get_settings
            model_version = get_settings().deepseek_model_name
            saved = await save_run_to_db(metrics, model_version, args.canary, args.output)
            # 注意：Windows 控制台默认 GBK，避免 ✓/⚠️ 等非 GBK 字符导致 UnicodeEncodeError
            drift_mark = "[DRIFT]" if saved["drift"] else "[OK]"
            print(f"  已落库 eval_runs#{saved['run_id']} | 模型 {model_version} | {drift_mark} | {saved['summary']}")

    asyncio.run(run_all())


if __name__ == "__main__":
    main()
