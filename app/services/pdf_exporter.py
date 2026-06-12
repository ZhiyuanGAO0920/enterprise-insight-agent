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
except ImportError:
    _WEASYPRINT_AVAILABLE = False

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


async def export_pdf(report: str, title: str = "经营分析报告", output_path: Path | None = None) -> bytes | None:
    """将报告导出为 PDF。

    Args:
        report: Markdown 格式的报告文本。
        title: 报告标题。
        output_path: 可选，保存路径。None 则返回 bytes。

    Returns:
        PDF 文件的字节内容，或 None（weasyprint 不可用时）。
    """
    if not _WEASYPRINT_AVAILABLE:
        logger.warning("weasyprint 未安装，无法生成 PDF")
        return None

    try:
        html_content = markdown_to_html(report, title)
        doc = WeasyHTML(string=html_content)
        pdf_bytes = doc.write_pdf()

        if output_path:
            output_path.write_bytes(pdf_bytes)
            logger.info("PDF 已导出", path=str(output_path))

        return pdf_bytes
    except Exception as e:
        logger.error("PDF 导出失败", error=str(e), exc_info=True)
        return None
