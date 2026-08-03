"""Demo 缓存预热脚本 — 录制前把 demo 问题跑一遍写入 Redis，录制时流式端点秒回。

用法:
    python scripts/warmup_demo_cache.py            # 预热 http://localhost:8002
    python scripts/warmup_demo_cache.py 8002       # 指定端口

流程:
    1. 登录 admin → 4 个 demo 问题依次走 /analyze 完整链路（真实 LLM 调用，写缓存）
    2. check_cache=true 校验每个问题已写入缓存（秒回即命中）

注意: 问题文本必须与 scripts/record_demo.py 中完全一致（缓存键含问题原文）。
缓存 TTL 10 分钟（app/api/routes/analysis.py CACHE_TTL_SEC），预热后立即录制。
"""

import json
import sys
import time
import urllib.request

# 与 scripts/record_demo.py 中输入的 4 个 demo 问题完全一致（一字不差）
QUESTIONS = [
    "上个月销售额最高的三家门店",
    "退款率最高的门店",
    "最近30天华东区销售为什么下降了？分析具体原因并给出改进建议",
    "分析最近一周的整体经营情况，涵盖销售、会员、库存",
]


def _post(base: str, path: str, body: dict, token: str | None = None) -> dict:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "8002"
    base = f"http://localhost:{port}/api/v1"
    print("=" * 60)
    print(f"  Demo 缓存预热 → {base}")
    print("=" * 60)

    login = _post(base, "/auth/login", {"username": "admin", "password": "admin123"})
    token = login["access_token"]
    print(f"  登录成功: admin (user_id={login.get('user_id')})")

    print("\n  [预热] 4 个问题走完整分析链路（写入 Redis 缓存）...")
    for i, q in enumerate(QUESTIONS, 1):
        t0 = time.time()
        resp = _post(base, "/analysis/analyze", {"question": q}, token)
        dt = time.time() - t0
        ok = bool(resp.get("report"))
        print(f"    [{i}/4] {q[:28]}… {'✅ 已缓存' if ok else '❌ 无报告'} ({dt:.0f}s)")
        if not ok:
            print(f"          agent_errors: {resp.get('agent_errors')}")
            return 1

    print("\n  [校验] check_cache=true 应秒回（不触发 LLM）...")
    for i, q in enumerate(QUESTIONS, 1):
        t0 = time.time()
        resp = _post(base, "/analysis/analyze?check_cache=true", {"question": q}, token)
        dt = time.time() - t0
        ok = bool(resp.get("report"))
        print(f"    [{i}/4] {'✅ 命中' if ok else '❌ MISS'} ({dt:.2f}s)")
        if not ok:
            print("          ❌ 缓存未命中，请检查 Redis 与缓存键一致性")
            return 1

    print("\n  预热完成 ✅ 10 分钟内录制，每次查询约 7 秒秒回")
    return 0


if __name__ == "__main__":
    sys.exit(main())
