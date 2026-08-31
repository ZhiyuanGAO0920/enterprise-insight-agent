# -*- coding: utf-8 -*-
"""旁白字幕 SRT：narration.json + durations.txt → subtitles.srt
时间轴含 xfade 0.3s 叠化偏移；字幕起点 = 段起点 + 0.5s。
用法: python scripts/video/make_srt.py
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
NARRATION = ROOT / "scripts" / "video" / "narration.json"
AUDIO_DIR = ROOT / "demo_output" / "video" / "audio"
OUT = AUDIO_DIR / "subtitles.srt"
XFADE = 0.3


def strip_tags(text: str) -> str:
    return re.sub(r"\([a-z]+\)", "", text).strip()


def ts(sec: float) -> str:
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms == 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main():
    narration = json.loads(NARRATION.read_text(encoding="utf-8"))
    durs = [float(x) for x in (AUDIO_DIR / "durations.txt").read_text(encoding="utf-8").split()]
    keys = sorted(narration)
    assert len(keys) == len(durs), f"{len(keys)} 段文本 vs {len(durs)} 段音频"

    starts = []
    cur = 0.0
    for d in durs:
        starts.append(cur)
        cur += d - XFADE
    total = cur + XFADE

    lines = []
    idx = 1
    for key, d, start in zip(keys, durs, starts):
        text = strip_tags(narration[key])
        lines.append(str(idx))
        lines.append(f"{ts(start + 0.5)} --> {ts(start + d - 0.3)}")
        lines.append(text)
        lines.append("")
        idx += 1

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ 字幕已生成: {OUT}")
    print(f"   成片总时长: {total:.1f}s ({len(keys)} 段, xfade={XFADE}s)")


if __name__ == "__main__":
    main()
