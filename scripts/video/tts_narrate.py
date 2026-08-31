# -*- coding: utf-8 -*-
"""edge-tts 旁白配音：narration.json → 10 段 MP3 + durations.txt
用法: python scripts/video/tts_narrate.py
"""
import asyncio
import json
import sys
from pathlib import Path

import edge_tts

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
NARRATION = ROOT / "scripts" / "video" / "narration.json"
AUDIO_DIR = ROOT / "demo_output" / "video" / "audio"
VOICE = "zh-CN-YunxiNeural"  # 云希：年轻男声，接近 MiniMax 温润男声
RATE = "-4%"  # 稍慢，演示节奏
PITCH = "+0Hz"


async def synth(text: str, out: Path):
    for attempt in range(4):
        try:
            tts = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH)
            await tts.save(str(out))
            return
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️ 第 {attempt + 1} 次失败: {e}")
            await asyncio.sleep(3 * (attempt + 1))
    raise RuntimeError(f"4 次重试后仍失败: {out.name}")


async def main():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    narration = json.loads(NARRATION.read_text(encoding="utf-8"))
    durs = []
    for key in sorted(narration):
        mp3 = AUDIO_DIR / f"audio_{key}.mp3"
        await synth(narration[key], mp3)
        # 时长用 ffprobe 实测（mutagen 可读 MP3）
        from mutagen.mp3 import MP3
        durs.append(round(float(MP3(str(mp3)).info.length), 3))
        print(f"[{key}] {durs[-1]:.2f}s  {mp3.name}")
    (AUDIO_DIR / "durations.txt").write_text(
        "\n".join(f"{d:.3f}" for d in durs), encoding="utf-8")
    print(f"✅ 共 {len(durs)} 段，总时长 {sum(durs):.1f}s")
    print(f"   输出: {AUDIO_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
