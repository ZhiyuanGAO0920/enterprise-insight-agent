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
# 评估函数
# ---------------------------------------------------------------------------


def check_dimension_coverage(report: str, expected: list[str]) -> float:
    """检查报告覆盖了多少个期望维度。

    Returns:
        0.0-1.0 的覆盖率分数。
    """
    if not expected:
        return 1.0  # 无期望维度时跳过
    report_lower = report.lower()
    hits = sum(1 for dim in expected if dim.lower() in report_lower)
    return hits / len(expected)


def check_result_rows(report: str, min_rows: int, max_rows: int) -> bool:
    """粗略估算报告中的数据行数（统计 Markdown 表格行）。"""
    table_rows = sum(1 for line in report.split("\n") if line.strip().startswith("|") and "---" not in line)
    data_rows = max(0, table_rows - 1)
    return min_rows <= data_rows <= max_rows


def check_no_hallucination(report: str) -> bool:
    """检查报告中是否有明显的幻觉信号。"""
    hallucination_signals = [
        "100% 准确",
    ]
    report_lower = report.lower()
    for signal in hallucination_signals:
        if signal.lower() in report_lower:
            return False
    return True


# ---------------------------------------------------------------------------
# V4.6.2：数值交叉校验（事实级幻觉检测）
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*([万亿]?)")
_YEAR_MIN, _YEAR_MAX = 1900, 2100

# 全量表清单：17 张 ORM 表（app/database/models.py）+ 4 张原生 SQL 表（迁移 003）
KNOWN_TABLES = {
    "alert_rules", "alerts", "analysis_history", "audit_log", "employee_performance",
    "member", "orders", "permissions", "role_permissions", "roles", "store", "tenants",
    "user_roles", "user_store_access", "user_wechat_bindings", "users", "weekly_reports",
    "supplier", "product", "inventory", "purchase_order",
}


def extract_numbers(text: str) -> list[float]:
    """从文本中提取数字（去千分位逗号、处理 万/亿 单位、排除年份区间）。

    示例："华东区销售额 1,280,000 元（12.8万）" -> [1280000.0, 128000.0]
    """
    out = []
    for m in _NUM_RE.finditer(text):
        s, unit = m.group(1), m.group(2)
        try:
            v = float(s.replace(",", ""))
        except ValueError:
            continue
        if unit == "万":
            v *= 1e4
        elif unit == "亿":
            v *= 1e8
        if _YEAR_MIN <= v <= _YEAR_MAX and v == int(v):
            continue  # 排除年份/日期类数字
        out.append(round(v, 2))
    return out


def cross_check_report(report: str, sources: list[dict], question: str) -> dict:
    """数值交叉校验：报告中的关键数字必须能在数据来源中找到出处。

    两级校验（V4.6.3 升级为「算术审计」）：
    1. 直接匹配：数字在 SQL 执行结果 / SQL 文本 / 用户问题 / 结果表合计 / 均值 中出现
       （相对容差 0.5%，覆盖万/亿改写）。
    2. 派生匹配：找不到出处的数字，用源数据重算常见派生公式验证——
       差（|a-b|）、比率（a/b 与 a/b*100 百分数形式）、增长百分率 ((a-b)/b*100)、
       乘积（a*b）、均值。LLM 合法算出的合计/客单价/增长率/占比都能通过，
       而编造数字几乎不可能与任意真值的差/比/积在 0.5% 内重合。

    只校验「大整数（>=100）或带小数」的数字，规避序号/天数/小计数等噪音；
    两级都找不到出处的视为幻觉信号，返回 Top5 缺失数字供人工复核。
    无任何数据可校验（如边界拒绝类问题）时标记 skipped，不参与通过率。
    """
    allowed: set[float] = set()
    source_means: list[float] = []
    for s in sources:
        nums = extract_numbers(s.get("raw_data", ""))
        allowed.update(nums)
        if nums:
            # 每张结果表的合计值 / 均值（LLM 常把整表求和、求均值，属于合法派生）
            allowed.add(round(sum(nums), 2))
            source_means.append(round(sum(nums) / len(nums), 2))
        allowed.update(extract_numbers(s.get("sql", "")))
    allowed.update(extract_numbers(question))
    allowed.update(round(m, 2) for m in source_means)

    report_numbers = [n for n in extract_numbers(report) if n >= 100 or n != int(n)]
    if not allowed:
        return {"rate": None, "missing": [], "skipped": True, "total": len(report_numbers)}
    if not report_numbers:
        return {"rate": 1.0, "missing": [], "skipped": False, "total": 0}

    allowed_sorted = sorted(allowed)

    def _within(n: float, a: float) -> bool:
        return abs(n - a) <= 0.005 * max(abs(a), abs(n), 1.0)

    def _find(v: float) -> bool:
        """二分查找 allowed 中是否存在 0.5% 容差内的值。"""
        import bisect
        i = bisect.bisect_left(allowed_sorted, v)
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(allowed_sorted) and _within(v, allowed_sorted[j]):
                return True
        return False

    def _derived_match(n: float) -> bool:
        """用源数据重算派生公式：差 / 比率 / 百分率 / 增长百分率 / 乘积。"""
        if abs(n) < 1e-9:
            return False
        for a in allowed_sorted:
            if abs(a) < 1e-9:
                continue
            # 差：|a - b| ≈ n  →  b = a-n 或 a+n
            if _find(a - n) or _find(a + n):
                return True
            # 比率：a/b ≈ n（如客单价 956908.03/12606≈75.9）
            if _find(a / n):
                return True
            # 百分率：a/b*100 ≈ n（如占比 43251.44/956908.03*100≈4.52）
            if _find(a * 100.0 / n):
                return True
            # 增长百分率：(a-b)/b*100 ≈ n → a/b*100 = n+100
            if _find(a * 100.0 / (n + 100.0)):
                return True
            # 乘积：a*b ≈ n
            if _find(n / a):
                return True
        return False

    missing = []
    for n in report_numbers:
        found = _find(n) or _derived_match(n)
        if not found:
            missing.append(n)
    missing.sort(reverse=True)
    return {
        "rate": (len(report_numbers) - len(missing)) / len(report_numbers),
        "missing": missing[:5],
        "skipped": False,
        "total": len(report_numbers),
    }


def compute_sql_accuracy(sources: list[dict]) -> dict:
    """SQL 执行成功率 + 表名白名单告警。

    - 执行失败：raw_data 以 [SQL_ERROR] 开头（sql_runner 的错误返回格式）
    - 表名告警：用 sql_runner._get_outermost_tables 提取外层 FROM 表名，不在白名单则告警
      （CTE/子查询引用不提取，只告警不判失败 —— 语义级"查对表"需 golden SQL，超出本指标范围，
      由 LLM-as-Judge 的 accuracy 维度覆盖）
    """
    total = len(sources)
    failed = 0
    unknown_tables: list[str] = []
    try:
        from app.tools.sql_runner import _get_outermost_tables
    except Exception:
        _get_outermost_tables = None
    for s in sources:
        raw = s.get("raw_data", "")
        if raw.startswith("[SQL_ERROR"):
            failed += 1
            continue
        if _get_outermost_tables is None:
            continue
        sql = s.get("sql", "")
        # CTE 名（WITH x AS / RECURSIVE / , y AS）不出现在 FROM 的白名单检查里
        cte_names = set(re.findall(
            r"\b(?:WITH|,)\s+(?:RECURSIVE\s+)?([a-zA-Z_]\w*)\s+AS\b", sql, re.IGNORECASE
        ))
        try:
            for t in _get_outermost_tables(sql):
                # 过滤 CTE 名与疑似别名（子查询别名如 FROM (...) t，sqlparse 会误提取）
                if len(t) < 3:
                    continue
                if t.lower() not in KNOWN_TABLES and t not in cte_names:
                    unknown_tables.append(t)
        except Exception:
            pass
    if total == 0:
        return {"total": 0, "failed": 0, "rate": None, "unknown_tables": []}
    return {
        "total": total,
        "failed": failed,
        "rate": (total - failed) / total,
        "unknown_tables": sorted(set(unknown_tables)),
    }


def classify_reflection(feedback_json: str | None, passed: bool) -> str:
    """质检状态四分类：passed / failed / parsing_fallback / skipped。

    - skipped：无 feedback（简单查询按设计跳过质检）
    - parsing_fallback：Reflection 未输出结构化结果，兜底按通过（summary 含 PARSING_FALLBACK）
    - passed / failed：真实质检结论
    """
    if not feedback_json:
        return "skipped"
    try:
        fb = json.loads(feedback_json)
    except Exception:
        fb = {}
    if "PARSING_FALLBACK" in str(fb.get("summary", "")):
        return "parsing_fallback"
    return "passed" if passed else "failed"


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
        analyze_data = json.dumps({"question": question["question"], "skip_reflection": skip_reflection}).encode()
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
            "reflection_status": (
                "ablation" if skip_reflection else classify_reflection(
                    data.get("reflection_feedback"), data.get("reflection_passed", False)
                )
            ),
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
# 报告输出
# ---------------------------------------------------------------------------


def compute_metrics(results: list[dict]) -> dict:
    """从结果列表中汇总核心指标。"""
    total = len(results)
    failed = sum(1 for r in results if r.get("error"))
    passed = total - failed

    dim_scores = [r["dimension_coverage"] for r in results if "dimension_coverage" in r]
    rows_ok = sum(1 for r in results if r.get("rows_in_range"))
    no_hall = sum(1 for r in results if r.get("no_hallucination"))
    avg_latency = sum(r.get("latency_ms", 0) for r in results) / max(total, 1)

    # ---- 数值交叉校验（skipped 不参与统计） ----
    # V4.6.3 算术审计后统一判罪阈值 <0.6：派生数字（差/比/百分率/乘积/均值）
    # 已能用源数据重算验证，健康报告（含 analysis）实测 0.93-1.0。
    cross_rates = [
        r["cross_check"]["rate"] for r in results
        if r.get("cross_check") and r["cross_check"].get("rate") is not None
    ]
    cross_fail = sum(1 for rate in cross_rates if rate < 0.6)
    cross_skipped = sum(1 for r in results if r.get("cross_check") and r["cross_check"].get("skipped"))

    # ---- SQL 执行成功率（无 SQL 的问题不参与） ----
    sql_rates = [
        r["sql_accuracy"]["rate"] for r in results
        if r.get("sql_accuracy") and r["sql_accuracy"].get("rate") is not None
    ]
    sql_failed = sum(r["sql_accuracy"]["failed"] for r in results if r.get("sql_accuracy"))
    sql_total = sum(r["sql_accuracy"]["total"] for r in results if r.get("sql_accuracy"))

    # ---- Reflection 四分类（修复监控指标失真的核心） ----
    rstatus = [r.get("reflection_status") for r in results]
    r_counts = {s: rstatus.count(s) for s in ("passed", "failed", "parsing_fallback", "skipped", "ablation")}
    r_counted = r_counts["passed"] + r_counts["failed"] + r_counts["parsing_fallback"]
    reflect_strict_pass = (r_counts["passed"] / r_counted) if r_counted else None
    reflect_effective_pass = (
        (r_counts["passed"] + r_counts["parsing_fallback"]) / r_counted if r_counted else None
    )

    # ---- LLM-as-Judge ----
    judge_dims = ("accuracy", "logic", "actionability", "completeness")
    judge_entries = [r["judge"] for r in results if r.get("judge")]
    judge_avg = {
        d: round(sum(j["scores"].get(d, 0) for j in judge_entries) / max(len(judge_entries), 1), 2)
        for d in judge_dims
    } if judge_entries else {}
    judge_pass_rate = round(
        sum(1 for j in judge_entries if j.get("pass")) / max(len(judge_entries), 1) * 100, 1
    ) if judge_entries else None

    by_type = {}
    for r in results:
        t = r.get("type", "unknown")
        if t not in by_type:
            by_type[t] = {"total": 0, "failed": 0, "dim_coverage": [], "latencies": []}
        by_type[t]["total"] += 1
        if r.get("error"):
            by_type[t]["failed"] += 1
        if "dimension_coverage" in r:
            by_type[t]["dim_coverage"].append(r["dimension_coverage"])
        if "latency_ms" in r:
            by_type[t]["latencies"].append(r["latency_ms"])

    type_summary = {}
    for t, v in by_type.items():
        type_summary[t] = {
            "total": v["total"],
            "failed": v["failed"],
            "avg_dim_coverage": round(sum(v["dim_coverage"]) / max(len(v["dim_coverage"]), 1), 3),
            "avg_latency_ms": int(sum(v["latencies"]) / max(len(v["latencies"]), 1)),
        }

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / max(total, 1) * 100, 1),
        "avg_dimension_coverage": round(sum(dim_scores) / max(len(dim_scores), 1), 3),
        "rows_in_range_rate": round(rows_ok / max(total, 1) * 100, 1),
        "no_hallucination_rate": round(no_hall / max(total, 1) * 100, 1),
        "cross_check_rate": round(sum(cross_rates) / max(len(cross_rates), 1), 3),
        "cross_check_failures": cross_fail,
        "cross_check_skipped": cross_skipped,
        "sql_accuracy": round(sum(sql_rates) / max(len(sql_rates), 1), 3),
        "sql_failed_count": sql_failed,
        "sql_total_count": sql_total,
        "reflection_status_counts": r_counts,
        "reflection_strict_pass_rate": round(reflect_strict_pass * 100, 1) if reflect_strict_pass is not None else None,
        "reflection_effective_pass_rate": round(reflect_effective_pass * 100, 1) if reflect_effective_pass is not None else None,
        "judge_avg_scores": judge_avg,
        "judge_pass_rate": judge_pass_rate,
        "avg_latency_ms": int(avg_latency),
        "by_type": type_summary,
    }


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

    asyncio.run(run_all())


if __name__ == "__main__":
    main()
