"""离线评估脚本 — 在修改 Prompt 后运行以量化验证分析质量。

用法：
    python tests/run_eval.py                    # 跑全部 20 条
    python tests/run_eval.py --type lookup      # 只跑查询型
    python tests/run_eval.py --type analysis    # 只跑分析型
    python tests/run_eval.py --id Q01           # 只跑单条
"""

import argparse
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
    # 减去表头
    data_rows = max(0, table_rows - 1)
    return min_rows <= data_rows <= max_rows


def check_no_hallucination(report: str) -> bool:
    """检查报告中是否有明显的幻觉信号（极端不可信的数字）。

    这是一个启发式检查，不是精确的幻觉检测。
    """
    hallucination_signals = [
        "100% 准确",  # AI 通常不应该说 100%
    ]
    report_lower = report.lower()
    for signal in hallucination_signals:
        if signal.lower() in report_lower:
            return False
    return True


# ---------------------------------------------------------------------------
# 主逻辑
# ---------------------------------------------------------------------------


async def run_single_eval(question: dict, token: str) -> dict:
    """对单条问题运行评估。"""
    import urllib.request

    analyze_data = json.dumps({"question": question["question"]}).encode()
    req = urllib.request.Request(
        "http://localhost:8003/api/analysis/analyze",
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

    # 提取所有 Agent 使用的 SQL（用于 SQL 准确性评估）
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
        "sqls": sqls[:3],  # 只保留前 3 条用于展示
        "errors": len(errors),
        "error_details": [f"{e['agent']}: {e.get('user_message', e.get('error', ''))[:80]}" for e in errors[:3]],
        "reflection_passed": data.get("reflection_passed"),
        "data_source_count": len(sources),
        "latency_ms": elapsed_ms,
    }


def print_report(results: list[dict]):
    """打印格式化的评估报告。"""
    total = len(results)
    failed = sum(1 for r in results if r.get("error"))
    passed = total - failed

    dim_scores = [r["dimension_coverage"] for r in results if "dimension_coverage" in r]
    rows_ok = sum(1 for r in results if r.get("rows_in_range"))
    no_hall = sum(1 for r in results if r.get("no_hallucination"))
    reflect_ok = sum(1 for r in results if r.get("reflection_passed"))
    avg_latency = sum(r.get("latency_ms", 0) for r in results) / max(total, 1)

    print()
    print("=" * 60)
    print("  V3 Agent 离线评估报告")
    print("=" * 60)
    print(f"  完成: {passed}/{total}    失败: {failed}/{total}")
    print(f"  维度覆盖率:      {sum(dim_scores)/max(len(dim_scores),1)*100:.0f}%")
    print(f"  行数合理:         {rows_ok}/{total}")
    print(f"  无幻觉信号:       {no_hall}/{total}")
    print(f"  Reflection 通过:  {reflect_ok}/{total}")
    print(f"  平均延迟:         {avg_latency/1000:.1f}s")
    print("-" * 60)

    # 按类型分组展示
    for qtype in ["lookup", "analysis", "edge"]:
        type_results = [r for r in results if r.get("type") == qtype]
        if not type_results:
            continue
        type_dim = sum(r.get("dimension_coverage", 0) for r in type_results) / len(type_results)
        type_latency = sum(r.get("latency_ms", 0) for r in type_results) / len(type_results)
        print(f"  [{qtype:8s}] {len(type_results)} 条 | 覆盖率 {type_dim*100:.0f}% | 平均 {type_latency/1000:.1f}s")

    print("-" * 60)

    # 单条明细
    for r in results:
        dim_pct = r.get("dimension_coverage", 0) * 100
        status = "✅" if not r.get("error") and r.get("rows_in_range") and r.get("no_hallucination") else "⚠️"
        error_info = f" | ERROR: {r['error']}" if r.get("error") else ""
        row_mark = "" if r.get("rows_in_range") else " | ROWS_OOB"
        hall_mark = "" if r.get("no_hallucination") else " | HALL?"
        print(
            f"  {status} {r['id']} [{r.get('type','?'):8s}] "
            f"dim={dim_pct:.0f}% lat={r.get('latency_ms',0)/1000:.1f}s"
            f"{row_mark}{hall_mark}{error_info}"
        )

    print("=" * 60)

    # 建议
    issues = []
    if rows_ok / max(total, 1) < 0.8:
        issues.append("行数检查通过率低于 80%，需要检查 Agent 是否在截断输出")
    if sum(dim_scores) / max(len(dim_scores), 1) < 0.7:
        issues.append("维度覆盖率低于 70%，需要检查 Prompt 是否遗漏了关键分析维度")
    if reflect_ok / max(total, 1) < 0.8:
        issues.append("Reflection 通过率低于 80%，需要检查质检 Agent 是否过于严格")

    if issues:
        print("\n  📋 改进建议:")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
    else:
        print("\n  ✅ 所有指标正常")

    print()


def main():
    parser = argparse.ArgumentParser(description="V3 Agent 离线评估")
    parser.add_argument("--type", choices=["lookup", "analysis", "edge"], help="只跑指定类型")
    parser.add_argument("--id", help="只跑指定 ID 的问题")
    parser.add_argument("--port", type=int, default=8003, help="V3 服务端口（默认 8003）")
    parser.add_argument("--output", help="输出 JSON 结果到文件")
    args = parser.parse_args()

    # 加载评估集
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

    # 获取认证 Token
    import asyncio

    async def run_all():
        import urllib.request

        # 登录
        login_data = json.dumps({"username": "admin", "password": "admin123"}).encode()
        try:
            req = urllib.request.Request(
                f"http://localhost:{args.port}/api/auth/login",
                data=login_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=10)
            token = json.loads(resp.read().decode("utf-8"))["access_token"]
            print(f"  登录成功")
        except Exception as e:
            print(f"  ❌ 登录失败: {e}")
            print(f"  请确保 V3 服务在端口 {args.port} 运行")
            return

        # 逐条评估
        results = []
        for i, q in enumerate(questions, 1):
            print(f"  [{i}/{len(questions)}] {q['id']}: {q['question'][:60]}...", end=" ", flush=True)
            result = await run_single_eval(q, token)
            results.append(result)
            if result.get("error"):
                print("❌")
            else:
                dim = result.get("dimension_coverage", 0) * 100
                print(f"✅ dim={dim:.0f}% lat={result.get('latency_ms',0)/1000:.1f}s")

        print_report(results)

        if args.output:
            output_path = Path(args.output)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"  结果已保存到 {output_path}")

    asyncio.run(run_all())


if __name__ == "__main__":
    main()
