"""V4 PDF 报告导出服务。

将 Markdown 分析报告渲染为专业 PDF 文档。
支持图表嵌入、中文排版、标准 A4 纸张。
"""

from pathlib import Path

from app.logging_config import get_logger

logger = get_logger("eia.services.pdf")

# weasyprint 为可选依赖，未安装时优雅降级
try:
    from weasyprint import HTML as WeasyHTML
    _WEASYPRINT_AVAILABLE = True
except Exception:
    _WEASYPRINT_AVAILABLE = False

# reportlab 为纯 Python 降级方案（Windows 开发环境 weasyprint 缺系统库时可用，
# 中文使用内置 CID 字体 STSong-Light，无需字体文件）
try:
    import os
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    _REPORTLAB_AVAILABLE = True
except Exception:
    _REPORTLAB_AVAILABLE = False
    TTFont = None  # type: ignore

# reportlab 中文字体：优先系统 TrueType 字体（带 ToUnicode 映射，文本可复制/搜索），
# 找不到时降级 CID 字体 STSong-Light（仅显示，不可复制）。
# Windows: msyh.ttc(微软雅黑)/simsun.ttc(宋体)；Linux: Noto Sans CJK / wqy-microhei。
def _register_cjk_font() -> str:
    _FONT_DIRS = [
        os.environ.get("WINDIR", r"C:\Windows") + r"\Fonts",
        "/usr/share/fonts/opentype/noto",
        "/usr/share/fonts/truetype",
        "/usr/local/share/fonts",
    ]
    _FONT_FILES = [
        "msyh.ttc", "msyh.ttf", "simsun.ttc", "simsun.ttf",
        "NotoSansCJK-Regular.ttc", "NotoSansCJKsc-Regular.otf",
        "wqy-microhei.ttc", "wqy-zenhei.ttc",
    ]
    for d in _FONT_DIRS:
        for f in _FONT_FILES:
            p = os.path.join(d, f)
            if not os.path.exists(p):
                continue
            try:
                pdfmetrics.registerFont(TTFont("CJK", p))
                return "CJK"
            except Exception:
                continue
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        return "STSong-Light"
    except Exception:
        return "Helvetica"


_CJK_FONT = _register_cjk_font() if _REPORTLAB_AVAILABLE else "Helvetica"

# 报告模板路径
TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"
REPORT_TEMPLATE = TEMPLATE_DIR / "report_template.html"


def markdown_to_html(report: str, title: str = "经营分析报告") -> str:
    """将 Markdown 报告转换为 HTML。

    Args:
        report: Markdown 格式的报告文本。
        title: 报告标题。

    Returns:
        完整 HTML 字符串。
    """
    # 基础 Markdown → HTML 转换
    html = report

    # 标题（使用正则确保正确闭合）
    import re
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)

    # 粗体和斜体
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)

    # 列表
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"(<li>.*</li>\n?)+", r"<ul>\g<0></ul>", html)

    # 表格：将 Markdown 表格转换为完整 HTML <table>
    _table_rows = []
    _in_table = False
    _is_first_data_row = True

    def _md_table_row_to_html(line):
        nonlocal _in_table, _is_first_data_row
        content = line.group(1)
        # 分隔行（|---|----|）—— 标记表头结束
        if re.match(r'^[\s\-:|]+$', content):
            _is_first_data_row = False
            return "\x00SEP\x00"  # 哨兵，稍后替换
        cells = [c.strip() for c in content.split("|")]
        if _is_first_data_row:
            tds = "".join(f"<th>{c}</th>" for c in cells)
            _is_first_data_row = False
        else:
            tds = "".join(f"<td>{c}</td>" for c in cells)
        return f"<tr>{tds}</tr>"

    # 收集连续的表格行
    lines = html.split("\n")
    result_lines = []
    table_buffer = []
    for line in lines:
        if re.match(r"^\|(.+)\|$", line):
            row_html = _md_table_row_to_html(re.match(r"^\|(.+)\|$", line))
            if row_html == "\x00SEP\x00":
                table_buffer.append(row_html)
            else:
                table_buffer.append(row_html)
        else:
            if table_buffer:
                # 结束当前表格，包裹为 <table>
                clean_rows = [r for r in table_buffer if r != "\x00SEP\x00"]
                result_lines.append("<table>" + "".join(clean_rows) + "</table>")
                table_buffer = []
            result_lines.append(line)
    if table_buffer:
        clean_rows = [r for r in table_buffer if r != "\x00SEP\x00"]
        result_lines.append("<table>" + "".join(clean_rows) + "</table>")

    html = "\n".join(result_lines)

    # 段落
    paragraphs = html.split("\n\n")
    html = "".join(
        f"<p>{p}</p>" if not p.startswith("<") else p
        for p in paragraphs
        if p.strip()
    )

    # 移除图表标记（PDF 中不渲染）
    html = re.sub(r"\[CHART:\w+\|.+?\]", "", html)
    html = re.sub(r"\[FOLLOWUP:.*?\]", "", html)

    # 包裹为完整 HTML
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  body {{ font-family: 'SimSun', 'Microsoft YaHei', serif; font-size: 12pt; line-height: 1.8; margin: 2cm; color: #333; }}
  h1 {{ font-size: 20pt; border-bottom: 2px solid #6366f1; padding-bottom: 8px; }}
  h2 {{ font-size: 16pt; color: #6366f1; margin-top: 24px; }}
  h3 {{ font-size: 14pt; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 10pt; }}
  th {{ background: #f5f5f5; font-weight: bold; }}
  ul {{ padding-left: 20px; }}
  li {{ margin: 4px 0; }}
  strong {{ color: #6366f1; }}
  .footer {{ text-align: center; font-size: 9pt; color: #999; margin-top: 30px; border-top: 1px solid #eee; padding-top: 12px; }}
</style>
</head>
<body>
<h1>{title}</h1>
{html}
<div class="footer">本报告由企业智能经营分析平台 V4 自动生成</div>
</body>
</html>"""


def _inline_md(text: str) -> str:
    """Markdown 行内格式 → reportlab Paragraph 支持的 HTML 标签。"""
    import re
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    return text


def _export_pdf_reportlab(report: str, title: str = "经营分析报告") -> bytes:
    """reportlab 降级渲染：纯 Python、无系统依赖，中文用内置 CID 字体 STSong-Light。

    支持标题、段落、粗体/斜体、列表、表格；[CHART]/[FOLLOWUP] 标记剥离。
    """
    from io import BytesIO

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title=title,
        topMargin=2 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
    )

    _FONT = _CJK_FONT
    s_title = ParagraphStyle("title", fontName=_FONT, fontSize=17, leading=25, spaceAfter=16, textColor=colors.HexColor("#1f2937"))
    s_h2 = ParagraphStyle("h2", fontName=_FONT, fontSize=13, leading=19, spaceBefore=12, spaceAfter=5, textColor=colors.HexColor("#4f46e5"))
    s_h3 = ParagraphStyle("h3", fontName=_FONT, fontSize=11.5, leading=17, spaceBefore=9, spaceAfter=4, textColor=colors.HexColor("#374151"))
    s_body = ParagraphStyle("body", fontName=_FONT, fontSize=10, leading=17, spaceAfter=5)
    s_cell = ParagraphStyle("cell", fontName=_FONT, fontSize=8.5, leading=13)
    s_footer = ParagraphStyle("footer", fontName=_FONT, fontSize=8, leading=12, alignment=TA_CENTER, textColor=colors.HexColor("#9ca3af"))

    import re
    story = [Paragraph(title, s_title)]

    lines = report.split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        i += 1
        if not stripped:
            continue
        stripped = re.sub(r"\[CHART:\w+\|.+?\]", "", stripped)
        stripped = re.sub(r"\[FOLLOWUP:.*?\]", "", stripped)
        stripped = stripped.strip()
        if not stripped:
            continue
        if stripped.startswith("### "):
            story.append(Paragraph(_inline_md(stripped[4:]), s_h3))
        elif stripped.startswith("## "):
            story.append(Paragraph(_inline_md(stripped[3:]), s_h2))
        elif stripped.startswith("# "):
            story.append(Paragraph(_inline_md(stripped[2:]), s_title))
        elif stripped.startswith("|") and stripped.endswith("|"):
            # 收集连续表格行（跳过 |---|---| 分隔行）
            rows = [lines[i - 1]]
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            data = []
            for row in rows:
                cells = [c.strip() for c in row.strip().strip("|").split("|")]
                if not all(re.match(r"^[\s\-:]+$", c) for c in cells):
                    data.append([Paragraph(_inline_md(c), s_cell) for c in cells])
            if data:
                ncols = max(len(r) for r in data)
                for r in data:
                    while len(r) < ncols:
                        r.append(Paragraph("", s_cell))
                tbl = Table(data, repeatRows=1)
                tbl.setStyle(TableStyle([
                    ("FONTNAME", (0, 0), (-1, -1), _FONT),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]))
                story.append(tbl)
                story.append(Spacer(1, 8))
        elif stripped.startswith("- "):
            while i < len(lines) and lines[i].strip().startswith("- "):
                story.append(Paragraph("• " + _inline_md(lines[i].strip()[2:]), s_body))
                i += 1
            story.append(Spacer(1, 3))
        else:
            story.append(Paragraph(_inline_md(stripped), s_body))

    story.append(Spacer(1, 24))
    story.append(Paragraph("本报告由企业智能经营分析平台 V4 自动生成", s_footer))
    doc.build(story)
    return buf.getvalue()


async def export_pdf(report: str, title: str = "经营分析报告", output_path: Path | None = None) -> bytes | None:
    """将报告导出为 PDF。

    Args:
        report: Markdown 格式的报告文本。
        title: 报告标题。
        output_path: 可选，保存路径。None 则返回 bytes。

    Returns:
        PDF 文件的字节内容，或 None（weasyprint 与 reportlab 均不可用时）。
    """
    if _WEASYPRINT_AVAILABLE:
        try:
            html_content = markdown_to_html(report, title)
            doc = WeasyHTML(string=html_content)
            pdf_bytes = doc.write_pdf()

            if output_path:
                output_path.write_bytes(pdf_bytes)
                logger.info("PDF 已导出", path=str(output_path))

            return pdf_bytes
        except Exception as e:
            logger.error("weasyprint PDF 导出失败，降级到 reportlab", error=str(e), exc_info=True)

    if _REPORTLAB_AVAILABLE:
        try:
            pdf_bytes = _export_pdf_reportlab(report, title)
            if output_path:
                output_path.write_bytes(pdf_bytes)
                logger.info("PDF 已导出（reportlab 降级）", path=str(output_path))
            return pdf_bytes
        except Exception as e:
            logger.error("reportlab PDF 导出失败", error=str(e), exc_info=True)
            return None

    logger.warning("PDF 导出不可用（weasyprint 和 reportlab 均未安装）")
    return None
