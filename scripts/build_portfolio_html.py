"""将作品集 Markdown 转为排版精美的自包含 HTML（可直接打印 PDF）"""
import re, base64, os
from markdown import markdown as md_to_html
from markdown.extensions.tables import TableExtension
from markdown.extensions.fenced_code import FencedCodeExtension

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
md_path = os.path.join(PROJECT, 'docs', '作品集-EIA-V4.md')
out_path = os.path.join(PROJECT, 'docs', '作品集-EIA-V4.html')

with open(md_path, encoding='utf-8') as f:
    md = f.read()

# 第一步：图片链接 → base64 HTML img 标签
def replace_img(m):
    alt = m.group(1)
    path = m.group(2)
    fpath = os.path.join(PROJECT, path.replace('../', ''))
    if os.path.exists(fpath):
        ext = fpath.split('.')[-1].lower()
        mime = 'image/png' if ext == 'png' else 'image/jpeg'
        with open(fpath, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
        return f'<p style="text-align:center"><img src="data:{mime};base64,{b64}" alt="{alt}" style="max-width:100%;border-radius:8px;margin:16px auto;box-shadow:0 2px 12px rgba(0,0,0,.1)"></p>'
    return m.group(0)

md = re.sub(r'!\[(.*?)\]\((.*?)\)', replace_img, md)

# 第二步：Markdown → HTML（使用 markdown 库）
extensions = [
    TableExtension(),
    FencedCodeExtension(),
    'markdown.extensions.codehilite',
]
html_body = md_to_html(md, extensions=extensions, output_format='html5')

# 第三步：套入精美模板
html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>高志远 · AI 产品作品集</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{
    max-width:860px;margin:0 auto;padding:48px 24px;
    font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei","Helvetica Neue",sans-serif;
    color:#1a1a2e;line-height:1.85;background:#fff;
    font-size:15px;
}}
h1{{
    font-size:30px;font-weight:700;color:#1a1a2e;
    border-bottom:3px solid #6366f1;padding-bottom:16px;margin-bottom:32px;
}}
h2{{
    font-size:22px;font-weight:700;color:#6366f1;
    margin-top:48px;margin-bottom:16px;
    padding-bottom:8px;border-bottom:1px solid #e5e7eb;
}}
h3{{font-size:17px;font-weight:600;color:#374151;margin-top:28px;margin-bottom:10px}}
h4{{font-size:15px;font-weight:600;color:#6b7280;margin-top:20px}}
p{{margin-bottom:14px}}
strong{{color:#4f46e5;font-weight:600}}
a{{color:#6366f1;text-decoration:none}}
a:hover{{text-decoration:underline}}
blockquote{{
    border-left:4px solid #6366f1;padding:8px 16px;margin:16px 0;
    background:#f8f7ff;color:#4b5563;border-radius:0 8px 8px 0;
}}
blockquote p{{margin-bottom:4px}}
table{{
    border-collapse:collapse;width:100%;margin:16px 0 24px;
    font-size:14px;
}}
thead{{background:#f3f4f6}}
th,td{{border:1px solid #e5e7eb;padding:10px 14px;text-align:left}}
th{{font-weight:600;color:#374151;font-size:13px;text-transform:uppercase;letter-spacing:0.5px}}
tr:nth-child(even){{background:#fafafa}}
img{{
    max-width:100%;border-radius:8px;margin:16px 0;
    box-shadow:0 2px 12px rgba(0,0,0,.08);
}}
code{{
    background:#f3f4f6;padding:2px 6px;border-radius:4px;font-size:13px;
    font-family:"SF Mono","Fira Code","Consolas",monospace;
}}
pre{{
    background:#1e293b;color:#e2e8f0;padding:20px 24px;border-radius:10px;
    overflow-x:auto;margin:16px 0;font-size:13px;line-height:1.6;
}}
pre code{{background:none;padding:0;color:inherit;font-size:inherit}}
ul,ol{{padding-left:24px;margin:12px 0}}
li{{margin-bottom:6px}}
hr{{border:none;border-top:1px solid #e5e7eb;margin:40px 0}}
/* Print */
@media print{{
    body{{margin:0;padding:20px;font-size:12px;max-width:100%}}
    h1{{font-size:22px}}h2{{font-size:17px}}
    img{{page-break-inside:avoid;box-shadow:none}}
    pre{{background:#f3f4f6;color:#1a1a2e}}
    @page{{margin:1.5cm}}
}}
</style>
</head>
<body>
{html_body}
<hr>
<p style="text-align:center;color:#9ca3af;font-size:13px;margin-top:32px">
Enterprise Insight Agent V4 · 2026 ·
<a href="https://github.com/ZhiyuanGAO0920/enterprise-insight-agent">GitHub</a>
</p>
</body>
</html>'''

with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)

size_mb = os.path.getsize(out_path) / 1048576
imgs = html.count('data:image')
print(f'Done: {out_path}')
print(f'  Size: {size_mb:.1f} MB | Images: {imgs} embedded')
print(f'  Open in browser → Ctrl+P → Save as PDF')
