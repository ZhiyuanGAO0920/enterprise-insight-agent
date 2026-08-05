"""反馈闭环分析脚本 —— 线上坏例 → 评估集迭代（V4.6.3）。

把线上用户反馈（user_feedback）与评估体系打通：
1. 统计最近 N 天反馈的评分分布、好评率
2. 按 Agent 聚合不准确率（与 /feedback/analyze API 同口径，但可离线全量）
3. 提取「不准确/不相关」坏例：问题原文 + 用户原因 + 质检是否通过
4. 生成评估集候选（BadCase → 评估用例），与现有 102 条去重，--apply 入库

用法：
    python scripts/analyze_feedback.py                     # 分析最近 30 天反馈并打印候选
    python scripts/analyze_feedback.py --days 90           # 更长时间窗口
    python scripts/analyze_feedback.py --apply             # 将候选写入 tests/eval_set.json（生成 Q103+）
    python scripts/analyze_feedback.py --apply --dry-run   # 预览将写入的条目，不落盘

说明：
- 候选条目的 expected_dimensions 为空（维度需人工补），min/max 行数按启发式给默认值。
- --apply 会直接修改 tests/eval_set.json，请先 review --dry-run 输出。
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.database.connection import get_session  # noqa: E402
from app.logging_config import get_logger  # noqa: E402

logger = get_logger("eia.scripts.analyze_feedback")

EVAL_SET_PATH = ROOT / "tests" / "eval_set.json"
# 坏例候选去重：与已有问题按归一化文本匹配（删除空白/标点，含中文引号）
_NORM_RE = re.compile(r"[\s，。！？、,.!?;；:：“”‘’（）()【】\[\]]")


def _norm(q: str) -> str:
    return _NORM_RE.sub("", q or "")


async def load_feedback(days: int, limit: int) -> list[dict]:
    """查询最近 N 天反馈 + 关联的分析记录。"""
    async with get_session() as session:
        rows = await session.execute(
            text(
                """
                SELECT
                    f.id, f.rating, f.reason, f.agent_issues, f.created_at,
                    a.question, a.reflection_passed
                FROM user_feedback f
                LEFT JOIN analysis_history a ON f.analysis_history_id = a.id
                WHERE f.created_at >= NOW() - (:days || ' days')::INTERVAL
                ORDER BY f.created_at DESC
                LIMIT :lim
                """
            ),
            {"days": str(days), "lim": limit},
        )
        return [dict(r._mapping) for r in rows.fetchall()]


def summarize(feedback: list[dict]) -> dict:
    """评分分布 + 按 Agent 聚合的不准确率。"""
    total = len(feedback)
    by_rating: dict[str, int] = {}
    for f in feedback:
        by_rating[f["rating"]] = by_rating.get(f["rating"], 0) + 1

    agent_issues: dict[str, list] = {}
    for f in feedback:
        issues = f["agent_issues"] or {}
        for agent in issues if isinstance(issues, dict) else {}:
            agent_issues.setdefault(agent, []).append(f)

    bad_agents = []
    for agent, items in agent_issues.items():
        bad = sum(1 for i in items if i["rating"] in ("inaccurate", "not_relevant"))
        bad_agents.append({
            "agent": agent,
            "total": len(items),
            "bad": bad,
            "bad_rate": round(bad * 100.0 / len(items), 1),
        })
    bad_agents.sort(key=lambda x: -x["bad_rate"])

    return {"total": total, "by_rating": by_rating, "bad_agents": bad_agents}


def build_candidates(feedback: list[dict], existing: list[dict]) -> list[dict]:
    """坏例 → 评估集候选条目（与现有问题去重）。"""
    existing_qs = {_norm(q["question"]) for q in existing}
    seen: set[str] = set()
    candidates = []
    for f in feedback:
        if f["rating"] not in ("inaccurate", "not_relevant"):
            continue
        question = (f.get("question") or "").strip()
        if not question:
            continue
        norm_q = _norm(question)
        if norm_q in existing_qs or norm_q in seen:
            continue
        seen.add(norm_q)

        # 启发式：含数量/排名词的偏查询型，否则分析型（维度需人工补）
        lookup_hint = re.search(r"排名|排行|多少|几个|哪些|Top|TOP", question)
        candidates.append({
            "question": question[:200],
            "source_feedback_id": f["id"],
            "reason": (f.get("reason") or "")[:200],
            "type": "lookup" if lookup_hint else "analysis",
            "category": "feedback",
            "expected_dimensions": [],
            "min_result_rows": 1 if lookup_hint else 3,
            "max_result_rows": 30 if lookup_hint else 50,
        })
    return candidates


def next_ids(existing: list[dict], count: int) -> list[str]:
    """生成新条目 ID：现有 Q01-Q102 之后接 Q103+。"""
    nums = [int(m.group(1)) for q in existing if (m := re.match(r"^Q(\d+)$", q.get("id", "")))]
    start = max(nums, default=0) + 1
    return [f"Q{i}" for i in range(start, start + count)]


async def main():
    parser = argparse.ArgumentParser(description="反馈闭环分析：线上坏例 → 评估集迭代")
    parser.add_argument("--days", type=int, default=30, help="统计窗口（天），默认 30")
    parser.add_argument("--limit", type=int, default=2000, help="最大反馈条数，默认 2000")
    parser.add_argument("--apply", action="store_true", help="将候选写入 tests/eval_set.json（Q103+）")
    parser.add_argument("--dry-run", action="store_true", help="只预览候选条目，不落盘")
    args = parser.parse_args()

    feedback = await load_feedback(args.days, args.limit)
    if not feedback:
        print(f"最近 {args.days} 天无反馈数据")
        return

    summary = summarize(feedback)
    print("=" * 70)
    print(f"  反馈闭环分析（最近 {args.days} 天，共 {summary['total']} 条）")
    print("=" * 70)
    print(f"  评分分布: {summary['by_rating']}")
    helpful = summary["by_rating"].get("helpful", 0)
    print(f"  好评率:   {helpful * 100.0 / max(summary['total'], 1):.1f}%")
    if summary["bad_agents"]:
        print("\n  按 Agent 不准确率（驱动 Prompt 优化优先级）:")
        for a in summary["bad_agents"][:8]:
            mark = "🔴" if a["bad_rate"] > 20 else "🟡" if a["bad_rate"] > 10 else "🟢"
            print(f"    {mark} {a['agent']}: {a['bad_rate']:.0f}% ({a['bad']}/{a['total']})")
    else:
        print("\n  （无 Agent 标记的反馈数据）")

    # ---- 坏例 → 评估集候选 ----
    with open(EVAL_SET_PATH, encoding="utf-8") as f:
        eval_set = json.load(f)
    candidates = build_candidates(feedback, eval_set["questions"])

    print(f"\n  坏例候选（与现有 {len(eval_set['questions'])} 条去重后）: {len(candidates)} 条")
    for c in candidates[:15]:
        print(f"    - [{c['type']}] {c['question'][:60]}")
        if c["reason"]:
            print(f"        用户原因: {c['reason'][:60]}")
    if len(candidates) > 15:
        print(f"    ... 等共 {len(candidates)} 条（完整列表见 --dry-run）")

    # ---- 三角验证：评估集问题被线上标记不准确的分布（闭环核心产出） ----
    eval_by_q = {_norm(q["question"]): q for q in eval_set["questions"]}
    bad_by_eval: dict[str, dict] = {}
    for f in feedback:
        if f["rating"] not in ("inaccurate", "not_relevant") or not f.get("question"):
            continue
        q = eval_by_q.get(_norm(f["question"].strip()))
        if q:
            key = q["id"]
            entry = bad_by_eval.setdefault(key, {"id": key, "question": q["question"], "count": 0})
            entry["count"] += 1
    if bad_by_eval:
        print("\n  🔺 三角验证：评估集问题被线上标记不准确（BadCase 直指评估用例）:")
        for e in sorted(bad_by_eval.values(), key=lambda x: -x["count"])[:10]:
            print(f"    - {e['id']} ×{e['count']}: {e['question'][:50]}")
        print("    建议：对高频问题重跑评估并人工抽检报告（run_eval.py --id 对应 ID）")
    else:
        print("\n  无评估集问题被标记不准确")

    # ---- 关联分析：不准确率 × 质检状态（验证 Reflection 是否真的预测用户不满） ----
    refl_stats: dict[str, dict] = {}
    for f in feedback:
        rp = f.get("reflection_passed")
        key = "passed" if rp is True else ("failed" if rp is False else "no_reflection")
        s = refl_stats.setdefault(key, {"total": 0, "bad": 0})
        s["total"] += 1
        if f["rating"] in ("inaccurate", "not_relevant"):
            s["bad"] += 1
    if refl_stats:
        print("\n  关联分析：不准确率 × 质检状态（质检过 ≠ 用户一定满意）")
        for key in ("passed", "failed", "no_reflection"):
            s = refl_stats.get(key)
            if not s or not s["total"]:
                continue
            rate = s["bad"] * 100.0 / s["total"]
            mark = "🔴" if rate > 30 else "🟡" if rate > 15 else "🟢"
            print(f"    {mark} {key:12s}: {rate:.0f}% 不准确（{s['bad']}/{s['total']}）")

    # ---- 关联分析：不准确率 × 是否评估集问题（线上分布与评估集是否同构） ----
    eval_fb = [f for f in feedback if f.get("question") and _norm(f["question"].strip()) in eval_by_q]
    other_fb = [f for f in feedback if f.get("question") and _norm(f["question"].strip()) not in eval_by_q]
    for label, group in (("评估集问题", eval_fb), ("非评估集问题", other_fb)):
        if not group:
            continue
        bad = sum(1 for f in group if f["rating"] in ("inaccurate", "not_relevant"))
        print(f"    {label:8s}: 不准确率 {bad * 100.0 / len(group):.0f}%（{bad}/{len(group)}）")

    if args.apply or args.dry_run:
        ids = next_ids(eval_set["questions"], len(candidates))
        entries = [{"id": ids[i], **{k: v for k, v in c.items() if k != "source_feedback_id"}, **{
            "source": f"feedback#{c['source_feedback_id']}"
        }} for i, c in enumerate(candidates)]
        if args.dry_run:
            print(f"\n  将新增 {len(entries)} 条（ID {ids[0]}-{ids[-1] if ids else ''}），含 source 字段记录出处:")
            for e in entries[:10]:
                print(f"    {e['id']} [{e['type']}] {e['question'][:60]} (source={e['source']})")
            if len(entries) > 10:
                print(f"    ... 等共 {len(entries)} 条")
            print("\n  ⚠️ 注意：expected_dimensions 为空，入库后建议人工补维度后运行评估")
            return

        # --apply：写入 eval_set.json（version bump）
        if entries:
            eval_set["questions"].extend(entries)
            old_ver = eval_set.get("version", "2.0")
            eval_set["version"] = f"{old_ver}+fb{len(entries)}"
            with open(EVAL_SET_PATH, "w", encoding="utf-8") as f:
                json.dump(eval_set, f, ensure_ascii=False, indent=2)
            print(f"\n  ✅ 已写入 {len(entries)} 条到 {EVAL_SET_PATH.name}（ID {ids[0]}-{ids[-1]}，version={eval_set['version']}）")
            print("     下一步：为新增条目补充 expected_dimensions 后运行 python tests/run_eval.py")
        else:
            print("\n  无新候选可写入（坏例均已覆盖或为空）")


if __name__ == "__main__":
    asyncio.run(main())
