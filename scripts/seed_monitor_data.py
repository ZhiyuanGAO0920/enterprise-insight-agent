import asyncio, os, random, sys
from datetime import datetime, timezone, timedelta
import asyncpg

DB_DSN = os.environ.get("DATABASE_URL", "postgresql+asyncpg://admin:admin123@localhost:5434/enterprise_db").replace("+asyncpg", "")
CST = timezone(timedelta(hours=8))

SAMPLE_QUESTIONS = [
    "各门店销售额排名",
    "华东区近30天销售额最高的门店是哪个",
    "各区域销售额占比",
    "各区域订单数对比",
    "昨日销售额最高的 Top 10 门店",
    "各品类销售额分布",
    "近7天日均销售额低于5000元的门店",
    "各区域客单价排名",
    "退款率最高的5家门店",
    "上月销售额环比增长的门店有哪些",
    "会员总数是多少",
    "各等级会员人数分布",
    "近30天新增会员数",
    "近30天流失会员数",
    "各门店会员数量排名",
    "会员复购率是多少",
    "各区域会员分布情况",
    "会员消费频次分布",
    "上月会员活跃率",
    "新会员占比最高的5家门店",
    "近30天退款金额超过1000元的门店有哪些",
    "各区域利润率排名",
    "各门店毛利率排行",
    "各品类利润率对比",
    "昨日总销售额和总退款额"
]

REF_PASS_RATE = 0.86
HELPFUL_RATE = 0.72
FEEDBACK_RATE = 0.35
AGENTS = ["sales","crm","finance","inventory","supply_chain","supervisor","aggregator","chart_advisor","report","reflection"]
AGENT_ERR = {"sales":0.03,"crm":0.02,"finance":0.04,"inventory":0.08,"supply_chain":0.06,"supervisor":0.01,"aggregator":0.0,"chart_advisor":0.02,"report":0.03,"reflection":0.01}

async def seed(days=30):
    conn = await asyncpg.connect(DB_DSN)
    try:
        today = datetime.now(CST).replace(hour=0,minute=0,second=0,microsecond=0,tzinfo=None)
        existing = await conn.fetchval("SELECT COUNT(*) FROM analysis_history WHERE create_time >= $1", today - timedelta(days=days))
        if False:
            pass
        await conn.execute("TRUNCATE analysis_history, user_feedback, agent_trace_events RESTART IDENTITY CASCADE")
        print("Old data cleared, re-seeding...")

        total_a = 0; total_f = 0; total_t = 0
        for day in range(days, -1, -1):
            d = today - timedelta(days=day)
            for _ in range(random.randint(5, 15)):
                q = random.choice(SAMPLE_QUESTIONS)
                reflected = random.random() < REF_PASS_RATE
                it = random.randint(2000, 6000)
                ot = random.randint(1000, 4000)
                cost = round(it * 1.0 / 1e6 + ot * 2.0 / 1e6, 6)
                ts = d + timedelta(hours=random.randint(8,22), minutes=random.randint(0,59))
                rid = await conn.fetchval(
                    "INSERT INTO analysis_history (question, report, reflection_passed, user_id, tenant_id, input_tokens, output_tokens, llm_cost, create_time) VALUES ($1, $2, $3, 1, 1, $4, $5, $6, $7) RETURNING id",
                    q, "## " + q + "\n\nSample analysis report...", reflected, it, ot, cost, ts
                )
                total_a += 1
                for ag in AGENTS:
                    err = None
                    if random.random() < AGENT_ERR.get(ag, 0.01):
                        err = "timeout"
                    el = int(random.gauss(3000, 1500))
                    el = max(200, min(30000, el))
                    await conn.execute(
                        "INSERT INTO agent_trace_events (session_id, node_name, elapsed_ms, error, created_at) VALUES ($1, $2, $3, $4, $5)",
                        "s" + str(rid), ag, el, err, ts + timedelta(seconds=random.randint(0, 60))
                    )
                    total_t += 1
                if random.random() < FEEDBACK_RATE:
                    rating = "helpful" if random.random() < HELPFUL_RATE else "bad"
                    reasons = ["", "brief", "vague", "missing", "long", "ok"]
                    await conn.execute(
                        "INSERT INTO user_feedback (analysis_history_id, rating, reason, created_at) VALUES ($1, $2, $3, $4)",
                        rid, rating, random.choice(reasons), ts + timedelta(seconds=random.randint(10, 300))
                    )
                    total_f += 1
        print("Seeded: " + str(total_a) + " analyses, " + str(total_f) + " feedback, " + str(total_t) + " traces")
    finally:
        await conn.close()

async def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    print("Seeding " + str(days) + " days of monitor data...")
    await seed(days)
    print("Done")

if __name__ == "__main__":
    asyncio.run(main())
