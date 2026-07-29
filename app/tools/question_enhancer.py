"""问题增强器 —— 在用户问题中注入系统指令以提升分析质量。

当前功能：
  - 排名/列表类问题的截断防护：注入指令要求 LLM 列出全部数据行，
    防止 LLM 在报告中只显示 Top 10 而遗漏其余数据。
"""

import re

# 排名/列表类问题指示性关键词
_RANKING_KEYWORDS = [
    "所有", "全部", "全部门", "全品类", "全区域",
    "排名", "排行", "榜单",
    "列表", "清单", "明细", "列举", "列出",
    "每家", "每个", "各门店", "各区域", "各品类",
    "TOP", "top", "Top",
]

# 排除模式：匹配关键词但实际非排名/列表语境
# 例如 "环比增长率" 中的 "比" 不应触发（但 "比" 不在关键词列表中，仅作示例）
# 当前关键词集合已足够精确，无需复杂排除

# 注入的系统指令
_RANKING_HINT = (
    "\n\n（注：这是一个排名/列表查询，请在报告中列出查询返回的"
    "全部数据行。如果 SQL 返回 100 行就列出 100 行，返回 50 行就列出 50 行。）"
)


def inject_ranking_hint(question: str) -> str:
    """检测是否排名/列表类查询，如是则注入截断防护指令。

    匹配逻辑：
      1. 中文关键词匹配：如果问题包含任何排名/列表指示词
      2. "前N" / "Top N" 显式排名模式：如 "前10门店"、"Top 5 商品"

    Args:
        question: 用户原始问题。

    Returns:
        增强后的问题（可能包含系统指令），或原问题（如果不匹配）。
    """
    # 检查中文关键词
    if any(kw in question for kw in _RANKING_KEYWORDS):
        return question + _RANKING_HINT

    # 检查显式排名模式："前N" / "Top N" / "top N"
    if re.search(r'(?:前|TOP|top)\s*\d+', question):
        return question + _RANKING_HINT

    return question
