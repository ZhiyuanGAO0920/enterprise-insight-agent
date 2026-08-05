"""存量向量回填 —— V4.6.3 嵌入语义修复后的历史数据校正。

背景：
  1. save_analysis_history 此前把「报告全文」做嵌入存库，而检索侧用「问题」做向量，
     语义错位导致改写句召回率仅 25%（scripts/eval_retrieval.py 实测）。
  2. 部分历史记录 embedding 为 NULL（保存时 Ollama 不可用，嵌入失败）。

修复后新记录嵌入问题文本；本脚本把**所有**存量记录按问题文本重嵌
（含 NULL 向量记录，补齐检索索引）。

策略（按问题文本去重，只嵌一次）：
  - 同一问题多条重复记录共享同一向量，全量 778 条 ≈ 250 个去重问题 → 约 5 分钟
  - 失败/零向量跳过并计数（不阻断）

用法：python scripts/backfill_embeddings.py [--limit 5000]
"""

import asyncio
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.database.connection import get_session  # noqa: E402
from app.logging_config import get_logger  # noqa: E402
from app.tools.embedding import get_embeddings  # noqa: E402
from app.tools.memory import _vec_to_str  # noqa: E402

logger = get_logger("eia.scripts.backfill_embeddings")


def _is_zero(vec: list[float]) -> bool:
    return not vec or not any(vec)


async def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5000
    async with get_session() as session:
        rows = await session.execute(text(
            "SELECT id, question FROM analysis_history "
            "WHERE question IS NOT NULL AND question != '' "
            "ORDER BY id DESC LIMIT :lim"
        ), {"lim": limit})
        records = rows.fetchall()
    print(f"待重嵌记录: {len(records)} 条（含此前 embedding 为 NULL 的记录）")

    # 按问题文本去重（同问题共享向量）
    question_ids: dict[str, list[int]] = {}
    for r in records:
        q = r[1].split("\n")[0].strip()
        question_ids.setdefault(q, []).append(r[0])
    print(f"去重后唯一问题: {len(question_ids)} 个")

    failed = 0
    updated = 0
    batch: list[str] = []
    batch_questions: list[str] = []

    async def flush() -> None:
        nonlocal updated, failed
        if not batch:
            return
        try:
            vecs = await get_embeddings(batch)
        except Exception as e:
            logger.warning("批量嵌入失败: %s", e)
            failed += len(batch)
            batch.clear()
            batch_questions.clear()
            return
        async with get_session() as session:
            for q, vec in zip(batch_questions, vecs):
                if _is_zero(vec):
                    failed += 1
                    continue
                ids = question_ids[q]
                await session.execute(
                    text("UPDATE analysis_history SET embedding = CAST(:e AS vector) WHERE id = ANY(:ids)"),
                    {"e": _vec_to_str(vec), "ids": ids},
                )
                updated += len(ids)
            await session.commit()
        batch.clear()
        batch_questions.clear()

    for q, ids in question_ids.items():
        batch.append(q)
        batch_questions.append(q)
        if len(batch) >= 16:
            await flush()
            print(f"  进度: {updated} 条已更新，{failed} 条失败", flush=True)
    await flush()

    print(f"\n完成: 更新 {updated} 条，失败/跳过 {failed} 条")


if __name__ == "__main__":
    asyncio.run(main())
