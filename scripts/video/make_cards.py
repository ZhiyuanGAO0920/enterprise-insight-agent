# -*- coding: utf-8 -*-
"""PIL 生成 3 张文字卡：S2 痛点卡 / S9 演进卡 / S10 片尾卡（1920x1080 深色科技风）
用法: python scripts/video/make_cards.py
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")

OUT = Path(__file__).resolve().parent.parent.parent / "demo_output" / "video"
W, H = 1920, 1080
BG = (15, 20, 35)
ACCENT = (64, 192, 255)
WHITE = (235, 240, 245)
GRAY = (150, 160, 175)
FONT = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def new_card() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    # 顶部/底部渐变条 + 网格点装饰（深色科技风）
    for x in range(0, W, 60):
        for y in range(0, H, 60):
            draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(30, 40, 60))
    draw.rectangle([0, 0, W, 8], fill=ACCENT)
    return img, draw


def center(draw: ImageDraw.ImageDraw, text: str, y: int, size: int,
           fill=WHITE, bold: bool = True):
    f = font(size, bold)
    box = draw.textbbox((0, 0), text, font=f)
    draw.text(((W - (box[2] - box[0])) / 2, y), text, font=f, fill=fill)


def make_s2():
    """痛点卡：传统方式的一天"""
    img, draw = new_card()
    center(draw, "连锁零售的一天", 180, 64, ACCENT)
    items = [
        ("✕ 几十家门店、上万笔订单、几千个会员", 360),
        ("✕ 导出 Excel → 手动透视表 → 写分析报告", 480),
        ("✕ 半天过去，结论还没出来", 600),
        ("✓ 现在：中文提问，60 秒拿到带图表的诊断报告", 760),
    ]
    for text, y in items:
        center(draw, text, y, 40, WHITE if text.startswith("✓") else GRAY,
               bold=text.startswith("✓"))
    img.save(OUT / "s02_pain_card.png")


def make_s9():
    """演进卡：V2 → V3 → V5 演进对比"""
    img, draw = new_card()
    center(draw, "版本演进", 120, 64, ACCENT)
    cols = [
        ("V2", ["3 个 Agent", "6 张表", "无图表无流式", "pip install"], (120, 160, 190)),
        ("V3", ["8 个 Agent", "多轮对话", "基础图表", "pip install"], (120, 160, 190)),
        ("V5", ["11 个 Agent 节点", "契约化质检 ×4", "SQL 全链路追溯", "242 条自动化测试", "Docker 一键部署"], ACCENT),
    ]
    col_w = 560
    start_x = (W - 3 * col_w) // 2
    for i, (title, lines, color) in enumerate(cols):
        x = start_x + i * col_w
        # 卡片底
        draw.rounded_rectangle([x + 30, 260, x + col_w - 30, 880],
                               radius=16, fill=(25, 34, 54), outline=color, width=3)
        center(draw, title, 300, 56, color)
        for j, line in enumerate(lines):
            y = 410 + j * 80
            f = font(30)
            box = draw.textbbox((0, 0), line, font=f)
            draw.text(((W - (box[2] - box[0])) / 2, y), line, font=f, fill=WHITE)
    img.save(OUT / "s09_evolution_card.png")


def make_s10():
    """片尾卡：部署 + 署名"""
    img, draw = new_card()
    center(draw, "代码已开源", 200, 60, ACCENT)
    f = font(42, bold=True)
    text = "docker-compose up -d"
    box = draw.textbbox((0, 0), text, font=f)
    draw.rounded_rectangle(
        [(W - box[2]) / 2 - 40, 380, (W + box[2]) / 2 + 40, 380 + box[3] + 30],
        radius=10, fill=(20, 30, 50), outline=ACCENT, width=2)
    draw.text(((W - box[2]) / 2, 390), text, font=f, fill=ACCENT)
    center(draw, "5 个容器 · 2 分钟跑起来", 540, 32, GRAY)
    center(draw, "GitHub: github.com/ZhiyuanGAO0920/enterprise-insight-agent", 640, 28, GRAY)
    center(draw, "高志远 —— 既懂 AI Agent 架构、也能写全栈代码的 AI 产品经理", 800, 34, WHITE)
    img.save(OUT / "s10_ending_card.png")


if __name__ == "__main__":
    make_s2()
    make_s9()
    make_s10()
    print("✅ 3 张文字卡已生成:", OUT)
