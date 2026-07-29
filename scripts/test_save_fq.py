"""Standalone test: verify save_analysis_history saves followup_questions correctly."""
import asyncio, json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.tools.memory import save_analysis_history

async def test():
    rid = await save_analysis_history(
        question="test_fq_save",
        report="Test report body. 门店销售数据.",
        reflection_passed=True,
        user_id=1,
        input_tokens=0, output_tokens=0, llm_cost=0.0,
        followup_questions=["测试追问1", "测试追问2", "测试追问3"],
    )
    print(f"Created record: {rid}")

    # Read back
    import asyncpg
    conn = await asyncpg.connect("postgresql://admin:admin123@localhost:15432/enterprise_db")
    val = await conn.fetchval("SELECT followup_questions FROM analysis_history WHERE id = $1", rid)
    print(f"Read back: {repr(val)}")
    if val:
        print(f"Parsed: {json.loads(val)}")
    await conn.close()
    print("SUCCESS" if val else "FAIL - NULL")

asyncio.run(test())
