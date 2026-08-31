# -*- coding: utf-8 -*-
"""EIA V5 Demo 视频合成：12 段（截图/卡片 + 旁白）→ demo_v5.mp4
每段：Ken Burns 轻微运镜 + 旁白；段间 xfade 0.3s 叠化 + acrossfade；
最后烧录字幕（微软雅黑）。
用法: python scripts/video/compose_video.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from mutagen.mp3 import MP3

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
VIDEO_DIR = ROOT / "demo_output" / "video"
AUDIO_DIR = VIDEO_DIR / "audio"
OUT = VIDEO_DIR / "demo_v5.mp4"
FFMPEG = "ffmpeg"
XFADE = 0.3
FPS = 25
W, H = 1920, 1080

# 段 → 画面映射（12 段）
SHOTS = [
    "s01_welcome.png",
    "s02_pain_card.png",
    "s03_users.png",
    "s04_dashboard.png",
    "s05_refund_query.png",
    "s06_east_report.png",
    "s06_trace_panel.png",
    "s07_weekly_report.png",
    "s08_pii_masked.png",
    "s08_monitor.png",
    "s09_evolution_card.png",
    "s10_ending_card.png",
]
AUDIO_KEYS = ["01", "02", "03", "04", "05", "06a", "06b", "07", "08a", "08b", "09", "10"]


def run(cmd: list[str], label: str):
    print(f"▶ {label}")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"❌ {label} 失败\n{r.stderr[-1500:]}")
        sys.exit(1)
    return r


def make_clip(shot: Path, audio: Path, dur: float, motion: str, out: Path):
    """单段：图 + 音频，Ken Burns 轻微运镜"""
    frames = max(int(round(dur * FPS)), 2)
    if motion == "zoom_in":
        z = "min(zoom+0.0009,1.10)"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    else:  # slow_zoom_in
        z = "min(zoom+0.0005,1.08)"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    vf = (
        f"scale=2200:1238,"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS}"
    )
    run([
        FFMPEG, "-y",
        "-loop", "1", "-i", str(shot),
        "-i", str(audio),
        "-vf", vf,
        "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(out),
    ], f"clip {out.name} ({dur:.1f}s, {motion})")


def main():
    durs = [float(MP3(str(AUDIO_DIR / f"audio_{k}.mp3")).info.length) for k in AUDIO_KEYS]
    print("段时长:", " ".join(f"{d:.2f}" for d in durs))
    clips = []
    motions = ["zoom_in", "slow_zoom_in"] * 6
    for i, (shot_name, audio_key, motion, dur) in enumerate(
            zip(SHOTS, AUDIO_KEYS, motions, durs), 1):
        shot = VIDEO_DIR / shot_name
        assert shot.exists(), f"缺画面 {shot}"
        out = VIDEO_DIR / "clips" / f"clip_{i:02d}.mp4"
        out.parent.mkdir(exist_ok=True)
        make_clip(shot, AUDIO_DIR / f"audio_{audio_key}.mp3", dur, motion, out)
        clips.append(out)
        print(f"  clip {i}/12 done ({dur:.1f}s)")

    # xfade 串联 + acrossfade 音频
    acc = 0.0
    offsets = []
    for k in range(11):
        acc += durs[k]
        offsets.append(acc - XFADE * (k + 1))
    flt = []
    cur = "[0:v]"
    for k in range(11):
        outl = f"[vx{k}]"
        flt.append(f"{cur}[{k + 1}:v]xfade=transition=fade:duration={XFADE}:offset={offsets[k]:.3f}{outl}")
        cur = outl
    aflt = []
    acur = "[0:a]"
    for k in range(11):
        outl = f"[ax{k}]"
        aflt.append(f"{acur}[{k + 1}:a]acrossfade=d={XFADE}{outl}")
        acur = outl

    # 字幕（英文临时路径 + UTF-8 + 微软雅黑）
    srt = AUDIO_DIR / "subtitles.srt"
    assert srt.exists(), "先运行 make_srt.py"
    tmp = Path(tempfile.gettempdir()) / "eia_demo_subtitles.srt"
    shutil.copyfile(srt, tmp)
    srt_esc = str(tmp).replace("\\", "/").replace(":", "\\:")
    flt.append(f"{cur}subtitles=filename='{srt_esc}':charenc=utf-8"
              f":force_style='FontName=Microsoft YaHei,FontSize=20,PrimaryColour=&H00FFFFFF,"
              f"OutlineColour=&H00101010,BorderStyle=1,Outline=2,Shadow=1,"
              f"MarginV=50,Alignment=2'[vfin]")

    total = acc + durs[11] + XFADE
    cmd = [FFMPEG, "-y"]
    for c in clips:
        cmd += ["-i", str(c)]
    cmd += ["-filter_complex", ";".join(flt + aflt),
            "-map", "[vfin]", "-map", acur,
            "-t", f"{total:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(OUT)]
    run(cmd, f"全片合成 → {OUT.name} ({total:.1f}s)")

    r = subprocess.run([FFMPEG, "-i", str(OUT)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    import re
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr)
    if m:
        hh, mm, ss = m.groups()
        print(f"✅ 成片时长: {int(hh) * 3600 + int(mm) * 60 + float(ss):.1f}s")
    print(f"✅ 完成: {OUT}")


if __name__ == "__main__":
    main()
