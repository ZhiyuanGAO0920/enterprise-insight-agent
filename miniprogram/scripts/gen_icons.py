# -*- coding: utf-8 -*-
"""生成 EIA 小程序图标资产。
- tabBar PNG 文件 -> miniprogram/assets/tabbar/*.png
- 内联图标 base64 WXSS -> miniprogram/styles/icons.wxss
全部为线性/填充矢量图标，颜色可控、跨端一致，替代原有 emoji。
"""
import base64
import io
import os

from PIL import Image, ImageDraw, ImageFont

S = 4                      # 超采样倍数（抗锯齿）
LOGICAL = 100              # 逻辑坐标空间：所有绘制函数按 0..100 取坐标
SIZE = 48                  # 内联图标输出尺寸(px)；由 png_b64 缩放到此尺寸
TAB = 81                   # tabBar 图标尺寸(px)；由 png_b64 缩放到此尺寸
WHITE = (255, 255, 255, 255)
TRANS = (0, 0, 0, 0)

ASSET_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "tabbar")
BRAND_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "brand")
STYLE_DIR = os.path.join(os.path.dirname(__file__), "..", "styles")

# EIA 品牌字标（Arial Bold 渲染，跨端一致；回退 Segoe UI Bold）
EIA_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
]


# ---------- 基础绘制助手（逻辑坐标 0..100） ----------
# 画布按 LOGICAL 建，不按输出尺寸 SIZE/TAB 建：绘制函数用的是 0..100 逻辑坐标，
# 乘 S 后需要 LOGICAL*S 的画布才装得下；最终尺寸由 png_b64 的 out_size 统一缩放。
# 曾经误用 SIZE*S（192px）建画布，导致坐标超出的部分被静默裁掉——图标只剩左上角。
def canvas():
    return Image.new("RGBA", (LOGICAL * S, LOGICAL * S), TRANS)


def tcanvas():
    # tabBar 图标同样按逻辑 0..100 绘制，输出尺寸在 png_b64(img, TAB) 指定
    return Image.new("RGBA", (LOGICAL * S, LOGICAL * S), TRANS)


def L(d, a, b, w, c):
    d.line([(a[0] * S, a[1] * S), (b[0] * S, b[1] * S)], fill=c, width=w * S, joint="curve")


def poly(d, pts, w, c):
    d.line([(x * S, y * S) for (x, y) in pts], fill=c, width=w * S, joint="curve")


def fpoly(d, pts, c):
    d.polygon([(x * S, y * S) for (x, y) in pts], fill=c)


def circ(d, cx, cy, r, c):
    d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], fill=c)


def ring(d, cx, cy, r, w, c):
    d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], outline=c, width=w * S)


def rrect(d, x, y, w, h, r, c):
    d.rounded_rectangle([x * S, y * S, (x + w) * S, (y + h) * S], radius=r * S, fill=c)


def rrect_out(d, x, y, w, h, r, wd, c):
    d.rounded_rectangle([x * S, y * S, (x + w) * S, (y + h) * S], radius=r * S, outline=c, width=wd * S)


def png_b64(img, out_size=SIZE):
    img = img.resize((out_size, out_size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ---------- 内联图标（线性，颜色传入） ----------
def ic_warning(c):
    img = canvas(); d = ImageDraw.Draw(img)
    poly(d, [(50, 14), (86, 82), (14, 82)], 8, c)
    L(d, (50, 40), (50, 62), 8, c); circ(d, 50, 72, 4, c)
    return png_b64(img)


def ic_arrow_up(c):
    img = canvas(); d = ImageDraw.Draw(img)
    L(d, (50, 82), (50, 24), 9, c); poly(d, [(34, 40), (50, 24), (66, 40)], 9, c)
    return png_b64(img)


def ic_arrow_down(c):
    img = canvas(); d = ImageDraw.Draw(img)
    L(d, (50, 18), (50, 76), 9, c); poly(d, [(34, 60), (50, 76), (66, 60)], 9, c)
    return png_b64(img)


def ic_trend(c):
    img = canvas(); d = ImageDraw.Draw(img)
    poly(d, [(16, 72), (40, 52), (58, 62), (84, 30)], 8, c)
    poly(d, [(70, 32), (84, 30), (78, 44)], 8, c)
    return png_b64(img)


def ic_chart(c):
    img = canvas(); d = ImageDraw.Draw(img)
    rrect(d, 22, 52, 14, 32, 3, c); rrect(d, 43, 36, 14, 48, 3, c); rrect(d, 64, 24, 14, 60, 3, c)
    return png_b64(img)


def ic_chat(c):
    img = canvas(); d = ImageDraw.Draw(img)
    rrect(d, 16, 18, 68, 46, 14, c); fpoly(d, [(30, 60), (30, 80), (50, 64)], c)
    return png_b64(img)


def ic_store(c):
    img = canvas(); d = ImageDraw.Draw(img)
    fpoly(d, [(14, 42), (50, 18), (86, 42)], c); rrect(d, 20, 42, 60, 40, 4, c)
    rrect(d, 41, 58, 18, 24, 2, WHITE)
    return png_b64(img)


def ic_box(c):
    img = canvas(); d = ImageDraw.Draw(img)
    rrect_out(d, 20, 28, 60, 52, 8, 8, c)
    L(d, (20, 52), (80, 52), 6, c); L(d, (50, 28), (50, 80), 6, c)
    return png_b64(img)


def ic_user(c):
    img = canvas(); d = ImageDraw.Draw(img)
    circ(d, 50, 36, 16, c); fpoly(d, [(22, 86), (34, 64), (66, 64), (78, 86)], c)
    return png_b64(img)


def ic_robot(c):
    img = canvas(); d = ImageDraw.Draw(img)
    rrect(d, 26, 26, 48, 44, 12, c)
    circ(d, 40, 48, 5, WHITE); circ(d, 60, 48, 5, WHITE)
    L(d, (50, 26), (50, 14), 5, c); circ(d, 50, 11, 4, c)
    return png_b64(img)


def ic_doc(c):
    img = canvas(); d = ImageDraw.Draw(img)
    rrect_out(d, 24, 16, 52, 68, 8, 8, c)
    L(d, (36, 40), (64, 40), 5, c); L(d, (36, 54), (64, 54), 5, c); L(d, (36, 68), (56, 68), 5, c)
    return png_b64(img)


def ic_bulb(c):
    img = canvas(); d = ImageDraw.Draw(img)
    ring(d, 50, 38, 22, 8, c); rrect(d, 40, 60, 20, 10, 3, c); L(d, (44, 70), (56, 70), 5, c)
    return png_b64(img)


def ic_clock(c):
    img = canvas(); d = ImageDraw.Draw(img)
    ring(d, 50, 50, 30, 8, c); L(d, (50, 50), (50, 30), 7, c); L(d, (50, 50), (66, 56), 7, c)
    return png_b64(img)


def ic_stop(c):
    img = canvas(); d = ImageDraw.Draw(img)
    rrect(d, 28, 28, 44, 44, 10, c)
    return png_b64(img)


def ic_check(c):
    img = canvas(); d = ImageDraw.Draw(img)
    poly(d, [(30, 52), (44, 66), (72, 34)], 9, c)
    return png_b64(img)


def ic_hourglass(c):
    img = canvas(); d = ImageDraw.Draw(img)
    fpoly(d, [(30, 24), (70, 24), (50, 50)], c); fpoly(d, [(50, 50), (30, 76), (70, 76)], c)
    return png_b64(img)


def ic_chevron_down(c):
    img = canvas(); d = ImageDraw.Draw(img)
    poly(d, [(30, 40), (50, 60), (70, 40)], 9, c)
    return png_b64(img)


def ic_share(c):
    img = canvas(); d = ImageDraw.Draw(img)
    rrect_out(d, 22, 42, 56, 40, 6, 8, c)
    L(d, (50, 42), (50, 18), 8, c); poly(d, [(36, 32), (50, 18), (64, 32)], 8, c)
    return png_b64(img)


def ic_building(c):
    img = canvas(); d = ImageDraw.Draw(img)
    rrect(d, 18, 40, 16, 44, 3, c); rrect(d, 40, 24, 16, 60, 3, c); rrect(d, 62, 34, 16, 50, 3, c)
    return png_b64(img)


def ic_close(c):
    img = canvas(); d = ImageDraw.Draw(img)
    L(d, (32, 32), (68, 68), 9, c); L(d, (68, 32), (32, 68), 9, c)
    return png_b64(img)


def ic_info(c):
    img = canvas(); d = ImageDraw.Draw(img)
    ring(d, 50, 50, 26, 8, c); L(d, (50, 42), (50, 64), 7, c); circ(d, 50, 32, 4, c)
    return png_b64(img)


# ---------- tabBar 图标（填充剪影） ----------
def tab_home(c):
    img = tcanvas(); d = ImageDraw.Draw(img)
    fpoly(d, [(50, 16), (84, 48), (74, 48), (74, 82), (26, 82), (26, 48), (16, 48)], c)
    return png_b64(img, TAB)


def tab_chat(c):
    img = tcanvas(); d = ImageDraw.Draw(img)
    rrect(d, 16, 18, 68, 46, 16, c); fpoly(d, [(34, 60), (34, 82), (56, 66)], c)
    return png_b64(img, TAB)


def tab_mine(c):
    img = tcanvas(); d = ImageDraw.Draw(img)
    circ(d, 50, 32, 16, c); fpoly(d, [(24, 84), (36, 58), (64, 58), (76, 84)], c)
    return png_b64(img, TAB)


# ---------- 颜色 ----------
C = {
    "primary": (26, 115, 232, 255),
    "primary_light": (74, 154, 245, 255),
    "success": (48, 209, 88, 255),
    "warning": (255, 149, 0, 255),
    "danger": (255, 59, 48, 255),
    "gray": (142, 142, 147, 255),
    "white": WHITE,
}

# 内联图标清单: (class_suffix, draw_fn, color_key)
INLINE = [
    ("warning", ic_warning, "warning"),
    ("warning-danger", ic_warning, "danger"),
    ("arrow-up", ic_arrow_up, "success"),
    ("arrow-down", ic_arrow_down, "danger"),
    ("trend", ic_trend, "primary"),
    ("chart", ic_chart, "gray"),
    ("chat", ic_chat, "white"),
    ("chat-primary", ic_chat, "primary"),
    ("store", ic_store, "gray"),
    ("box", ic_box, "gray"),
    ("user", ic_user, "white"),
    ("robot", ic_robot, "primary"),
    ("doc", ic_doc, "primary"),
    ("bulb", ic_bulb, "warning"),
    ("clock", ic_clock, "gray"),
    ("stop", ic_stop, "white"),
    ("check", ic_check, "white"),
    ("hourglass", ic_hourglass, "white"),
    ("chevron-down", ic_chevron_down, "gray"),
    ("share", ic_share, "gray"),
    ("close", ic_close, "danger"),
    ("info", ic_info, "gray"),
]

# ---------- 生成内联图标 WXSS ----------
lines = [
    "/* styles/icons.wxss — 自绘线性图标（base64 PNG，跨端一致，替代 emoji） */",
    "/* 由 scripts/gen_icons.py 生成，请勿手改 */",
    ".icon {",
    "  display: inline-block;",
    "  width: 40rpx;",
    "  height: 40rpx;",
    "  background-repeat: no-repeat;",
    "  background-position: center;",
    "  background-size: contain;",
    "  vertical-align: middle;",
    "}",
    ".icon-sm { width: 28rpx; height: 28rpx; }",
    ".icon-lg { width: 56rpx; height: 56rpx; }",
    ".icon-xl { width: 80rpx; height: 80rpx; }",
]

for suffix, fn, ck in INLINE:
    b64 = fn(C[ck])
    lines.append(".icon-%s { background-image: url(data:image/png;base64,%s); }" % (suffix, b64))

os.makedirs(STYLE_DIR, exist_ok=True)
with open(os.path.join(STYLE_DIR, "icons.wxss"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("icons.wxss written:", len(INLINE), "icons")

# ---------- 生成 tabBar PNG 文件 ----------
os.makedirs(ASSET_DIR, exist_ok=True)
tabs = [
    ("home", tab_home),
    ("chat", tab_chat),
    ("mine", tab_mine),
]
gray = C["gray"]; blue = C["primary"]
for name, fn in tabs:
    img_gray = fn(gray)
    img_blue = fn(blue)
    # fn 返回 base64（已 resize 到 TAB），这里重新生成为文件
    # 直接调用底层以拿到 Image 写出
    if name == "home":
        ig = tab_home(gray); ib = tab_home(blue)
    elif name == "chat":
        ig = tab_chat(gray); ib = tab_chat(blue)
    else:
        ig = tab_mine(gray); ib = tab_mine(blue)
    # ig/ib are base64 strings; decode and save
    for b64data, suffix in [(ig, ""), (ib, "_active")]:
        raw = base64.b64decode(b64data)
        with open(os.path.join(ASSET_DIR, "%s%s.png" % (name, suffix)), "wb") as f:
            f.write(raw)
print("tabbar png written: home/chat/mine x2")

# ---------- 生成 EIA 品牌字标 ----------
# 用于 AI 助手空状态等品牌露出位：跨端渲染一致（不依赖系统字体字重），
# 白色版配深色/渐变底盘，蓝色版配白底。
BLUE_RGBA = (26, 115, 232, 255)  # #1A73E8 = --color-primary


def _load_eia_font(size):
    for path in EIA_FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _eia_letters(color, size, tracking):
    """EIA 字母本体：逐字母排版 + 正字距，裁剪到内容边界。"""
    font = _load_eia_font(size)
    text = "EIA"
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    widths = []
    for ch in text:
        box = probe.textbbox((0, 0), ch, font=font)
        widths.append(box[2] - box[0])
    total = sum(widths) + tracking * (len(text) - 1)
    pad = 12
    img = Image.new("RGBA", (total + pad * 2, size * 2 + pad * 2), TRANS)
    d = ImageDraw.Draw(img)
    x = pad
    for ch, w in zip(text, widths):
        d.text((x, pad), ch, font=font, fill=color)
        x += w + tracking
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def make_eia_logo(color, size=96, tracking=5):
    """EIA 完整品牌标识 = 粗体字标 + 右下角上升折线（增长洞察，复用 ic_trend）。
    size=96 → 输出约 118x86 @3x，显示约 39x29px；配 160rpx 底盘时字标饱满且不压迫。
    跨端一致：不依赖系统字体的 900 字重（安卓无 900 会退化成 700）。"""
    letters = _eia_letters(color, size, tracking)

    # 折线符号：复用图标库 ic_trend，按字标比例缩放
    trend = Image.open(io.BytesIO(base64.b64decode(ic_trend(color))))
    tw = int(size * 0.46)
    trend = trend.resize((tw, tw), Image.LANCZOS)

    # 构图：字标居左上，折线压在右下角（与字标尾部轻微重叠，形成整体感）
    ox = int(tw * 0.52)
    oy = int(tw * 0.52)
    W = letters.width + ox
    H = letters.height + oy
    canvas_img = Image.new("RGBA", (W, H), TRANS)
    canvas_img.paste(letters, (0, 0), letters)
    canvas_img.paste(trend, (W - tw, H - tw), trend)

    bbox = canvas_img.getbbox()
    return canvas_img.crop(bbox) if bbox else canvas_img


os.makedirs(BRAND_DIR, exist_ok=True)
make_eia_logo(WHITE).save(os.path.join(BRAND_DIR, "eia-white.png"))
make_eia_logo(BLUE_RGBA).save(os.path.join(BRAND_DIR, "eia-blue.png"))
print("brand png written: eia-white / eia-blue")
print("DONE")
