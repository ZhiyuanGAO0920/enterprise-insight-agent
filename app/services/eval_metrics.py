"""离线评估的纯指标函数 —— run_eval.py 与金丝雀闭环（app/api/routes/eval.py）共享。

V4.7 抽取：指标逻辑原在 tests/run_eval.py，金丝雀端点需要同一套口径
（compute_metrics / cross_check / classify_reflection 等）判定漂移，
故抽到 app/services 保证单一事实来源。全部为纯函数，无 I/O 副作用。
"""

import json
import re

# ---------------------------------------------------------------------------
# 基础规则检查
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
# 指标汇总（compute_metrics 与 run_eval.print_report 共用口径）
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
