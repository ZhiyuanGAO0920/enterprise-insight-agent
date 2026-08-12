"""PII 脱敏工具（T-03）— 输出层统一脱敏，数据库原样存储。

拦截点：
- sql_runner 结果出口（写缓存前）→ LLM 上下文/报告/表格/图表全部安全
- 审计中间件 query_params → 日志无明文手机号

设计约束：
- 只在输出侧做，绝不动数据库存储（个保法：存储原样、展示脱敏）
- 正则带数字边界（(?<!\\d) / (?!\\d)），避免误伤恰好 11 位的非手机号数字列
- 手机号：前 3 后 4 保留，中间 4 位掩码（138****5678）
"""
import re

# 11 位大陆手机号：1[3-9] + 9 位数字 = 前 3(1[3-9]\d) + 中 4 + 后 4，前后非数字边界
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{1})(\d{4})(\d{4})(?!\d)")
# 带分隔符变体：138 1234 5678 / 138-1234-5678
_PHONE_VARIANT_RE = re.compile(r"(?<!\d)(1[3-9]\d{1})[- ](\d{4})[- ](\d{4})(?!\d)")


def mask_phone(text: str) -> str:
    """手机号 → 138****5678。非字符串/空值原样返回。"""
    if not text or not isinstance(text, str):
        return text
    # 先处理带分隔符变体（否则 "-" 会挡住主模式）
    text = _PHONE_VARIANT_RE.sub(r"\1****\3", text)
    return _PHONE_RE.sub(r"\1****\3", text)


def mask_pii(text: str) -> str:
    """通用 PII 脱敏入口（当前仅手机号，预留邮箱/身份证扩展）。"""
    return mask_phone(text)
