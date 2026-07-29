"""离线评估脚本 — 在修改 Prompt 后运行以量化验证分析质量。

用法：
    python tests/run_eval.py                       # 跑全部 102 条
    python tests/run_eval.py --type lookup         # 只跑查询型
    python tests/run_eval.py --type analysis       # 只跑分析型
    python tests/run_eval.py --id Q01              # 只跑单条
    python tests/run_eval.py --parallel 5          # 并发 5 条（默认串行）
    python tests/run_eval.py --output result.json  # 输出结果到 JSON
    python tests/run_eval.py --compare baseline.json  # 与基线对比
"""

import argparse
import asyncio
import json
import os
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
# 异步并发执行
# ---------------------------------------------------------------------------


async def run_single_eval(question: dict, token: str, port: int, sem: asyncio.Semaphore | None = None) -> dict:
    """对单条问题运行评估。"""
    import urllib.request

    async def _run():
        analyze_data = json.dumps({"question": question["question"]}).encode()
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
                "question": question["question"][:60],
                "error": str(e),
                "latency_ms": int((time.monotonic() - t_start) * 1000),
            }

        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        report = data.get("report") or ""
        errors = data.get("agent_errors", [])
        sources = data.get("data_sources", [])

        sqls = [s.get("sql", "") for s in sources if s.get("sql")]

        return {
            "id": question["id"],
            "type": question["type"],
            "question": question["question"][:80],
            "report_length": len(report),
            "dimension_coverage": check_dimension_coverage(report, question.get("expected_dimensions", [])),
            "rows_in_range": check_result_rows(report, question.get("min_result_rows", 0), question.get("max_result_rows", 999)),
            "no_hallucination": check_no_hallucination(report),
            "sql_count": len(sqls),
            "sqls": sqls[:3],
            "errors": len(errors),
            "error_details": [f"{e['agent']}: {e.get('user_message', e.get('error', ''))[:80]}" for e in errors[:3]],
            "reflection_passed": data.get("reflection_passed"),
            "data_source_count": len(sources),
            "latency_ms": elapsed_ms,
        }

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
    reflect_ok = sum(1 for r in results if r.get("reflection_passed"))
    avg_latency = sum(r.get("latency_ms", 0) for r in results) / max(total, 1)

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
        "reflection_pass_rate": round(reflect_ok / max(total, 1) * 100, 1),
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
          f"行数合理: {metrics['rows_in_range_rate']:.0f}%  "
          f"无幻觉: {metrics['no_hallucination_rate']:.0f}%")
    print(f"  Reflection 通过:  {metrics['reflection_pass_rate']:.0f}%  "
          f"平均延迟: {metrics['avg_latency_ms']/1000:.1f}s")
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
        status = "OK" if not r.get("error") and r.get("rows_in_range") and r.get("no_hallucination") else "!!"
        error_info = f" | ERROR: {r['error']}" if r.get("error") else ""
        row_mark = "" if r.get("rows_in_range") else " | ROWS_OOB"
        hall_mark = "" if r.get("no_hallucination") else " | HALL?"
        print(
            f"  {status} {r['id']} [{r.get('type','?'):8s}] "
            f"dim={dim_pct:.0f}% lat={r.get('latency_ms',0)/1000:.1f}s"
            f"{row_mark}{hall_mark}{error_info}"
        )

    print("=" * 70)

    rows_ok = sum(1 for r in results if r.get("rows_in_range"))
    no_hall = sum(1 for r in results if r.get("no_hallucination"))
    reflect_ok = sum(1 for r in results if r.get("reflection_passed"))
    dim_scores = [r["dimension_coverage"] for r in results if "dimension_coverage" in r]

    issues = []
    if rows_ok / max(len(results), 1) < 0.8:
        issues.append("行数检查通过率低于 80%，需要检查 Agent 是否在截断输出")
    if sum(dim_scores) / max(len(dim_scores), 1) < 0.7:
        issues.append("维度覆盖率低于 70%，需要检查 Prompt 是否遗漏了关键分析维度")
    if reflect_ok / max(len(results), 1) < 0.8:
        issues.append("Reflection 通过率低于 80%，需要检查质检 Agent 是否过于严格")
    if no_hall / max(len(results), 1) < 0.95:
        issues.append("幻觉信号检出率偏低，需检查报告是否有编造数据的情况")

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

        results = []
        total = len(questions)
        t_start = time.monotonic()
        for i, q in enumerate(questions, 1):
            print(f"  [{i:3d}/{total}] {q['id']:4s}: {q['question'][:50]:50s}...", end=" ", flush=True)
            result = await run_single_eval(q, token, args.port, sem)
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
