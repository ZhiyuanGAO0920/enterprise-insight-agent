"""Demo 数据增强 — 让演示数据更真实、更有说服力。幂等安全。"""
import asyncio, random
from datetime import datetime, timedelta, timezone

import asyncpg

CST = timezone(timedelta(hours=8))
TODAY = datetime.now(CST).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)


async def enrich():
    conn = await asyncpg.connect("postgresql://admin:admin123@localhost:15432/enterprise_db")

    # ---- 1. 扩展供应商 (8 -> 30) ----
    n = await conn.fetchval("SELECT COUNT(*) FROM supplier")
    if n < 20:
        cats = ["生鲜", "日用品", "饮料", "零食", "调味品", "冷冻食品", "乳制品"]
        for i in range(30 - n):
            c = random.choice(cats)
            await conn.execute(
                "INSERT INTO supplier (supplier_name, category, contact, phone, lead_time_days, on_time_rate, quality_score, status) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,'active')",
                f"供应商-{c}-{i+1:02d}",
                c,
                f"联系人{random.choice('张李王赵陈周')}{random.choice('明强华伟丽')}",
                f"138{random.randint(10000000,99999999)}",
                random.randint(1, 14),
                round(random.uniform(65, 99), 1),
                round(random.uniform(60, 98), 1),
            )
        print(f"Suppliers: {n} -> {await conn.fetchval('SELECT COUNT(*) FROM supplier')}")

    # ---- 2. 扩展商品 (30 -> 100) ----
    n = await conn.fetchval("SELECT COUNT(*) FROM product")
    if n < 80:
        cat_prods = {
            "生鲜": ["新鲜菠菜", "有机西红柿", "进口牛油果", "鲜活基围虾", "散养土鸡蛋", "新鲜猪里脊", "鲜活鲈鱼", "有机西兰花", "新鲜草莓", "新鲜蓝莓"],
            "日用品": ["竹浆抽纸", "厨房湿巾", "垃圾袋", "洗洁精", "洗衣液", "洗手液", "保鲜膜", "钢丝球", "海绵擦", "洁厕灵"],
            "饮料": ["无糖乌龙茶", "鲜榨橙汁", "椰奶", "气泡水", "拿铁咖啡", "酸梅汤", "柠檬茶", "矿泉水", "能量饮料", "豆奶"],
            "零食": ["原味薯片", "坚果混合装", "牛肉干", "海苔卷", "巧克力棒", "果冻布丁", "苏打饼干", "红枣夹核桃", "辣条", "鱿鱼丝"],
            "调味品": ["生抽酱油", "蚝油", "豆瓣酱", "花椒油", "老陈醋", "鸡精", "黑胡椒粉", "芝麻油", "料酒", "辣椒酱"],
            "冷冻食品": ["速冻水饺", "手抓饼", "汤圆", "冰淇淋", "冷冻虾仁", "牛排", "披萨", "速冻馄饨", "火锅肉片", "薯条"],
            "乳制品": ["纯牛奶", "酸奶", "奶酪片", "黄油", "淡奶油", "芝士碎", "炼乳", "植物奶", "奶盖粉", "布丁粉"],
        }
        for cat, names in cat_prods.items():
            for name in names:
                if await conn.fetchval("SELECT 1 FROM product WHERE product_name = $1", name):
                    continue
                await conn.execute(
                    "INSERT INTO product (product_name, category, unit_price, supplier_id, shelf_life_days) "
                    "VALUES ($1,$2,$3,(SELECT id FROM supplier ORDER BY RANDOM() LIMIT 1),$4)",
                    name, cat,
                    round(random.uniform(3, 200), 2),
                    random.randint(3, 365),
                )
        print(f"Products: {n} -> {await conn.fetchval('SELECT COUNT(*) FROM product')}")

    # ---- 3. 补齐库存 (每个商品分配随机门店) ----
    products = await conn.fetch("SELECT id FROM product")
    stores = await conn.fetch("SELECT id FROM store")
    sids = [s["id"] for s in stores]
    added = 0
    for p in products:
        for sid in random.sample(sids, min(12, len(sids))):
            if await conn.fetchval("SELECT 1 FROM inventory WHERE product_id=$1 AND store_id=$2", p["id"], sid):
                continue
            await conn.execute(
                "INSERT INTO inventory (product_id, store_id, quantity, safety_stock, last_restock_date) "
                "VALUES ($1,$2,$3,$4,$5)",
                p["id"], sid,
                random.randint(0, 200),
                random.randint(10, 30),
                TODAY - timedelta(days=random.randint(1, 14)),
            )
            added += 1
    print(f"Inventory: {await conn.fetchval('SELECT COUNT(*) FROM inventory')} records (+{added})")

    # ---- 4. 制造低库存预警 ----
    low = await conn.fetch("SELECT id FROM inventory ORDER BY RANDOM() LIMIT 25")
    for item in low:
        await conn.execute("UPDATE inventory SET quantity=$1 WHERE id=$2", random.randint(0, 5), item["id"])
    print(f"Low stock alerts: {len(low)} items set to 0-5 units")

    # ---- 5. 填充最近 30 天 + 明天订单（覆盖看板数据，避免零值） ----
    members = await conn.fetch("SELECT member_id AS id FROM member")
    products_all = await conn.fetch("SELECT id, unit_price FROM product")
    mids = [m["id"] for m in members]

    # 生成 30 天前到今天的数据，再额外多生成一天（明天）确保看板不出现零值
    all_days = list(range(30, -1, -1)) + [-1]  # -1 表示明天
    for days_ago in all_days:
        day = TODAY - timedelta(days=days_ago) if days_ago >= 0 else TODAY + timedelta(days=1)
        cnt = await conn.fetchval(
            "SELECT COUNT(*) FROM orders WHERE create_time >= $1 AND create_time < $2",
            day, day + timedelta(days=1),
        )
        if cnt > 100:
            continue
        # 每天生成 120-250 笔订单，近期的多一些，远期少一些
        if days_ago >= 30:
            num = random.randint(80, 150)
        elif days_ago >= 14:
            num = random.randint(120, 200)
        elif days_ago >= 0:
            num = random.randint(150, 250)
        else:
            num = random.randint(120, 200)  # 明天
        batch = []
        for _ in range(num):
            sid = random.choice(sids)
            mid = random.choice(mids)
            p = random.choice(products_all)
            amt = round(float(p["unit_price"]) * random.uniform(0.8, 3.0), 2)
            refund = round(amt * random.uniform(0.3, 1.0), 2) if random.random() < 0.06 else 0.0
            ts = day + timedelta(hours=random.randint(8, 22), minutes=random.randint(0, 59))
            batch.append((sid, mid, amt, refund, ts))
        await conn.copy_records_to_table("orders", columns=["store_id", "member_id", "amount", "refund_amount", "create_time"], records=batch)
        print(f"  {day.strftime('%m/%d')}: {num} orders ({cnt} existed)")

    # ---- 6. 制造高退款门店 ----
    high_sids = random.sample(sids, 5)
    for sid in high_sids:
        orders = await conn.fetch(
            "SELECT order_id AS id, amount FROM orders WHERE store_id=$1 AND create_time>=$2 AND refund_amount=0 ORDER BY RANDOM() LIMIT 25",
            sid, TODAY - timedelta(days=30),
        )
        for o in orders:
            await conn.execute("UPDATE orders SET refund_amount=$1 WHERE order_id=$2",
                round(float(o["amount"]) * random.uniform(0.5, 1.0), 2), o["id"])
    names = await conn.fetch("SELECT store_name FROM store WHERE id=ANY($1)", high_sids)
    print(f"High-refund stores: {[n['store_name'] for n in names]}")

    # ---- 7. 补充采购单 ----
    suppliers = await conn.fetch("SELECT id FROM supplier")
    for s in suppliers:
        cnt = await conn.fetchval("SELECT COUNT(*) FROM purchase_order WHERE supplier_id=$1", s["id"])
        if cnt == 0:
            p = random.choice(products_all)
            await conn.execute(
                "INSERT INTO purchase_order (supplier_id, product_id, quantity, unit_cost, total_cost, order_date, received_date, status) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                s["id"], p["id"],
                random.randint(10, 100),
                round(random.uniform(5, 300), 2),
                round(random.uniform(500, 10000), 2),
                TODAY - timedelta(days=random.randint(5, 45)),
                TODAY - timedelta(days=random.randint(0, 20)) if random.random() > 0.3 else None,
                random.choice(["delivered", "delivered", "delivered", "pending", "delayed"]),
            )

    # ---- 8. 最近新增会员 ----
    mc = await conn.fetchval("SELECT COUNT(*) FROM member WHERE register_date >= $1", TODAY - timedelta(days=30))
    if mc < 100:
        levels = ["普通会员"] * 5 + ["银卡会员"] * 3 + ["金卡会员"] * 1 + ["钻石会员"]
        channels = ["门店注册", "APP", "小程序", "地推", "老带新"]
        batch = []
        for _ in range(200):
            batch.append((
                f"会员{random.randint(10000,99999)}",
                random.choice(levels),
                f"138{random.randint(10000000,99999999)}",
                random.choice(channels),
                random.choice(["18-25", "26-35", "36-45", "46-55", "55+"]),
                random.choice(["男", "女"]),
                TODAY - timedelta(days=random.randint(0, 30)),
            ))
        await conn.copy_records_to_table("member", columns=["name", "level", "phone", "channel", "age_group", "gender", "register_date"], records=batch)
        print(f"Members: added {len(batch)} recent registrations")

    # ---- 汇总 ----
    print(f"\n=== Done ===")
    for t in ['store','orders','member','supplier','product','inventory','purchase_order']:
        print(f"  {t:20s}: {await conn.fetchval(f'SELECT COUNT(*) FROM {t}')}")
    ts = await conn.fetchval("SELECT COALESCE(SUM(amount),0) FROM orders WHERE create_time >= CURRENT_DATE")
    tc = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE create_time >= CURRENT_DATE")
    print(f"  Today: {tc} orders, sales={ts:,.0f}")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(enrich())
