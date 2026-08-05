"""临时对比脚本：在指定端口跑评估集子集（每类型前 4 条）。

用法：
    python scripts/eval_subset.py <port> <output.json>              # 普通跑
    python scripts/eval_subset.py <port> <output.json> --skip-reflection  # 对照实验：跳过质检
跑完输出每条耗时 + 汇总 metrics，供改动前后对比。
"""
import asyncio
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tests import run_eval  # noqa: E402


async def main():
    port = int(sys.argv[1])
    out = sys.argv[2]
    skip_reflection = "--skip-reflection" in sys.argv
    with open(ROOT / "tests" / "eval_set.json", encoding="utf-8") as f:
        questions = json.load(f)["questions"]

    picked = []
    for t in ("lookup", "analysis", "edge"):
        picked += [q for q in questions if q["type"] == t][:4]
    print(f"子集 {len(picked)} 条: {[q['id'] for q in picked]}"
          + ("（对照实验：跳过 Reflection）" if skip_reflection else ""), flush=True)

    login_data = json.dumps({"username": "admin", "password": "admin123"}).encode()
    req = urllib.request.Request(
        f"http://localhost:{port}/api/v1/auth/login",
        data=login_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    token = json.loads(urllib.request.urlopen(req, timeout=10).read())["access_token"]

    results = []
    for i, q in enumerate(picked, 1):
        print(f"[{i}/{len(picked)}] {q['id']} ({q['type']}) {q['question'][:40]}", flush=True)
        r = await run_eval.run_single_eval(q, token, port, None, skip_reflection=skip_reflection)
        results.append(r)
        if r.get("error"):
            print(f"  ERR {r['error'][:100]}", flush=True)
        else:
            print(f"  OK dim={r.get('dimension_coverage', 0) * 100:.0f}% lat={r['latency_ms'] / 1000:.1f}s", flush=True)

    with open(out, "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, ensure_ascii=False, indent=2)
    metrics = run_eval.compute_metrics(results)
    print("\nMETRICS:", json.dumps(metrics, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
