"""Quick test for followup_questions save bug."""
import json, http.client, io, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

with open(r"C:\Users\GaoZhiyuan\AppData\Local\Temp\login_resp.txt") as f:
    token = json.load(f)["access_token"]

conn = http.client.HTTPConnection("localhost", 8002, timeout=180)
body = json.dumps({"question": "门店销售排名", "session_id": "fq-final-test-2"}).encode("utf-8")
conn.request("POST", "/api/v1/analysis/analyze-stream", body, {
    "Authorization": "Bearer " + token,
    "Content-Type": "application/json",
})
r = conn.getresponse()
raw = r.read().decode("utf-8")
conn.close()

# Try to parse every data: line, looking for type=done
for line in raw.split("\n"):
    if line.startswith("data: "):
        try:
            evt = json.loads(line[6:])
            if evt.get("type") == "done":
                fq = evt.get("followup_questions", [])
                print("SUCCESS: fq =", json.dumps(fq, ensure_ascii=False))
                print("SUCCESS: rid =", evt.get("record_id"))
                break
        except json.JSONDecodeError:
            continue
else:
    print("No done event found in", len(raw), "bytes of output")
