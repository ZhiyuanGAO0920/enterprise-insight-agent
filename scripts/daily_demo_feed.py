"""每日 Demo 数据投喂 —— 每天生成少量随机订单，保持看板数据鲜活。

用法：
  python scripts/daily_demo_feed.py          # 只补今天（默认）
  python scripts/daily_demo_feed.py --tomorrow  # 补明天

可配合 Windows 任务计划程序 / n8n 定时触发。
"""

import asyncio, os, random, argparse
from datetime import datetime, timezone, timedelta
import asyncpg

CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
DB_DSN = os.environ.get("DATABASE_URL", "postgresql+asyncpg://admin:admin123@localhost:15432/enterprise_db").replace("+asyncpg", "")


async def feed(target_date: datetime):
    """为 target_date 生成 50-200 笔随机订单（如已有则跳过）。"""
    conn = await asyncpg.connect(DB_DSN)
    try:
        cnt = await conn.fetchval(
            "SELECT COUNT(*) FROM orders WHERE create_time >= $1 AND create_time < $2",
            target_date, target_date + timedelta(days=1),
        )
        label = target_date.strftime("%m/%d")
        if cnt > 50:
            print(f"[SKIP] {label}: already has {cnt} orders")
            return

        stores = await conn.fetch("SELECT id FROM store")
        members = await conn.fetch("SELECT member_id AS id FROM member")
        products = await conn.fetch("SELECT id, unit_price FROM product")
        sids = [s["id"] for s in stores]
        mids = [m["id"] for m in members]

        num = random.randint(50, 200)
        batch = []
        for _ in range(num):
            sid = random.choice(sids)
            mid = random.choice(mids) if random.random() > 0.1 else None
            p = random.choice(products)
            amt = round(float(p["unit_price"]) * random.uniform(0.8, 3.0), 2)
            refund = round(amt * random.uniform(0.3, 1.0), 2) if random.random() < 0.06 else 0.0
            ts = target_date + timedelta(hours=random.randint(8, 22), minutes=random.randint(0, 59))
            batch.append((sid, mid, amt, refund, ts))

        await conn.copy_records_to_table(
            "orders",
            columns=["store_id", "member_id", "amount", "refund_amount", "create_time"],
            records=batch,
        )
        print(f"[OK]   {label}: added {num} orders (had {cnt})")
    finally:
        await conn.close()


async def main():
    parser = argparse.ArgumentParser(description="每日 Demo 数据投喂")
    parser.add_argument("--tomorrow", action="store_true", help="补充明天的数据而非今天")
    args = parser.parse_args()

    target = TODAY + timedelta(days=1) if args.tomorrow else TODAY
    print(f"Feeding orders for {target.strftime('%Y-%m-%d')} ...")
    await feed(target)


if __name__ == "__main__":
    asyncio.run(main())
