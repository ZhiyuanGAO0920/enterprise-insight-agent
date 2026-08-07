"""回填质检假失败记录 —— V4.6.2 修复后的历史数据校正。

背景：V4.5 的 simple 查询按设计跳过质检（graph.after_report 直接去 save_memory），
但 analysis_history.reflection_passed 默认 False，导致所有简单查询被误记为"质检未过"，
污染了质量监控的通过率指标（8 月初暴跌至 58% 即此原因，实际 ~93%）。

修复（app/agents/memory_node.py）已让新记录不再误判，本脚本校正存量数据。

翻转规则（保守，只动确定是假失败的行）：
  - reflection_passed = false
  - reflection_issues 为空（simple 跳过质检不会产生 issues；真失败必有 issues）
  - 报告长度 >= 200 字（短报告是真实的内容缺失，保持"未过"）

用法：
  python scripts/fix_reflection_false_failures.py [days=7] [--dry-run]
"""

import asyncio
import sys

from sqlalchemy import text

from app.database.connection import get_session


async def main() -> None:
    days = 7
    dry_run = False
    for arg in sys.argv[1:]:
        if arg == "--dry-run":
            dry_run = True
        elif arg.isdigit():
            days = int(arg)

    async with get_session() as s:
        before = (await s.execute(text(
            "SELECT COUNT(*) FROM analysis_history"
            " WHERE reflection_passed = false AND create_time >= NOW() - (:d || ' days')::INTERVAL"
        ), {"d": str(days)})).scalar()

        sql = text("""
            UPDATE analysis_history SET reflection_passed = true
            WHERE reflection_passed = false
              AND (reflection_issues IS NULL OR reflection_issues::text IN ('[]', 'null'))
              AND LENGTH(report) >= 200
              AND create_time >= NOW() - (:d || ' days')::INTERVAL
        """)

        if dry_run:
            # dry-run 只统计符合条件的行数，不执行 UPDATE
            cnt = (await s.execute(text("""
                SELECT COUNT(*) FROM analysis_history
                WHERE reflection_passed = false
                  AND (reflection_issues IS NULL OR reflection_issues::text IN ('[]', 'null'))
                  AND LENGTH(report) >= 200
                  AND create_time >= NOW() - (:d || ' days')::INTERVAL
            """), {"d": str(days)})).scalar()
            print(f"[dry-run] 近 {days} 天将翻转 {cnt} 条记录（未过总数 {before}）")
            return

        res = await s.execute(sql, {"d": str(days)})
        await s.commit()

        after = (await s.execute(text(
            "SELECT COUNT(*) FROM analysis_history"
            " WHERE reflection_passed = false AND create_time >= NOW() - (:d || ' days')::INTERVAL"
        ), {"d": str(days)})).scalar()
        print(f"近 {days} 天：未过 {before} → 已翻转 {res.rowcount} → 剩余未过 {after}")


if __name__ == "__main__":
    asyncio.run(main())
