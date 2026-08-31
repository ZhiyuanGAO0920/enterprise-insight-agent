"""V5 T-10a / Phase 2：Claim-level Grounding 校验器（零 LLM，纯确定性）。

核心算法：
  1. **抽 claim**：报告文本按句拆分 → 保留「含数字的陈述句」（关键结论口径，方案 §8.2）
  2. **数字归一化**：125,000.50 / 12.5万 / 125% / 12.5亿 → 可比数值；同时保留字面量
  3. **匹配判定**：claim 的每个数字在任一 data_sources[i].raw_data 中存在即可 grounded
     - 精确子串（去掉千分位逗号 + 统一大小写后）命中 → 直接 grounded
     - 归一化数值 fuzzy（±0.5% 相对误差）命中 → grounded
  4. **输出**：Evidence Coverage = grounded_claims / total_claims

注意：
  - 纯确定性，零 LLM 成本，可在 Reflection 后置校验 / eval_runner / 监控仪表板三处复用
  - 不替代 Reflection 的 Reasoning Validity（因果判断），只校验数字真实性
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, asdict
from typing import Any

# ---------------------------------------------------------------------------
# 数字提取 + 归一化
# ---------------------------------------------------------------------------

# 中文单位映射：万/亿/万%
_CN_UNIT = {"万": 10_000, "亿": 100_000_000, "k": 1_000, "K": 1_000, "w": 10_000, "W": 10_000}

# 数字正则：支持 123 / 123.45 / 1,234,567.89 / 12万 / 12.5% / -3.14
# 组 1 = 数值主体，组 2 = 可选单位，组 3 = 可选 %
_NUM_RE = re.compile(
    r"(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*([万亿kKwW])?(%)?"
)


@dataclass
class NumberToken:
    """报告或 raw_data 中提取的一个数字。"""
    original: str          # 原始字面量（如 "1,234,567.89 万%"）
    value: float           # 归一化数值（1234567.89）；百分比值 / 100 存储
    is_percent: bool       # 是否带 %


def extract_numbers(text: str) -> list[NumberToken]:
    """从任意文本中提取数字 token 列表。"""
    if not text:
        return []
    tokens: list[NumberToken] = []
    for m in _NUM_RE.finditer(text):
        raw_num = m.group(1).replace(",", "")     # 去千分位
        unit = m.group(2)
        percent = m.group(3)
        try:
            val = float(raw_num)
        except ValueError:
            continue
        if unit and unit in _CN_UNIT:
            val *= _CN_UNIT[unit]
        is_pct = percent is not None
        if is_pct:
            val /= 100.0
        tokens.append(NumberToken(original=m.group(0), value=val, is_percent=is_pct))
    return tokens


# ---------------------------------------------------------------------------
# Claim 抽取
# ---------------------------------------------------------------------------

# 句末标点 / 换行符 拆分
_SPLIT_RE = re.compile(r"[。！？!?\n]+")


def extract_claims(report_text: str) -> list[str]:
    """从报告正文提取「含数字的陈述句」（关键结论，口径已定）。"""
    if not report_text:
        return []
    raw_sentences = _SPLIT_RE.split(report_text)
    claims: list[str] = []
    for s in raw_sentences:
        s = s.strip().strip("#*•- \t")
        if not s:
            continue
        # 太短（<6 字符）、纯 markdown 标题（只有 --- 或 #）跳过
        if len(s) < 6:
            continue
        if set(s) <= {"-", "=", " "}:
            continue
        # 含数字的陈述句（正则里已经包含 %. 数字，足够）
        if _NUM_RE.search(s):
            claims.append(s)
    return claims


# ---------------------------------------------------------------------------
# 数字匹配
# ---------------------------------------------------------------------------

_FUZZY_TOL = 0.005  # 相对误差 ±0.5%


def _fuzzy_equal(a: float, b: float, a_pct: bool, b_pct: bool) -> bool:
    """归一化数值 fuzzy 匹配。

    - 同 pct 标志：用 ±0.5% 相对误差（容忍正常四舍五入、展示近似）
    - 异 pct 标志：数据库常把比例值存为 0.xx（小数），报告里展示为 xx%——这是同一个口径的两种写法。
      但 50（绝对值）vs 0.5（50%）语义不同。因此：
      * 仅当**值完全相等（1e-9 内）**时视为匹配，防止 50 与 0.5 串配。
    """
    if a == 0 and b == 0:
        return True
    denom = max(abs(a), abs(b))
    if denom == 0:
        return False
    re = abs(a - b) / denom
    if a_pct == b_pct:
        return re <= _FUZZY_TOL
    # 异 pct：只有值"几乎完全相等"才认为是同口径不同写法
    return re <= 1e-9


def _literal_match(tok: NumberToken, raw_text: str) -> bool:
    """字面量子串匹配（去掉千分位、空白后再比）。"""
    canon_original = re.sub(r"[\s,]", "", tok.original)
    canon_raw = re.sub(r"[\s,]", "", raw_text)
    if canon_original and canon_original in canon_raw:
        return True
    # 兼容：Decimal 包装 (raw_data 是 SQLAlchemy 结果 repr)
    # 如 "Decimal('125000.50')" 包含 "125000.50"
    stripped_value = tok.original.strip()
    # 去掉末尾单位 / % 子串，纯数值段
    val_match = re.match(r"(-?[\d,]+\.?\d*)", tok.original.replace(",", ""))
    if val_match and val_match.group(1) in canon_raw:
        return True
    return False


# ---------------------------------------------------------------------------
# 核心数据结构
# ---------------------------------------------------------------------------

@dataclass
class ClaimCheck:
    claim: str                           # 原句
    numbers: list[dict]                  # [{original, value, is_percent}]
    grounded: bool                       # 是否至少 1 个数字命中证据
    matched_source_ids: list[int]        # 命中的 data_sources id（1-based，来自 agent.base）


@dataclass
class GroundingResult:
    total_claims: int = 0
    grounded_claims: int = 0
    evidence_coverage: float = 0.0       # grounded / total（0 个 claim 时 = 0.0）
    details: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_claims": self.total_claims,
            "grounded_claims": self.grounded_claims,
            "evidence_coverage": self.evidence_coverage,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def check_report_grounding(
    report_text: str,
    data_sources: list[dict] | None,
) -> GroundingResult:
    """校验报告数字是否被 data_sources.raw_data 支撑。

    Args:
        report_text: 报告正文（Markdown，通常是 state["report"]）。
        data_sources: 证据链 list[{id,agent,sql,row_count,raw_data,...}]。

    Returns:
        GroundingResult，含 Evidence Coverage 指标 + 每条 claim 的详细判定。
    """
    claims = extract_claims(report_text)
    ds_list = data_sources or []
    # 预提取每个 data_source 的 raw_data（字符串归一化：去空白 + 去千分位加速后续子串）
    ds_raws: list[str] = []
    for ds in ds_list:
        raw = ds.get("raw_data", "") if isinstance(ds, dict) else ""
        ds_raws.append(str(raw) if raw is not None else "")

    result = GroundingResult(total_claims=len(claims))
    if not claims:
        return result

    for claim in claims:
        num_toks = extract_numbers(claim)
        if not num_toks:
            # extract_claims 已经过滤无数字，但归一化失败兜底
            result.details.append(ClaimCheck(
                claim=claim, numbers=[], grounded=False, matched_source_ids=[],
            ).__dict__)
            continue

        grounded_any = False
        matched_ids: list[int] = []

        for tok in num_toks:
            for idx, raw in enumerate(ds_raws):
                if not raw:
                    continue
                hit = (
                    _literal_match(tok, raw)
                    or any(
                        _fuzzy_equal(tok.value, other.value, tok.is_percent, other.is_percent)
                        for other in extract_numbers(raw)
                    )
                )
                if hit:
                    grounded_any = True
                    ds_id = (ds_list[idx].get("id") if isinstance(ds_list[idx], dict) else None) or (idx + 1)
                    if ds_id not in matched_ids:
                        matched_ids.append(ds_id)

        check = ClaimCheck(
            claim=claim,
            numbers=[asdict(t) for t in num_toks],
            grounded=grounded_any,
            matched_source_ids=matched_ids,
        )
        result.details.append(check.__dict__)
        if grounded_any:
            result.grounded_claims += 1

    result.evidence_coverage = (
        round(result.grounded_claims / result.total_claims, 4)
        if result.total_claims > 0 else 0.0
    )
    return result


# ---------------------------------------------------------------------------
# Numerical Consistency（契约项 1，系统确定性）：report 数字 vs data_sources.raw_data 数字
# ---------------------------------------------------------------------------

@dataclass
class NumericalResult:
    """数值一致性检查结果。"""
    total_report_numbers: int = 0
    matched_numbers: int = 0
    coverage: float = 0.0          # 0~1
    score: int = 0                 # 0~100（coverage * 100 取整）
    unmatched: list[dict] = field(default_factory=list)  # [{original, value, is_percent, matched_source_ids}]


def check_numerical_consistency(report_text: str, data_sources: list[dict] | None) -> NumericalResult:
    """检查 report 中所有出现的数字是否在任一 data_sources.raw_data 的值域内存在。

    与 grounding 的区别：
      - grounding = 「每个含数字的 claim 至少 1 个数字命中」（按 claim 聚合，关键结论视角）
      - numerical = 「report 中每一个数字 token」都在 raw_data 里存在（按数字粒度，严格一致性视角）
    """
    ds_list = data_sources or []
    result = NumericalResult()
    # 预提取所有 data_source 的数字（作为基准集合）
    source_nums: list[NumberToken] = []
    for ds in ds_list:
        if not isinstance(ds, dict):
            continue
        raw = ds.get("raw_data", "")
        if raw is None:
            continue
        source_nums.extend(extract_numbers(str(raw)))

    report_nums = extract_numbers(report_text or "")
    result.total_report_numbers = len(report_nums)
    if not report_nums:
        result.score = 100
        result.coverage = 1.0
        return result

    for tok in report_nums:
        matched_ids: list[int] = []
        hit = False
        for idx, s in enumerate(source_nums):
            if _literal_match(tok, s.original) or _fuzzy_equal(
                tok.value, s.value, tok.is_percent, s.is_percent
            ):
                hit = True
                ds_id = idx  # number 级无 ds_id，直接用位置做 trace
                if ds_id not in matched_ids:
                    matched_ids.append(ds_id)
        if hit:
            result.matched_numbers += 1
        else:
            result.unmatched.append({
                "original": tok.original,
                "value": tok.value,
                "is_percent": tok.is_percent,
            })

    result.coverage = (
        round(result.matched_numbers / result.total_report_numbers, 4)
        if result.total_report_numbers else 0.0
    )
    result.score = int(round(result.coverage * 100))
    return result
