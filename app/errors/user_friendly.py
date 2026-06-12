"""用户友好错误消息 — V3 功能 (P2-2)。

受 FEATURE_FRIENDLY_ERRORS 环境变量控制。禁用时，原始错误直接透传。
启用时，技术错误被映射为带图标和建议操作的中文用户友好消息。

用法：
    from app.errors.user_friendly import to_user_message
    user_msg = to_user_message(raw_error_string)
"""

import re
from typing import Optional

from app.config import get_settings

# ---------------------------------------------------------------------------
# 错误模式 → 用户友好消息映射
# ---------------------------------------------------------------------------
# 每条记录：(正则表达式模式, {user_message, action, icon})
# 按顺序匹配；首次匹配生效。

ERROR_MAP: list[tuple[str, dict]] = [
    # --- 认证 ---
    (
        r"(?i)invalid\s+(username|password|credentials)",
        {
            "user_message": "用户名或密码错误，请重试。如果忘记密码，请联系管理员重置。",
            "action": "retry_login",
            "icon": "🔐",
        },
    ),
    (
        r"(?i)token.*(expir|invalid|revok)",
        {
            "user_message": "登录已过期或失效，请重新登录。",
            "action": "redirect_login",
            "icon": "🔑",
        },
    ),
    (
        r"(?i)account.*(disabl|inactive)",
        {
            "user_message": "账户已被禁用，请联系管理员。",
            "action": "contact_admin",
            "icon": "🚫",
        },
    ),
    # --- 速率限制 ---
    (
        r"(?i)rate\s*limit",
        {
            "user_message": "请求太频繁了，请稍等片刻再试。",
            "action": "wait_retry",
            "icon": "⏱️",
        },
    ),
    # --- 权限 ---
    (
        r"(?i)(permission|unauthorized|forbidden|403)",
        {
            "user_message": "您没有权限执行此操作。如需更多权限，请联系管理员。",
            "action": "contact_admin",
            "icon": "🔒",
        },
    ),
    # --- SQL 错误 —— Agent 将自动重试 ---
    (
        r"(?i)column.*does\s*not\s*exist",
        {
            "user_message": "数据查询遇到技术问题，已自动调整查询方式并重试。",
            "action": "auto_retry",
            "icon": "🔄",
        },
    ),
    (
        r"(?i)relation.*does\s*not\s*exist",
        {
            "user_message": "数据表未找到，已自动调整查询方式并重试。",
            "action": "auto_retry",
            "icon": "🔄",
        },
    ),
    (
        r"(?i)syntax\s*error",
        {
            "user_message": "查询语句需要调整，已自动修正并重试。",
            "action": "auto_retry",
            "icon": "🔄",
        },
    ),
    # --- 网络 / 连接 ---
    (
        r"(?i)(connection.*(refus|timeout|reset)|cannot\s*connect)",
        {
            "user_message": "服务暂时无法连接，请稍后重试。如持续出现，请联系管理员检查服务状态。",
            "action": "retry_later",
            "icon": "🔌",
        },
    ),
    (
        r"(?i)(timeout|timed\s*out)",
        {
            "user_message": "请求超时，可能是数据量较大或网络不稳定。请稍后重试或尝试缩小查询范围。",
            "action": "retry_or_narrow",
            "icon": "⏳",
        },
    ),
    # --- LLM / API ---
    (
        r"(?i)(api.*(key|auth).*invalid|401.*unauthorized)",
        {
            "user_message": "AI 服务认证失败，请联系管理员检查 API 密钥配置。",
            "action": "notify_admin",
            "icon": "🤖",
        },
    ),
    (
        r"(?i)(insufficient.*quota|rate.*limit.*token|429)",
        {
            "user_message": "AI 服务调用次数已达上限，请稍后重试或联系管理员升级配额。",
            "action": "retry_later",
            "icon": "📊",
        },
    ),
    # --- 数据库 ---
    (
        r"(?i)(database.*error|sql.*error|execution.*fail)",
        {
            "user_message": "数据处理遇到暂时问题，已自动记录并重试。如问题持续，请联系管理员。",
            "action": "auto_retry",
            "icon": "🗄️",
        },
    ),
    # --- 嵌入向量 ---
    (
        r"(?i)(embedding|ollama).*(error|fail|unreachable)",
        {
            "user_message": "向量分析服务暂时不可用，分析结果可能缺少历史参考。不影响本次分析的核心结论。",
            "action": "degraded_continue",
            "icon": "🧬",
        },
    ),
    # --- 校验 ---
    (
        r"(?i)(validation|invalid.*(input|request|parameter))",
        {
            "user_message": "请求格式有误。请尝试用更简洁明确的方式重新描述您的问题。",
            "action": "rephrase",
            "icon": "📝",
        },
    ),
]

# ---------------------------------------------------------------------------
# 通用兜底消息
# ---------------------------------------------------------------------------

FALLBACK_MESSAGE = {
    "user_message": "系统遇到一个意外问题，已自动记录。请尝试重新提问，或换个方式描述您的问题。",
    "action": "report_and_retry",
    "icon": "⚠️",
}


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def _match_error(raw_error: str) -> Optional[dict]:
    """将原始错误字符串与已知模式进行匹配。

    返回匹配的模板字典，如果没有匹配则返回 None。
    """
    for pattern, template in ERROR_MAP:
        if re.search(pattern, raw_error, re.IGNORECASE):
            return template
    return None


def to_user_message(raw_error: str) -> dict:
    """将原始技术错误转换为用户友好消息字典。

    当 FEATURE_FRIENDLY_ERRORS 禁用时，返回包装在最小字典中的原始错误。

    Args:
        raw_error: 来自 agent_errors 或异常的原始错误字符串。

    Returns:
        包含 user_message、action、icon、raw 键的字典（raw 始终包含）。
    """
    settings = get_settings()

    if not settings.feature_friendly_errors:
        # 功能禁用 —— 透传原始错误
        return {
            "user_message": raw_error,
            "action": "none",
            "icon": "",
            "raw": raw_error,
        }

    matched = _match_error(raw_error)
    if matched:
        return {**matched, "raw": raw_error}

    return {**FALLBACK_MESSAGE, "raw": raw_error}


def format_agent_errors(agent_errors: list[dict]) -> list[dict]:
    """将 Agent 错误字典列表格式化为用户友好版本。

    Args:
        agent_errors: 来自 AnalysisState 的 {"agent": str, "error": str} 字典列表。

    Returns:
        同样的列表，每个错误增加了 user_message、action、icon 字段。
    """
    result = []
    for err in agent_errors:
        friendly = to_user_message(err.get("error", str(err)))
        result.append({
            "agent": err.get("agent", "unknown"),
            "error": err.get("error", ""),
            "user_message": friendly["user_message"],
            "action": friendly["action"],
            "icon": friendly["icon"],
        })
    return result
