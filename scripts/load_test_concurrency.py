"""V4 并发压测脚本 — 用真实数据验证"60 秒内获得诊断报告"承诺。

用法:
    python scripts/load_test_concurrency.py            # 压测 http://localhost:8002
    python scripts/load_test_concurrency.py 8002       # 指定端口

流程:
    1. 登录 admin（admin/admin123）→ 获取 JWT
    2. 基线: 1 个 simple + 1 个 comprehensive 顺序执行（冷查询）
    3. 并发 5: 5 个 comprehensive 同时提交
    4. 并发 10: 10 个混合问题（7 comprehensive + 3 simple）同时提交
    5. 预热: 重跑基线 comprehensive（Redis 缓存命中，验证热路径）
    6. 流式探针: 1 个冷查询走 /analyze-stream，测首个事件 + done 事件耗时

度量口径:
    - 冷查询 = 问题文本从未出现在缓存中（模拟 95% 新问题的真实场景）
    - 通过标准 = 请求成功返回完整报告（report 非空）
    - 结果写入 scripts/load_test_results.json 留档

注意: 每次 comprehensive 冷查询会真实调用 LLM（约 ¥0.05-0.15），
      全脚本约 14 次 comprehensive + 4 次 simple，总成本约 ¥1-2。
"""

import asyncio
import json
import statistics
import sys
import time

import httpx

BASE = "http://localhost:{port}/api/v1"
LOGIN = {"username": "admin", "password": "admin123"}
REQ_TIMEOUT = httpx.Timeout(420.0, connect=10.0)

# ── 压测问题集（全部互不相同，保证冷查询；simple 走快路径，comprehensive 走完整链路）──
SIMPLE_QS = [
    "上个月销售额最高的五家门店",
    "退款率最高的三家门店",
    "最近一周库存周转率最低的五个商品",
    "会员总数最多的五个区域",
]

COMPREHENSIVE_QS = [
    "最近30天华东区销售为什么下降了？分析具体原因并给出改进建议",
    "分析最近一周的整体经营情况，涵盖销售、会员、库存",
    "最近90天客单价趋势如何？找出波动原因并给出建议",
    "哪些会员有流失风险？分析原因并给出召回建议",
    "上季度哪些供应商延迟最严重？对门店销售有什么影响",
    "上个月库存缺货最严重的商品有哪些？怎么改进补货策略",
    "分析最近一个月各品类毛利率变化，找出下滑的品类并给出建议",
    "最近14天新会员增长放缓的原因是什么？给出增长建议",
    "上周退货金额最高的品类是哪些？退货原因分布如何",
    "最近三个月销售额整体趋势如何？有没有异常月份，原因是什么",
    "分析门店经营健康度，找出表现最差的门店和改善方向",
    "本月环比上月整体销售下滑了，请做根因诊断并给出建议",
    "对比华东和华南两个区域的销售表现，分析差异原因",
    "分析上周门店销售、会员和库存的综合表现，找出三个最需要改进的方面",
]

results: list[dict] = []


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return float("nan")
    idx = min(len(sorted_vals) - 1, max(0, round(p * (len(sorted_vals) - 1))))
    return round(sorted_vals[idx], 1)


def _stats(vals: list[float]) -> str:
    if not vals:
        return "  (无成功样本)"
    s = sorted(vals)
    return f"n={len(s)}  min={min(s):.1f}s  p50={_pct(s, 0.5)}s  p95={_pct(s, 0.95)}s  p99={_pct(s, 0.99)}s  max={max(s):.1f}s"


async def analyze(client: httpx.AsyncClient, token: str, question: str, qtype: str, tag: str) -> dict:
    """单个冷查询: POST /analysis/analyze，记录耗时与结果。"""
    rec = {"question": question, "type": qtype, "tag": tag}
    t0 = time.monotonic()
    try:
        resp = await client.post(
            f"{BASE}/analysis/analyze",
            json={"question": question},
            headers={"Authorization": f"Bearer {token}"},
        )
        dt = time.monotonic() - t0
        rec["duration"] = round(dt, 1)
        if resp.status_code == 429:
            rec["status"] = "rate_limited"
            print(f"    [{'!' if qtype == 'comprehensive' else '.'}] 429 限流 {question[:24]}…")
        else:
            body = resp.json()
            ok = bool(body.get("report"))
            rec["status"] = "ok" if ok else "no_report"
            rec["report_len"] = len(body.get("report") or "")
            rec["agent_errors"] = body.get("agent_errors")
            if ok:
                print(f"    [OK] {question[:26]}… {dt:6.1f}s ({len(body['report'])} chars)")
            else:
                print(f"    [FAIL] {question[:26]}… {dt:6.1f}s 无报告 errors={rec['agent_errors']}")
    except httpx.TimeoutException:
        rec["status"] = "timeout"
        rec["duration"] = 420.0
        print(f"    [FAIL] {question[:26]}… 超时(420s)")
    except Exception as e:
        rec["status"] = "error"
        rec["duration"] = round(time.monotonic() - t0, 1)
        rec["error"] = str(e)[:200]
        print(f"    [FAIL] {question[:26]}… 异常 {str(e)[:120]}")
    results.append(rec)
    return rec


async def stream_probe(client: httpx.AsyncClient, token: str, question: str) -> None:
    """流式探针: 测首个事件(TTFB) 与 done 事件耗时。"""
    print("\n  [探针] /analyze-stream 冷查询...")
    t0 = time.monotonic()
    first_event = done_ts = None
    report_len = 0
    try:
        async with client.stream(
            "POST",
            f"{BASE}/analysis/analyze-stream",
            json={"question": question},
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            async for line in resp.aiter_lines():
                if first_event is None and line.startswith("event:"):
                    first_event = time.monotonic() - t0
                if line.startswith("data:"):
                    try:
                        ev = json.loads(line[5:])
                        if ev.get("type") == "done" and done_ts is None:
                            done_ts = time.monotonic() - t0
                            report_len = len(ev.get("report") or "")
                    except json.JSONDecodeError:
                        pass
        rec = {
            "question": question, "type": "stream_probe", "tag": "stream",
            "ttfb": round(first_event, 2) if first_event else None,
            "done_at": round(done_ts, 1) if done_ts else None,
            "report_len": report_len,
            "status": "ok" if done_ts else "incomplete",
        }
        results.append(rec)
        print(f"    首个事件 {rec['ttfb']}s，报告完成 {rec['done_at']}s，长度 {report_len}")
    except Exception as e:
        results.append({"question": question, "type": "stream_probe", "status": "error", "error": str(e)[:200]})
        print(f"    [FAIL] 流式异常 {str(e)[:120]}")


async def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "8002"
    global BASE
    BASE = BASE.format(port=port)
    print("=" * 66)
    print(f"  V4 并发压测 → {BASE}（admin，真实 LLM 冷查询）")
    print("=" * 66)

    # trust_env=False + proxy=None: 与 app/llm.py 一致，规避 Windows 注册表代理
    # （httpx 0.28.1 在 win32 上读取畸形代理 URL 会抛 InvalidURL）
    async with httpx.AsyncClient(timeout=REQ_TIMEOUT, trust_env=False, proxy=None) as client:
        # 1. 登录
        login = await client.post(f"{BASE}/auth/login", json=LOGIN)
        if login.status_code != 200:
            print(f"登录失败: HTTP {login.status_code} {login.text[:200]}")
            return 1
        token = login.json()["access_token"]
        print(f"  登录成功 admin (user_id={login.json().get('user_id')})")

        # 2. 基线（顺序，1 simple + 1 comprehensive）
        print("\n  [基线] 顺序执行 1 simple + 1 comprehensive ...")
        await analyze(client, token, SIMPLE_QS[0], "simple", "baseline")
        await analyze(client, token, COMPREHENSIVE_QS[0], "comprehensive", "baseline")

        # 3. 并发 5（全部 comprehensive）
        print(f"\n  [并发5] {len(COMPREHENSIVE_QS[1:6])} 个 comprehensive 同时提交 ...")
        await asyncio.gather(*[analyze(client, token, q, "comprehensive", "conc5") for q in COMPREHENSIVE_QS[1:6]])

        # 4. 并发 10（7 comprehensive + 3 simple）
        c10 = COMPREHENSIVE_QS[6:13] + SIMPLE_QS[1:4]
        print(f"\n  [并发10] {len(c10)} 个混合问题同时提交 ...")
        await asyncio.gather(*[
            analyze(client, token, q, "comprehensive" if i < 7 else "simple", "conc10")
            for i, q in enumerate(c10)
        ])

        # 5. 预热（重跑基线 comprehensive，应命中 Redis 缓存）
        print("\n  [预热] 重跑基线 comprehensive（应命中缓存）...")
        await analyze(client, token, COMPREHENSIVE_QS[0], "comprehensive", "warm")

        # 6. 流式探针
        await stream_probe(client, token, COMPREHENSIVE_QS[13])

    # ── 汇总 ──
    print("\n" + "=" * 66)
    print("  汇总")
    print("=" * 66)
    cold_comp = [r for r in results if r["type"] == "comprehensive" and r["tag"] != "warm" and r.get("status") == "ok"]
    cold_simple = [r for r in results if r["type"] == "simple" and r.get("status") == "ok"]
    warm = [r for r in results if r["tag"] == "warm"]
    stream = [r for r in results if r["type"] == "stream_probe"]

    print(f"\n  冷查询 comprehensive（完整链路，n={len(cold_comp)}）:")
    print(f"    {_stats([r['duration'] for r in cold_comp])}")
    within60 = [r for r in cold_comp if r["duration"] <= 60]
    print(f"    ≤60s 达成率: {len(within60)}/{len(cold_comp)} = {len(within60) / len(cold_comp) * 100:.0f}%")

    print(f"\n  冷查询 simple（快路径，n={len(cold_simple)}）:")
    print(f"    {_stats([r['duration'] for r in cold_simple])}")

    if warm:
        print(f"\n  热查询（缓存命中，n={len(warm)}）:")
        print(f"    {_stats([r['duration'] for r in warm])}")

    if stream:
        s = stream[0]
        print(f"\n  流式探针: TTFB(首个事件)={s.get('ttfb')}s  done={s.get('done_at')}s  status={s.get('status')}")

    bad = [r for r in results if r.get("status") not in ("ok",) and r.get("type") != "stream_probe"]
    if bad:
        print(f"\n  !! 失败/异常请求 {len(bad)} 个:")
        for r in bad:
            print(f"    {r.get('status')} | {r.get('question', '')[:30]} | {r.get('error', r.get('agent_errors', ''))}")

    with open("scripts/load_test_results.json", "w", encoding="utf-8") as f:
        json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}, f, ensure_ascii=False, indent=1)
    print("\n  结果已保存 → scripts/load_test_results.json")
    return 0 if not bad else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
