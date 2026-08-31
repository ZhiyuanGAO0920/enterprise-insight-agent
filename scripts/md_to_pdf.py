# -*- coding: utf-8 -*-
"""Markdown → PDF（Chrome/Edge headless 打印）
用法: python scripts/md_to_pdf.py <input.md> <output.pdf>
"""
import re
import sys
from pathlib import Path

import markdown

CSS = """
<style>
  body { font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
         font-size: 14px; line-height: 1.7; color: #222; margin: 24px; }
  h1 { font-size: 26px; border-bottom: 2px solid #333; padding-bottom: 8px; }
  h2 { font-size: 20px; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin-top: 28px; }
  h3 { font-size: 16px; }
  table { border-collapse: collapse; width: 100%; margin: 12px 0; }
  th, td { border: 1px solid #999; padding: 6px 10px; text-align: left; }
  th { background: #f0f0f0; }
  code { background: #f5f5f5; padding: 2px 5px; border-radius: 3px;
         font-family: Consolas, monospace; font-size: 13px; }
  pre { background: #f5f5f5; padding: 12px; border-radius: 6px;
        overflow-x: auto; }
  pre code { background: none; padding: 0; }
  img { max-width: 100%; border: 1px solid #ddd; border-radius: 4px; margin: 8px 0; }
  blockquote { border-left: 4px solid #999; margin: 12px 0; padding: 4px 14px;
               color: #555; background: #fafafa; }
  @page { size: A4; margin: 18mm 16mm; }
</style>
"""


def main():
    src = Path(sys.argv[1]).resolve()
    dst = Path(sys.argv[2]).resolve()
    text = src.read_text(encoding="utf-8")

    # 图片相对路径 → 绝对路径（file:///）
    demo = src.parent.parent / "demo_output"
    text = re.sub(r"\]\((\.\./demo_output/[^)]+)\)",
                  lambda m: f"]({(demo / Path(m.group(1)).name).as_uri()})",
                  text)

    body = markdown.markdown(text, extensions=["tables", "fenced_code", "toc"])
    html = f"<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>{CSS}</head><body>{body}</body></html>"

    tmp = src.parent / f"_{src.stem}.html"
    tmp.write_text(html, encoding="utf-8")
    print(tmp)


if __name__ == "__main__":
    main()
